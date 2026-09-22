import json
import threading
import urllib.error
import urllib.parse
import urllib.request

import pytest

from graphview.config import Config
from graphview.http_api import make_server
from graphview.service import GraphService

TOKEN = "test-token"


@pytest.fixture
def base(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "Alice.md").write_text("[[Bob]]", encoding="utf-8")
    (vault / "Bob.md").write_text("hello", encoding="utf-8")
    svc = GraphService(Config(sources=[
        {"name": "vault", "adapter": "wikilinks", "path": str(vault)}]))
    server = make_server(svc, TOKEN, port=0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def get(base, path, token=TOKEN, **params):
    if token:
        params["token"] = token
    url = f"{base}{path}?{urllib.parse.urlencode(params, doseq=True)}"
    with urllib.request.urlopen(url) as r:
        return r.status, r.headers, r.read()


def get_json(base, path, **params):
    return json.loads(get(base, path, **params)[2])


def test_binds_to_loopback_only(base):
    assert base.startswith("http://127.0.0.1:")


def test_api_without_or_with_wrong_token_is_forbidden(base):
    for token in (None, "wrong"):
        with pytest.raises(urllib.error.HTTPError) as err:
            get(base, "/api/graph", token=token)
        assert err.value.code == 403


def test_token_is_accepted_in_header(base):
    req = urllib.request.Request(f"{base}/api/stats", headers={"X-Graphview-Token": TOKEN})
    with urllib.request.urlopen(req) as r:
        assert json.loads(r.read())["nodes"] == 2


def test_graph_node_neighbors_search_stats_types(base):
    assert len(get_json(base, "/api/graph")["nodes"]) == 2
    assert get_json(base, "/api/graph", node_types="missing")["nodes"] == []
    assert get_json(base, "/api/node", id="vault:Alice")["node"]["label"] == "Alice"
    assert len(get_json(base, "/api/neighbors", id="vault:Bob", depth=1)["nodes"]) == 2
    assert get_json(base, "/api/search", q="ali")["matches"][0]["id"] == "vault:Alice"
    assert get_json(base, "/api/stats")["edges"] == 1
    assert "note" in get_json(base, "/api/types")["node_types"]


def test_repeated_params_become_lists(base):
    d = get_json(base, "/api/graph", node_types=["note", "tag"])
    assert len(d["nodes"]) == 2


def test_bad_number_is_a_400_not_a_crash(base):
    with pytest.raises(urllib.error.HTTPError) as err:
        get(base, "/api/neighbors", id="vault:Bob", depth="deep")
    assert err.value.code == 400


def test_unknown_api_path_is_404(base):
    with pytest.raises(urllib.error.HTTPError) as err:
        get(base, "/api/nope")
    assert err.value.code == 404


def test_viewer_is_served_without_token_and_cannot_escape_its_folder(base):
    status, headers, body = get(base, "/", token=None)
    assert status == 200 and b"<html" in body.lower()
    with pytest.raises(urllib.error.HTTPError) as err:
        get(base, "/../config.py", token=None)
    assert err.value.code in (403, 404)


def test_only_get_is_allowed(base):
    req = urllib.request.Request(f"{base}/api/graph?token={TOKEN}", data=b"x", method="POST")
    with pytest.raises(urllib.error.HTTPError) as err:
        urllib.request.urlopen(req)
    assert err.value.code in (405, 501)


def test_foreign_host_header_is_rejected(base):
    req = urllib.request.Request(f"{base}/api/stats?token={TOKEN}",
                                 headers={"Host": "evil.example.com"})
    with pytest.raises(urllib.error.HTTPError) as err:
        urllib.request.urlopen(req)
    assert err.value.code == 403


def test_a_port_in_use_is_an_error_not_a_silent_shadow(base):
    port = int(base.rsplit(":", 1)[1])
    from graphview.config import Config
    from graphview.service import GraphService
    other = GraphService(Config(sources=[]))
    with pytest.raises(OSError):
        make_server(other, "tok2", port=port)
