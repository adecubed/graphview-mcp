"""Read-only operations on a Graph. Each returns a new Graph or plain data."""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from typing import Iterable

from .model import Graph, Node
from .worklist import build as worklist  # noqa: F401  (ops.worklist)


def _induced(g: Graph, node_ids: Iterable[str], edge_types=None) -> Graph:
    """Subgraph on node_ids; edges cut by the selection are not 'dropped'."""
    keep = set(node_ids)
    wanted = set(edge_types) if edge_types else None
    sub = Graph()
    for nid in keep:
        sub.add_node(g.nodes[nid])
    for e in g.edges:
        if e.source_id in keep and e.target_id in keep \
                and (wanted is None or e.type in wanted):
            sub.add_edge(e)
    sub.finalize()
    return sub


def subgraph(g: Graph, node_types=None, edge_types=None, sources=None) -> Graph:
    types = set(node_types) if node_types else None
    srcs = set(sources) if sources else None
    ids = [n.id for n in g.nodes.values()
           if (types is None or n.type in types)
           and (srcs is None or n.source in srcs)]
    return _induced(g, ids, edge_types)


def neighbors(g: Graph, node_id: str, depth: int = 1, edge_types=None) -> Graph:
    if node_id not in g.nodes:
        return Graph()
    wanted = set(edge_types) if edge_types else None
    adjacent: dict[str, set[str]] = {}
    for e in g.edges:
        if wanted is None or e.type in wanted:
            adjacent.setdefault(e.source_id, set()).add(e.target_id)
            adjacent.setdefault(e.target_id, set()).add(e.source_id)
    seen, frontier = {node_id}, {node_id}
    for _ in range(max(depth, 0)):
        frontier = {m for n in frontier for m in adjacent.get(n, ())} - seen
        if not frontier:
            break
        seen |= frontier
    return _induced(g, seen, edge_types)


def shortest_path(g: Graph, start: str, end: str, edge_types=None) -> list[str]:
    """Node ids from start to end over the fewest links, whatever their direction.

    Empty when there is no way through, or either node is unknown. Neighbours are
    visited in id order, so equally short paths always give the same answer.
    """
    if start not in g.nodes or end not in g.nodes:
        return []
    if start == end:
        return [start]
    wanted = set(edge_types) if edge_types else None
    adjacent: dict[str, set[str]] = {}
    for e in g.edges:
        if wanted is None or e.type in wanted:
            adjacent.setdefault(e.source_id, set()).add(e.target_id)
            adjacent.setdefault(e.target_id, set()).add(e.source_id)
    came_from = {start: None}
    frontier = [start]
    while frontier and end not in came_from:
        reached = []
        for nid in frontier:
            for other in sorted(adjacent.get(nid, ())):
                if other not in came_from:
                    came_from[other] = nid
                    reached.append(other)
        frontier = reached
    if end not in came_from:
        return []
    path = [end]
    while came_from[path[-1]] is not None:
        path.append(came_from[path[-1]])
    return path[::-1]


def sample(g: Graph, limit: int) -> tuple[Graph, int]:
    """Keep the `limit` best-connected nodes. Returns (graph, total node count)."""
    total = len(g.nodes)
    if total <= limit:
        return g, total
    ranked = sorted(g.nodes, key=lambda nid: (-g.degree(nid), nid))
    return _induced(g, ranked[:limit]), total


def _words(text: str) -> list[str]:
    """Lower-case words with accents stripped; `_`, `-`, `.` and the like split words."""
    plain = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.findall(r"[a-z0-9]+", plain.lower())


def _flatten(value) -> str:
    if isinstance(value, dict):
        return " ".join(_flatten(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return " ".join(_flatten(v) for v in value)
    return str(value)


def search(g: Graph, query: str, limit: int = 50) -> list[Node]:
    """Word search that forgives separators, case, accents and word order.

    Each query word scores 3 when a label word starts with it, 2 when it sits
    inside a label word, 1 when it is only in the props. Nodes that have every
    word come first; if none has them all, nodes with any word are returned.
    """
    wanted = _words(query)
    if not wanted:
        return []
    complete, partial = [], []
    for n in g.nodes.values():
        label_words = _words(n.label)
        label_text = " ".join(label_words)
        props_text = " ".join(_words(_flatten(n.props)))
        scores = []
        for word in wanted:
            if any(w.startswith(word) for w in label_words):
                scores.append(3)
            elif word in label_text:
                scores.append(2)
            elif word in props_text:
                scores.append(1)
            else:
                scores.append(0)
        if all(scores):
            complete.append((-sum(scores), -g.degree(n.id), n.id, n))
        elif any(scores):
            hits = sum(1 for s in scores if s)
            partial.append((-hits, -sum(scores), -g.degree(n.id), n.id, n))
    ranked = sorted(complete) if complete else sorted(partial)
    return [entry[-1] for entry in ranked[:limit]]


def stats(g: Graph) -> dict:
    return {
        "nodes": len(g.nodes),
        "edges": len(g.edges),
        "by_node_type": dict(Counter(n.type for n in g.nodes.values())),
        "by_edge_type": dict(Counter(e.type for e in g.edges)),
        "by_source": dict(Counter(n.source for n in g.nodes.values())),
        "dropped_edges": g.dropped_edges,
        "warnings": list(g.warnings),
    }
