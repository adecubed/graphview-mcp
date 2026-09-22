from graphview import ops
from graphview.model import Edge, Graph, Node


def chain_graph() -> Graph:
    """a -knows-> b -knows-> c -works_at-> d, plus isolated e from source t."""
    g = Graph()
    for nid, label, typ, src in [
        ("s:a", "Alice", "person", "s"),
        ("s:b", "Bob", "person", "s"),
        ("s:c", "Carol", "person", "s"),
        ("s:d", "Acme", "company", "s"),
        ("t:e", "Elsewhere", "note", "t"),
    ]:
        g.add_node(Node(nid, label, typ, src))
    g.add_edge(Edge("s:a", "s:b", "knows"))
    g.add_edge(Edge("s:b", "s:c", "knows"))
    g.add_edge(Edge("s:c", "s:d", "works_at"))
    g.finalize()
    return g


def test_subgraph_by_node_type_drops_edges_to_removed_nodes():
    sub = ops.subgraph(chain_graph(), node_types=["person"])
    assert set(sub.nodes) == {"s:a", "s:b", "s:c"}
    assert all(e.type == "knows" for e in sub.edges)
    assert sub.dropped_edges == 0


def test_subgraph_by_edge_type_and_source():
    sub = ops.subgraph(chain_graph(), edge_types=["works_at"], sources=["s"])
    assert "t:e" not in sub.nodes
    assert [e.type for e in sub.edges] == ["works_at"]


def test_neighbors_depth_follows_edges_in_both_directions():
    g = chain_graph()
    assert set(ops.neighbors(g, "s:b", depth=1).nodes) == {"s:a", "s:b", "s:c"}
    assert set(ops.neighbors(g, "s:b", depth=2).nodes) == {"s:a", "s:b", "s:c", "s:d"}


def test_neighbors_respects_edge_types():
    sub = ops.neighbors(chain_graph(), "s:c", depth=1, edge_types=["works_at"])
    assert set(sub.nodes) == {"s:c", "s:d"}


def test_neighbors_unknown_node_is_empty():
    assert ops.neighbors(chain_graph(), "s:nope").nodes == {}


def test_sample_keeps_highest_degree_nodes_and_reports_total():
    sampled, total = ops.sample(chain_graph(), limit=2)
    assert total == 5
    assert set(sampled.nodes) == {"s:b", "s:c"}
    assert len(sampled.edges) == 1


def test_sample_under_limit_returns_everything():
    g = chain_graph()
    sampled, total = ops.sample(g, limit=100)
    assert total == 5 and len(sampled.nodes) == 5


def test_search_is_case_insensitive_and_ranks_label_before_props():
    g = chain_graph()
    g.nodes["s:d"].props["note"] = "Bob founded it"
    hits = ops.search(g, "bob")
    assert [n.id for n in hits] == ["s:b", "s:d"]


def test_search_empty_query_returns_nothing():
    assert ops.search(chain_graph(), "  ") == []


def test_stats_counts_by_type_and_source():
    s = ops.stats(chain_graph())
    assert s["nodes"] == 5 and s["edges"] == 3
    assert s["by_node_type"] == {"person": 3, "company": 1, "note": 1}
    assert s["by_edge_type"] == {"knows": 2, "works_at": 1}
    assert s["by_source"] == {"s": 4, "t": 1}


def slug_graph() -> Graph:
    g = Graph()
    for nid, label, props in [
        ("b:1", "atlas_server", {}),
        ("b:2", "atlas-desktop", {}),
        ("b:3", "pager_interface", {"note": "talks to the Atlas server"}),
        ("b:4", "Café Résumé", {}),
        ("b:5", "server_rack", {}),
    ]:
        g.add_node(Node(nid, label, "entity", "b", props))
    g.finalize()
    return g


def test_search_ignores_separators_case_and_word_order():
    g = slug_graph()
    for query in ("atlas server", "Atlas_Server", "server atlas", "atlas-server", "  ATLAS   server "):
        assert [n.id for n in ops.search(g, query)][0] == "b:1", query


def test_search_all_words_in_label_beat_words_spread_over_props():
    assert [n.id for n in ops.search(slug_graph(), "atlas server")] == ["b:1", "b:3"]


def test_search_ignores_accents():
    assert [n.id for n in ops.search(slug_graph(), "cafe resume")] == ["b:4"]


def test_search_falls_back_to_any_word_when_no_node_has_them_all():
    found = [n.id for n in ops.search(slug_graph(), "atlas kubernetes")]
    assert set(found) == {"b:1", "b:2", "b:3"}


def test_search_finds_fragments_inside_words_but_ranks_whole_word_starts_first():
    g = slug_graph()
    g.add_node(Node("b:6", "webserver", "entity", "b"))
    g.finalize()
    found = [n.id for n in ops.search(g, "server")]
    assert set(found) == {"b:1", "b:3", "b:5", "b:6"}
    assert found.index("b:6") > found.index("b:1") and found.index("b:6") > found.index("b:5")
