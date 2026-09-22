# A graph contract for memory servers: a proposal, and questions

Status: proposal, not implemented. Comments wanted, in an issue.

## The problem

Every agent memory keeps a graph, and every one keeps it differently: a SQLite
file, a Neo4j database, a JSON file, a service behind an HTTP API. A viewer
that wants to show them needs an adapter per memory, and the adapter needs to
know the schema. That works (this repository has three), but it does not scale
past the memories the viewer's authors have seen.

The memories that are MCP servers already speak a protocol the viewer can
speak. If they exposed a small, common set of tools over their graph, any
viewer could read any of them, and the memory would stay the only thing that
knows its own schema.

## The proposal

Two tools, in the memory server's own tool list, with the canonical shapes this
viewer uses internally. Two more are optional.

### `graph_schema()`

What is in the graph, without the graph.

```json
{
  "node_types": [{"name": "entity", "count": 745, "props": ["mention_count", "last_seen"]},
                 {"name": "fact",   "count": 938, "props": ["content", "confidence", "created_at"]}],
  "edge_types": [{"name": "mentions", "count": 2093}, {"name": "supersedes", "count": 147}],
  "capabilities": {"search": true, "provenance": true, "since": true},
  "id_format": "fact:<key> | <slug>"
}
```

### `graph_query(filter)`

A subgraph, in the shape a force-directed renderer eats.

Request, every field optional:

```json
{"node_types": ["fact"], "edge_types": ["mentions"], "ids": ["fact:x"],
 "around": "fact:x", "depth": 1, "since": "2026-07-01", "limit": 500}
```

Reply:

```json
{"nodes": [{"id": "fact:x", "label": "x", "type": "fact",
            "props": {"content": "...", "confidence": 0.9}, "created_at": "2026-07-20T10:00:00Z"}],
 "links": [{"source": "fact:x", "target": "acme", "type": "mentions"}],
 "meta":  {"total_nodes": 1834, "sampled": true}}
```

`limit` is a promise the server keeps by dropping the least connected nodes
first and saying so in `meta`. `around` + `depth` is the neighbourhood of one
node; `ids` is a set of nodes and the links among them; nothing means "the
whole graph, sampled to `limit`".

### `graph_search(query)`, optional

The memory's own recall, so a viewer can put a question box in front of it:

```json
{"answer": "optional written answer",
 "hits": [{"id": "fact:x", "text": "the snippet the memory would show", "score": 0.83}]}
```

### `graph_provenance(id)`, optional

Where a node comes from:

```json
{"supersedes": ["fact:x_v2", "fact:x_v1"], "superseded_by": [],
 "sources": [{"id": "ep-0412", "created_at": "2026-07-19", "text": "what happened"}]}
```

## What this viewer would do with it

Add one adapter, `mcp`, that connects to the memory server, calls
`graph_schema` once and `graph_query` as needed, and never needs a YAML
mapping. Everything else here (the rim, the worklist, the time-lapse, the
coverage pass, provenance) works on the canonical shape already.

## Questions we cannot answer alone

1. **Ids.** Must a node id be stable across calls? Across restarts? A viewer
   keeps a graph in memory for hours and asks for neighbourhoods by id.
2. **Size.** Is `limit` with degree-based sampling the right default, or should
   the contract have real pagination (`cursor`)? Memories with a million nodes
   exist; this viewer has only met thousands.
3. **Time.** `since` on `created_at` is enough for a time-lapse of growth. Is it
   enough for "what did the memory believe on date D"? That needs an end date
   too (`superseded_at`), which most memories do not keep.
4. **Links with weight.** Some memories keep one link per source document,
   thousands of them between the same two nodes. Should `graph_query` return
   them merged with a `count`, or raw? (This viewer merges for agents and keeps
   them raw for the screen.)
5. **Search results outside the graph.** A recall can return a fact the graph
   never linked. Should `graph_search` say so (`in_graph: false`), or should
   every fact be a node by contract?
6. **Privacy.** A viewer can be pointed at a memory that holds personal data.
   Should the contract carry a masking flag, or is that the viewer's problem?
7. **Who would implement it.** If you run a memory server, which of these four
   tools would you expose tomorrow, and which would you refuse to? That answer
   matters more than any of the above.
