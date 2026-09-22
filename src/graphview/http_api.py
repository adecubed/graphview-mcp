"""Local HTTP face of GraphService: a JSON API for the viewer plus its static files.

Read-only, loopback only. Every /api/ call needs the token; the Host header
must be a loopback name, which stops DNS-rebinding pages from reading the graph.
"""

from __future__ import annotations

import hmac
import json
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .service import GraphService

VIEWER_DIR = (Path(__file__).parent / "viewer").resolve()
LOOPBACK_HOSTS = {"127.0.0.1", "localhost"}


class BadRequest(ValueError):
    pass


def _one(params: dict, key: str, default=None):
    values = params.get(key)
    return values[0] if values else default


def _many(params: dict, key: str):
    values = [v for raw in params.get(key, []) for v in raw.split(",") if v]
    return values or None


def _int(params: dict, key: str, default):
    raw = _one(params, key)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        raise BadRequest(f"'{key}' must be a number") from None


def _route(service: GraphService, path: str, p: dict):
    if path == "/api/graph":
        return service.get_graph(_many(p, "node_types"), _many(p, "edge_types"),
                                 _many(p, "sources"), _int(p, "limit", None))
    if path == "/api/node":
        return service.get_node(_one(p, "id", ""))
    if path == "/api/neighbors":
        return service.neighbors(_one(p, "id", ""), _int(p, "depth", 1),
                                 _many(p, "edge_types"), _int(p, "limit", None))
    if path == "/api/search":
        return service.search(_one(p, "q", ""), _int(p, "limit", 50))
    if path == "/api/path":
        return service.path(_one(p, "from", ""), _one(p, "to", ""), _many(p, "edge_types"))
    if path == "/api/coverage":
        report = service.coverage()
        return {"available": True, **report} if report else {"available": False}
    if path == "/api/lookup":
        return service.lookup(_one(p, "id", ""), _one(p, "prop", ""))
    if path == "/api/provenance":
        return service.provenance(_one(p, "id", ""))
    if path == "/api/stats":
        return service.stats()
    if path == "/api/worklist":
        return service.worklist()
    if path == "/api/worklist/history":
        return {"history": service.worklist_history()}
    if path == "/api/types":
        return service.list_types()
    if path == "/api/reload":
        return service.reload()
    return None


def make_server(service: GraphService, token: str, port: int = 0) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args) -> None:  # stdout belongs to MCP stdio
            pass

        def _send(self, status: int, body: bytes, content_type: str,
                  download_as: str | None = None) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            if download_as:
                self.send_header("Content-Disposition", f'attachment; filename="{download_as}"')
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, payload) -> None:
            self._send(status, json.dumps(payload, ensure_ascii=False, default=str)
                       .encode("utf-8"), "application/json; charset=utf-8")

        def do_GET(self) -> None:
            host = (self.headers.get("Host") or "").rsplit(":", 1)[0]
            if host not in LOOPBACK_HOSTS:
                return self._json(403, {"error": "forbidden host"})
            url = urlsplit(self.path)
            if url.path.startswith("/api/"):
                return self._api(url.path, parse_qs(url.query))
            return self._static(url.path)

        def _api(self, path: str, params: dict) -> None:
            given = self.headers.get("X-Graphview-Token") or _one(params, "token", "")
            if not hmac.compare_digest(given.encode(), token.encode()):
                return self._json(403, {"error": "missing or wrong token"})
            if path == "/api/worklist" and _one(params, "format") == "md":
                return self._send(200, service.worklist_markdown().encode("utf-8"),
                                  "text/markdown; charset=utf-8", "graphview-worklist.md")
            try:
                result = _route(service, path, params)
            except BadRequest as exc:
                return self._json(400, {"error": str(exc)})
            if result is None:
                return self._json(404, {"error": "unknown endpoint"})
            self._json(200, result)

        def _static(self, path: str) -> None:
            relative = path.lstrip("/") or "index.html"
            file = (VIEWER_DIR / relative).resolve()
            if not file.is_relative_to(VIEWER_DIR) or not file.is_file():
                return self._json(404, {"error": "not found"})
            kind = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
            if kind.startswith("text/") or kind.endswith("javascript"):
                kind += "; charset=utf-8"
            self._send(200, file.read_bytes(), kind)

    return _Server(("127.0.0.1", port), Handler)


class _Server(ThreadingHTTPServer):
    # The stdlib sets SO_REUSEADDR, and on Windows that lets a second process bind
    # a port that is already taken: the viewer would start "fine" while every
    # request went to whatever was there first. A port in use must be an error.
    allow_reuse_address = False
