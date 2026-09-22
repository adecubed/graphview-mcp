"""The worklist: what in a graph probably wants fixing at its source.

Three lists, all read straight off the graph's shape:

- unlinked: nodes with no links at all (the viewer's rim);
- islands: small groups cut off from the main body;
- duplicates: same-type nodes whose names differ only in separators, case,
  accents, or a letter or two. Likely the same thing written twice.

The viewer never fixes anything. This is the list you take to whatever does.
"""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from datetime import date
from difflib import SequenceMatcher

from .model import Graph, Node

ISLAND_MAX = 12          # the viewer uses the same number
SIMILARITY = 0.88
MIN_NAME = 5             # shorter names are too easy to confuse: "bm25" and "bm26"
MAX_DUPLICATES = 500
TEXT_KEYS = ("content", "text", "description", "summary")
HUB_MIN_NEIGHBOURS = 25   # below this a graph is too small for "a large share" to mean much
HUB_SHARE = 0.05          # linked to one node in twenty


def _plain(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return " ".join(re.findall(r"[a-z0-9]+", folded))


def _brief(g: Graph, node: Node) -> dict:
    text = next((str(node.props[k]) for k in TEXT_KEYS if node.props.get(k)), "")
    text = " ".join(text.split())
    return {"id": node.id, "label": node.label, "type": node.type, "source": node.source,
            "degree": g.degree(node.id), "created_at": node.created_at,
            "text": text if len(text) <= 160 else text[:160].rstrip() + "…"}


def _components(g: Graph) -> list[list[str]]:
    adjacent: dict[str, set[str]] = {nid: set() for nid in g.nodes}
    for e in g.edges:
        adjacent[e.source_id].add(e.target_id)
        adjacent[e.target_id].add(e.source_id)
    seen: set[str] = set()
    groups = []
    for start in g.nodes:
        if start in seen:
            continue
        seen.add(start)
        stack, group = [start], []
        while stack:
            nid = stack.pop()
            group.append(nid)
            for other in adjacent[nid] - seen:
                seen.add(other)
                stack.append(other)
        groups.append(sorted(group))
    return groups


def _duplicates(g: Graph) -> list[dict]:
    by_type: dict[str, list[tuple[str, Node]]] = defaultdict(list)
    for node in g.nodes.values():
        name = _plain(node.label)
        if len(name) >= MIN_NAME:
            by_type[node.type].append((name, node))

    pairs = []
    for named in by_type.values():
        # Near-equal names nearly always share their first letters, so only nodes
        # in the same small bucket are compared: all pairs would be quadratic.
        buckets: dict[str, list[tuple[str, Node]]] = defaultdict(list)
        for name, node in named:
            buckets[name.replace(" ", "")[:2]].append((name, node))
        for bucket in buckets.values():
            for i, (name_a, a) in enumerate(bucket):
                for name_b, b in bucket[i + 1:]:
                    if name_a == name_b:
                        score = 1.0
                    else:
                        matcher = SequenceMatcher(None, name_a, name_b, autojunk=False)
                        if matcher.quick_ratio() < SIMILARITY:
                            continue
                        score = round(matcher.ratio(), 3)
                        if score < SIMILARITY:
                            continue
                    first, second = sorted((a, b), key=lambda n: n.id)
                    pairs.append({"a": _brief(g, first), "b": _brief(g, second),
                                  "similarity": score})
    pairs.sort(key=lambda p: (-p["similarity"], p["a"]["id"], p["b"]["id"]))
    return pairs[:MAX_DUPLICATES]


def _hubs(g: Graph) -> list[dict]:
    """Nodes linked to a large share of the graph.

    Some are real hubs. Others are generic words (the owner's name, the product,
    "project") that got extracted as entities: they tell nothing apart and pull
    noise into every search. Neighbours are counted once, however many links.
    """
    neighbours: dict[str, set[str]] = defaultdict(set)
    for e in g.edges:
        if e.source_id != e.target_id:
            neighbours[e.source_id].add(e.target_id)
            neighbours[e.target_id].add(e.source_id)
    floor = max(HUB_MIN_NEIGHBOURS, HUB_SHARE * len(g.nodes))
    hubs = [{**_brief(g, g.nodes[nid]), "neighbours": len(others),
             "share": round(len(others) / len(g.nodes), 3)}
            for nid, others in neighbours.items() if len(others) >= floor]
    return sorted(hubs, key=lambda h: (-h["neighbours"], h["id"]))


def build(g: Graph) -> dict:
    groups = _components(g)
    biggest = max((len(group) for group in groups), default=0)
    unlinked = [_brief(g, g.nodes[group[0]]) for group in groups
                if len(group) == 1 and biggest > 1]
    islands = [[_brief(g, g.nodes[nid]) for nid in group] for group in groups
               if 1 < len(group) <= ISLAND_MAX and len(group) < biggest]
    unlinked.sort(key=lambda n: n["id"])
    islands.sort(key=lambda island: (-len(island), island[0]["id"]))
    duplicates = _duplicates(g)
    hubs = _hubs(g)
    return {
        "summary": {"nodes": len(g.nodes), "unlinked": len(unlinked), "islands": len(islands),
                    "island_nodes": sum(len(i) for i in islands), "duplicates": len(duplicates),
                    "hubs": len(hubs)},
        "duplicates": duplicates, "hubs": hubs, "islands": islands, "unlinked": unlinked,
    }


def _trend(history: list[dict]) -> list[str]:
    """The last exports as a table, and what changed since the one before."""
    if len(history) < 2:
        return []
    lines = ["## Trend", "", "| date | nodes | duplicates | islands | unlinked |",
             "|---|---|---|---|---|"]
    for e in history[-12:]:
        lines.append(f"| {e['date']} | {e['nodes']} | {e['duplicates']} | {e['islands']} | {e['unlinked']} |")
    before, now = history[-2], history[-1]
    change = ", ".join(f"{name} {now[name] - before[name]:+d}" if now[name] != before[name]
                       else f"{name} 0" for name in ("duplicates", "islands", "unlinked"))
    return lines + ["", f"Since {before['date']}: {change}.", ""]


def to_markdown(worklist: dict, title: str = "", history: list[dict] | None = None) -> str:
    s = worklist["summary"]
    lines = [f"# Worklist: {title}" if title else "# Worklist", "",
             f"{date.today().isoformat()}. {s['nodes']} nodes: {s['duplicates']} likely duplicates, "
             f"{s['islands']} islands ({s['island_nodes']} nodes), {s['unlinked']} unlinked.", "",
             "Names are in backticks exactly as the source has them.", ""]
    lines += _trend(history or [])

    lines += [f"## Likely duplicates ({s['duplicates']})", "",
              "Same type, near-equal names. `=` differs only in separators, case or accents.", ""]
    for pair in worklist["duplicates"]:
        sign = "=" if pair["similarity"] == 1.0 else "≈"
        note = "" if pair["similarity"] == 1.0 else f", {pair['similarity']:.2f}"
        lines.append(f"- [ ] `{pair['a']['label']}` {sign} `{pair['b']['label']}` "
                     f"({pair['a']['type']}{note}; {pair['a']['degree']} and {pair['b']['degree']} links)")

    hubs = worklist.get("hubs", [])
    lines += ["", f"## Very connected ({len(hubs)})", "",
              "Linked to a large share of the graph. A real hub is fine. A generic word",
              "extracted as an entity tells nothing apart and adds noise to every search:",
              "a candidate for the extractor's stop list.", ""]
    for hub in hubs:
        lines.append(f"- [ ] `{hub['label']}` ({hub['type']}): linked to {hub['neighbours']} nodes, "
                     f"{hub['share']:.0%} of the graph")

    lines += ["", f"## Islands ({s['islands']})", "",
              "Small groups with no link to the main body. Often one missing link, or a",
              "name that should be an alias of something in the middle.", ""]
    for island in worklist["islands"]:
        lines.append("- [ ] " + ", ".join(f"`{n['label']}`" for n in island))

    lines += ["", f"## Unlinked ({s['unlinked']})", "", "Nodes with no links at all.", ""]
    for node in worklist["unlinked"]:
        tail = f": {node['text']}" if node["text"] else ""
        lines.append(f"- [ ] `{node['label']}` ({node['type']}){tail}")
    return "\n".join(lines) + "\n"
