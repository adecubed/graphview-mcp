# graphview build — turning an archive into a graph

Date: 2026-09-23. Builds on the v0.1 design (2026-09-21).

## Goal

Today graphview shows graphs that already exist. Most archives are not graphs:
a mailbox, a folder of files, a spreadsheet, a vector index. `graphview build`
reads one of those, works out the links nobody wrote down, and writes a graph
the viewer, the app and the MCP server can open as they are today. Every link
carries its evidence: the rule that produced it and the row, message or
document it came from. The source is never written to.

Built for a person first, an agent second: the output must explain itself to
someone looking at it, and that same explanation is what makes it safe for an
agent to use.

## Why now

Two days of pointing the viewer at a real memory found two defects nobody had
seen in a year of benchmarks (a confidence threshold that hid old facts, and a
provenance field that held the distillation batch instead of the sources).
Both were visible only because the graph put the evidence next to the claim.
A builder that puts evidence next to every link it creates makes that the
default instead of a discovery.

## In scope for v1

- `graphview build <source> -o <dir>`: builds `graph.db`, `graphview.yaml`,
  `build.md`, `build.json` in `<dir>`. Re-running rebuilds the directory.
- Sources: a **table** (CSV, JSONL, Parquet, XLSX), a **folder** of documents
  (Markdown, text, PDF), a **Chroma** collection. Each is a *connector* that
  yields records; the engine does the rest.
- Deterministic link rules: `part_of`, `shares:<field>`, `refers_to`,
  `mentions`, `similar_to`. All free, repeatable, no model, no network.
  `mentions` finds known names and patterned identifiers in text (the
  customers of the table in the PDFs, the invoice numbers of the folder in the
  mail); it is what ties sources together. `similar_to` only where vectors
  already exist; the builder computes none.
- Several sources in one build (`graphview build sales.csv ./offers -o out/`),
  because the links across sources are the point.
- A build report in words, and "why this link?" in the viewer's panel.
- A library API (`graphview.build`) so a host application (GigaMail first) can
  feed records and get a graph without going through files.

No model of any kind in v1: no LLM, no embedding model. "Installs in one
click" has to be literally true, and a graph of a mailbox or a sales folder is
already rich without one. The `Record`/`Evidence` design leaves room for a
model-read rule later, added when a corpus shows the dictionary is not enough.

## Out of scope for v1

LLM entity and relation extraction, embedding computation, Qdrant, LanceDB,
pgvector, Outlook/Exchange, Google Workspace, SharePoint, incremental
rebuilds, multi-user permissions, a server edition, an installer. The
connector and rule interfaces are designed so these are additions, not
rewrites.

## Where the boundary sits

The repo stays Apache-2.0: engine, viewer, MCP, and the developer connectors
(table, folder, Chroma). Connectors to a product's own data live in that
product (the GigaMail connector lives in GigaMail). Anything sold later
(installer, corporate connectors, server edition) is born in its own repo;
nothing in this repo is closed afterwards.

## Architecture

```
CONNECTOR -> records -> ENGINE (rules, evidence) -> WRITER -> graph.db + graphview.yaml + build.md
                                                              |
                                              serve / app / mcp  (unchanged)
```

### Records

A connector yields `Record`s. This is the whole contract between a source and
the engine:

```python
@dataclass
class Record:
    id: str                    # stable within the source
    kind: str                  # "row", "document", "chunk", "message", "person", ...
    label: str
    text: str = ""             # what a model or a text search would read
    fields: dict = {}          # structured values: author, date, tags, amount...
    parent: str | None = None  # id of the record this is part of (chunk -> document)
    refs: dict[str, list[str]] = {}   # field -> ids of other records it points to
    vector: list[float] | None = None
    created_at: str | None = None
    origin: str = ""           # where a human would find it: path, row number, message id
```

Connectors are generators; the engine never needs all records in memory at
once for the deterministic rules except `similar_to`.

### Connectors (v1)

- **table**: one file, one record per row (`kind="row"`). Label: the first
  column that looks like a name (`name`, `title`, `subject`, `customer`...),
  else the first text column. `fields` = all columns. Vectors: a column of
  JSON lists if present. XLSX via `openpyxl`, Parquet via `pyarrow`, both
  optional extras.
- **folder**: one record per document (`kind="document"`), `text` from the
  file (PDF via `pypdf`, optional extra), `fields` = size, extension,
  modified time, front-matter if Markdown. Documents are not chunked in v1:
  a `mentions` link points at a document and quotes the line.
- **chroma**: one record per item in a collection (`kind="chunk"`),
  `text`=document, `fields`=metadata, `vector`=embedding, `parent` from the
  metadata key named in `--parent` (default: `source`).

### Rules

Each rule is a function `(records) -> iter[Link]` with a name; the name is the
edge type in the graph, so the viewer's filter panel toggles rules one by one.

```python
@dataclass
class Link:
    a: str; b: str; type: str
    evidence: Evidence
    props: dict = {}

@dataclass
class Evidence:
    rule: str                # "part_of", "shares:author", ...
    where: list[str]         # record ids that justify the link
    quote: str = ""          # the exact text the link rests on
    score: float | None = None
```

- `part_of`: `record.parent` → link to the parent. Always on.
- `shares:<field>`: two records with the same non-empty value of `<field>`.
  The user names the fields (`--share author --share tag`); with none given,
  the engine proposes fields whose values repeat but are not near-unique and
  not near-constant (between 2 and 20% distinct), and says so in the report.
  A value shared by more than `--share-max` records (default 200) becomes a
  **hub node** of type `value:<field>` with `has:<field>` links instead of a
  clique; the report says which values were turned into hubs.
- `refers_to`: a field value equal to another record's `id` or `label`
  (exact, case-insensitive), or a `[[wikilink]]`/path in `text` that resolves
  to a record. Evidence quotes the value.
- `similar_to`: cosine nearest neighbours on `vector` (k=5, threshold 0.80,
  both adjustable), only when vectors exist. Rendered dashed. Evidence carries
  the score. Numpy in memory for up to ~200k vectors; above that the report
  says the rule was skipped and why.
- `mentions`: a record's `text` contains a known name or a patterned
  identifier. Two dictionaries, both built from the records themselves, so
  the rule needs nothing from outside:
  - **names**: the labels of records of a kind the user names
    (`--mention-kind row`, default: every kind that is not `document`),
    matched as whole words, case-insensitive, three characters or more, after
    dropping labels that are dictionary words of the text's language (a
    customer called "Mario" is fine; a tag called "the" is not). The report
    lists names dropped for being too common (more than `--mention-max`
    records, default 200, same hub logic as `shares`).
  - **identifiers**: emails, phone numbers, IBANs, dates, amounts with a
    currency, and any field whose values all match one shape (an invoice
    number like `2026-0142`, an order code like `ORD-8812`): the engine
    infers the shape from the field's values and searches the texts for it.
    An identifier that matches a record's field links to that record
    (`mentions`); one that matches nothing becomes a node of kind
    `value:<shape>` when it appears in at least two records, so the two
    documents quoting the same unknown invoice number still meet.

  Evidence quotes the line where the match is. This is the rule that ties
  sources together: the customer of a CSV row appears in a PDF; the invoice
  number of a PDF appears in a mail. It is exact, repeatable and citable.
  Rendered solid, because it reads the text as written.

Links are undirected for `shares` and `similar_to` (stored once, `a < b`),
directed for the others.

### Room for a model, later

A rule that has a model read text (entities and relations the dictionary
cannot see) would be one more `(records) -> iter[Link]` with the same
`Evidence`, under the rule we had to retrofit in the Brain on 2026-09-22:
an item that does not cite the record and quote the span is not written. It
is not in v1; it gets built when a corpus shows `mentions` is not enough,
measured, not assumed.

### Output

`graph.db` (SQLite):

```sql
nodes(id TEXT PRIMARY KEY, kind TEXT, label TEXT, text TEXT, fields JSON,
      created_at TEXT, origin TEXT)
edges(id INTEGER PRIMARY KEY, a TEXT, b TEXT, type TEXT, props JSON)
evidence(edge_id INTEGER, rule TEXT, record_id TEXT, quote TEXT, score REAL)
build(key TEXT PRIMARY KEY, value TEXT)   -- source, options, versions, when
```

`graphview.yaml` maps it with the existing sqlite adapter (nodes by `kind`,
edges by `type`, `refs`/`lookups` so the panel resolves evidence rows), and
marks `similar_to` as `inferred: true`, which the viewer draws dashed. Nothing in the viewer's data path changes; one new
edge flag.

`build.md` is written for a person: what was read, how many nodes of each
kind, each rule with its count and the fields or thresholds it used, the
hubs created, what was dropped and why, how long it took. `build.json` is
the same as data.

### Library API

```python
from graphview.build import build
report = build(records, out_dir, rules=..., options=...)
```

`records` is any iterable of `Record`. This is what GigaMail calls with its
messages, people and attachments; the file connectors are just generators
that produce the same thing.

### Viewer

Two additions, both small: edges flagged `inferred` are drawn dashed and
listed under an "inferred" heading in the filter panel; clicking a link in
the node panel opens "why this link?" with the rule, the records it rests on
(resolved through `lookups`, like source episodes today) and the quote.

### CLI

```
graphview build data.csv -o out/ [--share author --share tag]
graphview build sales.csv ./offers -o out/     # rows and documents, linked by mentions
graphview build chroma://path/to/db/collection -o out/ [--parent source] [--similar 0.8]
graphview serve out/      # or app, mcp
```

## Error handling

- A connector that cannot read a file skips it and lists it in the report;
  it never aborts the build.
- A rule that would exceed a budget (`shares` clique, `similar_to` size)
  degrades as described and says so; no silent partial output.
- A `mentions` dictionary that would be empty (no names, no shapes) is
  reported, not treated as an error.
- Rebuilding into a non-empty `<dir>` that is not a previous build refuses;
  a previous build is replaced.

## Testing

- Unit tests per rule on hand-made records (including the hub threshold,
  the case-insensitive `refers_to`, the `a < b` storage).
- One test per connector on a fixture (a 20-row CSV, a 5-document folder with
  one PDF, a Chroma collection built in the test).
- An end-to-end test: build a fixture, open it with `GraphService`, check the
  panel's `refs` resolve the evidence rows and `inferred` reaches the viewer.
- `mentions` tested on a CSV plus two text files: the customer of a row
  found in a PDF's text, an invoice number found in two documents and turned
  into a `value:` node, a label that is a common word not matched.
- The real trial, outside the test suite: Simone's sales folder
  (file connector) and a GigaMail mailbox (library API). Findings from those
  go back into the rules, not into special cases.

## Open questions

- Hub threshold: 200 is a guess; the sales folder will tell.
- Whether `similar_to` should be on by default when vectors exist, or off
  until asked. Leaning on: it is the reason someone points us at a vector
  store.
- Which shapes `mentions` should infer on its own; start with "all values
  of a field share one pattern of digits, letters and separators", and let the
  sales folder say what it misses.
