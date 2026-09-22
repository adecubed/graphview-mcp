"""Any SQLite database, through a declarative mapping of tables to nodes and edges.

A node prop can hold references to rows elsewhere (a fact's source episodes,
say): declare `refs: {prop: lookup}` on the node spec and the lookup's query
under `lookups:`; the viewer and the tools resolve them on demand.

The database is opened read-only (`mode=ro` plus `query_only`), so neither a
mapping mistake nor a hostile `query:` can change it, and a missing file is an
error instead of a new empty database.
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

from ..model import Edge, Graph, Node

IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
SELECT_ONLY = re.compile(r"^\s*(select|with)\b", re.IGNORECASE)


def _ident(name: str) -> str:
    if not isinstance(name, str) or not IDENTIFIER.match(name):
        raise ValueError(f"'{name}' is not a valid identifier")
    return f'"{name}"'


def _source_sql(spec: dict) -> str:
    if "query" in spec:
        if not SELECT_ONLY.match(spec["query"]):
            raise ValueError("query must be a SELECT")
        return f"SELECT * FROM ({spec['query'].rstrip().rstrip(';')})"
    return f"SELECT * FROM {_ident(spec['table'])}"


def _type_of(spec: dict, row: sqlite3.Row, default: str) -> str:
    kind = spec.get("type", default)
    if isinstance(kind, dict):
        value = row[kind["column"]]
        return str(value) if value not in (None, "") else default
    return str(kind)


def _props(spec: dict, row: sqlite3.Row) -> dict:
    out = {c: row[c] for c in spec.get("props", []) if row[c] is not None}
    # a ref prop holds ids: a JSON list in the column becomes a real list
    for prop in spec.get("refs") or {}:
        value = out.get(prop)
        if isinstance(value, str) and value.lstrip().startswith("["):
            try:
                out[prop] = [x if isinstance(x, (str, int)) else str(x) for x in json.loads(value)]
            except ValueError:
                pass
    return out


MAX_LOOKUP = 200


def _lookup_sql(name: str, spec: dict) -> str:
    sql = str(spec.get("query", ""))
    if not SELECT_ONLY.match(sql):
        raise ValueError(f"lookup '{name}': query must be a SELECT")
    if sql.count("?") != 1:
        raise ValueError(f"lookup '{name}': query needs exactly one ? placeholder for the id")
    return sql.rstrip().rstrip(";")


class SqliteMapAdapter:
    def __init__(self, source: dict) -> None:
        self.name = source["name"]
        self.path = Path(source["path"])
        self.node_specs = source.get("nodes") or []
        self.edge_specs = source.get("edges") or []
        self.attach = source.get("attach") or {}
        self.lookups = source.get("lookups") or {}
        # prop name -> lookup name, over every node spec
        self.refs: dict[str, str] = {}
        for spec in self.node_specs:
            self.refs.update(spec.get("refs") or {})

    def _nid(self, native, prefix: str | None) -> str:
        return f"{self.name}:{prefix}/{native}" if prefix else f"{self.name}:{native}"

    def load(self) -> Graph:
        for spec in self.node_specs + self.edge_specs:  # fail early on a bad mapping
            _source_sql(spec)
        for alias in self.attach:
            _ident(alias)
        for name, spec in self.lookups.items():
            _lookup_sql(name, spec)
        # Other databases join in under an alias (`sem.facts`), read-only like
        # the main one; mode=ro also makes a missing file an error.
        con = self._connect()
        g = Graph()
        try:
            for spec in self.node_specs:
                self._guarded(g, spec, con, self._load_nodes)
            for spec in self.edge_specs:
                self._guarded(g, spec, con, self._load_edges)
        finally:
            con.close()
        g.finalize()
        return g

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(f"{self.path.resolve().as_uri()}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        for alias, path in self.attach.items():
            con.execute(f"ATTACH DATABASE ? AS {_ident(alias)}",
                        (f"{Path(path).resolve().as_uri()}?mode=ro",))
        con.execute("PRAGMA query_only = ON")
        return con

    def lookup(self, name: str, ids: list) -> list[dict]:
        """Resolve referenced rows, in the order asked; unknown ids are left out."""
        spec = self.lookups.get(name)
        if not spec or not ids:
            return []
        sql = _lookup_sql(name, spec)
        con = self._connect()
        try:
            rows = []
            for native in ids[:MAX_LOOKUP]:
                row = con.execute(sql, (native,)).fetchone()
                if row is not None:
                    rows.append(dict(row))
            return rows
        finally:
            con.close()

    def _guarded(self, g: Graph, spec: dict, con, loader) -> None:
        """One broken table mapping becomes a warning; the rest still loads."""
        try:
            loader(g, spec, con)
        except sqlite3.OperationalError as exc:
            if "readonly" in str(exc).lower():
                raise
            g.warnings.append(f"{self.name}: {spec.get('table', 'query')}: {exc}")
        except (KeyError, IndexError) as exc:
            g.warnings.append(f"{self.name}: {spec.get('table', 'query')}: no column {exc}")

    def _load_nodes(self, g: Graph, spec: dict, con) -> None:
        prefix = spec.get("id_prefix")
        default_type = spec.get("table", "node")
        for row in con.execute(_source_sql(spec)):
            native = row[spec["id"]]
            if native is None:
                continue
            label = row[spec["label"]] if spec.get("label") else None
            created = row[spec["created_at"]] if spec.get("created_at") else None
            g.add_node(Node(self._nid(native, prefix),
                            str(label) if label not in (None, "") else str(native),
                            _type_of(spec, row, default_type), self.name,
                            _props(spec, row),
                            str(created) if created is not None else None))

    def _load_edges(self, g: Graph, spec: dict, con) -> None:
        from_prefix, to_prefix = spec.get("from_prefix"), spec.get("to_prefix")
        default_type = spec.get("table", "related")
        for row in con.execute(_source_sql(spec)):
            start, end = row[spec["from"]], row[spec["to"]]
            if start is None or end is None:
                continue
            g.add_edge(Edge(self._nid(start, from_prefix), self._nid(end, to_prefix),
                            _type_of(spec, row, default_type), _props(spec, row)))
