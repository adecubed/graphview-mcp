import asyncio
import inspect
import json

from graphview import ops
from graphview.config import Config
from graphview.model import Edge, Graph, Node
from graphview.service import GraphService
from graphview.worklist import to_markdown


def line_graph() -> Graph:
    """a - b - c - d, a shortcut a - x - d of another link type, and a loner."""
    g = Graph()
    for nid in ("a", "b", "c", "d", "x", "loner"):
        g.add_node(Node(f"s:{nid}", nid.upper(), "thing", "s"))
    for a, b, kind in [("a", "b", "road"), ("b", "c", "road"), ("d", "c", "road"),
                       ("a", "x", "air"), ("x", "d", "air")]:
        g.add_edge(Edge(f"s:{a}", f"s:{b}", kind))
    g.finalize()
    return g


def test_shortest_path_ignores_link_direction():
    assert ops.shortest_path(line_graph(), "s:a", "s:d") == ["s:a", "s:x", "s:d"]
    assert ops.shortest_path(line_graph(), "s:d", "s:a") == ["s:d", "s:x", "s:a"]


def test_shortest_path_can_be_limited_to_link_types():
    path = ops.shortest_path(line_graph(), "s:a", "s:d", edge_types=["road"])
    assert path == ["s:a", "s:b", "s:c", "s:d"]


def test_no_path_unknown_node_and_same_node():
    g = line_graph()
    assert ops.shortest_path(g, "s:a", "s:loner") == []
    assert ops.shortest_path(g, "s:a", "s:nope") == []
    assert ops.shortest_path(g, "s:a", "s:a") == ["s:a"]


def test_service_path_returns_the_chain_with_its_links(tmp_path):
    for name, body in [("A", "[[B]]"), ("B", "[[C]]"), ("C", "x"), ("Far", "alone")]:
        (tmp_path / f"{name}.md").write_text(body, encoding="utf-8")
    svc = GraphService(Config(sources=[{"name": "v", "adapter": "wikilinks", "path": str(tmp_path)}]))
    found = svc.path("v:A", "v:C")
    assert found["found"] is True and found["steps"] == 2
    assert [n["id"] for n in found["nodes"]] == ["v:A", "v:B", "v:C"]
    assert {(l["source"], l["target"]) for l in found["links"]} == {("v:A", "v:B"), ("v:B", "v:C")}
    assert svc.path("v:A", "v:Far") == {"found": False, "steps": None, "nodes": [], "links": []}


def hub_graph() -> Graph:
    g = Graph()
    g.add_node(Node("s:me", "me", "entity", "s"))
    g.add_node(Node("s:team", "team", "entity", "s"))
    for i in range(60):
        g.add_node(Node(f"s:f{i}", f"fact_{i}", "fact", "s"))
        g.add_edge(Edge(f"s:f{i}", "s:me", "mentions"))
        g.add_edge(Edge(f"s:f{i}", "s:me", "about"))       # parallel links are one neighbour
        if i < 8:
            g.add_edge(Edge(f"s:f{i}", "s:team", "mentions"))
    g.finalize()
    return g


def test_nodes_linked_to_a_large_share_of_the_graph_are_flagged():
    hubs = ops.worklist(hub_graph())["hubs"]
    assert [(h["label"], h["neighbours"]) for h in hubs] == [("me", 60)]
    assert hubs[0]["share"] == round(60 / 62, 3)
    assert ops.worklist(hub_graph())["summary"]["hubs"] == 1


def test_a_small_graph_has_no_hubs_however_central_a_node_is():
    assert ops.worklist(line_graph())["hubs"] == []


def test_markdown_lists_the_hubs():
    text = to_markdown(ops.worklist(hub_graph()))
    assert "## Very connected (1)" in text
    assert "- [ ] `me` (entity): linked to 60 nodes, 97% of the graph" in text


def test_path_is_exposed_over_http_and_mcp(tmp_path):
    import threading
    import urllib.request
    from urllib.parse import urlencode

    from graphview.http_api import make_server
    from graphview.mcp_server import build_server

    for name, body in [("A", "[[B]]"), ("B", "x")]:
        (tmp_path / f"{name}.md").write_text(body, encoding="utf-8")
    svc = GraphService(Config(sources=[{"name": "v", "adapter": "wikilinks", "path": str(tmp_path)}]))
    server = make_server(svc, "tok", port=0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        query = urlencode({"token": "tok", "from": "v:A", "to": "v:B"})
        with urllib.request.urlopen(f"http://127.0.0.1:{server.server_address[1]}/api/path?{query}") as r:
            assert json.loads(r.read())["steps"] == 1
    finally:
        server.shutdown()
        server.server_close()

    mcp = build_server(svc, opener=lambda url: None)
    result = mcp.call_tool("path", {"from_id": "v:A", "to_id": "v:B"})
    result = asyncio.run(result) if inspect.isawaitable(result) else result
    result = result[0] if isinstance(result, tuple) else result
    chain = json.loads(getattr(result, "content", result)[0].text)
    assert [n["label"] for n in chain["nodes"]] == ["A", "B"]
    assert "props" not in chain["nodes"][0]
