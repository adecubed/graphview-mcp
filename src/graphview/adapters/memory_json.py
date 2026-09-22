"""memory.json written by the Knowledge Graph Memory MCP server.

Accepts both the JSONL form (one entity or relation per line) and a single
object with `entities` and `relations` lists.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..model import Edge, Graph, Node


class MemoryJsonAdapter:
    def __init__(self, source: dict | str, path: str | Path | None = None) -> None:
        # built from a source dict ({name, adapter, path}) or, in tests, from (name, path)
        if isinstance(source, dict):
            source, path = source["name"], source["path"]
        name = source
        self.name = name
        self.path = Path(path)

    def _records(self, g: Graph) -> list[dict]:
        text = self.path.read_text(encoding="utf-8")
        try:
            whole = json.loads(text)
        except json.JSONDecodeError:
            whole = None
        if isinstance(whole, dict) and ("entities" in whole or "relations" in whole):
            return ([{**e, "type": "entity"} for e in whole.get("entities", [])]
                    + [{**r, "type": "relation"} for r in whole.get("relations", [])])
        if isinstance(whole, dict):
            return [whole]
        records = []
        for number, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                g.warnings.append(f"{self.name}: line {number} is not valid JSON ({exc.msg})")
        return records

    def load(self) -> Graph:
        g = Graph()
        for rec in self._records(g):
            if not isinstance(rec, dict):
                continue
            if rec.get("type") == "entity" and "name" in rec:
                g.add_node(Node(f"{self.name}:{rec['name']}", rec["name"],
                                rec.get("entityType") or "entity", self.name,
                                {"observations": rec.get("observations", [])}))
            elif rec.get("type") == "relation" and "from" in rec and "to" in rec:
                g.add_edge(Edge(f"{self.name}:{rec['from']}", f"{self.name}:{rec['to']}",
                                rec.get("relationType") or "related"))
        g.finalize()
        return g
