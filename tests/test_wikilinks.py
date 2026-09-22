from pathlib import Path

from graphview.adapters.wikilinks import WikilinksAdapter


def make_vault(root: Path) -> Path:
    (root / "people").mkdir()
    (root / ".obsidian").mkdir()
    (root / ".obsidian" / "junk.md").write_text("[[Alice]]", encoding="utf-8")
    (root / "people" / "Alice.md").write_text(
        "---\ntype: person\nrole: founder\n---\n"
        "Works with [[Bob|Bobby]] at [[Acme#History]]. #team\n"
        "```\n[[NotALink]] #notatag\n```\n",
        encoding="utf-8")
    (root / "people" / "Bob.md").write_text(
        "Knows [[alice]] and [[Nobody Yet]]. #team #people/friends\n",
        encoding="utf-8")
    (root / "Acme.md").write_text("# Acme\nA company. See [[people/Alice]].\n",
                                  encoding="utf-8")
    return root


def load(tmp_path):
    return WikilinksAdapter("vault", make_vault(tmp_path)).load()


def test_notes_become_nodes_with_prefixed_ids(tmp_path):
    g = load(tmp_path)
    assert g.nodes["vault:people/Alice"].label == "Alice"
    assert g.nodes["vault:Acme"].type == "note"
    assert g.nodes["vault:Acme"].source == "vault"
    assert g.nodes["vault:Acme"].created_at is not None


def test_frontmatter_type_overrides_and_other_keys_become_props(tmp_path):
    alice = load(tmp_path).nodes["vault:people/Alice"]
    assert alice.type == "person"
    assert alice.props["role"] == "founder"


def test_links_resolve_by_name_alias_heading_path_and_case(tmp_path):
    g = load(tmp_path)
    links = {(e.source_id, e.target_id) for e in g.edges if e.type == "links_to"}
    assert ("vault:people/Alice", "vault:people/Bob") in links
    assert ("vault:people/Alice", "vault:Acme") in links
    assert ("vault:people/Bob", "vault:people/Alice") in links
    assert ("vault:Acme", "vault:people/Alice") in links


def test_unresolved_link_becomes_missing_node(tmp_path):
    g = load(tmp_path)
    assert g.nodes["vault:?Nobody Yet"].type == "missing"
    assert g.dropped_edges == 0


def test_tags_become_nodes_and_code_blocks_are_ignored(tmp_path):
    g = load(tmp_path)
    assert g.nodes["vault:#team"].type == "tag"
    assert "vault:#people/friends" in g.nodes
    assert "vault:#notatag" not in g.nodes
    assert "vault:?NotALink" not in g.nodes
    tagged = [e for e in g.edges if e.type == "tagged" and e.target_id == "vault:#team"]
    assert len(tagged) == 2


def test_hidden_folders_are_skipped(tmp_path):
    assert not any("junk" in nid for nid in load(tmp_path).nodes)


def test_created_comes_from_frontmatter_when_present(tmp_path):
    (tmp_path / "Dated.md").write_text("---\ncreated: 2024-03-05\n---\nx", encoding="utf-8")
    (tmp_path / "Stamped.md").write_text("---\ndate: 2025-01-02T10:30:00\n---\nx", encoding="utf-8")
    (tmp_path / "Plain.md").write_text("x", encoding="utf-8")
    g = WikilinksAdapter("v", tmp_path).load()
    assert g.nodes["v:Dated"].created_at == "2024-03-05"
    assert g.nodes["v:Stamped"].created_at == "2025-01-02T10:30:00"
    assert g.nodes["v:Plain"].created_at.startswith("20")  # falls back to the file time
    assert "created" not in g.nodes["v:Dated"].props
