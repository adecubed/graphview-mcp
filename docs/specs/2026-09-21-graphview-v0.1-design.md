# graphview-mcp v0.1 — design

Date: 2026-09-21. Working name, may change.

## Goal

An open-source MCP server that shows any graph-shaped memory as a full-screen,
rotatable 3D graph with a "ask the memory" text box. Read-only. The author's own
agent memory is one adapter among several, not a special case.

## In scope for v0.1

- Adapters: markdown folder with `[[wikilinks]]` (Obsidian), `memory.json`
  (Anthropic Memory MCP), SQLite with a declarative YAML mapping.
- MCP server (stdio) with graph tools plus `open_viewer`.
- Full-screen 3D viewer: colour by type, node size by degree, click for detail
  and neighbours, filters by type and source, text search that lights up the
  matches, flies the camera to them and dims the rest.
- Optional label masking (default regexes: email, IBAN, US SSN, phone).

## Out of scope (roadmap)

SQL auto-introspection, Postgres/DuckDB/Neo4j/GraphML/CSV, the MCP-to-MCP
`graph_schema`/`graph_query` contract, inline MCP Apps view, time-lapse,
natural-language recall, a desktop shell.
Hooks kept in the interfaces: optional adapter `search`, standard `created_at`.

## Architecture

```
sources -> ADAPTER -> CORE (canonical model) -> SERVER -> VIEWER
```

1. **Core** (pure Python, no MCP or web dependency).
   `Node(id, label, type, source, props, created_at)`,
   `Edge(source_id, target_id, type, props)`, `Graph`.
   Operations: filtered subgraph, neighbours to depth N, stats, text search,
   sampling above a limit (keep highest-degree nodes, report how many were cut).
   Masking is applied on output only, never to internal data.
2. **Adapters**. Interface: `load() -> Graph`; optional `search(query)` and
   `node_detail(id)`. One file per adapter, chosen by configuration. Several
   sources can load together; node ids are prefixed with the source name and
   every node carries `source`. SQLite is always opened with `mode=ro`.
   The graph is loaded in memory at start and reloaded on request.
3. **Server**. One process, two faces over the same core: MCP tools on stdio
   (`get_graph`, `get_node`, `neighbors`, `search`, `graph_stats`, `list_types`,
   `open_viewer`) and a small HTTP JSON API on `127.0.0.1` that also serves the
   viewer's static files. Read-only. A random token is required on every API
   call; `open_viewer` opens the browser with it.
4. **Viewer**. Static page, one JS bundle (esbuild), no framework. Three.js via
   `3d-force-graph`. Knows only the HTTP API and the canonical model. Modules:
   `api`, `scene`, `state`, `panels`. The built bundle ships inside the Python
   package so users do not need Node.

## Viewer behaviour

Full-viewport scene on a near-black background; translucent overlay panels
(filters left, detail right, status top, query box bottom).
State machine `idle -> searching -> results -> focus`; `Esc` goes back one
state. `results`: matches glow, the rest drops to 10% opacity, the camera frames
the matches. `focus`: camera flies to the node, neighbours highlighted, detail
panel opens. Labels only on large or nearby nodes. Links coloured by type with
directional particles.

## Configuration

`graphview.yaml`: list of sources (adapter, path, mapping), colour overrides,
masking on/off, node limit. Without a file: `graphview <path>` guesses the
adapter from the path (folder -> wikilinks, `.json` -> memory, `.db`/`.sqlite`
needs a mapping).

SQLite mapping:

```yaml
sources:
  - name: brain
    adapter: sqlite
    path: /path/to/brain.db
    nodes:
      - table: entities          # or query: "SELECT ..."
        id: id
        label: name
        type: {column: kind}     # or a fixed string
        created_at: created_at
        props: [email, notes]
    edges:
      - table: links
        from: from_id
        to: to_id
        type: {column: link_type}
```

## Errors

A source that fails to open does not block the others; the problem shows in the
status bar and in `graph_stats`. Edges pointing at missing nodes are dropped and
counted. Above the node limit the graph is sampled with a "showing N of M" note.

## Testing

pytest with small fixtures (mini vault, `memory.json`, SQLite built in the
test), test first. HTTP API tests including token rejection. Viewer checked by
hand in a browser on an example vault. Final run on a real memory with masking
on.

## Decisions

Python server (same language as the memory it was built against). Browser as the first shell;
Electron only later, inside the existing console. Licence Apache-2.0.
