import json

from graphview import history
from graphview.worklist import to_markdown

SUMMARY = {"nodes": 100, "unlinked": 40, "islands": 5, "island_nodes": 12, "duplicates": 9}
SOURCES = [{"name": "brain", "adapter": "sqlite", "path": "/data/g.db"}]


def test_each_export_adds_a_dated_line(graphview_home):
    history.record(SOURCES, SUMMARY, today="2026-09-01")
    entries = history.record(SOURCES, {**SUMMARY, "unlinked": 31}, today="2026-09-15")
    assert [(e["date"], e["unlinked"]) for e in entries] == [("2026-09-01", 40), ("2026-09-15", 31)]
    assert (graphview_home / "worklist-history.jsonl").exists()


def test_a_second_export_on_the_same_day_replaces_the_first(graphview_home):
    history.record(SOURCES, SUMMARY, today="2026-09-01")
    entries = history.record(SOURCES, {**SUMMARY, "duplicates": 3}, today="2026-09-01")
    assert len(entries) == 1 and entries[0]["duplicates"] == 3


def test_different_sources_keep_separate_histories(graphview_home):
    other = [{"name": "notes", "adapter": "wikilinks", "path": "/vault"}]
    history.record(SOURCES, SUMMARY, today="2026-09-01")
    history.record(other, {**SUMMARY, "nodes": 7}, today="2026-09-01")
    assert [e["nodes"] for e in history.load(SOURCES)] == [100]
    assert [e["nodes"] for e in history.load(other)] == [7]
    # the same sources listed in another order are the same memory
    assert history.key(SOURCES + other) == history.key(other + SOURCES)


def test_a_damaged_line_is_skipped_not_fatal(graphview_home):
    history.record(SOURCES, SUMMARY, today="2026-09-01")
    file = graphview_home / "worklist-history.jsonl"
    file.write_text("{broken\n" + file.read_text(encoding="utf-8"), encoding="utf-8")
    entries = history.record(SOURCES, SUMMARY, today="2026-09-02")
    assert [e["date"] for e in entries] == ["2026-09-01", "2026-09-02"]


def test_the_file_holds_counts_and_nothing_from_the_graph(graphview_home):
    history.record(SOURCES, {**SUMMARY, "secret": "alice@example.com"}, today="2026-09-01")
    line = json.loads((graphview_home / "worklist-history.jsonl").read_text(encoding="utf-8"))
    assert set(line) == {"key", "date", "nodes", "unlinked", "islands", "island_nodes", "duplicates", "hubs"}
    assert "/data/g.db" not in json.dumps(line)


def test_markdown_shows_the_trend_and_the_change_since_last_time():
    entries = [{"date": "2026-09-01", **SUMMARY},
               {"date": "2026-09-15", **SUMMARY, "unlinked": 31, "duplicates": 11}]
    worklist = {"summary": entries[-1], "duplicates": [], "islands": [], "unlinked": []}
    text = to_markdown(worklist, "brain", entries)
    assert "## Trend" in text
    assert "| 2026-09-15 | 100 | 11 | 5 | 31 |" in text
    assert "Since 2026-09-01: duplicates +2, islands 0, unlinked -9." in text


def test_a_first_export_has_no_trend_section():
    worklist = {"summary": SUMMARY, "duplicates": [], "islands": [], "unlinked": []}
    assert "## Trend" not in to_markdown(worklist, "brain", [{"date": "2026-09-01", **SUMMARY}])


def test_exporting_markdown_records_but_reading_json_does_not(tmp_path, graphview_home):
    from graphview.config import Config
    from graphview.service import GraphService

    (tmp_path / "A.md").write_text("[[B]]", encoding="utf-8")
    (tmp_path / "B.md").write_text("x", encoding="utf-8")
    service = GraphService(Config(sources=[
        {"name": "v", "adapter": "wikilinks", "path": str(tmp_path)}]))
    service.worklist()
    assert service.worklist_history() == []
    service.worklist_markdown()
    assert len(service.worklist_history()) == 1
