"""Links facts through time: which fact replaced which, which page repeats something already replaced, and which
current sources disagree. Deterministic: no model takes part.

Facts are compared within a `(subject, predicate)` group, in `valid_from` order. Values are compared after
normalising case, spacing and punctuation.

1. **Restates.** A later fact with the same value as an earlier one restates it: `(later)-[:RESTATES]->(earlier)`.
2. **Supersedes.** A later fact B with a different value replaces an earlier fact A when B's authority is higher.
   With equal authority it replaces A only when A had already ended by then (`A.valid_to <= B.valid_from`, as in
   the ownership map's history), or when B is clearly newer: see the dispute window below.
   Then `(A)-[:SUPERSEDED_BY {reason: 'newer'}]->(B)` and `A.valid_to = B.valid_from`.
3. **Stale restatement.** A fact L whose value differs from a higher-authority fact H that stood when L was
   written (H stated on or before L, not ended, not yet replaced) is out of date from the start:
   `(L)-[:SUPERSEDED_BY {reason: 'stale'}]->(H)` and `L.stale = true`. Its page belongs on the fix list. L is not
   a dispute: the higher authority decides.
4. **Dispute.** Two facts with equal authority and different values that both remain current are linked with
   `(A)-[:CONTRADICTS]->(B)`. Neither is picked. This applies to single-valued predicates (`owned_by`,
   `decided`); for free-sentence predicates the judge adds `CONTRADICTS {reason: 'judged'}`, which `link` keeps.

5. **Stated together.** A fact never replaces or disputes a value its own passage also states. "Owned by Billing
   and Platform Features" is two facts from one passage, and both hold. The ownership map restates every owner in
   an area's new list when the list changes, so a co-owner who stays is not replaced by the one who joins.

**The dispute window.** A fact's reference date is the later of its `valid_from` and the last update of the
document that states it: the last time someone edited that source and left the fact in place. For two facts of
equal authority that disagree, the later one replaces the earlier only when its reference date is more than
`DISPUTE_WINDOW_DAYS` after the earlier one's. Otherwise neither is older than the other's last update by a clear
margin, so both stand and they are disputed. A page edited in March is replaced by one edited in September; two
pages edited a week apart that disagree are a dispute; and an old fact whose page was edited last week still
counts as recent.

**Removed passages.** A fact whose passage a document no longer has (`removed_at`) is closed on the removal date,
and opens again if the passage returns.

`link` recomputes everything from the facts each time and writes only the difference, so running it twice
changes nothing. `valid_to` values it sets are marked `closed_by` ('link' or 'removed') so they can be undone when
the facts change; a `valid_to` a connector wrote is left alone.
"""

import re
from dataclasses import dataclass, field
from datetime import date

DISPUTE_WINDOW_DAYS = 30
# Predicates where one subject holds many values at once, so a different value is an addition, not a change.
# Process and policy facts are free sentences: several hold for one topic at once, and whether two of them
# conflict is a question of meaning, which `verify.conflicts.judge` asks per topic.
MULTI_VALUED = frozenset({"uses", "leads", "member_of", "contact_for", "process", "policy"})
EDGES = ("SUPERSEDED_BY", "RESTATES", "CONTRADICTS")

FACTS = """
MATCH (f:Fact)
OPTIONAL MATCH (f)-[:STATED_IN]->(p:Passage)
OPTIONAL MATCH (p)<-[:HAS|HAD]-(d:Document)
RETURN f.id, f.subject, f.predicate, f.value, f.valid_from, f.valid_to, f.closed_by, f.authority, f.stale,
       f.passage_id, p.removed_at, d.updated_at
"""
# No aggregation here: FalkorDB 6.0.2 crashes when it groups on a key that is null, such as a missing property.


@dataclass
class _Fact:
    id: str
    subject: str
    predicate: str
    value: str
    vf: str
    vt: str | None  # the end the sources give: a connector's valid_to, or the passage's removal
    auth: int
    ref: str  # the later of valid_from and the document's last update
    passage: str = ""


@dataclass
class Plan:
    edges: dict[tuple[str, str, str], str | None] = field(default_factory=dict)  # (type, from, to) -> reason
    closed: dict[str, tuple[str, str]] = field(default_factory=dict)  # id -> (valid_to, closed_by)
    stale: set[str] = field(default_factory=set)


def _norm(value) -> str:
    return " ".join(re.sub(r"[^\w\s:-]", " ", str(value or "").lower()).split())


def _days(a: str, b: str) -> int:
    return (date.fromisoformat(b[:10]) - date.fromisoformat(a[:10])).days


def _plan_group(fs: list[_Fact], plan: Plan) -> None:
    fs = sorted(fs, key=lambda f: (f.vf, -f.auth, f.id))
    by_id = {f.id: f for f in fs}
    sup: dict[str, str] = {}
    pending: list[tuple[str, str]] = []
    multi = fs[0].predicate in MULTI_VALUED
    stated: dict[str, set[str]] = {}
    for f in fs:
        if f.passage:
            stated.setdefault(f.passage, set()).add(f.value)

    def standing(e: _Fact, t: str) -> bool:
        replaced = e.id in sup and by_id[sup[e.id]].vf <= t
        return e.vf <= t and (e.vt is None or e.vt > t) and not replaced

    for i, x in enumerate(fs):
        earlier = fs[:i]
        same = [e for e in earlier if e.value == x.value]
        if same:
            plan.edges[("RESTATES", x.id, same[-1].id)] = None
        if multi:
            continue
        higher = [e for e in earlier if e.auth > x.auth and standing(e, x.vf)]
        if higher and not any(e.value == x.value for e in higher):
            h = max(higher, key=lambda e: (e.auth, e.vf))
            sup[x.id] = h.id
            plan.edges[("SUPERSEDED_BY", x.id, h.id)] = "stale"
            plan.stale.add(x.id)
            continue
        for e in earlier:
            if e.id in sup or e.value == x.value or x.auth < e.auth:
                continue
            if e.value in stated.get(x.passage, ()):  # x's own source still says e's value: they hold together
                continue
            ended = e.vt is not None and e.vt <= x.vf
            if x.auth > e.auth or ended or _days(e.ref, x.ref) > DISPUTE_WINDOW_DAYS:
                sup[e.id] = x.id
                plan.edges[("SUPERSEDED_BY", e.id, x.id)] = "newer"
                if e.vt is None:
                    plan.closed[e.id] = (max(x.vf, e.vf), "link")
            else:
                pending.append((e.id, x.id))

    for a, b in pending:
        if not ({a, b} & sup.keys()) and by_id[a].vt is None and by_id[b].vt is None:
            plan.edges[("CONTRADICTS", a, b)] = None


def plan_links(rows: list[list]) -> tuple[Plan, dict[str, dict]]:
    """Rows from `FACTS` to the links and closures the rules call for, plus each fact's stored state."""
    plan, state, groups = Plan(), {}, {}
    # A passage held by its document through both HAS and HAD gives a fact twice: keep the latest document date.
    latest: dict[str, list] = {}
    for row in rows:
        if row[0] not in latest or (row[-1] or "") > (latest[row[0]][-1] or ""):
            latest[row[0]] = row
    for fid, subject, predicate, value, vf, vt, closed_by, auth, stale, pid, removed_at, doc_updated in latest.values():
        state[fid] = {"valid_to": vt, "closed_by": closed_by, "stale": bool(stale)}
        source_vt = None if closed_by in ("link", "removed") else vt
        if source_vt is None and removed_at:
            source_vt = removed_at
            plan.closed[fid] = (removed_at, "removed")
        vf = vf or "0000-01-01"
        ref = max(vf, doc_updated or vf)
        f = _Fact(fid, subject, predicate, _norm(value), vf, source_vt, int(auth or 0), ref, pid or "")
        groups.setdefault((subject, predicate), []).append(f)
    for fs in groups.values():
        if len(fs) > 1:
            _plan_group(fs, plan)
    return plan, state


def _run(graph, query: str, rows: list) -> None:
    for i in range(0, len(rows), 500):
        graph.query(query, {"rows": rows[i : i + 500]})


def link(graph) -> dict[str, int]:
    plan, state = plan_links(graph.query(FACTS).result_set)

    existing = {
        (t, a, b): reason
        for t, a, b, reason in graph.query(
            "MATCH (a:Fact)-[r:SUPERSEDED_BY|RESTATES|CONTRADICTS]->(b:Fact) RETURN type(r), a.id, b.id, r.reason"
        ).result_set
    }
    for t in EDGES:
        # Conflicts the judge found (reason 'judged') are not the linker's to remove.
        gone = [
            {"a": a, "b": b}
            for (tt, a, b), reason in existing.items()
            if tt == t and (tt, a, b) not in plan.edges and reason != "judged"
        ]
        _run(graph, f"UNWIND $rows AS r MATCH (:Fact {{id: r.a}})-[e:{t}]->(:Fact {{id: r.b}}) DELETE e", gone)
        new = [
            {"a": a, "b": b, "reason": reason}
            for (tt, a, b), reason in plan.edges.items()
            if tt == t and existing.get((tt, a, b), "") != reason
        ]
        _run(
            graph,
            f"""UNWIND $rows AS r MATCH (a:Fact {{id: r.a}}), (b:Fact {{id: r.b}})
                MERGE (a)-[e:{t}]->(b) SET e.reason = r.reason""",
            new,
        )

    # Validity windows: close what the rules closed, reopen what they no longer close.
    window = []
    for fid, s in state.items():
        want = plan.closed.get(fid)
        if want and (s["valid_to"], s["closed_by"]) != want:
            window.append({"id": fid, "to": want[0], "by": want[1]})
        elif not want and s["closed_by"] in ("link", "removed"):
            window.append({"id": fid, "to": None, "by": None})
    _run(graph, "UNWIND $rows AS r MATCH (f:Fact {id: r.id}) SET f.valid_to = r.to, f.closed_by = r.by", window)
    _run(
        graph,
        "UNWIND $rows AS r MATCH (f:Fact {id: r.id}) SET f.stale = r.stale",
        [{"id": fid, "stale": fid in plan.stale or None} for fid, s in state.items() if s["stale"] != (fid in plan.stale)],
    )

    stale_pages = graph.query(
        "MATCH (f:Fact {stale: true})-[:STATED_IN]->(:Passage)<-[:HAS]-(d:Document) RETURN count(DISTINCT d)"
    ).result_set[0][0]
    kinds = [t for t, _, _ in plan.edges]
    return {
        "superseded": kinds.count("SUPERSEDED_BY") - len(plan.stale),
        "stale": len(plan.stale),
        "restates": kinds.count("RESTATES"),
        "contradicts": kinds.count("CONTRADICTS"),
        "closed_removed": sum(1 for _, by in plan.closed.values() if by == "removed"),
        "stale_pages": stale_pages,
    }
