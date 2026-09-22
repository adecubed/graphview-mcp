from graphview.masking import Masker
from graphview.model import Edge, Graph, Node


def small_graph() -> Graph:
    g = Graph()
    g.add_node(Node("s:a", "Alice", "person", "s"))
    g.add_node(Node("s:b", "Bob", "person", "s"))
    g.add_node(Node("s:c", "Acme", "company", "s"))
    g.add_edge(Edge("s:a", "s:b", "knows"))
    g.add_edge(Edge("s:a", "s:c", "works_at"))
    g.finalize()
    return g


def test_degree_counts_both_directions():
    g = small_graph()
    assert g.degree("s:a") == 2
    assert g.degree("s:b") == 1


def test_finalize_drops_and_counts_dangling_edges():
    g = Graph()
    g.add_node(Node("s:a", "Alice", "person", "s"))
    g.add_edge(Edge("s:a", "s:ghost", "knows"))
    g.finalize()
    assert g.edges == []
    assert g.dropped_edges == 1


def test_merge_keeps_nodes_edges_and_warnings():
    g = small_graph()
    other = Graph()
    other.add_node(Node("t:x", "X", "note", "t"))
    other.warnings.append("t: something odd")
    other.finalize()
    g.merge(other)
    assert "t:x" in g.nodes
    assert g.warnings == ["t: something odd"]


def test_to_dict_uses_force_graph_field_names():
    d = small_graph().to_dict()
    node = next(n for n in d["nodes"] if n["id"] == "s:a")
    assert node == {
        "id": "s:a", "label": "Alice", "type": "person", "source": "s",
        "props": {}, "created_at": None, "degree": 2,
    }
    assert {"source": "s:a", "target": "s:b", "type": "knows", "props": {}} in d["links"]


def test_to_dict_masks_labels_and_props_but_not_stored_data():
    g = Graph()
    g.add_node(Node("s:a", "alice@example.com", "person", "s",
                    props={"mail": "alice@example.com", "age": 40}))
    g.finalize()
    d = g.to_dict(masker=Masker())
    node = d["nodes"][0]
    assert "alice@example.com" not in node["label"]
    assert "alice@example.com" not in node["props"]["mail"]
    assert node["props"]["age"] == 40
    assert g.nodes["s:a"].label == "alice@example.com"


def test_to_dict_masks_strings_inside_lists_and_dicts():
    g = Graph()
    g.add_node(Node("s:a", "A", "person", "s", props={
        "observations": ["mail me at a@example.com"], "nested": {"m": "b@example.com"}}))
    g.finalize()
    props = g.to_dict(masker=Masker())["nodes"][0]["props"]
    assert "example.com" not in str(props)


def test_compact_dict_collapses_parallel_edges_and_drops_link_props():
    g = Graph()
    g.add_node(Node("s:a", "A", "x", "s"))
    g.add_node(Node("s:b", "B", "x", "s"))
    for key in ("mail-1", "mail-2", "mail-3"):
        g.add_edge(Edge("s:a", "s:b", "mentions", {"source_key": key}))
    g.add_edge(Edge("s:b", "s:a", "mentions", {"source_key": "mail-4"}))
    g.finalize()
    links = g.to_dict(compact=True)["links"]
    assert links == [{"source": "s:a", "target": "s:b", "type": "mentions", "count": 3},
                     {"source": "s:b", "target": "s:a", "type": "mentions", "count": 1}]
    assert len(g.to_dict()["links"]) == 4
