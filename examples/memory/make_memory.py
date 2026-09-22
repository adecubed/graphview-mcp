"""Generate the example agent memory: two SQLite files about a fictional lab.

The same lab as examples/vault, but as an agent would remember it: episodes
(things that happened) distilled into atomic facts about entities, with the
shape a real memory has and a viewer must cope with:

- facts that supersede earlier versions (chains up to four long, some merges);
- facts nobody linked to an entity (they form the rim);
- a few small groups cut off from the rest (islands);
- confidence and last-use dates spread out, so colouring by them says something;
- creation dates over eighteen months, for the time-lapse.

Everything is invented. Two files, to show `attach:` in the mapping:

    graph.db    entities and typed links between them and the facts
    memory.db   facts, superseded facts, and the episodes they came from

    python examples/memory/make_memory.py      # rewrites both files
"""

from __future__ import annotations

import json
import random
import sqlite3
import re
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).parent
START = datetime(2025, 3, 3, 9, 0)
DAYS = 540

PEOPLE = ["ada_moretti", "leo_bianchi", "nora_feld", "ivan_krol", "mei_tanaka", "omar_haddad",
          "sara_lindqvist", "tom_okoye", "yuki_arai", "pablo_reyes", "hana_novak", "elio_serra",
          "greta_holm", "rafi_cohen", "lin_wei", "dara_quinn", "milo_varga", "ines_duarte"]
PROJECTS = ["lighthouse", "tidewater", "quiet_orbit", "paper_kite", "salt_road", "glass_harbor",
            "north_signal", "ember_line"]
TOOLS = ["vector_search", "bm25_index", "entity_resolver", "distiller", "recall_gate", "masker",
         "consolidation_job", "episode_store", "alias_table", "judge_model", "graph_sync", "reranker"]
PLACES = ["harbour_office", "north_lab", "the_annex", "station_room"]
CHANNELS = ["chat", "voice", "email", "meeting"]

STATE_FACTS = [  # (name, template, first value, later values): these produce supersedes chains
    ("port", "{p} runs on port {v}.", "8010", ["8766", "8767"]),
    ("ships", "{p} ships every {v}.", "Friday", ["Thursday", "Wednesday"]),
    ("lead", "{p} is led by {v}.", None, None),
    ("deploy", "{p} is deployed on {v}.", "the old rack", ["Render", "the north lab cluster"]),
    ("index", "{p} stores its index in {v}.", "a JSON file", ["SQLite", "SQLite with FTS5"]),
    ("model", "The default model for {p} is {v}.", "flash-1", ["flash-2", "flash-2.5"]),
    ("status", "{p} is {v}.", "in design", ["active", "paused", "done"]),
]
STRUCT_FACTS = [  # (tag for the key, template)
    ("ranking", "{p} uses {t} to rank what it retrieves."),
    ("retention", "{p} keeps every episode for 180 days before archiving it."),
    ("origin", "{p} was started to replace the shared spreadsheet the lab used before."),
    ("pairing", "{who} pairs with {who2} on {p} most afternoons."),
    ("owner", "{who} owns the {t} in {p} and reviews every change to it."),
    ("demo", "The demo of {p} is given from {where}."),
    ("mcp", "{p} exposes {t} through an MCP server with read-only tools."),
    ("author", "{who} wrote the first version of {t} in a weekend."),
    ("meetings", "Meetings about {p} happen in {where} on Mondays."),
    ("rewrite", "{t} was rewritten once after it dropped facts nobody mentioned any more."),
]
# Loose facts, never linked to an entity: the rim. Subjects times predicates,
# so each sentence has its own words and the worklist does not mistake them
# for duplicates of one another.
LOOSE_SUBJECTS = ["The reading group", "The fan in the annex", "The domain renewal", "The whiteboard photo",
                  "The quote about maps", "Lunch near the station", "The archives podcast", "The keyboard experiment",
                  "The napkin diagram", "The retirement gift", "The offsite train", "The retro notes",
                  "The second napkin", "The poster sketch", "The reviewer's comment", "The cache bug"]
LOOSE_PREDICATES = ["meets at four when nobody objects.", "was never written down properly.",
                    "came up again in June and was dropped.", "is still pinned to the wall of the annex.",
                    "turned out to be right about the cache.", "belongs to whoever asked last."]


def main() -> None:
    rng = random.Random(23)
    graph_path, memory_path = HERE / "graph.db", HERE / "memory.db"
    for path in (graph_path, memory_path):
        if path.exists():
            path.unlink()

    def when(lo: float, hi: float) -> datetime:
        return START + timedelta(days=rng.uniform(lo, hi) * DAYS, hours=rng.randint(0, 9))

    iso = lambda d: d.isoformat(timespec="seconds")
    entities: dict[str, tuple[str, datetime]] = {}
    for name in PEOPLE:
        entities[name] = ("person", when(0, 0.6))
    for name in PROJECTS:
        entities[name] = ("project", when(0, 0.7))
    for name in TOOLS:
        entities[name] = ("tool", when(0.05, 0.8))
    for name in PLACES:
        entities[name] = ("place", when(0, 0.3))

    episodes: list[tuple[str, datetime, str, str]] = []       # id, at, channel, summary
    facts: list[dict] = []
    links: list[tuple[str, str, str, datetime]] = []          # src, dst, kind, at
    ep_counter = 0

    def new_episode(at: datetime, summary: str) -> str:
        nonlocal ep_counter
        ep_counter += 1
        eid = f"ep-{ep_counter:04d}"
        episodes.append((eid, at, rng.choice(CHANNELS), summary))
        return eid

    taken: set[str] = set()

    def slug_for(content: str) -> str:
        """Descriptive keys, as a real memory has: the first words of the fact."""
        words = [w for w in re.findall(r"[a-z0-9]+", content.lower()) if w not in ("the", "a", "of", "is", "in", "on")]
        base = "_".join(words[:6]) or "fact"
        key, n = base, 2
        while key in taken:
            key, n = f"{base}_{n}", n + 1
        taken.add(key)
        return key

    def add_fact(key: str | None, content: str, at: datetime, about: list[str], *, supersedes=None,
                 confidence=None, relation="fact", n_sources=None) -> dict:
        # an explicit key that is already taken gets a counter, like a derived one
        key = slug_for(content) if key is None else key if key not in taken else slug_for(key.replace("_", " "))
        taken.add(key)
        n_sources = n_sources if n_sources is not None else rng.choice([1, 1, 2, 3, 5])
        sources = [new_episode(at - timedelta(days=rng.uniform(0, 20)), f"{rng.choice(CHANNELS)}: {content[:60]}")
                   for _ in range(n_sources)]
        last_used = at + timedelta(days=rng.uniform(0, max(1, (START + timedelta(days=DAYS) - at).days)))
        fact = {"key": key, "content": content, "confidence": confidence if confidence is not None
                else round(rng.uniform(0.35, 1.0), 2), "created_at": iso(at), "last_used": iso(last_used),
                "relation": relation, "supersedes": supersedes, "sources": sources, "superseded": 0}
        facts.append(fact)
        for slug in about:
            links.append((f"fact:{key}", slug, "mentions", at))
        return fact

    # State facts: chains of versions. Each new version supersedes the previous.
    for project in PROJECTS:
        for name, template, first, later in STATE_FACTS:
            if rng.random() < 0.55:
                continue
            values = [first] + list(later or []) if first else [rng.choice(PEOPLE), rng.choice(PEOPLE)]
            values = values[: rng.randint(1, len(values))]
            at = entities[project][1] + timedelta(days=rng.uniform(1, 60))
            previous = None
            for i, value in enumerate(values):
                key = f"{project}_{name}_v{i + 1}"
                about = [project] + ([value] if value in PEOPLE else [])
                fact = add_fact(key, template.format(p=project.replace("_", " "), v=value), at, about,
                                supersedes=previous["key"] if previous else None,
                                relation="updates" if previous else "fact")
                if previous:
                    previous["superseded"] = 1
                    links.append((f"fact:{fact['key']}", f"fact:{previous['key']}", "supersedes", at))
                previous = fact
                at += timedelta(days=rng.uniform(20, 120))

    # Structural facts: the body of the memory.
    for i in range(170):
        project = rng.choice(PROJECTS)
        who, who2, tool, where = rng.choice(PEOPLE), rng.choice(PEOPLE), rng.choice(TOOLS), rng.choice(PLACES)
        tag, template = rng.choice(STRUCT_FACTS)
        content = template.format(p=project.replace("_", " "), t=tool.replace("_", " "),
                                  who=who.replace("_", " ").title(), who2=who2.replace("_", " ").title(),
                                  where=where.replace("_", " "))
        about = [project] + [x for x in (who, who2, tool, where) if "{" + {who: "who", who2: "who2", tool: "t", where: "where"}[x] + "}" in template]
        add_fact("_".join(sorted(set(about)) + [tag]), content, when(0.02, 1.0), sorted(set(about)))

    # Two merges: a fact that replaced two earlier ones at once.
    for n, project in enumerate(rng.sample(PROJECTS, 2)):
        at = when(0.5, 0.9)
        a = add_fact(f"merge_{n}_a", f"{project.replace('_', ' ')} has a nightly build.", at - timedelta(days=90), [project], n_sources=1)
        b = add_fact(f"merge_{n}_b", f"The nightly build of {project.replace('_', ' ')} runs the evaluation set.", at - timedelta(days=60), [project], n_sources=1)
        merged = add_fact(f"merge_{n}_merged", f"{project.replace('_', ' ')} has a nightly build that runs the evaluation set.",
                          at, [project, "judge_model"], supersedes=[a["key"], b["key"]], relation="merged", confidence=0.95)
        a["superseded"] = b["superseded"] = 1
        links += [(f"fact:{merged['key']}", f"fact:{a['key']}", "supersedes", at),
                  (f"fact:{merged['key']}", f"fact:{b['key']}", "supersedes", at)]

    # Loose facts: distilled, never tied to anything. The rim.
    for subject in LOOSE_SUBJECTS:
        for predicate in LOOSE_PREDICATES:
            add_fact(None, f"{subject} {predicate}", when(0, 1.0), [], n_sources=1)

    # A few likely duplicates on purpose: the same thing written twice.
    for project in rng.sample(PROJECTS, 3):
        add_fact(f"{project}_weekly_review", f"{project.replace('_', ' ')} has a weekly review on Monday.", when(0.2, 0.6), [project], n_sources=1)
        add_fact(f"{project}_weekly_reviews", f"{project.replace('_', ' ')} holds weekly reviews on Mondays.", when(0.6, 0.9), [project], n_sources=1)

    # Islands: three tiny groups that only talk to each other.
    for n, group in enumerate([["sourdough_log", "flour_notes", "oven_schedule"],
                               ["bike_route_north", "tyre_pressure"],
                               ["office_plants", "watering_rota", "light_levels"]]):
        at = when(0.3, 0.8)
        for slug in group:
            entities[slug] = ("thing", at)
        for slug in group:
            other = rng.choice([g for g in group if g != slug])
            add_fact(f"island_{n}_{slug}", f"{slug.replace('_', ' ')} goes with {other.replace('_', ' ')}.", at, [slug, other], n_sources=1)

    # Entity-to-entity links: who works on what, what uses what.
    for person in PEOPLE:
        for project in rng.sample(PROJECTS, rng.randint(1, 2)):
            links.append((person, project, "works_on", entities[person][1]))
    for project in PROJECTS:
        for tool in rng.sample(TOOLS, rng.randint(2, 4)):
            links.append((project, tool, "uses", entities[project][1]))

    con = sqlite3.connect(graph_path)
    con.executescript("""
        CREATE TABLE entities (slug TEXT PRIMARY KEY, kind TEXT, first_seen TEXT, mentions INTEGER);
        CREATE TABLE links (src TEXT, dst TEXT, kind TEXT, created_at TEXT);
    """)
    mentions = {}
    for src, dst, kind, _ in links:
        if kind == "mentions":
            mentions[dst] = mentions.get(dst, 0) + 1
    con.executemany("INSERT INTO entities VALUES (?, ?, ?, ?)",
                    [(slug, kind, iso(at), mentions.get(slug, 0)) for slug, (kind, at) in entities.items()])
    con.executemany("INSERT INTO links VALUES (?, ?, ?, ?)", [(s, d, k, iso(a)) for s, d, k, a in links])
    con.commit()
    con.close()

    con = sqlite3.connect(memory_path)
    con.executescript("""
        CREATE TABLE facts (key TEXT PRIMARY KEY, content TEXT, confidence REAL, created_at TEXT,
                            last_used TEXT, relation TEXT, supersedes TEXT, sources TEXT, superseded INTEGER);
        CREATE TABLE episodes (id TEXT PRIMARY KEY, created_at TEXT, channel TEXT, summary TEXT);
    """)
    con.executemany("INSERT INTO facts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", [
        (f["key"], f["content"], f["confidence"], f["created_at"], f["last_used"], f["relation"],
         json.dumps(f["supersedes"]) if isinstance(f["supersedes"], list) else f["supersedes"],
         json.dumps(f["sources"]), f["superseded"]) for f in facts])
    con.executemany("INSERT INTO episodes VALUES (?, ?, ?, ?)", [(e, iso(at), ch, s) for e, at, ch, s in episodes])
    con.commit()
    con.close()
    print(f"{len(entities)} entities, {len(facts)} facts ({sum(f['superseded'] for f in facts)} superseded), "
          f"{len(links)} links, {len(episodes)} episodes")


if __name__ == "__main__":
    main()
