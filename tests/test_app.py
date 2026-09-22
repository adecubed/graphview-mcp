import json

import pytest

from graphview import app
from graphview.config import ConfigError


def test_choice_is_remembered_in_graphviews_own_folder_and_recalled(graphview_home, tmp_path):
    assert app.recall_choice() is None
    app.remember("folder", str(tmp_path))
    assert json.loads((graphview_home / "app.json").read_text(encoding="utf-8")) == {"kind": "folder", "path": str(tmp_path)}
    assert app.recall_choice() == {"kind": "folder", "path": str(tmp_path)}


def test_a_remembered_path_that_no_longer_exists_is_forgotten(graphview_home, tmp_path):
    app.remember("file", str(tmp_path / "gone.json"))
    assert app.recall_choice() is None


def test_config_for_each_kind_of_choice(tmp_path):
    (tmp_path / "vault").mkdir()
    assert app.config_for("folder", str(tmp_path / "vault")).sources[0]["adapter"] == "wikilinks"
    (tmp_path / "memory.json").write_text("", encoding="utf-8")
    assert app.config_for("file", str(tmp_path / "memory.json")).sources[0]["adapter"] == "memory_json"
    (tmp_path / "graphview.yaml").write_text("sources:\n  - {name: v, adapter: wikilinks, path: vault}\n", encoding="utf-8")
    assert app.config_for("config", str(tmp_path / "graphview.yaml")).sources[0]["name"] == "v"
    (tmp_path / "brain.db").write_bytes(b"")
    with pytest.raises(ConfigError, match="graphview.yaml"):
        app.config_for("file", str(tmp_path / "brain.db"))


def test_app_command_without_pywebview_explains_how_to_get_it(monkeypatch, capsys):
    import builtins
    real_import = builtins.__import__

    def no_webview(name, *args, **kwargs):
        if name == "webview":
            raise ImportError("no module named webview")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_webview)
    from graphview import cli
    assert cli.main(["app"]) == 2
    assert "[app]" in capsys.readouterr().err


def test_the_setup_api_returns_a_url_or_an_error_and_never_navigates_itself(tmp_path, graphview_home, monkeypatch):
    loaded = []

    class FakeWindow:
        def load_url(self, url):
            loaded.append(url)

    (tmp_path / "vault").mkdir()
    monkeypatch.setattr(app, "pick_dialog", lambda window, kind: [str(tmp_path / "vault")])
    opened = []
    api = app._Api(FakeWindow(), lambda kind, path: opened.append((kind, path)) or "http://127.0.0.1:1/#t")
    assert api.pick("folder") == {"url": "http://127.0.0.1:1/#t"}
    assert opened == [("folder", str(tmp_path / "vault"))] and loaded == []

    (tmp_path / "brain.db").write_bytes(b"")
    monkeypatch.setattr(app, "pick_dialog", lambda window, kind: [str(tmp_path / "brain.db")])
    assert "graphview.yaml" in app._Api(FakeWindow(), app.config_for).pick("file")["error"]

    monkeypatch.setattr(app, "pick_dialog", lambda window, kind: None)  # the user cancelled
    assert app._Api(FakeWindow(), None).pick("folder") == {"error": ""}
