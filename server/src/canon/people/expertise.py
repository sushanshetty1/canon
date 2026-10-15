"""Who knows each area, from what they did on the documents about it.

`(:Person)-[:KNOWS {score, evidence, docs}]->(:Area)` is computed in Cypher:

- The documents about an area are those linked to it (`(:Document)-[:ABOUT]->(:Area)`, from labels and changed
  paths) and the pages whose facts are about it. Ownership map commits are left out: editing the map is
  bookkeeping, not knowledge of the area.
- Each activity edge on such a document weighs DECIDED 4, AUTHORED 3, REVIEWED 2, COMMENTED 1, halved for every
  180 days since it happened.
- Membership of the team that owns the area now adds 2.

`evidence` is a JSON object of counts per kind (`{"decided": 0, "authored": 4, ...}`), with `member` true or
false, and `docs` holds the ids of the person's heaviest documents on the area, for display. Recomputing replaces
every KNOWS edge: each run stamps the edges it writes and removes the ones it did not.
"""

import time
from datetime import date

WEIGHTS = {"DECIDED": 4, "AUTHORED": 3, "REVIEWED": 2, "COMMENTED": 1}
MEMBER_WEIGHT = 2
HALF_LIFE_DAYS = 180
TOP_DOCS = 6

# Days since year 0 of an ISO date, to within a day (leap days are approximate); only differences are used.
_CUMULATIVE = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]


def day_number(iso: str) -> int:
    y, m, d = int(iso[:4]), int(iso[5:7]), int(iso[8:10])
    return 365 * y + y // 4 + _CUMULATIVE[m - 1] + d


def _day_expr(expr: str) -> str:
    return (
        f"(365 * toInteger(substring({expr}, 0, 4)) + toInteger(substring({expr}, 0, 4)) / 4"
        f" + {_CUMULATIVE}[toInteger(substring({expr}, 5, 2)) - 1] + toInteger(substring({expr}, 8, 2)))"
    )


# The documents about each area: linked directly, or through facts their passages state.
AREA_DOCS = """
CALL {
  MATCH (d:Document)-[:ABOUT]->(a:Area) RETURN d, a
  UNION
  MATCH (a:Area)<-[:ABOUT]-(:Fact)-[:STATED_IN]->(:Passage)<-[:HAS]-(d:Document)
  WHERE d.kind <> 'ownership_map'
  RETURN d, a
}
"""

_WEIGHT = "CASE type(r) " + " ".join(f"WHEN '{k}' THEN {v}" for k, v in WEIGHTS.items()) + " ELSE 0 END"
_COUNT = "sum(CASE type(r) WHEN '{rel}' THEN 1 ELSE 0 END)"

ACTIVITY = (
    AREA_DOCS
    + f"""
MATCH (p:Person)-[r:DECIDED|AUTHORED|REVIEWED|COMMENTED]->(d)
WITH p, a, d, r, ($today - {_day_expr("coalesce(r.at, d.updated_at, $today_iso)")}) AS age
WITH p, a, d,
     sum({_WEIGHT} * 0.5 ^ (toFloat(CASE WHEN age < 0 THEN 0 ELSE age END) / $half_life)) AS w,
     {_COUNT.format(rel="DECIDED")} AS decided, {_COUNT.format(rel="AUTHORED")} AS authored,
     {_COUNT.format(rel="REVIEWED")} AS reviewed, {_COUNT.format(rel="COMMENTED")} AS commented
WITH p, a, d, w, decided, authored, reviewed, commented ORDER BY w DESC, d.id
WITH p, a, sum(w) AS score, sum(decided) AS decided, sum(authored) AS authored, sum(reviewed) AS reviewed,
     sum(commented) AS commented, collect(d.id) AS docs
MERGE (p)-[k:KNOWS]->(a)
SET k.score = score, k.decided = decided, k.authored = authored, k.reviewed = reviewed, k.commented = commented,
    k.member = false, k.docs = docs[0..$top], k.run = $run
RETURN count(k)
"""
)

# The team that owns an area now: its current owned_by facts from the ownership map, the authority on ownership.
OWNERS = """
MATCH (f:Fact {predicate: 'owned_by'})-[:ABOUT]->(a:Area), (f)-[:VALUE]->(t:Team)
WHERE f.valid_to IS NULL AND NOT (f)-[:SUPERSEDED_BY]->() AND f.authority >= 3
"""

MEMBERS = (
    OWNERS
    + """
MATCH (p:Person)-[:MEMBER_OF]->(t)
WITH DISTINCT p, a
MERGE (p)-[k:KNOWS]->(a)
SET k.score = CASE WHEN k.run = $run THEN k.score ELSE 0 END + $member,
    k.decided = CASE WHEN k.run = $run THEN k.decided ELSE 0 END,
    k.authored = CASE WHEN k.run = $run THEN k.authored ELSE 0 END,
    k.reviewed = CASE WHEN k.run = $run THEN k.reviewed ELSE 0 END,
    k.commented = CASE WHEN k.run = $run THEN k.commented ELSE 0 END,
    k.docs = CASE WHEN k.run = $run THEN k.docs ELSE [] END,
    k.member = true, k.run = $run
RETURN count(k)
"""
)

EVIDENCE = """
MATCH (:Person)-[k:KNOWS {run: $run}]->(:Area)
SET k.evidence = toJSON({decided: k.decided, authored: k.authored, reviewed: k.reviewed, commented: k.commented,
                         member: k.member})
RETURN count(k)
"""

PRUNE = "MATCH (:Person)-[k:KNOWS]->(:Area) WHERE k.run <> $run DELETE k RETURN count(k)"


def compute(graph, *, today: str | None = None) -> dict[str, int]:
    """Recompute every KNOWS edge. Returns how many were written and how many old ones were removed."""
    today = today or date.today().isoformat()
    params = {
        "today": day_number(today),
        "today_iso": today,
        "half_life": float(HALF_LIFE_DAYS),
        "top": TOP_DOCS,
        "member": MEMBER_WEIGHT,
        "run": time.time_ns(),
    }
    one = lambda q: graph.query(q, params).result_set[0][0]  # noqa: E731
    from_activity = one(ACTIVITY)
    from_membership = one(MEMBERS)
    written = one(EVIDENCE)
    removed = one(PRUNE)
    return {"knows": written, "from_activity": from_activity, "from_membership": from_membership, "removed": removed}
