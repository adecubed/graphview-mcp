"""Canonical graph model. Every adapter produces this; nothing else is ever shown."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any


def _mask_value(value: Any, masker) -> Any:
    if isinstance(value, str):
        return masker.mask(value)
    if isinstance(value, dict):
        return {k: _mask_value(v, masker) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_mask_value(v, masker) for v in value]
    return value


@dataclass
class Node:
    id: str
    label: str
    type: str
    source: str
    props: dict[str, Any] = field(default_factory=dict)
    created_at: str | None = None


@dataclass
class Edge:
    source_id: str
    target_id: str
    type: str
    props: dict[str, Any] = field(default_factory=dict)


class Graph:
    def __init__(self) -> None:
        self.nodes: dict[str, Node] = {}
        self.edges: list[Edge] = []
        self.warnings: list[str] = []
        self.dropped_edges = 0
        self._degree: Counter[str] = Counter()

    def add_node(self, node: Node) -> None:
        self.nodes[node.id] = node

    def add_edge(self, edge: Edge) -> None:
        self.edges.append(edge)

    def finalize(self) -> None:
        """Drop edges whose endpoints are missing and recompute degrees."""
        kept = [e for e in self.edges
                if e.source_id in self.nodes and e.target_id in self.nodes]
        self.dropped_edges += len(self.edges) - len(kept)
        self.edges = kept
        self._degree = Counter()
        for e in kept:
            self._degree[e.source_id] += 1
            self._degree[e.target_id] += 1

    def merge(self, other: Graph) -> None:
        self.nodes.update(other.nodes)
        self.edges.extend(other.edges)
        self.warnings.extend(other.warnings)
        self.dropped_edges += other.dropped_edges
        self.finalize()

    def masked_copy(self, masker) -> Graph:
        """Same graph with labels and props masked; ids and edges are shared."""
        copy = Graph()
        for n in self.nodes.values():
            copy.add_node(Node(n.id, masker.mask(n.label), n.type, n.source,
                               _mask_value(n.props, masker), n.created_at))
        copy.edges = list(self.edges)
        copy.warnings = list(self.warnings)
        copy.dropped_edges = self.dropped_edges
        copy.finalize()
        return copy

    def degree(self, node_id: str) -> int:
        return self._degree[node_id]

    def node_dict(self, node: Node, masker=None) -> dict[str, Any]:
        label, props = node.label, node.props
        if masker is not None:
            label = masker.mask(label)
            props = _mask_value(props, masker)
        return {
            "id": node.id, "label": label, "type": node.type,
            "source": node.source, "props": props,
            "created_at": node.created_at, "degree": self.degree(node.id),
        }

    def to_dict(self, masker=None, compact: bool = False) -> dict[str, Any]:
        """Serialise with the field names 3d-force-graph expects (nodes/links).

        `compact` is for agents: parallel edges (same ends and type, e.g. one
        per source document) collapse into one link with a `count`, and link
        props are left out.
        """
        if compact:
            counts = Counter((e.source_id, e.target_id, e.type) for e in self.edges)
            links = [{"source": s, "target": t, "type": kind, "count": n}
                     for (s, t, kind), n in counts.items()]
        else:
            links = [{"source": e.source_id, "target": e.target_id,
                      "type": e.type, "props": e.props} for e in self.edges]
        return {
            "nodes": [self.node_dict(n, masker) for n in self.nodes.values()],
            "links": links,
            "meta": {"dropped_edges": self.dropped_edges,
                     "warnings": list(self.warnings)},
        }
