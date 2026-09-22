"""Recall coverage: run many questions through a memory's search, see what it reaches.

Two things come out of a pass:

- how often each node was retrieved, and so which part of the memory no
  question ever reaches. If that part has a shape (the rim, one island, one
  period), that is a diagnosis a benchmark score does not give;
- for questions that say what they expect, whether the expected text was among
  what came back. A wrong answer with the right fact retrieved is a generation
  problem; without it, a retrieval problem.

Questions come from files (a benchmark's cases) and from probes: one question
per node of a type, made of its name, which measures what can be reached
starting from the entities.

The report is saved in the user's own folder, next to the worklist history. It
holds the questions and node ids, so treat it like the memory it describes.
"""

from __future__ import annotations

import json
import os
import re
from datetime import date
from pathlib import Path

from . import history
from .model import Graph
from .worklist import TEXT_KEYS

QUESTION_FIELDS = ("question", "query", "q")


def load_questions(paths) -> list[dict]:
    """From .json (a list of strings or objects), .jsonl, or plain text, one per line."""
    loaded = []
    for path in map(Path, paths):
        text = path.read_text(encoding="utf-8")
        if path.suffix == ".json":
            rows = json.loads(text)
            rows = rows if isinstance(rows, list) else rows.get("questions", [])
        elif path.suffix == ".jsonl":
            rows = [json.loads(line) for line in text.splitlines() if line.strip()]
        else:
            rows = [line.strip() for line in text.splitlines()
                    if line.strip() and not line.lstrip().startswith("#")]
        for row in rows:
            if isinstance(row, str):
                question, expected = row, []
            elif isinstance(row, dict):
                question = next((row[f] for f in QUESTION_FIELDS if isinstance(row.get(f), str)), None)
                expected = _groups(row.get("expected"))
            else:
                continue
            if question and question.strip():
                loaded.append({"question": question.strip(), "expected": expected, "origin": path.name})
    return loaded


def _groups(expected) -> list[list[str]]:
    """Normalise to groups of alternatives: every group must match, any alternative will do.

    That is the shape benchmark cases use (`[["8766"], ["harbour", "port"]]`). A flat
    list of strings is read as one group each, a single string as one group of one.
    """
    if not expected:
        return []
    if isinstance(expected, str):
        return [[expected]]
    return [[str(a) for a in group] if isinstance(group, (list, tuple)) else [str(group)]
            for group in expected]


def satisfied(expected: list[list[str]], text: str) -> bool | None:
    """Whole tokens only: `8766` is not found inside `18766`. None when nothing is expected."""
    if not expected:
        return None

    def present(words: str) -> bool:
        return re.search(rf"(?<!\w){re.escape(words)}(?!\w)", text, re.IGNORECASE) is not None

    return all(any(present(alternative) for alternative in group) for group in expected)


def probe_questions(g: Graph, node_type: str, limit: int | None = None) -> list[dict]:
    """One question per node of a type: its name as words. Best connected first."""
    nodes = sorted((n for n in g.nodes.values() if n.type == node_type),
                   key=lambda n: (-g.degree(n.id), n.label))
    probes = []
    for node in nodes[:limit]:
        words = " ".join(re.findall(r"[^\W_]+", node.label))
        if words:
            probes.append({"question": words, "expected": [], "origin": f"probe:{node_type}"})
    return probes


def _text_of(match: dict) -> str:
    parts = [match.get("snippet") or "", match.get("label") or ""]
    parts += [str(match.get("props", {}).get(key) or "") for key in TEXT_KEYS]
    return " ".join(parts)


def run(service, questions: list[dict], limit: int = 50, progress=None) -> dict:
    hits: dict[str, int] = {}
    rows, modes = [], set()
    for done, item in enumerate(questions, start=1):
        result = service.search(item["question"], limit)
        modes.add(result.get("mode", "text"))
        matches = [m for m in result["matches"] if not m.get("unlinked")]
        for match in matches:
            hits[match["id"]] = hits.get(match["id"], 0) + 1
        # Two levels, because the gap between them is the finding: the expected
        # text can be in the facts that were listed, or only in the answer composed
        # around them (entity cards, other memory levels), or nowhere.
        retrieved = satisfied(item["expected"], " ".join(_text_of(m) for m in result["matches"]))
        in_answer = satisfied(item["expected"], result.get("answer") or "")
        rows.append({"question": item["question"], "origin": item["origin"],
                     "expected": item["expected"], "retrieved": retrieved, "in_answer": in_answer,
                     "hits": [m["id"] for m in matches]})
        if progress:
            progress(done, len(questions))

    total = len(service.graph.nodes)
    judged = [r for r in rows if r["retrieved"] is not None]
    # A search that returns facts will never return an entity: counting entities as
    # "never retrieved" would drown the finding. Reach is reported per type, for the
    # types the search returned at least once.
    nodes = getattr(service.graph, "nodes", {})
    kinds = {nid: getattr(node, "type", None) for nid, node in nodes.items()}
    returned = {kinds.get(nid) for nid in hits} - {None}
    reach = {kind: [sum(1 for nid in hits if kinds.get(nid) == kind),
                    sum(1 for k in kinds.values() if k == kind)] for kind in sorted(returned)}
    return {
        "date": date.today().isoformat(),
        "summary": {"questions": len(rows), "nodes": total, "ever_retrieved": len(hits),
                    "never_retrieved": total - len(hits), "with_expectation": len(judged),
                    "expected_retrieved": sum(1 for r in judged if r["retrieved"]),
                    "expected_in_answer": sum(1 for r in judged if r["in_answer"]),
                    "mode": "recall" if "recall" in modes else "text",
                    "reach_by_type": reach},
        "hits": hits,
        "questions": rows,
    }


def _file(sources: list[dict]) -> Path:
    home = os.environ.get("GRAPHVIEW_HOME") or str(Path.home() / ".graphview")
    return Path(home) / f"coverage-{history.key(sources)}.json"


def save(sources: list[dict], report: dict) -> Path:
    file = _file(sources)
    file.parent.mkdir(parents=True, exist_ok=True)
    draft = file.with_suffix(".tmp")
    draft.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    draft.replace(file)
    return file


def load(sources: list[dict]) -> dict | None:
    file = _file(sources)
    if not file.exists():
        return None
    try:
        return json.loads(file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
