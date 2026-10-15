"""Decisions as the API shows them: every decision with its people, areas, pull requests and replacements.

Each query is a plain match without aggregation (FalkorDB 6.0.2 crashes when it groups on a null), assembled here.
"""

from canon.graph import read as facts_read

DECISIONS = """
MATCH (d:Decision)
OPTIONAL MATCH (d)-[:PROPOSED_IN]->(doc:Document)
RETURN d, doc.id, doc.author
"""
PEOPLE = """
MATCH (p:Person)-[e:DECIDED]->(d:Decision) WHERE d.id IN $ids
RETURN d.id, p.handle, coalesce(p.name, p.handle), p.role, e.how, e.at
"""
AREAS = "MATCH (d:Decision)-[:ABOUT]->(a:Area) WHERE d.id IN $ids RETURN d.id, a.slug, coalesce(a.name, a.slug)"
PULLS = """
MATCH (d:Decision)-[e:IMPLEMENTED_BY]->(p:Document) WHERE d.id IN $ids
RETURN d.id, p.id, p.title, p.url, p.updated_at, p.author, e.how
"""
REPLACED = """
MATCH (a:Decision)-[e:SUPERSEDED_BY]->(b:Decision) WHERE a.id IN $ids OR b.id IN $ids
RETURN a.id, b.id, e.reason, e.by
"""


def _shape(props: dict, doc_id: str | None, author: str | None) -> dict:
    return {
        "id": props["id"],
        "title": props.get("title"),
        "status": props.get("status"),
        "proposed_at": props.get("proposed_at"),
        "decided_at": props.get("decided_at"),
        "replaced_at": props.get("replaced_at"),
        "closed_at": props.get("closed_at"),
        "summary": props.get("summary") or "",
        "url": props.get("url"),
        "doc_id": doc_id,
        "author": author,
        "people": [],
        "areas": [],
        "pulls": [],
        "superseded_by": [],
        "supersedes": [],
    }


def decisions(graph, ids: list[str] | None = None) -> list[dict]:
    """Every decision (or those named), oldest proposal first."""
    out: dict[str, dict] = {}
    for d, doc_id, author in graph.query(DECISIONS).result_set:
        props = dict(d.properties)
        if ids is None or props["id"] in ids:
            out[props["id"]] = _shape(props, doc_id, author)
    keys = list(out)
    if not keys:
        return []
    for did, handle, name, role, how, at in graph.query(PEOPLE, {"ids": keys}).result_set:
        out[did]["people"].append({"handle": handle, "name": name, "role": role, "how": how, "at": at})
    for did, slug, name in graph.query(AREAS, {"ids": keys}).result_set:
        out[did]["areas"].append({"slug": slug, "name": name})
    for did, pid, title, url, at, author, how in graph.query(PULLS, {"ids": keys}).result_set:
        out[did]["pulls"].append({"id": pid, "title": title, "url": url, "merged_at": at, "author": author, "how": how})
    for a, b, reason, by in graph.query(REPLACED, {"ids": keys}).result_set:
        if a in out:
            out[a]["superseded_by"].append({"id": b, "reason": reason, "by": by})
        if b in out:
            out[b]["supersedes"].append({"id": a, "reason": reason, "by": by})
    for d in out.values():
        d["people"].sort(key=lambda p: (p["how"] != "approved", p["handle"]))
        d["areas"].sort(key=lambda a: a["name"].lower())
        d["pulls"].sort(key=lambda p: p["merged_at"] or "")
    return sorted(out.values(), key=lambda d: (d["proposed_at"] or d["decided_at"] or "", d["id"]))


def decision(graph, decision_id: str) -> dict | None:
    """One decision, with the titles of the decisions around it, its RFC's opening passages and its dated facts."""
    found = decisions(graph, [decision_id])
    if not found:
        return None
    d = found[0]
    linked = {x["id"] for x in d["superseded_by"] + d["supersedes"]}
    titles = {x["id"]: x for x in decisions(graph, list(linked))} if linked else {}
    for x in d["superseded_by"] + d["supersedes"]:
        other = titles.get(x["id"], {})
        x.update({"title": other.get("title"), "status": other.get("status"), "decided_at": other.get("decided_at")})
    passages = graph.query(
        """MATCH (:Decision {id: $id})-[:PROPOSED_IN]->(:Document)-[:HAS]->(p:Passage) RETURN p.id, p.text""",
        {"id": decision_id},
    ).result_set
    fact_ids = [
        r[0]
        for r in graph.query(
            "MATCH (f:Fact) WHERE f.subject = $subject RETURN f.id ORDER BY f.valid_from", {"subject": f"decision:{decision_id}"}
        ).result_set
    ]
    rows = facts_read.facts(graph, fact_ids)
    d["facts"] = [rows[i] for i in fact_ids if i in rows]
    d["passages"] = len(passages)
    return d
