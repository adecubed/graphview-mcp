"""Generate the demo vault: a fictional lab's notes over eighteen months.

Everything here is invented. The vault is built to show what the viewer does:
typed notes, hubs, a few small islands, loose notes that end up on the rim, and
creation dates spread out so the time-lapse has a story to tell.

    python examples/make_vault.py        # rewrites examples/vault
"""

from __future__ import annotations

import random
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).parent / "vault"
START = date(2025, 3, 3)
DAYS = 540

PEOPLE = ["Ada Moretti", "Leo Bianchi", "Nora Feld", "Ivan Krol", "Mei Tanaka", "Omar Haddad",
          "Sara Lindqvist", "Tom Okoye", "Yuki Arai", "Pablo Reyes", "Hana Novak", "Elio Serra",
          "Greta Holm", "Rafi Cohen", "Lin Wei", "Dara Quinn", "Milo Varga", "Ines Duarte",
          "Kofi Mensah", "Vera Sokol", "Noor Aziz", "Tess Marlow", "Juno Park", "Aldo Ferri"]
PROJECTS = ["Lighthouse", "Tidewater", "Quiet Orbit", "Paper Kite", "Salt Road",
            "Glass Harbor", "North Signal", "Ember Line", "Slow River"]
CONCEPTS = ["Spaced repetition", "Knowledge graph", "Vector search", "BM25", "Entity resolution",
            "Deduplication", "Federation", "Masking", "Force layout", "Provenance",
            "Consolidation", "Recall", "Episodic memory", "Semantic memory", "Working memory",
            "Decay", "Reinforcement", "Alias table", "Reranking", "Chunking", "Embeddings",
            "Stopwords", "Tokenizer", "Graph sampling", "Community detection", "Read-only access",
            "Local first", "Sync conflict", "Schema mapping", "Wikilinks", "Frontmatter",
            "Time-lapse", "Bloom", "Sprite rendering", "Orbit controls", "Latency budget",
            "Evaluation set", "Judge model", "Ground truth", "Regression test"]
TAGS = ["research", "infra", "design", "memory", "urgent", "idea", "retro", "demo"]
# Small groups that link only among themselves: they show up as islands.
ISLANDS = [["Sourdough log", "Flour notes", "Oven schedule"],
           ["Bike route north", "Bike route coast", "Tyre pressure"],
           ["Chess openings", "Endgame drills"],
           ["Office plants", "Watering rota", "Repotting day", "Light levels"]]
# Notes nobody links to and that link to nothing: they form the rim.
LOOSE = ["a name for the reading group", "why does the fan rattle", "book - the art of memory",
         "talk idea - forgetting on purpose", "quote about maps and territories",
         "is the whiteboard photo anywhere", "colour of the new logo", "lunch place near the station",
         "podcast about archives", "todo - renew the domain", "half a thought about indexes",
         "what did the reviewer mean", "the dream about the library", "gift for the retirement",
         "train times in august", "keyboard layout experiment", "one line about trust",
         "paper to reread someday", "conference deadline guess", "recipe from the offsite",
         "a better word for recall", "the diagram on the napkin", "question for the lawyers",
         "stray idea about colour", "note to self about naming", "unfinished haiku",
         "who owns the old server", "the photo of the first demo", "a list with one item",
         "reminder that went nowhere", "sketch for a poster", "thing to ask at the next retro",
         "why we stopped using the wiki", "a title without a talk", "the second napkin"]


def main() -> None:
    rng = random.Random(11)
    # Only the notes go: a sync client may be holding the folders themselves.
    for old in ROOT.rglob("*.md"):
        old.unlink()

    def day(lo: float, hi: float) -> str:
        """A date within the given fractions of the vault's lifetime."""
        return (START + timedelta(days=int(rng.uniform(lo, hi) * DAYS))).isoformat()

    def write(folder: str, name: str, front: dict, body: str) -> None:
        path = ROOT / folder / f"{name}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        head = "---\n" + "".join(f"{k}: {v}\n" for k, v in front.items()) + "---\n"
        path.write_text(head + body + "\n", encoding="utf-8")

    def links(names) -> str:
        return ", ".join(f"[[{n}]]" for n in names)

    # The lab starts small: a few people, two projects, the core ideas.
    born = {}
    for i, person in enumerate(PEOPLE):
        born[person] = day(0, 0.08) if i < 6 else day(0.05, 0.8)
    for i, project in enumerate(PROJECTS):
        born[project] = day(0, 0.05) if i < 2 else day(0.1 + i * 0.07, 0.2 + i * 0.08)
    for i, concept in enumerate(CONCEPTS):
        born[concept] = day(0, 0.15) if i < 12 else day(0.1, 0.95)

    # Each project has a home: its own people and its own ideas. A few people sit
    # in two projects and a few ideas are shared, and those are the bridges. Without
    # this the vault is one ball of wool and the viewer has no structure to show.
    shuffled_people = PEOPLE[:]
    rng.shuffle(shuffled_people)
    shuffled_concepts = CONCEPTS[:]
    rng.shuffle(shuffled_concepts)
    teams, ideas = {}, {}
    for i, project in enumerate(PROJECTS):
        teams[project] = shuffled_people[i * 24 // len(PROJECTS):(i + 1) * 24 // len(PROJECTS)]
        ideas[project] = shuffled_concepts[i * 40 // len(PROJECTS):(i + 1) * 40 // len(PROJECTS)]
    for i, project in enumerate(PROJECTS):  # the bridges
        neighbour = PROJECTS[(i + 1) % len(PROJECTS)]
        if i % 2 == 0:
            teams[project] = teams[project] + [teams[neighbour][0]]
        if i % 3 == 0:
            ideas[project] = ideas[project] + [ideas[neighbour][0]]
    home = {c: p for p in PROJECTS for c in ideas[p][:4]}

    for concept in CONCEPTS:
        nearby = [c for c in ideas.get(home.get(concept), CONCEPTS) if c != concept]
        related = rng.sample(nearby, min(len(nearby), rng.choice([1, 2])))
        write("concepts", concept, {"type": "concept", "created": born[concept]},
              f"Notes on {concept.lower()}. Related: {links(related)}. #{rng.choice(TAGS)}")

    for project in PROJECTS:
        write("projects", project,
              {"type": "project", "created": born[project],
               "status": rng.choice(["active", "active", "paused", "done"])},
              f"Lead: [[{teams[project][0]}]]. Team: {links(teams[project][1:])}.\n"
              f"Builds on {links(ideas[project])}. #{rng.choice(TAGS)}")

    for person in PEOPLE:
        mine = [p for p in PROJECTS if person in teams[p]]
        mates = [m for p in mine for m in teams[p] if m != person]
        write("people", person,
              {"type": "person", "created": born[person],
               "role": rng.choice(["engineer", "researcher", "designer", "analyst"])},
              f"Works on {links(mine)}. Often pairs with [[{rng.choice(mates)}]].")

    for i in range(110):
        project = rng.choice(PROJECTS)
        # A meeting cannot happen before its project exists.
        when = max(day(0.02, 1.0), born[project])
        follow = "[[Open questions]]" if i % 9 == 0 else f"[[{rng.choice(ideas[project])}]]"
        write("meetings", f"{when} {project} sync {i:03d}", {"type": "meeting", "created": when},
              f"Present: {links(rng.sample(teams[project], 2))}.\n"
              f"Topic: [[{project}]]. Follow-up: {follow}.")

    for i in range(36):
        project = rng.choice(PROJECTS)
        write("papers", f"Reading {i + 1:02d}", {"type": "paper", "created": day(0.05, 1.0)},
              f"Shared by [[{rng.choice(teams[project])}]]. About {links(rng.sample(ideas[project], 2))}.")

    for group in ISLANDS:
        when = day(0.2, 0.9)
        for name in group:
            write("personal", name, {"type": "note", "created": when},
                  f"See also {links([n for n in group if n != name])}.")

    for name in LOOSE:
        write("inbox", name, {"type": "note", "created": day(0.0, 1.0)},
              "Jotted down in a hurry. Never filed.")

    print(sum(1 for _ in ROOT.rglob("*.md")), "notes written to", ROOT)


if __name__ == "__main__":
    main()
