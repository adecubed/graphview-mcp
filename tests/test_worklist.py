from graphview import ops
from graphview.model import Edge, Graph, Node
from graphview.worklist import to_markdown


def messy_graph() -> Graph:
    g = Graph()
    nodes = [
        # the main body
        ("b:ada", "ada_moretti", "entity", {}), ("b:acme", "acme", "entity", {}),
        ("b:lab", "orbit_lab", "entity", {}), ("b:f1", "fact_one", "fact", {"content": "Ada leads the lab."}),
        ("b:hq", "headquarters", "entity", {}), ("b:roof", "roof_garden", "entity", {}),
        # the same things written another way
        ("b:ada2", "Ada-Moretti", "entity", {}), ("b:lab2", "orbit_labs", "entity", {}),
        # same words, different type: not a duplicate
        ("b:acme_fact", "acme", "fact", {}),
        # an island of two
        ("b:bike", "bike_route", "entity", {}), ("b:tyre", "tyre_pressure", "entity", {}),
        # nobody links these
        ("b:loose", "fan_rattles", "fact", {"content": "The fan rattles at noon. " * 20}),
        ("b:alone", "unfiled_thought", "fact", {}),
    ]
    for nid, label, kind, props in nodes:
        g.add_node(Node(nid, label, kind, "b", props))
    for a, b in [("b:ada", "b:acme"), ("b:ada", "b:lab"), ("b:f1", "b:ada"), ("b:f1", "b:lab"),
                 ("b:ada2", "b:acme"), ("b:lab2", "b:acme"), ("b:acme_fact", "b:acme"),
                 ("b:hq", "b:acme"), ("b:roof", "b:hq"), ("b:bike", "b:tyre")]:
        g.add_edge(Edge(a, b, "relates"))
    g.finalize()
    return g


def test_unlinked_nodes_are_listed_with_a_short_text():
    unlinked = ops.worklist(messy_graph())["unlinked"]
    assert [n["id"] for n in unlinked] == ["b:alone", "b:loose"]
    loose = unlinked[1]
    assert loose["text"].startswith("The fan rattles at noon.") and len(loose["text"]) <= 161


def test_islands_are_small_groups_apart_from_the_main_one():
    islands = ops.worklist(messy_graph())["islands"]
    assert [[n["id"] for n in island] for island in islands] == [["b:bike", "b:tyre"]]


def test_likely_duplicates_pair_same_type_nodes_with_near_equal_names():
    pairs = ops.worklist(messy_graph())["duplicates"]
    found = {(p["a"]["id"], p["b"]["id"]) for p in pairs}
    assert found == {("b:ada", "b:ada2"), ("b:lab", "b:lab2")}
    exact = next(p for p in pairs if p["a"]["id"] == "b:ada")
    assert exact["similarity"] == 1.0  # only separators and case differ
    assert 0.85 <= next(p for p in pairs if p["a"]["id"] == "b:lab")["similarity"] < 1.0


def test_summary_counts_match_the_lists():
    w = ops.worklist(messy_graph())
    assert w["summary"] == {"nodes": 13, "unlinked": 2, "islands": 1, "island_nodes": 2, "duplicates": 2, "hubs": 0}


def test_a_clean_graph_has_an_empty_worklist():
    g = Graph()
    g.add_node(Node("s:a", "alpha", "x", "s"))
    g.add_node(Node("s:b", "beta", "x", "s"))
    g.add_edge(Edge("s:a", "s:b", "r"))
    g.finalize()
    w = ops.worklist(g)
    assert w["unlinked"] == [] and w["islands"] == [] and w["duplicates"] == []


def test_markdown_has_a_checkbox_per_item_and_the_ids_needed_to_act():
    text = to_markdown(ops.worklist(messy_graph()), title="brain")
    assert text.startswith("# Worklist: brain")
    assert "- [ ] `ada_moretti` = `Ada-Moretti`" in text
    assert "- [ ] `unfiled_thought`" in text
    assert "`bike_route`, `tyre_pressure`" in text
    assert text.count("- [ ]") == 2 + 1 + 2  # duplicates, islands, unlinked (no hubs here)


def test_service_http_and_mcp_expose_it(tmp_path):
    import asyncio
    import inspect
    import json
    import threading
    import urllib.request

    from graphview.config import Config
    from graphview.http_api import make_server
    from graphview.mcp_server import build_server
    from graphview.service import GraphService

    (tmp_path / "A.md").write_text("[[B]]", encoding="utf-8")
    (tmp_path / "B.md").write_text("x", encoding="utf-8")
    (tmp_path / "Loose.md").write_text("alone", encoding="utf-8")
    service = GraphService(Config(sources=[
        {"name": "v", "adapter": "wikilinks", "path": str(tmp_path)}]))
    assert service.worklist()["summary"]["unlinked"] == 1

    server = make_server(service, "tok", port=0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        with urllib.request.urlopen(f"{base}/api/worklist?token=tok") as r:
            assert json.loads(r.read())["unlinked"][0]["label"] == "Loose"
        with urllib.request.urlopen(f"{base}/api/worklist?token=tok&format=md") as r:
            assert "text/markdown" in r.headers["Content-Type"]
            assert "attachment" in r.headers["Content-Disposition"]
            assert "- [ ] `Loose`" in r.read().decode("utf-8")
    finally:
        server.shutdown()
        server.server_close()

    mcp = build_server(service, opener=lambda url: None)
    result = mcp.call_tool("worklist", {})
    result = asyncio.run(result) if inspect.isawaitable(result) else result
    result = result[0] if isinstance(result, tuple) else result
    content = getattr(result, "content", result)
    assert json.loads(content[0].text)["summary"]["unlinked"] == 1
