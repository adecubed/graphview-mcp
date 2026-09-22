import sqlite3

import pytest

from graphview.adapters import build_adapter
from graphview.adapters.sqlite_map import SqliteMapAdapter


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "brain.db"
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE entities (id INTEGER PRIMARY KEY, name TEXT, kind TEXT,
                               email TEXT, created TEXT);
        CREATE TABLE docs (doc_id TEXT PRIMARY KEY, title TEXT);
        CREATE TABLE links (src INTEGER, dst INTEGER, rel TEXT, weight REAL);
        CREATE TABLE mentions (doc TEXT, entity INTEGER);
        INSERT INTO entities VALUES (1, 'Alice', 'person', 'a@example.com', '2026-01-02'),
                                    (2, 'Acme', 'company', NULL, NULL),
                                    (3, NULL, 'person', NULL, NULL);
        INSERT INTO docs VALUES ('d1', 'Contract');
        INSERT INTO links VALUES (1, 2, 'works_at', 0.9), (1, 99, 'knows', 0.1);
        INSERT INTO mentions VALUES ('d1', 1);
    """)
    con.commit()
    con.close()
    return path


def mapping(path):
    return {
        "name": "brain", "adapter": "sqlite", "path": str(path),
        "nodes": [
            {"table": "entities", "id": "id", "label": "name",
             "type": {"column": "kind"}, "created_at": "created", "props": ["email"]},
            {"table": "docs", "id": "doc_id", "label": "title", "type": "document",
             "id_prefix": "doc"},
        ],
        "edges": [
            {"table": "links", "from": "src", "to": "dst",
             "type": {"column": "rel"}, "props": ["weight"]},
            {"table": "mentions", "from": "doc", "to": "entity", "type": "mentions",
             "from_prefix": "doc"},
        ],
    }


def test_rows_become_nodes_with_type_from_column_or_fixed(db):
    g = build_adapter(mapping(db)).load()
    alice = g.nodes["brain:1"]
    assert (alice.label, alice.type, alice.created_at) == ("Alice", "person", "2026-01-02")
    assert alice.props == {"email": "a@example.com"}
    assert g.nodes["brain:doc/d1"].type == "document"


def test_null_label_falls_back_to_id_and_null_props_are_left_out(db):
    g = build_adapter(mapping(db)).load()
    assert g.nodes["brain:3"].label == "3"
    assert g.nodes["brain:2"].props == {}


def test_edges_with_type_column_props_prefixes_and_dangling_count(db):
    g = build_adapter(mapping(db)).load()
    found = {(e.source_id, e.target_id, e.type) for e in g.edges}
    assert found == {("brain:1", "brain:2", "works_at"),
                     ("brain:doc/d1", "brain:1", "mentions")}
    assert g.dropped_edges == 1
    works = next(e for e in g.edges if e.type == "works_at")
    assert works.props == {"weight": 0.9}


def test_query_can_replace_table(db):
    m = mapping(db)
    m["nodes"] = [{"query": "SELECT id, upper(name) AS shout, kind FROM entities WHERE name IS NOT NULL",
                   "id": "id", "label": "shout", "type": {"column": "kind"}}]
    m["edges"] = []
    g = build_adapter(m).load()
    assert {n.label for n in g.nodes.values()} == {"ALICE", "ACME"}


def test_database_is_opened_read_only(db):
    m = mapping(db)
    m["nodes"] = [{"query": "DELETE FROM entities", "id": "id", "label": "name", "type": "x"}]
    with pytest.raises(Exception, match="readonly|read-only|SELECT"):
        SqliteMapAdapter(m).load()
    assert sqlite3.connect(db).execute("SELECT count(*) FROM entities").fetchone()[0] == 3


def test_missing_database_is_an_error_not_a_new_empty_file(tmp_path):
    m = mapping(tmp_path / "nope.db")
    with pytest.raises(Exception):
        SqliteMapAdapter(m).load()
    assert not (tmp_path / "nope.db").exists()


def test_bad_identifier_in_mapping_is_rejected(db):
    m = mapping(db)
    m["nodes"][0]["table"] = "entities; DROP TABLE entities"
    with pytest.raises(ValueError, match="identifier"):
        SqliteMapAdapter(m).load()


def test_a_broken_table_mapping_warns_and_the_rest_still_loads(db):
    m = mapping(db)
    m["nodes"].append({"table": "no_such_table", "id": "id", "label": "x", "type": "x"})
    g = SqliteMapAdapter(m).load()
    assert "brain:1" in g.nodes
    assert any("no_such_table" in w for w in g.warnings)


@pytest.fixture
def two_dbs(db, tmp_path):
    other = tmp_path / "semantic.db"
    con = sqlite3.connect(other)
    con.executescript("""
        CREATE TABLE facts (key TEXT PRIMARY KEY, content TEXT);
        INSERT INTO facts VALUES ('f1', 'Alice works at Acme'), ('f2', 'A fact nobody links to');
    """)
    con.commit()
    con.close()
    return db, other


def test_attach_joins_a_second_database_read_only(two_dbs):
    db, other = two_dbs
    m = mapping(db)
    m["attach"] = {"sem": str(other)}
    m["nodes"].append({"query": "SELECT 'fact/' || key AS id, key, content FROM sem.facts",
                       "id": "id", "label": "key", "type": "fact", "props": ["content"]})
    g = SqliteMapAdapter(m).load()
    assert g.nodes["brain:fact/f2"].props == {"content": "A fact nobody links to"}
    assert g.warnings == []

    m["nodes"][-1]["query"] = "SELECT key AS id, key, content FROM sem.facts; DELETE FROM sem.facts"
    SqliteMapAdapter(m).load()
    assert sqlite3.connect(other).execute("SELECT count(*) FROM facts").fetchone()[0] == 2


def test_attach_rejects_bad_alias_and_reports_missing_file(two_dbs, tmp_path):
    db, other = two_dbs
    m = mapping(db)
    m["attach"] = {"sem; DROP": str(other)}
    with pytest.raises(ValueError, match="identifier"):
        SqliteMapAdapter(m).load()
    m["attach"] = {"sem": str(tmp_path / "missing.db")}
    with pytest.raises(Exception):
        SqliteMapAdapter(m).load()
    assert not (tmp_path / "missing.db").exists()


@pytest.fixture
def with_episodes(two_dbs, tmp_path):
    db, sem = two_dbs
    epi = tmp_path / "episodes.db"
    con = sqlite3.connect(epi)
    con.executescript("""
        CREATE TABLE episodes (task_id TEXT PRIMARY KEY, created TEXT, summary TEXT);
        INSERT INTO episodes VALUES ('e1', '2026-07-01', 'Alice joined Acme'),
                                    ('e2', '2026-07-02', 'Contract signed');
    """)
    con.commit()
    con.close()
    m = mapping(db)
    m["attach"] = {"sem": str(sem), "epi": str(epi)}
    m["nodes"][0]["props"] = ["email", "sources"]
    m["nodes"][0]["query"] = ("SELECT id, name, kind, email, created, "
                              "'[\"e1\", \"e2\", \"ghost\"]' AS sources FROM entities")
    m["nodes"][0]["refs"] = {"sources": "episode"}
    m["lookups"] = {"episode": {"query": "SELECT task_id AS id, created, summary FROM epi.episodes WHERE task_id = ?"}}
    return m


def test_refs_are_declared_on_the_adapter_and_ids_parsed_from_json(with_episodes):
    adapter = SqliteMapAdapter(with_episodes)
    g = adapter.load()
    assert adapter.refs == {"sources": "episode"}
    assert g.nodes["brain:1"].props["sources"] == ["e1", "e2", "ghost"]


def test_lookup_resolves_ids_read_only_and_skips_unknown(with_episodes):
    adapter = SqliteMapAdapter(with_episodes)
    rows = adapter.lookup("episode", ["e2", "ghost", "e1"])
    assert rows == [{"id": "e2", "created": "2026-07-02", "summary": "Contract signed"},
                    {"id": "e1", "created": "2026-07-01", "summary": "Alice joined Acme"}]
    assert adapter.lookup("no_such_lookup", ["e1"]) == []
    assert adapter.lookup("episode", []) == []


def test_lookup_query_must_be_a_select_with_one_placeholder(with_episodes):
    with_episodes["lookups"]["episode"]["query"] = "DELETE FROM epi.episodes WHERE task_id = ?"
    with pytest.raises(ValueError, match="SELECT"):
        SqliteMapAdapter(with_episodes).load()
    with_episodes["lookups"]["episode"]["query"] = "SELECT * FROM epi.episodes"
    with pytest.raises(ValueError, match="placeholder"):
        SqliteMapAdapter(with_episodes).load()
