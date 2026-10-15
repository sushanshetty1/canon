"""What the people screens show: who knows an area and on what evidence, and what one person knows."""

from canon.people.bus_factor import evidence, owners

RELS = ("DECIDED", "AUTHORED", "REVIEWED", "COMMENTED")

AREA = "MATCH (a:Area {slug: $slug}) RETURN a.slug, coalesce(a.name, a.slug), a.bus_factor, a.knowers"

KNOWERS = """
MATCH (p:Person)-[k:KNOWS]->(a:Area {slug: $slug})
OPTIONAL MATCH (a)-[d:DEPENDS_ON]->(p)
RETURN p.handle, coalesce(p.name, p.handle), p.role, k.score, k.evidence, coalesce(k.docs, []), d IS NOT NULL
ORDER BY k.score DESC, p.handle
"""

TEAMS = """
MATCH (p:Person)-[:MEMBER_OF]->(t:Team) WHERE p.handle IN $handles
RETURN p.handle, collect(coalesce(t.name, t.slug))
"""

DOCS = """
MATCH (p:Person)-[r]->(d:Document)
WHERE p.handle IN $handles AND d.id IN $ids AND type(r) IN $rels
RETURN p.handle, d.id, d.title, d.url, d.kind, d.updated_at, type(r), r.at
"""


def _teams(graph, handles: list[str]) -> dict[str, list[str]]:
    if not handles:
        return {}
    return {h: sorted(ts) for h, ts in graph.query(TEAMS, {"handles": handles}).result_set}


def area_people(graph, slug: str, *, limit: int = 24) -> dict | None:
    """The people who know an area, strongest first, each with their counts and the documents behind them."""
    found = graph.query(AREA, {"slug": slug}).result_set
    if not found:
        return None
    _, name, bus, knowers = found[0]
    rows = graph.query(KNOWERS, {"slug": slug}).result_set
    shown = rows[:limit]
    handles = [r[0] for r in shown]
    teams = _teams(graph, handles)
    ids = sorted({i for r in shown for i in r[5]})
    docs: dict[tuple[str, str], dict] = {}
    if ids:
        for handle, did, title, url, kind, updated, rel, at in graph.query(
            DOCS, {"handles": handles, "ids": ids, "rels": list(RELS)}
        ).result_set:
            doc = docs.setdefault(
                (handle, did),
                {"id": did, "title": title, "url": url, "kind": kind, "date": updated, "acts": []},
            )
            doc["acts"].append({"rel": rel.lower(), "at": at})
    people = []
    for handle, pname, role, score, ev, doc_ids, depends in shown:
        mine = []
        for i in doc_ids:
            if (handle, i) in docs:
                d = docs[(handle, i)]
                d["acts"].sort(key=lambda a: RELS.index(a["rel"].upper()))
                mine.append(d)
        people.append(
            {
                "handle": handle,
                "name": pname,
                "role": role,
                "teams": teams.get(handle, []),
                "score": round(score, 2),
                "evidence": evidence(ev),
                "depends": depends,
                "docs": mine,
            }
        )
    return {
        "area": {
            "slug": slug,
            "name": name,
            "owners": owners(graph).get(slug, []),
            "bus_factor": bus or 0,
            "knowers": knowers or 0,
        },
        "people": people,
        "total": len(rows),
    }


PERSON = "MATCH (p:Person {handle: $handle}) RETURN p.handle, coalesce(p.name, p.handle), p.role"

PERSON_AREAS = """
MATCH (p:Person {handle: $handle})-[k:KNOWS]->(a:Area)
OPTIONAL MATCH (a)-[d:DEPENDS_ON]->(p)
RETURN a.slug, coalesce(a.name, a.slug), k.score, k.evidence, d IS NOT NULL, coalesce(a.bus_factor, 0)
ORDER BY k.score DESC, a.slug
"""


def person(graph, handle: str) -> dict | None:
    """One person and the areas they know, strongest first, with the areas that depend on them marked."""
    found = graph.query(PERSON, {"handle": handle.lower()}).result_set
    if not found:
        return None
    h, name, role = found[0]
    areas = [
        {"slug": s, "name": n, "score": round(score, 2), "evidence": evidence(ev), "depends": dep, "bus_factor": bus}
        for s, n, score, ev, dep, bus in graph.query(PERSON_AREAS, {"handle": h}).result_set
    ]
    return {"person": {"handle": h, "name": name, "role": role, "teams": _teams(graph, [h]).get(h, [])}, "areas": areas}
