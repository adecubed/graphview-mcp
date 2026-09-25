"""What's in here: named sets of nodes a mapping declares, with plain names applied."""
import asyncio
import inspect
import json
import sqlite3

import pytest

from graphview.config import Config, load_config
from graphview.service import GraphService


@pytest.fixture
def built(tmp_path):
    db = tmp_path / "graph.db"
    con = sqlite3.connect(db)
    con.executescript("""
        CREATE TABLE nodes (id TEXT PRIMARY KEY, kind TEXT, label TEXT);
        INSERT INTO nodes VALUES ('thing/key/a14', 'key', 'A.1.4'), ('thing/key/a15', 'key', 'A.1.5'),
                                 ('f/offers/x.docx', 'document', 'x'), ('f/offers/y.docx', 'document', 'y'),
                                 ('s/row-1', 'row', 'A.1.4');
        CREATE TABLE edges (a TEXT, b TEXT, type TEXT);
        INSERT INTO edges VALUES ('s/row-1', 'thing/key/a14', 'describes');
        CREATE TABLE groups (id INTEGER PRIMARY KEY, kind TEXT, name TEXT, field TEXT, members TEXT);
        INSERT INTO groups(kind, name, field, members) VALUES
            ('thing', 'key', NULL, '["thing/key/a14", "thing/key/a15", "thing/key/ghost"]'),
            ('folder', 'offers', NULL, '["f/offers/x.docx", "f/offers/y.docx"]'),
            ('category', 'piano: Primo', 'piano', '["s/row-1"]'),
            ('category', 'piano: Terra', 'piano', '["s/row-9"]');
    """)
    con.commit(); con.close()
    (tmp_path / "graphview.yaml").write_text(f"""
names: {{key: Flats, piano: Floor}}
sources:
  - name: built
    adapter: sqlite
    path: graph.db
    nodes:
      - table: nodes
        id: id
        label: label
        type: {{column: kind}}
    edges:
      - table: edges
        from: a
        to: b
        type: {{column: type}}
    groups:
      query: SELECT kind, name, field, members FROM groups ORDER BY id
""", encoding="utf-8")
    return tmp_path


def test_the_adapter_reads_groups_with_prefixed_member_ids(built):
    from graphview.adapters.sqlite_map import SqliteMapAdapter
    cfg = load_config(str(built / "graphview.yaml"), None)
    adapter = SqliteMapAdapter(cfg.sources[0])
    groups = adapter.groups()
    assert groups[0] == {"name": "key", "kind": "thing", "field": "",
                         "members": ["built:thing/key/a14", "built:thing/key/a15", "built:thing/key/ghost"]}
    assert groups[2]["field"] == "piano"


def test_the_service_applies_names_and_drops_members_not_in_the_graph(built):
    svc = GraphService(load_config(str(built / "graphview.yaml"), None))
    out = svc.groups()
    assert out["names"] == {"key": "Flats", "piano": "Floor"}
    by = {(g["kind"], g["name"]): g for g in out["groups"]}
    assert by[("thing", "Flats")]["count"] == 2 and by[("thing", "Flats")]["ids"] == ["built:thing/key/a14", "built:thing/key/a15"]
    assert by[("folder", "offers")]["count"] == 2
    assert by[("category", "Floor: Primo")]["field"] == "piano"
    assert ("category", "Floor: Terra") not in by            # its only member is not a node
    assert svc.groups(max_ids=1)["groups"][0]["ids"] == ["built:thing/key/a14"]


def test_a_source_without_groups_declares_none(tmp_path):
    svc = GraphService(Config(sources=[{"name": "v", "adapter": "wikilinks", "path": str(tmp_path)}]))
    assert svc.groups() == {"groups": [], "names": {}}


def test_groups_over_http_and_mcp(built):
    import threading
    import urllib.request

    from graphview.http_api import make_server
    from graphview.mcp_server import build_server

    svc = GraphService(load_config(str(built / "graphview.yaml"), None))
    server = make_server(svc, "tok", port=0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{server.server_address[1]}/api/groups?token=tok") as r:
            assert json.loads(r.read())["groups"][0]["name"] == "Flats"
    finally:
        server.shutdown(); server.server_close()
    mcp = build_server(svc, opener=lambda url: None)
    result = mcp.call_tool("groups", {"max_ids": 1})
    result = asyncio.run(result) if inspect.isawaitable(result) else result
    result = result[0] if isinstance(result, tuple) else result
    out = json.loads(getattr(result, "content", result)[0].text)
    assert out["groups"][0]["ids"] == ["built:thing/key/a14"]
