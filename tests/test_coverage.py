import json

import pytest

from graphview import coverage
from graphview.config import Config
from graphview.service import GraphService


@pytest.fixture
def service(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    notes = {
        "Ada": "---\ntype: person\n---\nLeads [[Lighthouse]].",
        "Leo": "---\ntype: person\n---\nWorks on [[Lighthouse]].",
        "Lighthouse": "---\ntype: project\ndescription: Ships every Friday from the harbour office\n---\nx",
        "Tidewater": "---\ntype: project\ndescription: Paused since March\n---\nx",
        "Forgotten": "Nobody ever asks about this.",
    }
    for name, body in notes.items():
        (vault / f"{name}.md").write_text(body, encoding="utf-8")
    return GraphService(Config(sources=[{"name": "v", "adapter": "wikilinks", "path": str(vault)}]))


def test_questions_load_from_json_jsonl_and_text(tmp_path):
    (tmp_path / "a.json").write_text(json.dumps([
        {"question": "who leads lighthouse", "expected": ["Ada"], "entity": "x"},
        "plain string question",
        {"query": "other field name"},
        {"no_question_here": 1},
    ]), encoding="utf-8")
    (tmp_path / "b.jsonl").write_text('{"question": "from jsonl"}\n\n', encoding="utf-8")
    (tmp_path / "c.txt").write_text("first line\n\n# a comment\nsecond line\n", encoding="utf-8")
    loaded = coverage.load_questions([tmp_path / "a.json", tmp_path / "b.jsonl", tmp_path / "c.txt"])
    assert [q["question"] for q in loaded] == [
        "who leads lighthouse", "plain string question", "other field name",
        "from jsonl", "first line", "second line"]
    assert loaded[0]["expected"] == [["Ada"]] and loaded[1]["expected"] == []
    assert loaded[0]["origin"] == "a.json"


def test_probe_makes_one_question_per_node_of_a_type_best_connected_first(service):
    probes = coverage.probe_questions(service.graph, "person", limit=10)
    assert [p["question"] for p in probes] == ["Ada", "Leo"]
    assert all(p["origin"] == "probe:person" and p["expected"] == [] for p in probes)
    assert len(coverage.probe_questions(service.graph, "person", limit=1)) == 1
    # a slug becomes words, the way a person would type it
    from graphview.model import Graph, Node
    g = Graph()
    g.add_node(Node("s:x", "atlas_server-v2", "entity", "s"))
    g.finalize()
    assert coverage.probe_questions(g, "entity")[0]["question"] == "atlas server v2"


def test_run_counts_hits_per_node_and_checks_what_was_expected(service):
    questions = [
        {"question": "lighthouse", "expected": [["every Friday"]], "origin": "t"},
        {"question": "tidewater", "expected": [["since April"]], "origin": "t"},   # retrieved, but the text is not there
        {"question": "zzzz nothing", "expected": [], "origin": "t"},
    ]
    seen = []
    report = coverage.run(service, questions, progress=lambda done, total: seen.append((done, total)))
    assert seen[-1] == (3, 3)
    assert report["hits"]["v:Lighthouse"] == 1 and report["hits"]["v:Tidewater"] == 1
    assert "v:Forgotten" not in report["hits"]
    first, second, third = report["questions"]
    assert first["retrieved"] is True and "v:Lighthouse" in first["hits"]
    assert second["retrieved"] is False and second["hits"]       # it found nodes, not the expected text
    assert third["retrieved"] is None and third["hits"] == []     # nothing expected: nothing to judge
    assert report["summary"] == {"questions": 3, "nodes": 5, "ever_retrieved": report["summary"]["ever_retrieved"],
                                 "never_retrieved": 5 - report["summary"]["ever_retrieved"],
                                 "with_expectation": 2, "expected_retrieved": 1, "expected_in_answer": 0, "mode": "text",
                                 "reach_by_type": {"project": [2, 2]}}
    assert report["summary"]["ever_retrieved"] >= 2


def test_report_is_saved_per_memory_and_served(service, graphview_home):
    assert service.coverage() is None
    report = coverage.run(service, [{"question": "lighthouse", "expected": [], "origin": "t"}])
    path = coverage.save(service.config.sources, report)
    assert path.parent == graphview_home and path.name.startswith("coverage-")
    served = service.coverage()
    assert served["summary"]["questions"] == 1 and served["hits"]["v:Lighthouse"] == 1
    assert served["date"] == report["date"]


def test_cli_runs_a_coverage_pass(service, tmp_path, graphview_home, capsys):
    from graphview import cli
    questions = tmp_path / "q.json"
    questions.write_text(json.dumps([{"question": "lighthouse", "expected": ["Friday"]}]), encoding="utf-8")
    vault = service.config.sources[0]["path"]
    code = cli.main(["coverage", vault, "--questions", str(questions), "--probe", "person"])
    assert code == 0
    err = capsys.readouterr().err
    assert "3 questions" in err and "expected text retrieved: 1 of 1" in err
    assert list(graphview_home.glob("coverage-*.json"))


def test_coverage_is_served_over_http(service, graphview_home):
    import threading
    import urllib.request

    from graphview.http_api import make_server

    coverage.save(service.config.sources,
                  coverage.run(service, [{"question": "lighthouse", "expected": [], "origin": "t"}]))
    server = make_server(service, "tok", port=0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{server.server_address[1]}/api/coverage?token=tok") as r:
            body = json.loads(r.read())
        assert body["available"] is True and body["hits"]["v:Lighthouse"] == 1
    finally:
        server.shutdown()
        server.server_close()


def test_expected_is_groups_of_alternatives_in_the_adebench_shape(tmp_path):
    (tmp_path / "cases.json").write_text(json.dumps([
        {"question": "a", "expected": [["8766"], ["harbour", "port"]]},   # every group, any alternative
        {"question": "b", "expected": ["flat", "strings"]},               # each string its own group
        {"question": "c", "expected": "one string"},
    ]), encoding="utf-8")
    a, b, c = coverage.load_questions([tmp_path / "cases.json"])
    assert a["expected"] == [["8766"], ["harbour", "port"]]
    assert b["expected"] == [["flat"], ["strings"]]
    assert c["expected"] == [["one string"]]


def test_expected_words_match_whole_tokens_and_any_alternative():
    text = "The service listens on port 8766, not 18766."
    assert coverage.satisfied([["8766"]], text) is True
    assert coverage.satisfied([["876"]], text) is False                  # not a whole token
    assert coverage.satisfied([["harbour", "PORT"]], text) is True         # any alternative, any case
    assert coverage.satisfied([["8766"], ["harbour"]], text) is False    # every group is needed
    assert coverage.satisfied([], text) is None


def test_a_case_can_be_in_the_answer_without_being_in_the_listed_hits():
    class Stub:
        class graph:
            nodes = {"s:a": 1}

        def search(self, query, limit):
            return {"mode": "recall", "answer": "Card: the harbour office ships every Friday.",
                    "matches": [{"id": "s:a", "label": "a", "props": {}, "snippet": "Something else."}]}

    report = coverage.run(Stub(), [{"question": "when", "expected": [["Friday"]], "origin": "t"}])
    row = report["questions"][0]
    assert row["retrieved"] is False and row["in_answer"] is True
    assert report["summary"]["expected_retrieved"] == 0 and report["summary"]["expected_in_answer"] == 1
