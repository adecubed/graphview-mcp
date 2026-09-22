"""Markdown folder with [[wikilinks]] (an Obsidian vault, or anything like it)."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

import yaml

from ..model import Edge, Graph, Node

FENCED_CODE = re.compile(r"```.*?```|~~~.*?~~~", re.DOTALL)
INLINE_CODE = re.compile(r"`[^`\n]*`")
WIKILINK = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|[^\]]*)?\]\]")
TAG = re.compile(r"(?<![\w/#])#([A-Za-z][\w/-]*)")


def _split_frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    try:
        meta = yaml.safe_load(text[3:end])
    except yaml.YAMLError:
        meta = None
    body = text[end + 4:]
    return (meta if isinstance(meta, dict) else {}), body


class WikilinksAdapter:
    def __init__(self, source: dict | str, path: str | Path | None = None) -> None:
        # built from a source dict ({name, adapter, path}) or, in tests, from (name, path)
        if isinstance(source, dict):
            source, path = source["name"], source["path"]
        name = source
        self.name = name
        self.root = Path(path)

    def _nid(self, native: str) -> str:
        return f"{self.name}:{native}"

    def load(self) -> Graph:
        g = Graph()
        notes: dict[str, str] = {}  # relative path without .md -> body
        for file in sorted(self.root.rglob("*.md")):
            rel = file.relative_to(self.root)
            if any(part.startswith(".") for part in rel.parts):
                continue
            key = rel.with_suffix("").as_posix()
            try:
                text = file.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                g.warnings.append(f"{self.name}: cannot read {rel}: {exc}")
                continue
            meta, body = _split_frontmatter(text)
            notes[key] = body
            props = {k: v for k, v in meta.items()
                     if k not in ("type", "tags", "created", "date")}
            props["path"] = rel.as_posix()
            # When the note says when it was written, believe it over the file
            # time, which a sync or a checkout resets for the whole vault at once.
            written = meta.get("created") or meta.get("date")
            if written is not None:
                created = written.isoformat() if hasattr(written, "isoformat") else str(written)
            else:
                modified = datetime.fromtimestamp(file.stat().st_mtime, tz=timezone.utc)
                created = modified.isoformat(timespec="seconds")
            g.add_node(Node(self._nid(key), rel.stem, str(meta.get("type") or "note"),
                            self.name, props, created))
            for tag in self._as_list(meta.get("tags")):
                self._add_tag(g, key, str(tag).lstrip("#"))

        by_path = {k.lower(): k for k in notes}
        by_name: dict[str, str] = {}
        for k in notes:  # sorted already: first match wins on duplicate names
            by_name.setdefault(k.rsplit("/", 1)[-1].lower(), k)

        for key, body in notes.items():
            clean = INLINE_CODE.sub("", FENCED_CODE.sub("", body))
            for match in WIKILINK.finditer(clean):
                target = match.group(1).strip()
                wanted = target.lower().removesuffix(".md")
                found = by_path.get(wanted) or by_name.get(wanted.rsplit("/", 1)[-1])
                if found is None:
                    found = f"?{target}"
                    if self._nid(found) not in g.nodes:
                        g.add_node(Node(self._nid(found), target, "missing", self.name))
                g.add_edge(Edge(self._nid(key), self._nid(found), "links_to"))
            for match in TAG.finditer(clean):
                self._add_tag(g, key, match.group(1))
        g.finalize()
        return g

    @staticmethod
    def _as_list(value) -> list:
        if value is None:
            return []
        return value if isinstance(value, list) else [value]

    def _add_tag(self, g: Graph, note_key: str, tag: str) -> None:
        tag_id = self._nid(f"#{tag}")
        if tag_id not in g.nodes:
            g.add_node(Node(tag_id, f"#{tag}", "tag", self.name))
        edge = Edge(self._nid(note_key), tag_id, "tagged")
        if edge not in g.edges:
            g.add_edge(edge)
