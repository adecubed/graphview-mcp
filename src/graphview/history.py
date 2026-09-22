"""A line of counts per worklist export, so the trend shows without diffing files.

The one thing graphview writes, and it writes it to the user's own folder
(`~/.graphview`, or `GRAPHVIEW_HOME`), never to a source. A line holds the date
and five numbers. The sources are identified by a hash, so no path or name from
the graph ends up in the file.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import date
from pathlib import Path

COUNTS = ("nodes", "unlinked", "islands", "island_nodes", "duplicates", "hubs")


def _file() -> Path:
    home = os.environ.get("GRAPHVIEW_HOME") or str(Path.home() / ".graphview")
    return Path(home) / "worklist-history.jsonl"


def key(sources: list[dict]) -> str:
    """The same sources, in any order, are the same memory."""
    parts = sorted(f"{s.get('name')}|{s.get('adapter')}|{s.get('path')}" for s in sources)
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()[:16]


def _read(file: Path) -> list[dict]:
    if not file.exists():
        return []
    entries = []
    for line in file.read_text(encoding="utf-8").splitlines():
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue  # a damaged line costs one data point, not the history
        if isinstance(entry, dict) and "key" in entry and "date" in entry:
            entries.append(entry)
    return entries


def load(sources: list[dict]) -> list[dict]:
    mine = key(sources)
    return sorted((e for e in _read(_file()) if e["key"] == mine), key=lambda e: e["date"])


def record(sources: list[dict], summary: dict, today: str | None = None) -> list[dict]:
    """Add today's counts (replacing an earlier export of the same day). Returns this memory's history."""
    file, mine, day = _file(), key(sources), today or date.today().isoformat()
    entry = {"key": mine, "date": day, **{name: int(summary.get(name, 0)) for name in COUNTS}}
    kept = [e for e in _read(file) if not (e["key"] == mine and e["date"] == day)]
    file.parent.mkdir(parents=True, exist_ok=True)
    draft = file.with_suffix(".tmp")
    draft.write_text("".join(json.dumps(e) + "\n" for e in kept + [entry]), encoding="utf-8")
    draft.replace(file)  # whole file or nothing: a crash cannot leave half a history
    return load(sources)
