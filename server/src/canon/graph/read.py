"""Reads a fact with where it came from: the passage, the document, and where it stands in time.

The check, retrieval and the API all show facts the same way, so they share these queries and this shape.
"""

LINEAGE = """
MATCH (f:Fact) WHERE f.id IN $ids
OPTIONAL MATCH (f)-[:STATED_IN]->(p:Passage)
OPTIONAL MATCH (p)<-[:HAS|HAD]-(d:Document)
OPTIONAL MATCH (f)-[:SUPERSEDED_BY]->(nx:Fact)
RETURN f, p, d, nx.id
"""

CHAIN_ENDS = """
MATCH (f:Fact) WHERE f.id IN $ids
MATCH (f)-[:SUPERSEDED_BY*1..6]->(n:Fact) WHERE NOT (n)-[:SUPERSEDED_BY]->()
RETURN f.id, n.id
"""

CONFLICTS = """
MATCH (f:Fact) WHERE f.id IN $ids
MATCH (f)-[:CONTRADICTS]-(c:Fact) WHERE c.valid_to IS NULL AND NOT (c)-[:SUPERSEDED_BY]->()
RETURN DISTINCT f.id, c.id
"""


def _props(node) -> dict:
    return dict(node.properties) if node is not None else {}


def facts(graph, ids) -> dict[str, dict]:
    """Each fact by id, with its passage and document. Ids not in the graph are left out."""
    ids = list(dict.fromkeys(ids))
    if not ids:
        return {}
    out: dict[str, dict] = {}
    for f, p, d, nxt in graph.query(LINEAGE, {"ids": ids}).result_set:
        fp, pp, dp = _props(f), _props(p), _props(d)
        # A passage can hang off its document by both HAS and HAD, which gives the same fact twice.
        if out.get(fp["id"], {}).get("doc_id"):
            continue
        out[fp["id"]] = {
            "fact_id": fp["id"],
            "fact": fp.get("text"),
            "subject": fp.get("subject"),
            "predicate": fp.get("predicate"),
            "value": fp.get("value"),
            "authority": fp.get("authority"),
            "valid_from": fp.get("valid_from"),
            "valid_to": fp.get("valid_to"),
            "stale": bool(fp.get("stale")),
            "current": fp.get("valid_to") is None and nxt is None,
            "superseded_by": nxt,
            "passage_id": pp.get("id"),
            "passage": pp.get("text"),
            "removed": pp.get("removed_at") is not None,
            "doc_id": dp.get("id"),
            "title": dp.get("title"),
            "url": dp.get("url"),
            "kind": dp.get("kind"),
            "date": dp.get("updated_at"),
        }
    return out


def chain_ends(graph, ids) -> dict[str, str]:
    """For each replaced fact, the fact at the end of its `SUPERSEDED_BY` chain: what holds now."""
    ids = list(dict.fromkeys(ids))
    return dict(graph.query(CHAIN_ENDS, {"ids": ids}).result_set) if ids else {}


def conflicts(graph, ids) -> dict[str, list[str]]:
    """For each fact, the current facts it contradicts."""
    out: dict[str, list[str]] = {}
    if ids:
        for f, c in graph.query(CONFLICTS, {"ids": list(dict.fromkeys(ids))}).result_set:
            out.setdefault(f, []).append(c)
    return out
