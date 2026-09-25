"""GraphService: the one place both the MCP tools and the HTTP API call into."""

from __future__ import annotations

import threading

from . import ops
from .adapters import load_all
from .config import Config
from .http_search import SearchUnavailable
from .masking import Masker
from .model import Graph

# Bright hues that stay readable on a near-black background.
PALETTE = ["#4cc9f0", "#f72585", "#b5e48c", "#ffd166", "#9d4edd", "#ff9f1c",
           "#2ec4b6", "#ef476f", "#a0c4ff", "#caffbf", "#ffadad", "#bdb2ff"]

# How many references a shared list needs before it reads as a batch stamp rather than
# as two nodes that honestly came from the same place.
BATCH_REFS = 3


class GraphService:
    def __init__(self, config: Config) -> None:
        self.config = config
        self._lock = threading.Lock()
        self._view = Graph()
        self._adapters: list = []
        self.reload()

    def reload(self) -> dict:
        graph, adapters = load_all(self.config.sources)
        if self.config.masking:
            # Everything served comes from the masked copy, search included,
            # so a query cannot be used to probe for a hidden value.
            graph = graph.masked_copy(Masker(self.config.mask_patterns))
        with self._lock:
            self._view, self._adapters = graph, adapters
            self._ref_lists = None
        return self.stats()

    def _ref_list_counts(self) -> dict:
        """How many nodes carry each exact reference list, per source and prop.

        Built on first use and dropped on reload. A writer that stamps the whole
        batch it was reading on every node it produces leaves the same list on
        nodes that have nothing to do with each other; counting the copies is
        what lets the panel say so instead of presenting them as sources.
        """
        with self._lock:
            if self._ref_lists is None:
                counts: dict[tuple, int] = {}
                declared = {getattr(a, "name", None): (getattr(a, "refs", {}) or {})
                            for a in self._adapters}
                for node in self._view.nodes.values():
                    for prop in declared.get(node.source, {}):
                        ids = node.props.get(prop)
                        if isinstance(ids, list) and ids:
                            key = (node.source, prop, frozenset(map(str, ids)))
                            counts[key] = counts.get(key, 0) + 1
                self._ref_lists = counts
            return self._ref_lists

    @property
    def graph(self) -> Graph:
        with self._lock:
            return self._view

    def get_graph(self, node_types=None, edge_types=None, sources=None,
                  limit: int | None = None, compact: bool = False,
                  max_links: int | None = None) -> dict:
        sub = ops.subgraph(self.graph, node_types, edge_types, sources)
        return self._sampled_dict(sub, limit, compact, max_links)

    def neighbors(self, node_id: str, depth: int = 1, edge_types=None,
                  limit: int | None = None, compact: bool = False,
                  max_links: int | None = None) -> dict:
        sub = ops.neighbors(self.graph, node_id, depth, edge_types)
        return self._sampled_dict(sub, limit, compact, max_links)

    def _sampled_dict(self, g: Graph, limit: int | None, compact: bool = False,
                      max_links: int | None = None) -> dict:
        sampled, total = ops.sample(g, limit or self.config.limit)
        out = sampled.to_dict(compact=compact)
        total_links = len(out["links"])
        if max_links is not None and total_links > max_links:
            # Heaviest first when there is a count; otherwise the order they came in.
            out["links"].sort(key=lambda link: -link.get("count", 1))
            out["links"] = out["links"][:max_links]
        out["meta"].update(total_nodes=total, sampled=len(sampled.nodes) < total,
                           total_links=total_links,
                           links_truncated=len(out["links"]) < total_links)
        return out

    def _adapter_of(self, node_id: str):
        name = node_id.partition(":")[0]
        return next((a for a in self._adapters if getattr(a, "name", None) == name), None)

    def _refs_of(self, node_id: str, props: dict) -> dict:
        """Which props of this node hold references, and to how many rows."""
        adapter = self._adapter_of(node_id)
        declared = getattr(adapter, "refs", {}) or {}
        out = {}
        for prop, lookup in declared.items():
            ids = props.get(prop)
            if isinstance(ids, list) and ids:
                out[prop] = {"lookup": lookup, "count": len(ids)}
                source = node_id.partition(":")[0]
                copies = self._ref_list_counts().get((source, prop, frozenset(map(str, ids))), 1)
                # Other nodes carry this exact list: a batch stamp, not provenance. One shared
                # reference is not a batch, though -- two facts learned from the same episode,
                # or the pair of nodes a mentions link rests on, are the ordinary case, and
                # warning about them cried wolf on well-formed graphs. Three is a pattern.
                if copies > 1 and len(ids) >= BATCH_REFS:
                    out[prop]["shared_with"] = copies - 1
        return out

    def lookup(self, node_id: str, prop: str) -> dict:
        """The rows a node's reference property points to, masked like everything else."""
        node = self.graph.nodes.get(node_id)
        if node is None:
            return {"error": f"no node with id '{node_id}'"}
        refs = self._refs_of(node_id, node.props)
        if prop not in refs:
            return {"error": f"'{prop}' is not a reference property"}
        adapter = self._adapter_of(node_id)
        try:
            rows = adapter.lookup(refs[prop]["lookup"], list(node.props[prop]))
        except Exception as exc:  # a lookup must never take the node panel down
            return {"error": f"lookup failed: {exc}"}
        if self.config.masking:
            from .model import _mask_value
            rows = _mask_value(rows, Masker(self.config.mask_patterns))
        return {"prop": prop, "lookup": refs[prop]["lookup"], "rows": rows}

    def provenance(self, node_id: str, edge_type: str = "supersedes", max_sources: int = 50) -> dict:
        """Where a node comes from: the chain of what it replaced (nearest first), what
        replaced it, and its resolved source rows."""
        g = self.graph
        node = g.nodes.get(node_id)
        if node is None:
            return {"error": f"no node with id '{node_id}'"}
        out_edges, in_edges = {}, {}
        for e in g.edges:
            if e.type == edge_type:
                out_edges.setdefault(e.source_id, []).append(e.target_id)
                in_edges.setdefault(e.target_id, []).append(e.source_id)

        def walk(start, step):
            chain, seen, frontier = [], {start}, [start]
            while frontier:
                nxt = []
                for nid in frontier:
                    for other in step.get(nid, []):
                        if other not in seen and other in g.nodes:
                            seen.add(other); chain.append(other); nxt.append(other)
                frontier = nxt
            return chain

        brief = lambda nid: {"id": nid, "label": g.nodes[nid].label, "type": g.nodes[nid].type,
                             "created_at": g.nodes[nid].created_at}
        sources = {}
        refs = self._refs_of(node_id, node.props)
        for prop in refs:
            found = self.lookup(node_id, prop)
            sources[prop] = found.get("rows", [])[:max_sources]
        return {"node": g.node_dict(node),
                "supersedes": [brief(n) for n in walk(node_id, out_edges)],
                "superseded_by": [brief(n) for n in walk(node_id, in_edges)],
                "refs": refs, "sources": sources}

    def get_node(self, node_id: str, compact: bool = False, max_per_type: int = 40) -> dict:
        """One node and its links grouped by type.

        `compact` is for agents: parallel links to the same neighbour merge into
        one entry with a `count`, neighbours shrink to id/label/type, and each
        group keeps its `max_per_type` heaviest entries next to the real `total`.
        """
        g = self.graph
        node = g.nodes.get(node_id)
        if node is None:
            return {"error": f"no node with id '{node_id}'"}
        links: dict[str, list] = {}
        for e in g.edges:
            if e.source_id == node_id:
                direction, other = "out", e.target_id
            elif e.target_id == node_id:
                direction, other = "in", e.source_id
            else:
                continue
            links.setdefault(e.type, []).append(
                {"direction": direction, "node": g.node_dict(g.nodes[other]), "props": e.props})
        if not compact:
            return {"node": g.node_dict(node), "links": links,
                    "refs": self._refs_of(node_id, node.props)}

        groups = {}
        for kind, entries in links.items():
            merged: dict[tuple, dict] = {}
            for entry in entries:
                other = entry["node"]
                slot = merged.setdefault((entry["direction"], other["id"]), {
                    "direction": entry["direction"], "count": 0,
                    "node": {"id": other["id"], "label": other["label"], "type": other["type"]}})
                slot["count"] += 1
            ranked = sorted(merged.values(), key=lambda item: -item["count"])
            groups[kind] = {"total": len(ranked), "items": ranked[:max_per_type]}
        return {"node": g.node_dict(node), "links": groups}

    def search(self, query: str, limit: int = 50) -> dict:
        """The source's own search when it has one (`mode: recall`), else text search.

        Recall hits keep the endpoint's order and carry its text as `snippet`. A
        hit with no node in the graph is kept and marked `unlinked`. If recall
        fails or finds nothing, text search answers and `notice` says why.
        """
        g = self.graph
        notices = []
        if query.strip() and not self.config.masking:
            hits, answers = [], []
            for adapter in self._adapters:
                if not hasattr(adapter, "search"):
                    continue
                try:
                    found = adapter.search(query)
                    if isinstance(found, dict):  # hits plus a written answer
                        if found.get("answer"):
                            answers.append(found["answer"])
                        found = found.get("hits", [])
                    hits += found
                except SearchUnavailable as exc:
                    notices.append(f"{exc}; used text search")
            if hits or answers:
                matches, seen = [], set()
                for hit in hits:
                    if hit["id"] in seen:
                        continue
                    seen.add(hit["id"])
                    node = g.nodes.get(hit["id"])
                    if node is not None:
                        match = g.node_dict(node)
                    else:
                        source, _, native = hit["id"].partition(":")
                        match = {"id": hit["id"], "label": native, "type": "unlinked",
                                 "source": source, "props": {}, "created_at": None,
                                 "degree": 0, "unlinked": True}
                    match["snippet"] = hit.get("text", "")
                    matches.append(match)
                return {"query": query, "mode": "recall", "matches": matches[:limit],
                        "answer": "\n\n".join(answers), "notice": "; ".join(notices)}
        return {"query": query, "mode": "text",
                "matches": [g.node_dict(n) for n in ops.search(g, query, limit)],
                "answer": "", "notice": "; ".join(notices)}

    def path(self, start: str, end: str, edge_types=None, compact: bool = False) -> dict:
        """How two nodes are connected: the shortest chain between them and its links."""
        g = self.graph
        ids = ops.shortest_path(g, start, end, edge_types)
        if not ids:
            return {"found": False, "steps": None, "nodes": [], "links": []}
        steps = set(zip(ids, ids[1:])) | set(zip(ids[1:], ids))
        wanted = set(edge_types) if edge_types else None
        links, seen = [], set()
        for e in g.edges:
            key = (e.source_id, e.target_id, e.type)
            if (e.source_id, e.target_id) in steps and key not in seen \
                    and (wanted is None or e.type in wanted):
                seen.add(key)
                links.append({"source": e.source_id, "target": e.target_id, "type": e.type})
        nodes = [g.node_dict(g.nodes[nid]) for nid in ids]
        if compact:
            nodes = [{"id": n["id"], "label": n["label"], "type": n["type"]} for n in nodes]
        return {"found": True, "steps": len(ids) - 1, "nodes": nodes, "links": links}

    def coverage(self) -> dict | None:
        """The last recall-coverage pass for these sources, if one was run (`graphview coverage`)."""
        from . import coverage
        return coverage.load(self.config.sources)

    def worklist(self) -> dict:
        """Unlinked nodes, islands and likely duplicates: what to go and fix at the source."""
        return ops.worklist(self.graph)

    def worklist_markdown(self) -> str:
        """The worklist as a checklist. An export is a deliberate act, so it is also
        what adds a line to the history; merely looking at the worklist does not."""
        from . import history
        from .worklist import to_markdown
        worklist = self.worklist()
        title = ", ".join(s.get("name", "?") for s in self.config.sources)
        try:
            entries = history.record(self.config.sources, worklist["summary"])
        except OSError:  # a read-only home must not cost the user their export
            entries = []
        return to_markdown(worklist, title, entries)

    def worklist_history(self) -> list[dict]:
        from . import history
        return [{k: v for k, v in e.items() if k != "key"}
                for e in history.load(self.config.sources)]

    def stats(self) -> dict:
        return ops.stats(self.graph)

    def groups(self, max_ids: int | None = None) -> dict:
        """What's in here: the named sets of nodes the sources declare (things, folders,
        recurring names, categories), with the plain names from `names:` applied."""
        g = self.graph
        names = self.config.names
        out = []
        for adapter in list(self._adapters):
            declare = getattr(adapter, "groups", None)
            if not callable(declare):
                continue
            try:
                declared = declare()
            except Exception as exc:  # a broken groups query must not take the panel down
                g.warnings.append(f"{getattr(adapter, 'name', '?')}: groups: {exc}")
                continue
            for item in declared:
                ids = [i for i in item.get("members", []) if i in g.nodes]
                if not ids:
                    continue
                kind, field, name = item.get("kind", "group"), item.get("field", ""), item["name"]
                if kind == "thing":
                    name = names.get(name, name)
                elif kind == "category" and field and name.startswith(f"{field}: "):
                    name = f"{names.get(field, field)}: {name[len(field) + 2:]}"
                out.append({"name": name, "kind": kind, "field": field, "count": len(ids),
                            "ids": ids if max_ids is None else ids[:max_ids]})
        return {"groups": out, "names": dict(names)}

    def list_types(self) -> dict:
        s = self.stats()

        def colored(counts: dict, offset: int) -> dict:
            return {name: {"count": counts[name],
                           "color": self.config.colors.get(
                               name, PALETTE[(i + offset) % len(PALETTE)])}
                    for i, name in enumerate(sorted(counts))}

        return {"node_types": colored(s["by_node_type"], 0),
                "edge_types": colored(s["by_edge_type"], 5),
                "sources": colored(s["by_source"], 8)}
