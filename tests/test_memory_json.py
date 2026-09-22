import json

from graphview.adapters.memory_json import MemoryJsonAdapter

ENTITIES = [
    {"type": "entity", "name": "Alice", "entityType": "person",
     "observations": ["Likes graphs", "Lives in Rome"]},
    {"type": "entity", "name": "Acme", "entityType": "company", "observations": []},
]
RELATIONS = [
    {"type": "relation", "from": "Alice", "to": "Acme", "relationType": "works_at"},
    {"type": "relation", "from": "Alice", "to": "Ghost", "relationType": "knows"},
]


def check(g):
    alice = g.nodes["mem:Alice"]
    assert alice.type == "person" and alice.label == "Alice"
    assert alice.props["observations"] == ["Likes graphs", "Lives in Rome"]
    assert [(e.source_id, e.target_id, e.type) for e in g.edges] == \
        [("mem:Alice", "mem:Acme", "works_at")]
    assert g.dropped_edges == 1


def test_jsonl_form(tmp_path):
    path = tmp_path / "memory.json"
    path.write_text("\n".join(json.dumps(r) for r in ENTITIES + RELATIONS) + "\n",
                    encoding="utf-8")
    check(MemoryJsonAdapter("mem", path).load())


def test_single_object_form(tmp_path):
    path = tmp_path / "memory.json"
    path.write_text(json.dumps({"entities": ENTITIES, "relations": RELATIONS}),
                    encoding="utf-8")
    check(MemoryJsonAdapter("mem", path).load())


def test_bad_lines_become_warnings_not_crashes(tmp_path):
    path = tmp_path / "memory.json"
    path.write_text(json.dumps(ENTITIES[0]) + "\n{not json\n", encoding="utf-8")
    g = MemoryJsonAdapter("mem", path).load()
    assert "mem:Alice" in g.nodes
    assert len(g.warnings) == 1 and "line 2" in g.warnings[0]
