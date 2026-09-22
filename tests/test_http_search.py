import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import pytest

from graphview.config import Config
from graphview.http_search import HttpSearch, SearchUnavailable
from graphview.service import GraphService


@pytest.fixture
def recall():
    """A fake recall endpoint. `state['reply']` decides what it answers."""
    state = {"reply": [{"key": "f1", "content": "Alice works at Acme", "confidence": 0.9}],
             "status": 200, "seen": []}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            url = urlsplit(self.path)
            length = int(self.headers.get("Content-Length") or 0)
            state["seen"].append({"path": url.path, "query": parse_qs(url.query),
                                  "body": self.rfile.read(length).decode() if length else ""})
            body = state["reply"] if isinstance(state["reply"], bytes) \
                else json.dumps(state["reply"]).encode()
            self.send_response(state["status"])
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    state["url"] = f"http://127.0.0.1:{server.server_address[1]}/memory/search"
    yield state
    server.shutdown()
    server.server_close()


def spec(recall, **extra):
    return {"url": recall["url"], "method": "POST",
            "params": {"query": "{query}", "limit": 5},
            "id": "fact:{key}", "text": "content", **extra}


def test_hits_carry_the_node_id_the_text_and_the_query_goes_in_the_params(recall):
    hits = HttpSearch("brain", spec(recall)).search("where does alice work?")
    assert hits == [{"id": "brain:fact:f1", "text": "Alice works at Acme"}]
    assert recall["seen"][0]["query"] == {"query": ["where does alice work?"], "limit": ["5"]}


def test_results_can_sit_under_a_key_and_the_query_can_go_in_a_json_body(recall):
    recall["reply"] = {"ok": True, "data": {"items": [{"key": "f2", "content": "x"}]}}
    s = spec(recall, results="data.items", body={"q": "{query}"})
    s.pop("params")
    assert HttpSearch("brain", s).search("hello")[0]["id"] == "brain:fact:f2"
    assert json.loads(recall["seen"][0]["body"]) == {"q": "hello"}


def test_rows_missing_the_id_field_are_skipped(recall):
    recall["reply"] = [{"content": "no key here"}, {"key": "f3", "content": "ok"}]
    assert [h["id"] for h in HttpSearch("brain", spec(recall)).search("x")] == ["brain:fact:f3"]


@pytest.mark.parametrize("break_it", ["status", "garbage", "shape", "down"])
def test_every_failure_is_one_clear_exception(recall, break_it):
    s = spec(recall)
    if break_it == "status":
        recall["status"] = 500
    elif break_it == "garbage":
        recall["reply"] = b"<html>not json</html>"
    elif break_it == "shape":
        recall["reply"] = {"unexpected": True}
    else:
        s["url"] = "http://127.0.0.1:9/none"
    with pytest.raises(SearchUnavailable):
        HttpSearch("brain", s, timeout=2).search("x")


def test_only_http_urls_are_accepted():
    with pytest.raises(ValueError, match="http"):
        HttpSearch("brain", {"url": "file:///etc/passwd", "id": "{key}"})


def make_service(tmp_path, recall, masking=False):
    import sqlite3
    db = tmp_path / "g.db"
    con = sqlite3.connect(db)
    con.executescript("""
        CREATE TABLE nodes (slug TEXT PRIMARY KEY, kind TEXT, content TEXT);
        CREATE TABLE edges (a TEXT, b TEXT, rel TEXT);
        INSERT INTO nodes VALUES ('fact:f1', 'fact', 'Alice works at Acme'),
                                 ('alice', 'entity', NULL), ('acme', 'entity', NULL);
        INSERT INTO edges VALUES ('fact:f1', 'alice', 'mentions'), ('fact:f1', 'acme', 'mentions');
    """)
    con.commit()
    con.close()
    source = {"name": "brain", "adapter": "sqlite", "path": str(db),
              "nodes": [{"table": "nodes", "id": "slug", "label": "slug",
                         "type": {"column": "kind"}, "props": ["content"]}],
              "edges": [{"table": "edges", "from": "a", "to": "b", "type": {"column": "rel"}}],
              "search": spec(recall)}
    return GraphService(Config(sources=[source], masking=masking))


def test_service_uses_recall_and_attaches_the_text_as_a_snippet(tmp_path, recall):
    out = make_service(tmp_path, recall).search("where does alice work?")
    assert out["mode"] == "recall"
    assert [(m["id"], m["snippet"]) for m in out["matches"]] == \
        [("brain:fact:f1", "Alice works at Acme")]


def test_a_hit_with_no_node_is_kept_and_marked_unlinked(tmp_path, recall):
    recall["reply"] = [{"key": "ghost", "content": "A fact the graph never linked"}]
    match = make_service(tmp_path, recall).search("anything")["matches"][0]
    assert match["unlinked"] is True and match["snippet"] == "A fact the graph never linked"
    assert match["id"] == "brain:fact:ghost"


def test_when_recall_is_down_the_text_search_answers_and_says_so(tmp_path, recall):
    recall["status"] = 500
    out = make_service(tmp_path, recall).search("alice")
    assert out["mode"] == "text"
    assert "brain" in out["notice"]
    assert [m["id"] for m in out["matches"]] == ["brain:alice", "brain:fact:f1"]


def test_recall_finding_nothing_falls_back_to_text_search(tmp_path, recall):
    recall["reply"] = []
    out = make_service(tmp_path, recall).search("acme")
    assert out["mode"] == "text" and out["matches"][0]["id"] == "brain:acme"


def test_recall_is_never_called_when_masking_is_on(tmp_path, recall):
    out = make_service(tmp_path, recall, masking=True).search("alice")
    assert out["mode"] == "text" and recall["seen"] == []


def test_an_answer_field_travels_with_the_hits(tmp_path, recall):
    recall["reply"] = {"summary": "Alice works at Acme since 2020.",
                       "raw": {"semantic": [{"key": "f1", "content": "Alice works at Acme"}]}}
    s = spec(recall, results="raw.semantic", answer="summary")
    found = HttpSearch("brain", s).search("where does alice work?")
    assert found == {"hits": [{"id": "brain:fact:f1", "text": "Alice works at Acme"}],
                     "answer": "Alice works at Acme since 2020."}

    service = make_service(tmp_path, recall)
    service.config.sources[0]["search"] = s
    service.reload()
    out = service.search("where does alice work?")
    assert out["mode"] == "recall" and out["answer"] == "Alice works at Acme since 2020."


def test_an_answer_with_no_hits_still_counts_as_recall(tmp_path, recall):
    recall["reply"] = {"summary": "Nothing about that, but here is what I know.", "raw": {"semantic": []}}
    service = make_service(tmp_path, recall)
    service.config.sources[0]["search"] = spec(recall, results="raw.semantic", answer="summary")
    service.reload()
    out = service.search("unknown thing")
    assert out["mode"] == "recall" and out["matches"] == [] and out["answer"].startswith("Nothing")


def test_a_reply_with_an_answer_but_no_result_list_means_no_hits_not_a_failure(recall):
    recall["reply"] = {"ok": True, "summary": "I know nothing about that.", "raw": {}}
    found = HttpSearch("brain", spec(recall, results="raw.semantic", answer="summary")).search("x")
    assert found == {"hits": [], "answer": "I know nothing about that."}
