import asyncio
import inspect
import json
import urllib.request
from urllib.parse import parse_qs, urlsplit

import pytest

from graphview.config import Config
from graphview.mcp_server import build_server
from graphview.service import GraphService


@pytest.fixture
def setup(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "Alice.md").write_text("[[Bob]]", encoding="utf-8")
    (vault / "Bob.md").write_text("hello", encoding="utf-8")
    service = GraphService(Config(sources=[
        {"name": "vault", "adapter": "wikilinks", "path": str(vault)}]))
    opened = []
    return build_server(service, opener=opened.append), opened


def resolve(value):
    return asyncio.run(value) if inspect.isawaitable(value) else value


def call(server, name, **arguments):
    result = resolve(server.call_tool(name, arguments))
    if isinstance(result, tuple):       # mcp 1.x: (content, structured)
        result = result[0]
    content = getattr(result, "content", result)  # mcp 2.x: CallToolResult
    return json.loads(content[0].text)


def test_all_tools_are_registered(setup):
    server, _ = setup
    names = {t.name for t in resolve(server.list_tools())}
    assert names == {"get_graph", "get_node", "neighbors", "search", "graph_stats",
                     "list_types", "reload", "open_viewer", "worklist", "path", "provenance", "groups"}


def test_graph_tools_return_canonical_json(setup):
    server, _ = setup
    assert len(call(server, "get_graph")["nodes"]) == 2
    assert call(server, "get_node", node_id="vault:Alice")["node"]["label"] == "Alice"
    assert len(call(server, "neighbors", node_id="vault:Bob")["nodes"]) == 2
    assert call(server, "search", query="bob")["matches"][0]["id"] == "vault:Bob"
    assert call(server, "graph_stats")["edges"] == 1


def test_open_viewer_starts_one_server_and_passes_focus_in_the_fragment(setup):
    server, opened = setup
    first = call(server, "open_viewer", focus="vault:Alice")
    second = call(server, "open_viewer", query="bob")
    assert opened == [first["url"], second["url"]]

    one, two = urlsplit(first["url"]), urlsplit(second["url"])
    assert one.hostname == "127.0.0.1" and one.netloc == two.netloc
    assert one.query == ""  # nothing sensitive in the part that gets sent or logged
    fragment = parse_qs(one.fragment)
    assert fragment["focus"] == ["vault:Alice"] and "token" in fragment
    assert parse_qs(two.fragment)["q"] == ["bob"]

    token = fragment["token"][0]
    with urllib.request.urlopen(f"http://{one.netloc}/api/stats?token={token}") as r:
        assert json.loads(r.read())["nodes"] == 2


def test_agent_answers_are_compact_by_default(setup):
    server, _ = setup
    graph = call(server, "get_graph")
    assert all(set(link) == {"source", "target", "type", "count"} for link in graph["links"])
    assert "links_truncated" in graph["meta"]
    around = call(server, "neighbors", node_id="vault:Bob")
    assert all("props" not in link for link in around["links"])
