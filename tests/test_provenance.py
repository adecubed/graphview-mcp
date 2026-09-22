import asyncio
import inspect
import json
import sqlite3

import pytest

from graphview.config import Config
from graphview.service import GraphService


@pytest.fixture
def service(tmp_path):
    db, epi = tmp_path / "g.db", tmp_path / "e.db"
    con = sqlite3.connect(db)
    con.executescript("""
        CREATE TABLE facts (key TEXT PRIMARY KEY, content TEXT, sources TEXT, supersedes TEXT);
        INSERT INTO facts VALUES ('v3', 'port is 8766', '["e2","e3"]', 'v2'),
                                 ('v2', 'port is 8010', '["e1"]', 'v1'),
                                 ('v1', 'port unknown', NULL, NULL),
                                 ('other', 'unrelated', '["e9"]', NULL),
                                 ('batch_a', 'from one batch', '["e1","e2","e3"]', NULL),
                                 ('batch_b', 'same batch', '["e3","e2","e1"]', NULL),
                                 ('batch_c', 'same batch again', '["e1","e2","e3"]', NULL);
    """)
    con.commit(); con.close()
    con = sqlite3.connect(epi)
    con.executescript("""
        CREATE TABLE episodes (task_id TEXT PRIMARY KEY, created TEXT, summary TEXT);
        INSERT INTO episodes VALUES ('e1', '2026-06-01', 'first guess'), ('e2', '2026-07-01', 'saw the config'),
                                    ('e3', '2026-07-02', 'confirmed on the phone, alice@example.com');
    """)
    con.commit(); con.close()
    source = {"name": "b", "adapter": "sqlite", "path": str(db), "attach": {"epi": str(epi)},
              "nodes": [{"table": "facts", "id": "key", "label": "key", "type": "fact",
                         "props": ["content", "sources"], "refs": {"sources": "episode"}}],
              "edges": [{"query": "SELECT key AS a, supersedes AS b FROM facts WHERE supersedes IS NOT NULL",
                         "from": "a", "to": "b", "type": "supersedes"}],
              "lookups": {"episode": {"query": "SELECT task_id AS id, created, summary FROM epi.episodes WHERE task_id = ?"}}}
    return GraphService(Config(sources=[source]))


def test_get_node_declares_its_refs_with_counts(service):
    d = service.get_node("b:v3")
    assert d["refs"] == {"sources": {"lookup": "episode", "count": 2}}
    assert d["node"]["props"]["sources"] == ["e2", "e3"]
    assert service.get_node("b:v1")["refs"] == {}


def test_refs_say_when_the_same_list_sits_on_other_nodes(service):
    # A distiller that stamps the whole batch on every fact it writes leaves
    # identical lists on unrelated nodes: the panel must not sell them as sources.
    assert service.get_node("b:batch_a")["refs"]["sources"] == {"lookup": "episode", "count": 3, "shared_with": 2}
    assert service.get_node("b:batch_b")["refs"]["sources"]["shared_with"] == 2   # order does not matter
    assert "shared_with" not in service.get_node("b:v3")["refs"]["sources"]      # a list of its own
    assert service.provenance("b:batch_a")["refs"]["sources"]["shared_with"] == 2
    service.reload()
    assert service.get_node("b:batch_c")["refs"]["sources"]["shared_with"] == 2


def test_lookup_resolves_a_nodes_ref_prop(service):
    rows = service.lookup("b:v3", "sources")
    assert [r["id"] for r in rows["rows"]] == ["e2", "e3"]
    assert rows["rows"][1]["summary"].startswith("confirmed")
    assert service.lookup("b:v3", "content") == {"error": "'content' is not a reference property"}
    assert service.lookup("b:nope", "sources")["error"].startswith("no node")


def test_lookup_is_masked_like_everything_else(tmp_path, service):
    service.config.masking = True
    service.reload()
    assert "alice@example.com" not in json.dumps(service.lookup("b:v3", "sources"))


def test_provenance_walks_the_chain_both_ways_and_resolves_sources(service):
    p = service.provenance("b:v2")
    assert [n["id"] for n in p["supersedes"]] == ["b:v1"]
    assert [n["id"] for n in p["superseded_by"]] == ["b:v3"]
    assert p["sources"] == {"sources": [{"id": "e1", "created": "2026-06-01", "summary": "first guess"}]}
    top = service.provenance("b:v3")
    assert [n["id"] for n in top["supersedes"]] == ["b:v2", "b:v1"]   # the whole chain, nearest first
    assert top["superseded_by"] == []
    assert "error" in service.provenance("b:nope")


def test_provenance_over_http_and_mcp(service):
    import threading
    import urllib.request
    from urllib.parse import urlencode

    from graphview.http_api import make_server
    from graphview.mcp_server import build_server

    server = make_server(service, "tok", port=0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        with urllib.request.urlopen(f"{base}/api/lookup?{urlencode({'token': 'tok', 'id': 'b:v3', 'prop': 'sources'})}") as r:
            assert len(json.loads(r.read())["rows"]) == 2
        with urllib.request.urlopen(f"{base}/api/provenance?{urlencode({'token': 'tok', 'id': 'b:v2'})}") as r:
            assert json.loads(r.read())["superseded_by"][0]["id"] == "b:v3"
    finally:
        server.shutdown(); server.server_close()

    mcp = build_server(service, opener=lambda url: None)
    result = mcp.call_tool("provenance", {"node_id": "b:v3"})
    result = asyncio.run(result) if inspect.isawaitable(result) else result
    result = result[0] if isinstance(result, tuple) else result
    out = json.loads(getattr(result, "content", result)[0].text)
    assert [n["label"] for n in out["supersedes"]] == ["v2", "v1"] and len(out["sources"]["sources"]) == 2
