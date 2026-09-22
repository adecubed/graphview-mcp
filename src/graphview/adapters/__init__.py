"""Adapters turn a source into the canonical Graph.

An adapter is any object with a `name` and a `load() -> Graph`. It may also
offer `search(query) -> [{"id": node id, "text": snippet}]`, best first, when
the source has a better search than plain text matching. Any source gets one
from a `search:` block in its mapping (see http_search.py).
"""

from __future__ import annotations

import importlib
from typing import Protocol

from ..model import Graph


class Adapter(Protocol):
    name: str

    def load(self) -> Graph: ...


# adapter name in graphview.yaml -> "module:Class". The class takes the whole
# source dict. Add a line here to add an adapter; nothing else needs to know.
REGISTRY: dict[str, str] = {
    "wikilinks": "graphview.adapters.wikilinks:WikilinksAdapter",
    "memory_json": "graphview.adapters.memory_json:MemoryJsonAdapter",
    "sqlite": "graphview.adapters.sqlite_map:SqliteMapAdapter",
}


def build_adapter(source: dict) -> Adapter:
    kind = str(source.get("adapter", ""))
    target = REGISTRY.get(kind)
    if target is None:
        raise ValueError(f"unknown adapter '{kind}' (known: {', '.join(sorted(REGISTRY))})")
    module_name, _, class_name = target.partition(":")
    module = importlib.import_module(module_name)
    return getattr(module, class_name)(source)


def load_all(sources: list[dict]) -> tuple[Graph, list[Adapter]]:
    """Load every source; one that fails becomes a warning, not a crash."""
    merged, adapters = Graph(), []
    for source in sources:
        label = source.get("name", "?")
        try:
            adapter = build_adapter(source)
            merged.merge(adapter.load())
            adapters.append(adapter)
        except Exception as exc:  # any source problem must not take the others down
            merged.warnings.append(f"{label}: {exc}")
            continue
        if source.get("search"):
            try:
                from ..http_search import HttpSearch
                adapter.search = HttpSearch(label, source["search"]).search
            except ValueError as exc:  # the graph still loads; only its search is plain
                merged.warnings.append(f"{label}: search: {exc}")
    merged.finalize()
    return merged, adapters
