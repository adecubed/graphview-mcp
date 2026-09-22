"""Plug a source's own search (vector recall, BM25, anything over HTTP) into the viewer.

Declared in the source mapping, so no source-specific code lives here:

    search:
      url: http://127.0.0.1:9000/search
      method: POST                      # default GET
      params: {query: "{query}", limit: 12}   # query string; `body:` sends JSON instead
      results: data.items               # where the list sits; omit if the reply is the list
      id: "fact:{key}"                  # node id built from each result row
      text: content                     # field shown as the snippet
      answer: summary                   # optional: where a written answer sits in the reply

Only the mapping's author chooses the URL; nothing from the graph or the viewer
can change it.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request


class SearchUnavailable(RuntimeError):
    """The endpoint is down, slow, or answered something unusable."""


def _fill(template, query: str):
    if isinstance(template, str):
        return template.replace("{query}", query)
    if isinstance(template, dict):
        return {k: _fill(v, query) for k, v in template.items()}
    if isinstance(template, list):
        return [_fill(v, query) for v in template]
    return template


class HttpSearch:
    def __init__(self, source_name: str, spec: dict, timeout: float = 8.0) -> None:
        self.source = source_name
        self.url = str(spec.get("url", ""))
        if urllib.parse.urlsplit(self.url).scheme not in ("http", "https"):
            raise ValueError(f"search url must be http or https, got '{self.url}'")
        if "id" not in spec:
            raise ValueError("search needs an 'id' template, e.g. \"fact:{key}\"")
        self.method = str(spec.get("method", "GET")).upper()
        self.params = spec.get("params")
        self.body = spec.get("body")
        self.results_path = [p for p in str(spec.get("results") or "").split(".") if p]
        self.id_template = str(spec["id"])
        self.text_field = spec.get("text")
        self.answer_path = [p for p in str(spec.get("answer") or "").split(".") if p]
        self.timeout = float(spec.get("timeout", timeout))  # seconds

    def search(self, query: str):
        """Hits in the endpoint's own order: [{"id": node id, "text": snippet}].

        With an `answer:` path in the spec, returns {"hits": [...], "answer": str} instead.
        """
        url = self.url
        if self.params:
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode(_fill(self.params, query))
        data = headers = None
        if self.body is not None:
            data = json.dumps(_fill(self.body, query), ensure_ascii=False).encode("utf-8")
            headers = {"Content-Type": "application/json"}
        request = urllib.request.Request(url, data=data, headers=headers or {}, method=self.method)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                reply = json.loads(response.read().decode("utf-8", errors="replace"))
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise SearchUnavailable(f"{self.source}: search endpoint failed ({exc})") from exc

        rows = self._dig(reply, self.results_path)
        answer = self._dig(reply, self.answer_path) if self.answer_path else None
        if rows is None and isinstance(answer, str):
            rows = []  # it answered; it just has no matching items to list
        if not isinstance(rows, list):
            raise SearchUnavailable(f"{self.source}: search reply has no result list")

        hits = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            try:
                native = self.id_template.format_map(row)
            except (KeyError, IndexError, ValueError):
                continue  # a row without the id field cannot be placed in the graph
            text = row.get(self.text_field) if self.text_field else None
            hits.append({"id": f"{self.source}:{native}",
                         "text": str(text) if text is not None else ""})
        if not self.answer_path:
            return hits
        return {"hits": hits, "answer": answer if isinstance(answer, str) else ""}

    @staticmethod
    def _dig(value, path: list[str]):
        for part in path:
            value = value.get(part) if isinstance(value, dict) else None
        return value
