"""Configuration: a graphview.yaml file, or a bare path whose adapter is guessed."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

DEFAULT_LIMIT = 5000


class ConfigError(ValueError):
    pass


@dataclass
class Config:
    sources: list[dict]
    masking: bool = False
    mask_patterns: list[str] | None = None
    limit: int = DEFAULT_LIMIT
    colors: dict[str, str] = field(default_factory=dict)
    names: dict[str, str] = field(default_factory=dict)   # plain names for kinds and groups


def _resolve(given: str, base: Path) -> str:
    path = Path(given).expanduser()
    return str(path if path.is_absolute() else (base / path).resolve())


def guess_adapter(path: Path) -> str:
    if path.is_dir():
        return "wikilinks"
    if path.suffix.lower() in (".json", ".jsonl"):
        return "memory_json"
    if path.suffix.lower() in (".db", ".sqlite", ".sqlite3"):
        raise ConfigError(
            f"{path.name} is a database: it needs a mapping. Write a graphview.yaml "
            "with an 'sqlite' source (see README) and pass it with --config.")
    raise ConfigError(f"cannot guess an adapter for {path}")


def load_config(config_path: str | None = None, cli_path: str | None = None) -> Config:
    if config_path:
        file = Path(config_path)
        try:
            raw = yaml.safe_load(file.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError) as exc:
            raise ConfigError(f"cannot read {file}: {exc}") from exc
        sources = raw.get("sources") or []
        if not sources:
            raise ConfigError(f"{file} lists no sources")
        names = [s.get("name") for s in sources]
        if None in names or "" in names:
            raise ConfigError("every source needs a name")
        if len(set(names)) != len(names):
            raise ConfigError("duplicate source names")
        for s in sources:
            if "path" in s:  # ~ is expanded; relative paths are relative to the config file
                s["path"] = _resolve(s["path"], file.parent)
            if isinstance(s.get("attach"), dict):
                s["attach"] = {alias: _resolve(p, file.parent) for alias, p in s["attach"].items()}
        return Config(sources=sources,
                      masking=bool(raw.get("masking", False)),
                      mask_patterns=raw.get("mask_patterns"),
                      limit=int(raw.get("limit", DEFAULT_LIMIT)),
                      colors=dict(raw.get("colors") or {}),
                      names={str(k): str(v) for k, v in (raw.get("names") or {}).items()})
    if cli_path:
        path = Path(cli_path)
        if not path.exists():
            raise ConfigError(f"{path} does not exist")
        return Config(sources=[{"name": path.stem if path.is_file() else path.name,
                                "adapter": guess_adapter(path), "path": str(path)}])
    raise ConfigError("give a path to a vault or memory file, or --config graphview.yaml")
