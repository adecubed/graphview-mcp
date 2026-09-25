"""MCP face of GraphService: graph tools for the agent, plus open_viewer."""

from __future__ import annotations

import json
import secrets
import threading
import webbrowser
from typing import Callable
from urllib.parse import urlencode

try:  # mcp 2.x
    from mcp.server.mcpserver import MCPServer
except ImportError:  # mcp 1.x, same class under its old name
    from mcp.server.fastmcp import FastMCP as MCPServer

from .http_api import make_server
from .service import GraphService

# Defaults for tool answers, sized for an agent's context rather than for a screen.
AGENT_LIMIT = 50
AGENT_MAX_LINKS = 150


def _json(payload: dict) -> str:
    """Dense JSON: the SDK pretty-prints dicts, which doubles what the agent has to read."""
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)


def build_server(service: GraphService, port: int = 0,
                 opener: Callable[[str], object] = webbrowser.open) -> MCPServer:
    mcp = MCPServer("graphview", instructions=(
        "Read-only view of a graph-shaped memory. Use search and neighbors to explore, "
        "get_node for details, and open_viewer to show the user a 3D view, optionally "
        "focused on a node id or on a search."))
    viewer: dict = {}
    lock = threading.Lock()

    def viewer_base() -> tuple[str, str]:
        with lock:
            if not viewer:
                token = secrets.token_urlsafe(24)
                http = make_server(service, token, port)
                threading.Thread(target=http.serve_forever, daemon=True).start()
                viewer.update(token=token, base=f"http://127.0.0.1:{http.server_address[1]}/")
            return viewer["base"], viewer["token"]

    @mcp.tool()
    def get_graph(node_types: list[str] | None = None, edge_types: list[str] | None = None,
                  sources: list[str] | None = None, limit: int = AGENT_LIMIT,
                  max_links: int = AGENT_MAX_LINKS) -> str:
        """Subgraph as {nodes, links, meta}. Filters are optional. Above `limit` nodes
        the best-connected ones are kept (meta.sampled). Parallel links are merged
        into one with a `count`; above `max_links` the heaviest are kept
        (meta.links_truncated). Prefer search and neighbors over a wide get_graph."""
        return _json(service.get_graph(node_types, edge_types, sources, limit,
                                       compact=True, max_links=max_links))

    @mcp.tool()
    def get_node(node_id: str, max_per_type: int = 40) -> str:
        """One node with its properties and its links grouped by link type. Each group
        has the real `total` and its `max_per_type` heaviest neighbours (id, label,
        type, count of parallel links). Use neighbors to walk further."""
        return _json(service.get_node(node_id, compact=True, max_per_type=max_per_type))

    @mcp.tool()
    def neighbors(node_id: str, depth: int = 1, edge_types: list[str] | None = None,
                  limit: int = AGENT_LIMIT, max_links: int = AGENT_MAX_LINKS) -> str:
        """Subgraph around a node, following links in both directions up to `depth`.
        Same sampling and link merging as get_graph."""
        return _json(service.neighbors(node_id, depth, edge_types, limit,
                                       compact=True, max_links=max_links))

    @mcp.tool()
    def search(query: str, limit: int = 20) -> str:
        """Find nodes by text in their label or properties. Best matches first."""
        return _json(service.search(query, limit))

    @mcp.tool()
    def graph_stats() -> dict:
        """Counts by node type, link type and source, plus load warnings."""
        return service.stats()

    @mcp.tool()
    def path(from_id: str, to_id: str, edge_types: list[str] | None = None) -> str:
        """How two nodes are connected: the shortest chain of nodes between them, link
        direction ignored, with the typed links along it. `found` is false when there
        is no way through. Get the ids from search."""
        return _json(service.path(from_id, to_id, edge_types, compact=True))

    @mcp.tool()
    def provenance(node_id: str) -> str:
        """Where a node comes from: the chain of nodes it superseded (nearest first),
        the ones that superseded it, and its source rows (e.g. the episodes a fact was
        distilled from), when the mapping declares them."""
        return _json(service.provenance(node_id))

    @mcp.tool()
    def worklist(max_items: int = 40) -> str:
        """What in this graph probably wants fixing at its source: likely duplicates
        (same-type nodes with near-equal names), hubs linked to a large share of the
        graph (possibly generic words), islands (small groups cut off from the main
        body) and unlinked nodes. `summary` has the real totals; each list is cut
        to `max_items`."""
        full = service.worklist()
        return _json({"summary": full["summary"],
                      **{k: full[k][:max_items]
                         for k in ("duplicates", "hubs", "islands", "unlinked")}})

    @mcp.tool()
    def list_types() -> dict:
        """Node types, link types and sources, each with its count and display colour."""
        return service.list_types()

    @mcp.tool()
    def groups(max_ids: int = 20) -> dict:
        """What's in here: the named sets of nodes the memory declares (the things it
        resolved, folders, recurring names, categories), each with its count and up to
        `max_ids` member ids. A plain-language table of contents for the graph."""
        return service.groups(max_ids=max_ids)

    @mcp.tool()
    def reload() -> dict:
        """Read every source again. Returns the new stats."""
        return service.reload()

    @mcp.tool()
    def open_viewer(focus: str | None = None, query: str | None = None) -> dict:
        """Open the 3D viewer in the user's browser. `focus` is a node id to fly to;
        `query` runs a search in the viewer. The URL works only on this machine."""
        base, token = viewer_base()
        fragment = {"token": token}
        if focus:
            fragment["focus"] = focus
        if query:
            fragment["q"] = query
        url = f"{base}#{urlencode(fragment)}"
        opener(url)
        return {"url": url, "opened": True}

    return mcp


def run(service: GraphService, port: int = 0) -> None:
    build_server(service, port).run()
