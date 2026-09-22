"""A stand-in for a memory's own recall, so the `search:` block has something to talk to.

Real memories rank facts with vectors, BM25, an LLM: this one scores facts by
how many words of the question they share, and composes a one-line answer from
the best one. It is here to show the shape of the exchange, not to be good.

    python examples/memory/recall_server.py        # listens on 127.0.0.1:7790

POST /ask  {"query": "..."}  ->  {"answer": "...", "results": [{"key", "content", "score"}, ...]}
"""

from __future__ import annotations

import json
import re
import sqlite3
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

DB = Path(__file__).parent / "memory.db"
STOP = {"the", "a", "an", "of", "on", "in", "is", "who", "what", "which", "does", "do", "for", "to", "and"}


def words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in STOP and len(w) > 1}


def recall(query: str, limit: int = 8) -> dict:
    wanted = words(query)
    con = sqlite3.connect(f"{DB.resolve().as_uri()}?mode=ro", uri=True)
    scored = []
    for key, content, confidence in con.execute("SELECT key, content, confidence FROM facts WHERE superseded = 0"):
        hit = len(wanted & words(f"{key} {content}"))
        if hit:
            scored.append((hit + confidence, key, content))  # words hit first, confidence breaks ties
    con.close()
    scored.sort(reverse=True)
    results = [{"key": k, "content": c, "score": round(s, 2)} for s, k, c in scored[:limit]]
    answer = (f"Best match: {results[0]['content']} ({len(results)} facts mention this.)"
              if results else "Nothing in memory matches that.")
    return {"answer": answer, "results": results}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
            reply = recall(str(body.get("query", "")))
            status = 200
        except (ValueError, sqlite3.Error) as exc:
            reply, status = {"error": str(exc)}, 400
        data = json.dumps(reply).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def serve(port: int = 7790) -> HTTPServer:
    return HTTPServer(("127.0.0.1", port), Handler)


if __name__ == "__main__":
    server = serve()
    print(f"example recall on http://127.0.0.1:{server.server_address[1]}/ask  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
