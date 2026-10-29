"""A pinned token: `--token` first, then $GRAPHVIEW_TOKEN, then a fresh random
secret per run. A pin must reach the URL and the server alike, whichever face
started the server."""

import asyncio
import inspect
import json
import urllib.request
from urllib.parse import parse_qs, urlsplit

import pytest

from graphview.cli import start_viewer
from graphview.config import Config
from graphview.http_api import resolve_token
from graphview.mcp_server import build_server
from graphview.service import GraphService


@pytest.fixture
def service(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "Alice.md").write_text("[[Bob]]", encoding="utf-8")
    (vault / "Bob.md").write_text("hello", encoding="utf-8")
    return GraphService(Config(sources=[
        {"name": "vault", "adapter": "wikilinks", "path": str(vault)}]))


def _resolve(value):
    return asyncio.run(value) if inspect.isawaitable(value) else value


def _call(server, name, **arguments):
    result = _resolve(server.call_tool(name, arguments))
    if isinstance(result, tuple):       # mcp 1.x: (content, structured)
        result = result[0]
    content = getattr(result, "content", result)  # mcp 2.x: CallToolResult
    return json.loads(content[0].text)


def _fragment_token(url):
    return parse_qs(urlsplit(url).fragment)["token"][0]


def test_without_a_pin_the_token_is_fresh_random_per_run(monkeypatch):
    monkeypatch.delenv("GRAPHVIEW_TOKEN", raising=False)
    assert resolve_token() != resolve_token()


def test_the_environment_variable_pins_the_token(monkeypatch):
    monkeypatch.setenv("GRAPHVIEW_TOKEN", "from-env")
    assert resolve_token() == "from-env"


def test_the_flag_beats_the_environment_variable(monkeypatch):
    monkeypatch.setenv("GRAPHVIEW_TOKEN", "from-env")
    assert resolve_token("from-flag") == "from-flag"


def test_a_pinned_token_lands_in_the_serve_url_and_the_server_honours_it(service):
    url = start_viewer(service, token="pinned-by-flag")
    assert _fragment_token(url) == "pinned-by-flag"
    base = url.split("#")[0]
    with urllib.request.urlopen(f"{base}api/stats?token=pinned-by-flag") as r:
        assert json.loads(r.read())["nodes"] == 2


def test_mcp_open_viewer_uses_the_pinned_token(service):
    opened = []
    server = build_server(service, token="pinned-by-flag", opener=opened.append)
    url = _call(server, "open_viewer")["url"]
    assert _fragment_token(url) == "pinned-by-flag"
    netloc = urlsplit(url).netloc
    with urllib.request.urlopen(f"http://{netloc}/api/stats?token=pinned-by-flag") as r:
        assert json.loads(r.read())["nodes"] == 2
