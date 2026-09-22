"""The example memory must show every feature the README promises, out of the box."""
import json
import sys
import threading
import urllib.request
from pathlib import Path

from graphview.config import load_config
from graphview.service import GraphService

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "memory"


def test_example_memory_loads_with_the_shapes_the_viewer_shows():
    svc = GraphService(load_config(str(EXAMPLE / "graphview.yaml")))
    s = svc.stats()
    assert s["warnings"] == [] and s["dropped_edges"] == 0
    assert {"person", "project", "tool", "fact", "fact_superseded"} <= set(s["by_node_type"])
    assert s["by_edge_type"]["supersedes"] > 20
    w = svc.worklist()["summary"]
    assert w["unlinked"] > 50 and w["islands"] == 3 and w["duplicates"] > 0

    chain = max((svc.provenance(n) for n in svc.graph.nodes if n.startswith("lab:fact:")),
                key=lambda p: len(p["supersedes"]))
    assert len(chain["supersedes"]) >= 2 and chain["sources"]["sources"]
    assert chain["sources"]["sources"][0].keys() >= {"id", "created_at", "channel", "summary"}


def test_example_recall_server_answers_and_the_search_block_understands_it():
    sys.path.insert(0, str(EXAMPLE))
    import recall_server
    server = recall_server.serve(port=0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]
    try:
        import sqlite3
        con = sqlite3.connect(f"{(EXAMPLE / 'memory.db').as_uri()}?mode=ro", uri=True)
        project = con.execute("SELECT key FROM facts WHERE key LIKE '%_port_v%' AND superseded = 0").fetchone()[0].split("_port_")[0]
        con.close()
        question = f"which port does {project.replace('_', ' ')} run on"
        body = json.dumps({"query": question}).encode()
        req = urllib.request.Request(f"http://127.0.0.1:{port}/ask", data=body, headers={"Content-Type": "application/json"})
        reply = json.loads(urllib.request.urlopen(req, timeout=10).read())
        assert reply["results"] and reply["answer"].startswith("Best match")
        assert reply["results"][0]["key"].startswith(f"{project}_port_")

        config = load_config(str(EXAMPLE / "graphview.yaml"))
        config.sources[0]["search"]["url"] = f"http://127.0.0.1:{port}/ask"
        out = GraphService(config).search(question)
        assert out["mode"] == "recall" and out["answer"].startswith("Best match")
        assert out["matches"] and all(m["id"].startswith("lab:fact:") for m in out["matches"])
    finally:
        server.shutdown()
        server.server_close()
