"""`graphview app`: the viewer in a window of its own, no browser.

The same local server as `serve`, shown through the system's web view
(pywebview: WebView2 on Windows, WebKit on macOS and Linux). With no memory
given, a first-run panel lets the user pick one: a notes folder, a
memory.json, or a graphview.yaml for a SQLite memory. The choice is remembered
in graphview's own folder, so the next start opens straight on it.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from .config import Config, ConfigError, load_config

CHOICE_FILE = "app.json"


def _own_folder() -> Path:
    return Path(os.environ.get("GRAPHVIEW_HOME") or str(Path.home() / ".graphview"))


def remember(kind: str, path: str) -> None:
    folder = _own_folder()
    folder.mkdir(parents=True, exist_ok=True)
    (folder / CHOICE_FILE).write_text(json.dumps({"kind": kind, "path": path}), encoding="utf-8")


def recall_choice() -> dict | None:
    file = _own_folder() / CHOICE_FILE
    if not file.exists():
        return None
    try:
        choice = json.loads(file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if isinstance(choice, dict) and choice.get("path") and Path(choice["path"]).exists():
        return choice
    return None


def config_for(kind: str, path: str) -> Config:
    """A configuration from what the user picked. `kind` is folder, file or config."""
    if kind == "config":
        return load_config(config_path=path)
    picked = Path(path)
    if picked.suffix.lower() in (".db", ".sqlite", ".sqlite3"):
        raise ConfigError("a SQLite memory needs a mapping: pick its graphview.yaml instead "
                          "(examples/memory/graphview.yaml in the repository shows one)")
    if picked.suffix.lower() in (".yaml", ".yml"):
        return load_config(config_path=path)
    return load_config(cli_path=path)


SETUP_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>graphview</title>
<style>
  body { margin: 0; height: 100vh; display: grid; place-items: center; background: #070b1c; color: #cfe9ff;
         font: 14px/1.5 ui-monospace, "Cascadia Mono", Consolas, monospace; }
  main { width: min(560px, 90vw); padding: 28px 32px; border: 1px solid rgba(76,201,240,.35);
         background: rgba(10,16,38,.74); }
  h1 { margin: 0 0 4px; font-size: 18px; font-weight: 500; letter-spacing: .08em; color: #4cc9f0; }
  p { margin: 0 0 18px; color: #6f8aa3; }
  button { display: block; width: 100%; margin: 8px 0; padding: 10px 14px; text-align: left; cursor: pointer;
           border: 1px solid rgba(76,201,240,.35); background: none; color: #cfe9ff; font: inherit; }
  button:hover { background: rgba(76,201,240,.16); }
  button b { color: #4cc9f0; font-weight: 500; }
  button span { display: block; color: #6f8aa3; font-size: 12px; }
  #status { min-height: 1.5em; margin-top: 14px; color: #ffd166; white-space: pre-wrap; }
</style></head>
<body><main>
  <h1>GRAPHVIEW</h1>
  <p>See what your agent knows, and how it finds it. Pick a memory to open.</p>
  <button onclick="pick('folder')"><b>A notes folder</b><span>Obsidian or any markdown with [[wikilinks]]</span></button>
  <button onclick="pick('file')"><b>A memory.json</b><span>the Knowledge Graph Memory MCP file</span></button>
  <button onclick="pick('config')"><b>A graphview.yaml</b><span>a SQLite memory, several sources, a recall endpoint</span></button>
  <div id="status"></div>
</main>
<script>
  async function pick(kind) {
    const s = document.getElementById('status');
    s.textContent = 'opening…';
    try {
      const r = await window.pywebview.api.pick(kind);
      if (r.url) location.href = r.url; else s.textContent = r.error || '';
    } catch (e) { s.textContent = String(e); }
  }
</script></body></html>
"""


def pick_dialog(window, kind: str):
    """The system's own file or folder dialog. Returns the chosen path(s) or None."""
    import webview

    dialogs = getattr(webview, "FileDialog", None)  # pywebview >= 5.1; the constants before
    folder = dialogs.FOLDER if dialogs else webview.FOLDER_DIALOG
    open_ = dialogs.OPEN if dialogs else webview.OPEN_DIALOG
    if kind == "folder":
        return window.create_file_dialog(folder)
    if kind == "file":
        return window.create_file_dialog(open_, file_types=("memory.json (*.json)", "All files (*.*)"))
    return window.create_file_dialog(open_, file_types=("graphview.yaml (*.yaml;*.yml)", "All files (*.*)"))


class _Api:
    """What the setup page can call. It runs in the Python process, not the page."""

    def __init__(self, window, open_memory) -> None:
        self.window = window
        self.open_memory = open_memory

    def pick(self, kind: str) -> dict:
        """Returns {"url": ...} for the page to navigate to, or {"error": ...}. The page
        navigates itself: doing it from here would race the delivery of this reply."""
        chosen = pick_dialog(self.window, kind)
        if not chosen:
            return {"error": ""}
        path = chosen[0] if isinstance(chosen, (list, tuple)) else chosen
        try:
            return {"url": self.open_memory(kind, str(path))}
        except ConfigError as exc:
            return {"error": str(exc)}
        except Exception as exc:  # a broken memory must show an error, not a blank window
            return {"error": f"could not open it: {exc}"}


def run(config_path: str | None = None, cli_path: str | None = None, port: int = 0,
        choose: bool = False) -> int:
    try:
        import webview
    except ImportError:
        print("graphview app needs pywebview: install graphview-mcp with the [app] extra, "
              "e.g.  uvx \"graphview-mcp[app]\" app", file=sys.stderr)
        return 2

    from .cli import start_viewer
    from .service import GraphService

    state: dict = {}

    def open_memory(kind: str, path: str) -> str:
        """Load the memory, start the local server, return the viewer URL."""
        config = config_for(kind, path)
        service = GraphService(config)
        url = start_viewer(service, port)
        state["service"] = service
        remember(kind, path)
        return url

    url = None
    if config_path:
        url = open_memory("config", config_path)
    elif cli_path:
        url = open_memory("file" if Path(cli_path).is_file() else "folder", cli_path)
    elif not choose and (last := recall_choice()):
        try:
            url = open_memory(last["kind"], last["path"])
        except Exception as exc:
            print(f"graphview: last memory could not be opened ({exc}); choose another", file=sys.stderr)

    if url:
        window = webview.create_window("graphview", url, width=1280, height=800, min_size=(720, 480))
    else:
        api = _Api(None, open_memory)
        window = webview.create_window("graphview", html=SETUP_HTML, js_api=api,
                                       width=720, height=480, min_size=(560, 400))
        api.window = window
    webview.start(private_mode=False, storage_path=str(_own_folder() / "webview"))
    return 0
