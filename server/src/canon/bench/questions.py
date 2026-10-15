"""The question set: real questions about PostHog whose right answers come from structured, dated records.

Gold answers are never written by a model. They come from the feature ownership map's history (who owns an area
now, who owned it before) and from PostHog's published team leads. The categories:

- **stale-trap**: an area whose owner changed while a handbook page still names the old team. Search finds the page.
- **changed**: an area whose owner changed in the last year.
- **history**: who owned an area before its current team.
- **lead**: who leads a team.
- **control**: an area whose owner has not changed in the last year.

Each question carries `gold` (any of these names is right) and `stale` (names that were right once and are not now).
"""

import json
import random
from pathlib import Path

SINCE = "2025-10-15"

OWNER_HISTORY = """
MATCH (f:Fact {predicate: 'owned_by', authority: 3})-[:ABOUT]->(a:Area)
OPTIONAL MATCH (f)-[:VALUE]->(t:Team)
RETURN a.slug, a.name, coalesce(t.name, f.value), f.valid_from, coalesce(f.valid_to, '')
"""
STALE_AREAS = "MATCH (f:Fact {stale: true})-[:ABOUT]->(a:Area) RETURN DISTINCT a.slug"
LEADS = "MATCH (p:Person)-[:LEADS]->(t:Team) RETURN t.slug, t.name, p.handle, p.role"


def build(graph, *, seed: int = 15, changed: int = 21, history: int = 6, leads: int = 10, controls: int = 6) -> list[dict]:
    areas: dict[str, dict] = {}
    for slug, name, team, start, end in graph.query(OWNER_HISTORY).result_set:
        a = areas.setdefault(slug, {"slug": slug, "name": name, "spans": []})
        a["spans"].append((start, end, team))
    for a in areas.values():
        a["spans"].sort()
        a["now"] = sorted({t for _, end, t in a["spans"] if not end})
        a["before"] = sorted({t for _, end, t in a["spans"] if end and end >= SINCE} - set(a["now"]))
    stale = {r[0] for r in graph.query(STALE_AREAS).result_set}
    rng = random.Random(seed)
    out: list[dict] = []

    def owner_q(a: dict, category: str) -> dict:
        return {
            "category": category,
            "question": f"Which team owns {a['name']}?",
            "gold": a["now"],
            "stale": a["before"],
            "area": a["slug"],
        }

    usable = [a for a in areas.values() if a["now"] and a["name"]]
    trap = sorted((a for a in usable if a["slug"] in stale and a["before"]), key=lambda a: a["slug"])
    out += [owner_q(a, "stale-trap") for a in trap]
    moved = sorted((a for a in usable if a["before"] and a["slug"] not in stale), key=lambda a: a["slug"])
    out += [owner_q(a, "changed") for a in rng.sample(moved, min(changed, len(moved)))]

    hist = [a for a in moved + trap if len(a["before"]) == 1]
    for a in rng.sample(sorted(hist, key=lambda a: a["slug"]), min(history, len(hist))):
        out.append({
            "category": "history",
            "question": f"Which team owned {a['name']} before {' and '.join(a['now'])}?",
            "gold": a["before"],
            "stale": [],
            "area": a["slug"],
        })

    steady = sorted(
        (a for a in usable if not a["before"] and all(start < SINCE for start, _, _ in a["spans"])),
        key=lambda a: a["slug"],
    )
    out += [owner_q(a, "control") for a in rng.sample(steady, min(controls, len(steady)))]

    teams: dict[str, dict] = {}
    for slug, name, handle, _ in graph.query(LEADS).result_set:
        # People are named by their public GitHub handle only; a lead without one is not asked about.
        if handle and not handle.startswith("name:"):
            teams.setdefault(slug, {"name": name, "gold": []})["gold"].append(handle)
    for slug in rng.sample(sorted(teams), min(leads, len(teams))):
        t = teams[slug]
        out.append({"category": "lead", "question": f"Who leads the {t['name']} team?", "gold": t["gold"], "stale": [], "team": slug})

    for i, q in enumerate(out):
        q["id"] = f"q{i + 1:02d}"
    return out


def save(questions: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(questions, indent=2, ensure_ascii=False) + "\n")


def load(path: Path) -> list[dict]:
    return json.loads(path.read_text())
