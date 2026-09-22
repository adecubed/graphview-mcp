# Contributing

Thank you for looking. Three kinds of contribution are especially welcome, in
this order: telling us what you could not see in your own memory (an issue),
an adapter for a memory we do not read yet, and comments on the open contract
proposal in `docs/graph-contract.md`.

## Running it

```bash
uv sync
uv run pytest                      # ~140 tests, all on temporary files
cd viewer-src && npm ci && npm run build   # only if you touch the viewer
```

The built viewer (`src/graphview/viewer/app.js`) is committed, so Python users
never need Node. CI rebuilds it and fails if it drifts from `viewer-src/`: if
you change the viewer, commit the rebuilt bundle with it. `?debug=1` on the
viewer URL exposes `window.__graphview` (the force-graph object and its data)
for poking at from the console.

## How it fits together

```
sources -> adapters -> canonical Graph -> GraphService -> HTTP API -> viewer
                                                      \-> MCP tools
```

- `model.py`: `Node(id, label, type, source, props, created_at)`,
  `Edge(source_id, target_id, type, props)`, `Graph`. Everything downstream
  knows only this.
- `ops.py`: subgraph, neighbours, shortest path, sampling, text search.
- `worklist.py`, `coverage.py`, `history.py`: the health lists, the recall
  coverage pass, and the one file graphview writes (`~/.graphview`).
- `service.py`: one class both faces call into. Masking happens here, on the
  way out, never on stored data.
- `http_api.py`, `mcp_server.py`, `cli.py`: the faces.
- `viewer-src/`: `api.js` (talks to the HTTP API), `state.js` (idle → searching
  → results → focus), `scene.js` (Three.js through 3d-force-graph), `panels.js`
  (the DOM), `main.js` (wires them). No framework.

## Writing an adapter

An adapter is a class with a `name` and a `load()` that returns a `Graph`. It
is built from the source dict in `graphview.yaml`, so it sees whatever keys the
user put there. Node ids must be `"<source name>:<native id>"`, so several
sources can share a view. Register it with one line in
`src/graphview/adapters/__init__.py`.

The whole of a CSV edge-list adapter:

```python
import csv
from pathlib import Path

from ..model import Edge, Graph, Node


class CsvEdgesAdapter:
    """A CSV with columns source,target[,type]: every name becomes a node."""

    def __init__(self, source: dict) -> None:
        self.name = source["name"]
        self.path = Path(source["path"])

    def load(self) -> Graph:
        g = Graph()
        with self.path.open(encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                for end in (row["source"], row["target"]):
                    g.add_node(Node(f"{self.name}:{end}", end, "node", self.name))
                g.add_edge(Edge(f"{self.name}:{row['source']}", f"{self.name}:{row['target']}",
                                row.get("type") or "linked"))
        g.finalize()          # drops edges to missing nodes and counts them
        return g
```

Things worth knowing:

- Put a load problem in `g.warnings` and carry on; raise only if nothing can
  be loaded. A broken source must not take the others down.
- `created_at` is an ISO string; the time-lapse and "colour by" read it. Any
  numeric or ISO-dated prop becomes something to colour by, for free.
- A prop named `content`, `text`, `description` or `summary` is shown as the
  node's text in the panel.
- Optional methods the service will use if present: `search(query)` returning
  `[{"id": node id, "text": snippet}]` (or `{"hits": [...], "answer": str}`)
  when the source has a better search than text matching; `lookup(name, ids)`
  and a `refs` dict (`{prop: lookup name}`) for provenance. The SQLite adapter
  shows both.
- Open every source read-only and say so in the docstring. The point of the
  whole tool is that it can be pointed at anything without fear.

Tests live in `tests/`, one file per adapter, on small fixtures built inside
the test. Write the failing test first; it keeps the adapter honest about what
it promises.

## Conventions

- Code, comments, commit messages and docs in English. Comments say why, not
  what.
- Read-only is a promise, not a default. Nothing writes to a source, ever.
  graphview's own files go under `~/.graphview` and hold counts and ids, not
  content.
- Answers to the agent are sized for a context window (see `mcp_server.py`);
  the viewer gets the full data.
- Every feature the README describes must be visible on `examples/` without
  a real memory. If you add one, extend `examples/memory/make_memory.py` so
  the invented memory shows it.

## The open proposal

`docs/graph-contract.md` describes two tools a memory server could expose so
that this viewer (or any other) reads it without an adapter. It is a question,
not a spec. If you run a memory server, that is the document we would most
like your opinion on.
