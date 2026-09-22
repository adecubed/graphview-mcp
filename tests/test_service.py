import json

from graphview.config import Config
from graphview.service import GraphService


def make_service(tmp_path, masking=False, limit=5000, extra_sources=()):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "Alice.md").write_text(
        "---\ntype: person\nmail: alice@example.com\n---\n[[Bob]] [[Acme]]", encoding="utf-8")
    (vault / "Bob.md").write_text("---\ntype: person\n---\n[[Acme]]", encoding="utf-8")
    (vault / "Acme.md").write_text("A company.", encoding="utf-8")
    mem = tmp_path / "memory.json"
    mem.write_text(json.dumps({"type": "entity", "name": "Zed", "entityType": "person",
                               "observations": []}), encoding="utf-8")
    sources = [{"name": "vault", "adapter": "wikilinks", "path": str(vault)},
               {"name": "mem", "adapter": "memory_json", "path": str(mem)},
               *extra_sources]
    return GraphService(Config(sources=sources, masking=masking, limit=limit))


def test_sources_are_merged(tmp_path):
    s = make_service(tmp_path).stats()
    assert s["by_source"] == {"vault": 3, "mem": 1}


def test_get_graph_filters_and_reports_sampling(tmp_path):
    svc = make_service(tmp_path)
    d = svc.get_graph(node_types=["person"], sources=["vault"])
    assert {n["id"] for n in d["nodes"]} == {"vault:Alice", "vault:Bob"}
    assert d["meta"]["total_nodes"] == 2 and d["meta"]["sampled"] is False
    d = svc.get_graph(limit=2)
    assert len(d["nodes"]) == 2
    assert d["meta"]["total_nodes"] == 4 and d["meta"]["sampled"] is True


def test_get_node_groups_links_by_type_and_direction(tmp_path):
    d = make_service(tmp_path).get_node("vault:Acme")
    assert d["node"]["label"] == "Acme"
    incoming = d["links"]["links_to"]
    assert {(l["direction"], l["node"]["id"]) for l in incoming} == \
        {("in", "vault:Alice"), ("in", "vault:Bob")}


def test_get_node_unknown_returns_error(tmp_path):
    assert "error" in make_service(tmp_path).get_node("vault:Nope")


def test_neighbors_and_search(tmp_path):
    svc = make_service(tmp_path)
    assert {n["id"] for n in svc.neighbors("vault:Bob", depth=1)["nodes"]} == \
        {"vault:Alice", "vault:Bob", "vault:Acme"}
    assert [n["id"] for n in svc.search("ali")["matches"]] == ["vault:Alice"]


def test_masking_applies_to_every_output(tmp_path):
    svc = make_service(tmp_path, masking=True)
    blob = json.dumps([svc.get_graph(), svc.get_node("vault:Alice"),
                       svc.search("alice"), svc.neighbors("vault:Alice")])
    assert "alice@example.com" not in blob


def test_search_is_not_an_oracle_for_masked_values(tmp_path):
    svc = make_service(tmp_path, masking=True)
    # The hidden part of the value must not change the answer: a right guess and
    # a wrong one look the same, and words found only in it find nothing.
    right = svc.search("alice@example.com")["matches"]
    wrong = svc.search("alice@elsewhere.org")["matches"]
    assert right == wrong
    assert svc.search("example.com")["matches"] == []

    plain = tmp_path / "plain"
    plain.mkdir()
    unmasked = make_service(plain, masking=False)
    assert [m["id"] for m in unmasked.search("example.com")["matches"]] == ["vault:Alice"]


def test_broken_source_becomes_warning_and_others_still_load(tmp_path):
    bad = [{"name": "gone", "adapter": "memory_json", "path": str(tmp_path / "no.json")},
           {"name": "odd", "adapter": "no_such_adapter", "path": "x"}]
    svc = make_service(tmp_path, extra_sources=bad)
    s = svc.stats()
    assert s["nodes"] == 4
    assert len(s["warnings"]) == 2
    assert any("gone" in w for w in s["warnings"])


def test_list_types_includes_colors_with_overrides(tmp_path):
    svc = make_service(tmp_path)
    svc.config.colors["person"] = "#ff0000"
    types = svc.list_types()
    assert types["node_types"]["person"] == {"count": 3, "color": "#ff0000"}
    assert types["node_types"]["note"]["color"].startswith("#")
    assert "links_to" in types["edge_types"]
    assert set(types["sources"]) == {"vault", "mem"}


def test_max_links_keeps_the_heaviest_and_says_so(tmp_path):
    svc = make_service(tmp_path)
    full = svc.get_graph(compact=True)
    assert full["meta"]["links_truncated"] is False
    cut = svc.get_graph(compact=True, max_links=1)
    assert len(cut["links"]) == 1
    assert cut["meta"]["links_truncated"] is True
    assert cut["meta"]["total_links"] == len(full["links"])


def test_compact_get_node_merges_parallel_links_slims_neighbours_and_caps(tmp_path):
    vault = tmp_path / "v2"
    vault.mkdir()
    (vault / "Hub.md").write_text(" ".join(f"[[N{i}]]" for i in range(10)) + " [[N0]] [[N0]]",
                                  encoding="utf-8")
    for i in range(10):
        (vault / f"N{i}.md").write_text("x", encoding="utf-8")
    svc = GraphService(Config(sources=[{"name": "v", "adapter": "wikilinks", "path": str(vault)}]))

    full = svc.get_node("v:Hub")
    assert len(full["links"]["links_to"]) == 12 and "props" in full["links"]["links_to"][0]["node"]

    d = svc.get_node("v:Hub", compact=True, max_per_type=4)
    group = d["links"]["links_to"]
    assert group["total"] == 10 and len(group["items"]) == 4
    assert group["items"][0] == {"direction": "out", "count": 3,
                                 "node": {"id": "v:N0", "label": "N0", "type": "note"}}
