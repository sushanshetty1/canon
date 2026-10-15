"""What a workspace reads: each kind of source with its documents, passages and facts, and when it was last read.

The Sources screen draws this. Document kinds are grouped as every connector groups them
(`canon.sources.connector.group_of`: docs, tickets, chats, decisions, structure), with structure shown as what it
holds: the code owners (an ownership map or CODEOWNERS history, with the areas it covers) and the people (who the
graph knows, and the roster facts that say who leads and belongs to which team).

- **docs**: handbook, docs, team pages, wiki pages, Notion and Confluence pages, uploaded pages;
- **tickets**: issues and pull requests, Linear and Jira issues;
- **chats**: comment threads, discussions, forum and Slack threads;
- **decisions**: RFCs, decision records and releases, with the Decisions built from them;
- **code_owners** and **people**: the structure group.

It also lists the workspace's connections (`(:Connection)`, see `canon.sources.connector`), never their secrets.
All counts are graph queries. Every aggregation groups on a coalesced key (FalkorDB 6.0.2 crashes grouping on null).
"""

import json

from canon.sources.connector import group_of

FAMILIES = ("docs", "tickets", "chats", "decisions", "code_owners", "people")

DOCS = """
MATCH (d:Document)
WITH coalesce(d.kind, '') AS kind, coalesce(d.read_at, '') AS read_at, coalesce(d.updated_at, '') AS updated
RETURN kind, count(*), max(read_at), max(updated)
"""
PASSAGES = """
MATCH (d:Document)-[:HAS]->(p:Passage)
WITH coalesce(d.kind, '') AS kind
RETURN kind, count(*)
"""
FACTS = """
MATCH (f:Fact)-[:STATED_IN]->(:Passage)<-[:HAS|HAD]-(d:Document)
OPTIONAL MATCH (f)-[s:SUPERSEDED_BY]->(:Fact)
WITH coalesce(d.kind, '') AS kind, f, CASE WHEN f.valid_to IS NULL AND s IS NULL THEN 1 ELSE 0 END AS now
WITH kind, f, min(now) AS now
RETURN kind, count(f), sum(now)
"""
SPEAKERS = """
MATCH (d:Document)-[:HAS]->(p:Passage)<-[:SAID]-(x:Person)
WITH coalesce(d.kind, '') AS kind, x
RETURN kind, count(DISTINCT x)
"""
DECISIONS = "MATCH (d:Decision) WITH coalesce(d.status, '') AS status RETURN status, count(*)"
OWNED = """
MATCH (a:Area)<-[:ABOUT]-(f:Fact {predicate: 'owned_by'}) WHERE f.valid_to IS NULL AND NOT (f)-[:SUPERSEDED_BY]->()
RETURN count(DISTINCT a)
"""
CONNECTIONS = """
MATCH (c:Connection)
RETURN coalesce(c.id, ''), coalesce(c.kind, ''), coalesce(c.label, ''), coalesce(c.status, ''),
       coalesce(c.last_synced_at, ''), coalesce(c.error, ''), coalesce(c.config, '{}')
ORDER BY coalesce(c.last_synced_at, '') DESC LIMIT 50
"""


def _family(kind: str) -> str:
    """The screen's source kind for a document kind: its group, with structure split into code owners and people."""
    group = group_of(kind)
    if group == "structure":
        return "people" if kind == "roster" else "code_owners"
    return group


def _config(raw: str) -> dict:
    """What the app may show of a connection's config: plain values only."""
    try:
        value = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}
    return {k: v for k, v in value.items() if isinstance(v, (str, int, float, bool)) and "secret" not in k and "token" not in k} if isinstance(value, dict) else {}


def _one(graph, query: str):
    rows = graph.query(query).result_set
    return rows[0] if rows else None


def summary(graph) -> dict:
    by_kind: dict[str, dict] = {}

    def kind(k: str) -> dict:
        return by_kind.setdefault(k, {"kind": k, "documents": 0, "passages": 0, "facts": 0, "current_facts": 0,
                                      "speakers": 0, "last_read": None, "newest": None})

    for k, n, read_at, updated in graph.query(DOCS).result_set:
        row = kind(k)
        row.update(documents=n, last_read=read_at or None, newest=updated or None)
    for k, n in graph.query(PASSAGES).result_set:
        kind(k)["passages"] = n
    for k, n, now in graph.query(FACTS).result_set:
        kind(k).update(facts=n, current_facts=int(now or 0))
    for k, n in graph.query(SPEAKERS).result_set:
        kind(k)["speakers"] = n

    families = {f: {"key": f, "documents": 0, "passages": 0, "facts": 0, "current_facts": 0, "last_read": None,
                    "newest": None, "kinds": []} for f in FAMILIES}
    for row in sorted(by_kind.values(), key=lambda r: -r["documents"]):
        if not row["kind"] or not row["documents"]:
            continue
        fam = families[_family(row["kind"])]
        fam["kinds"].append(row)
        for key in ("documents", "passages", "facts", "current_facts"):
            fam[key] += row[key]
        for key in ("last_read", "newest"):
            if row[key] and (fam[key] is None or row[key] > fam[key]):
                fam[key] = row[key]

    statuses = {s: n for s, n in graph.query(DECISIONS).result_set if s}
    families["decisions"]["decisions"] = sum(statuses.values())
    families["decisions"]["statuses"] = statuses
    families["code_owners"]["areas"] = (_one(graph, OWNED) or [0])[0]

    people = families["people"]
    people["people"] = (_one(graph, "MATCH (p:Person) RETURN count(p)") or [0])[0]
    people["teams"] = (_one(graph, "MATCH (t:Team) RETURN count(t)") or [0])[0]
    people["speakers"] = (_one(graph, "MATCH (p:Person)-[:SAID]->(:Passage) RETURN count(DISTINCT p)") or [0])[0]
    reads = [f["last_read"] for f in families.values() if f["last_read"]]
    people["last_read"] = max(reads) if reads else None

    connections = [
        {"id": cid, "kind": kind_, "label": label, "status": status or None, "last_synced_at": synced or None,
         "error": error or None, "config": _config(config)}
        for cid, kind_, label, status, synced, error, config in graph.query(CONNECTIONS).result_set
    ]
    source = _one(graph, "MATCH (s:Source) RETURN s.repo, s.synced_at LIMIT 1")
    return {
        "families": [families[f] for f in FAMILIES],
        "connections": connections,
        "repo": {"repo": source[0], "synced_at": source[1]} if source else None,
        "totals": {
            "documents": sum(f["documents"] for f in families.values()),
            "facts": (_one(graph, "MATCH (f:Fact) RETURN count(f)") or [0])[0],
        },
    }
