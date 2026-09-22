from pathlib import Path

import pytest

from graphview.config import ConfigError, load_config


def test_bare_folder_guesses_wikilinks(tmp_path):
    cfg = load_config(cli_path=str(tmp_path))
    assert cfg.sources == [{"name": tmp_path.name, "adapter": "wikilinks",
                            "path": str(tmp_path)}]
    assert cfg.masking is False and cfg.limit == 5000


def test_bare_json_guesses_memory(tmp_path):
    f = tmp_path / "memory.json"
    f.write_text("", encoding="utf-8")
    assert load_config(cli_path=str(f)).sources[0]["adapter"] == "memory_json"


def test_bare_database_needs_a_mapping(tmp_path):
    f = tmp_path / "x.db"
    f.write_bytes(b"")
    with pytest.raises(ConfigError, match="mapping"):
        load_config(cli_path=str(f))


def test_yaml_file_with_relative_paths_and_options(tmp_path):
    (tmp_path / "vault").mkdir()
    cfg_file = tmp_path / "graphview.yaml"
    cfg_file.write_text(
        "sources:\n"
        "  - name: notes\n    adapter: wikilinks\n    path: vault\n"
        "masking: true\nlimit: 200\n"
        "colors:\n  person: '#ff0000'\n", encoding="utf-8")
    cfg = load_config(config_path=str(cfg_file))
    assert cfg.sources[0]["path"] == str(tmp_path / "vault")
    assert cfg.masking is True and cfg.limit == 200
    assert cfg.colors == {"person": "#ff0000"}


def test_duplicate_source_names_are_rejected(tmp_path):
    cfg_file = tmp_path / "graphview.yaml"
    cfg_file.write_text(
        "sources:\n"
        "  - {name: a, adapter: wikilinks, path: .}\n"
        "  - {name: a, adapter: wikilinks, path: .}\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="duplicate"):
        load_config(config_path=str(cfg_file))


def test_nothing_given_is_an_error():
    with pytest.raises(ConfigError):
        load_config()


def test_tilde_in_path_is_expanded(tmp_path):
    cfg_file = tmp_path / "graphview.yaml"
    cfg_file.write_text("sources:\n  - {name: a, adapter: wikilinks, path: ~/vault}\n",
                        encoding="utf-8")
    cfg = load_config(config_path=str(cfg_file))
    assert cfg.sources[0]["path"] == str(Path.home() / "vault")


def test_attach_paths_are_resolved_like_the_main_path(tmp_path):
    cfg_file = tmp_path / "graphview.yaml"
    cfg_file.write_text(
        "sources:\n  - name: b\n    adapter: sqlite\n    path: g.db\n"
        "    attach: {sem: data/s.db}\n", encoding="utf-8")
    source = load_config(config_path=str(cfg_file)).sources[0]
    assert source["attach"] == {"sem": str(tmp_path / "data" / "s.db")}


def test_cli_mask_flag_overrides_the_config(tmp_path, monkeypatch):
    from graphview import cli
    seen = {}
    monkeypatch.setattr(cli, "GraphService", lambda config: seen.setdefault("config", config))
    monkeypatch.setattr(cli, "start_viewer", lambda service, port=0: (_ for _ in ()).throw(SystemExit(0)))
    with pytest.raises(SystemExit):
        cli.main(["serve", str(tmp_path), "--mask"])
    assert seen["config"].masking is True
