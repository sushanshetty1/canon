"""Fix nodes: one per out-of-date line, routed to the people who should change it.

    (:Fix {id, status, old, new, reason, created_at, ...})
      -[:ABOUT]->(:Fact)        the stale fact(s) the line states
      -[:EVIDENCE]->(:Fact)     what holds now: the end of each stale fact's SUPERSEDED_BY chain
      -[:ON]->(:Document)       the page
      -[:ROUTED_TO {role}]->(:Team|:Person)

Statuses: `open` (waiting for a person), `approved` (a person said yes; filing is under way or failed), `filed`
(an issue exists, or in dry run was recorded), `dismissed` (a person said no, with a reason), and `resolved` (the
page no longer states the stale fact, so the fix closed itself).

`build(graph)` is graph work only and idempotent: it opens a fix for every stale fact on a current passage that no
fix covers yet, resolves fixes whose facts are no longer stale (and reopens them if they come back), keeps each open
fix's evidence and routing up to date, and forgets a draft whose evidence or line changed. Drafting is
`canon.fixes.draft`.

Routing is a graph question, in order: the team that owns an area the page is about; otherwise the team that owns
the stale fact's subject area now, with its lead; otherwise the page's last author.
"""

import hashlib
from datetime import UTC, datetime

from canon.graph import read
from canon.extract.facts import CONVERSATIONS
from canon.types import entity

LIVE = ("open", "approved")  # statuses a person has not finished with
STATUSES = ("open", "approved", "filed", "dismissed", "resolved")

# Pages only: a ticket or a chat is a record of what someone said on a day, not a page anyone keeps up to date, so
# an out-of-date line in one is history, not something to fix.
STALE = """
MATCH (f:Fact {stale: true})-[:STATED_IN]->(p:Passage)<-[:HAS]-(d:Document)
WHERE NOT coalesce(d.kind, '') IN $conversations
RETURN DISTINCT f.id, f.subject, p.id, d.id
"""
EXISTING = """
MATCH (x:Fix)
OPTIONAL MATCH (x)-[:ABOUT]->(f:Fact)
OPTIONAL MATCH (x)-[:EVIDENCE]->(e:Fact)
RETURN x.id, x.status, f.id, e.id, x.resolved_at
"""
# No aggregation in these reads: FalkorDB 6.0.2 crashes when it groups on a key that can be null.
# One path per MATCH where a pattern predicate is in the WHERE: a second MATCH after one loses its variables.

OWNERS = """
MATCH (a:Area {slug: $slug})<-[:ABOUT]-(f:Fact {predicate: 'owned_by'})-[:VALUE]->(t:Team)
WHERE f.valid_to IS NULL AND NOT (f)-[:SUPERSEDED_BY]->()
OPTIONAL MATCH (f)-[:STATED_IN]->(:Passage)<-[:HAS|HAD]-(d:Document)
WITH t.slug AS slug, coalesce(t.name, t.slug) AS team, coalesce(a.name, a.slug) AS area,
     coalesce(f.authority, 0) AS authority, coalesce(f.valid_from, '') AS since, coalesce(d.kind, '') AS kind
RETURN slug, team, area, authority, since, kind
ORDER BY authority DESC, since DESC, slug
"""
LEADS = "MATCH (p:Person)-[:LEADS]->(:Team {slug: $slug}) RETURN p.handle, coalesce(p.name, p.handle) ORDER BY p.handle"
PAGE_AREAS = "MATCH (:Document {id: $id})-[:ABOUT]->(a:Area) RETURN a.slug ORDER BY a.slug"
AUTHOR = """
MATCH (d:Document {id: $id})
OPTIONAL MATCH (p:Person)-[e:AUTHORED]->(d)
WITH coalesce(d.author, '') AS author, coalesce(d.updated_at, '') AS updated, p.handle AS handle,
     coalesce(p.name, p.handle) AS name, coalesce(e.at, '') AS at
RETURN author, updated, handle, name, at
ORDER BY at DESC
"""

KIND_WORDS = {"ownership_map": "the ownership map", "team_page": "its team page", "handbook": "the handbook", "rfc": "an RFC",
              "adr": "a decision record"}
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _day(iso: str) -> str:
    try:
        y, m, d = iso[:10].split("-")
        return f"{MONTHS[int(m) - 1]} {int(d)}, {y}"
    except (ValueError, IndexError):
        return iso


def fix_id(fact_id: str) -> str:
    return "fix-" + hashlib.sha1(fact_id.encode()).hexdigest()[:12]


class TransitionError(RuntimeError):
    """The fix is not in a state that allows this. The message is safe to show."""


# --- Routing ----------------------------------------------------------------------------------------


def _owner(graph, area: str) -> tuple | None:
    rows = graph.query(OWNERS, {"slug": area}).result_set
    return tuple(rows[0]) if rows else None


def route(graph, doc_id: str, subjects: list[str]) -> tuple[list[dict], str]:
    """Who should change a page, and why: `([{"kind", "key", "name", "role", "team"?}], reason)`."""
    for area in [r[0] for r in graph.query(PAGE_AREAS, {"id": doc_id}).result_set]:
        found = _owner(graph, area)
        if found:
            slug, team, area_name, *_ = found
            return [{"kind": "team", "key": slug, "name": team, "role": "owner"}], f"{team} owns {area_name}, which this page is about."

    routed: list[dict] = []
    reasons: list[str] = []
    for subject in dict.fromkeys(subjects):
        parsed = entity(subject)
        if not parsed or parsed[0] != "Area":
            continue
        found = _owner(graph, parsed[2])
        if not found or any(r["key"] == found[0] for r in routed):
            continue
        slug, team, area_name, _, since, kind = found
        routed.append({"kind": "team", "key": slug, "name": team, "role": "owner"})
        for handle, name in graph.query(LEADS, {"slug": slug}).result_set:
            routed.append({"kind": "person", "key": handle, "name": name, "role": "lead", "team": slug})
        where = KIND_WORDS.get(kind, "the graph")
        reasons.append(f"{team} owns {area_name}, the area this line is about, on {where} since {_day(since)}.")
    if routed:
        return routed, " ".join(reasons)

    rows = graph.query(AUTHOR, {"id": doc_id}).result_set
    if rows:
        author, updated, handle, name, at = rows[0]
        if handle or author:
            key = handle or author
            when = _day(at or updated)
            return [{"kind": "person", "key": key, "name": name or key, "role": "author"}], (
                f"No team owns what this line is about, so it goes to the page's last author, who edited it on {when}."
            )
    return [], "Nobody in the graph owns this page."


def _write_route(graph, fid: str, routed: list[dict], reason: str) -> None:
    graph.query("MATCH (x:Fix {id: $id})-[r:ROUTED_TO]->() DELETE r", {"id": fid})
    for r in routed:
        label, prop = ("Team", "slug") if r["kind"] == "team" else ("Person", "handle")
        graph.query(
            f"MATCH (x:Fix {{id: $id}}), (n:{label} {{{prop}: $key}}) MERGE (x)-[e:ROUTED_TO]->(n) SET e.role = $role, e.team = $team",
            {"id": fid, "key": r["key"], "role": r["role"], "team": r.get("team")},
        )
    graph.query("MATCH (x:Fix {id: $id}) SET x.reason = $reason", {"id": fid, "reason": reason})


def reroute(graph, fid: str) -> None:
    rows = graph.query(
        "MATCH (x:Fix {id: $id})-[:ABOUT]->(f:Fact) OPTIONAL MATCH (x)-[:ON]->(d:Document) RETURN f.subject, d.id ORDER BY f.id",
        {"id": fid},
    ).result_set
    if rows:
        _write_route(graph, fid, *route(graph, rows[0][1], [r[0] for r in rows]))


# --- Build ------------------------------------------------------------------------------------------


def build(graph) -> dict[str, int]:
    rows = graph.query(STALE, {"conversations": list(CONVERSATIONS)}).result_set
    stale = {fid: (subject, pid, doc) for fid, subject, pid, doc in rows}
    ends = read.chain_ends(graph, list(stale))

    fixes: dict[str, dict] = {}
    for xid, status, about, evidence, resolved_at in graph.query(EXISTING).result_set:
        x = fixes.setdefault(xid, {"status": status, "about": set(), "evidence": set(), "resolved_at": resolved_at})
        if about:
            x["about"].add(about)
        if evidence:
            x["evidence"].add(evidence)
    covered = {f for x in fixes.values() for f in x["about"]}
    now = _now()
    counts = {"stale_facts": len(stale), "created": 0, "resolved": 0, "reopened": 0, "redrafted": 0}
    touched: list[str] = []

    for fid, (subject, pid, doc) in sorted(stale.items()):
        if fid in covered:
            continue
        xid = fix_id(fid)
        graph.query(
            """MATCH (f:Fact {id: $fact}), (d:Document {id: $doc})
               MERGE (x:Fix {id: $id}) ON CREATE SET x.status = 'open', x.created_at = $now
               SET x.updated_at = $now, x.passage_id = $pid
               MERGE (x)-[:ABOUT]->(f) MERGE (x)-[:ON]->(d)""",
            {"id": xid, "fact": fid, "doc": doc, "pid": pid, "now": now},
        )
        fixes[xid] = {"status": "open", "about": {fid}, "evidence": set(), "resolved_at": None}
        counts["created"] += 1

    for xid, x in fixes.items():
        live = [f for f in sorted(x["about"]) if f in stale]
        if not live:
            if x["status"] in LIVE:
                graph.query(
                    "MATCH (x:Fix {id: $id}) SET x.status = 'resolved', x.resolved_at = $now, x.updated_at = $now",
                    {"id": xid, "now": now},
                )
                counts["resolved"] += 1
            elif x["status"] in ("filed", "dismissed") and not x["resolved_at"]:
                graph.query("MATCH (x:Fix {id: $id}) SET x.resolved_at = $now", {"id": xid, "now": now})
            continue
        if x["status"] == "resolved":
            graph.query(
                "MATCH (x:Fix {id: $id}) SET x.status = 'open', x.resolved_at = NULL, x.updated_at = $now",
                {"id": xid, "now": now},
            )
            x["status"] = "open"
            counts["reopened"] += 1
        elif x["status"] in ("filed", "dismissed") and x["resolved_at"]:
            graph.query("MATCH (x:Fix {id: $id}) SET x.resolved_at = NULL", {"id": xid})
        if x["status"] not in LIVE:
            continue  # a filed or dismissed fix keeps the evidence and routing a person acted on
        want = {ends.get(f) for f in live} - {None}
        if want != x["evidence"]:
            graph.query("MATCH (x:Fix {id: $id})-[r:EVIDENCE]->() DELETE r", {"id": xid})
            graph.query(
                "MATCH (x:Fix {id: $id}) UNWIND $ids AS e MATCH (f:Fact {id: e}) MERGE (x)-[:EVIDENCE]->(f)",
                {"id": xid, "ids": sorted(want)},
            )
            if x["evidence"]:  # the newer fact changed, so the old draft no longer says what holds
                graph.query(
                    "MATCH (x:Fix {id: $id}) SET x.new = NULL, x.old = NULL, x.draft_error = NULL, x.checked = NULL",
                    {"id": xid},
                )
                counts["redrafted"] += 1
        touched.append(xid)

    # A draft whose line is no longer on the page is forgotten.
    gone = graph.query(
        """MATCH (x:Fix)-[:ABOUT]->(:Fact)-[:STATED_IN]->(p:Passage)
           WHERE x.status IN $live AND x.old IS NOT NULL AND NOT p.text CONTAINS x.old
           SET x.old = NULL, x.new = NULL, x.draft_error = NULL, x.checked = NULL
           RETURN DISTINCT x.id""",
        {"live": list(LIVE)},
    ).result_set
    counts["redrafted"] += len(gone)

    for xid in touched:
        reroute(graph, xid)

    pages = graph.query(
        "MATCH (x:Fix)-[:ON]->(d:Document) WHERE x.status IN $live RETURN count(DISTINCT d)", {"live": list(LIVE)}
    ).result_set[0][0]
    return {**counts, **totals(graph), "pages": pages}


# --- Reading ----------------------------------------------------------------------------------------

FIXES = """
MATCH (x:Fix) WHERE x.status IN $statuses
OPTIONAL MATCH (x)-[:ON]->(d:Document)
RETURN x, d
"""
EDGES = "MATCH (x:Fix)-[r:ABOUT|EVIDENCE]->(f:Fact) WHERE x.id IN $ids RETURN x.id, type(r), f.id"
ROUTED = """
MATCH (x:Fix)-[r:ROUTED_TO]->(n) WHERE x.id IN $ids
RETURN x.id, coalesce(r.role, ''), r.team, coalesce(labels(n)[0], ''), coalesce(n.slug, n.handle), coalesce(n.name, n.slug, n.handle)
"""
ORDER = {"owner": 0, "lead": 1, "author": 2}


def _ordered(routed: list[dict]) -> list[dict]:
    """Each team followed by its lead; people routed on their own (a page's author) after the teams."""
    teams = sorted((r for r in routed if r["kind"] == "team"), key=lambda r: r["name"].lower())
    people = sorted((r for r in routed if r["kind"] == "person"), key=lambda r: (ORDER.get(r["role"], 9), r["name"].lower()))
    out = []
    for t in teams:
        out += [t, *(p for p in people if p.get("team") == t["key"])]
    return out + [p for p in people if p not in out]


def _shape(x: dict, d: dict, facts: dict, about: list[str], evidence: list[str], routed: list[dict]) -> dict:
    stale = [facts[i] for i in about if i in facts]
    passage = stale[0] if stale else {}
    return {
        "id": x["id"],
        "status": x.get("status") or "open",
        "old": x.get("old"),
        "new": x.get("new"),
        "checked": x.get("checked"),
        "draft_error": x.get("draft_error"),
        "reason": x.get("reason"),
        "created_at": x.get("created_at"),
        "updated_at": x.get("updated_at"),
        "resolved_at": x.get("resolved_at"),
        "page": {
            "id": d.get("id"),
            "title": d.get("title"),
            "url": d.get("url"),
            "kind": d.get("kind"),
            "updated_at": d.get("updated_at"),
            "author": d.get("author"),
        },
        "passage": {"id": passage.get("passage_id"), "text": passage.get("passage")},
        "stale": stale,
        "evidence": [facts[i] for i in evidence if i in facts],
        "routed": _ordered(routed),
        "approved_by": x.get("approved_by"),
        "approved_at": x.get("approved_at"),
        "issue": {
            "repo": x.get("issue_repo"),
            "url": x.get("issue_url"),
            "title": x.get("issue_title"),
            "body": x.get("issue_body"),
            "dry_run": bool(x.get("dry_run")),
            "error": x.get("issue_error"),
            "filed_at": x.get("filed_at"),
        },
        "dismissed": {"by": x.get("dismissed_by"), "at": x.get("dismissed_at"), "reason": x.get("dismiss_reason")},
    }


def list_fixes(graph, statuses=STATUSES) -> list[dict]:
    rows = graph.query(FIXES, {"statuses": list(statuses)}).result_set
    if not rows:
        return []
    ids = [x.properties["id"] for x, _ in rows]
    links: dict[str, dict[str, list[str]]] = {i: {"ABOUT": [], "EVIDENCE": []} for i in ids}
    for xid, rel, fid in graph.query(EDGES, {"ids": ids}).result_set:
        links[xid][rel].append(fid)
    routed: dict[str, list[dict]] = {i: [] for i in ids}
    for xid, role, team, label, key, name in graph.query(ROUTED, {"ids": ids}).result_set:
        r = {"kind": "team" if label == "Team" else "person", "key": key, "name": name, "role": role}
        if team:
            r["team"] = team
        routed[xid].append(r)
    facts = read.facts(graph, [f for v in links.values() for fs in v.values() for f in fs])
    out = [
        _shape(dict(x.properties), dict(d.properties) if d else {}, facts, sorted(links[xid]["ABOUT"]),
               sorted(links[xid]["EVIDENCE"]), routed[xid])
        for (x, d), xid in zip(rows, ids)
    ]
    # Pages in title order, and on each page its lines in the order the page has them.
    return sorted(out, key=lambda f: ((f["page"]["title"] or "").lower(), f["passage"]["id"] or "", f["id"]))


def get_fix(graph, fid: str) -> dict | None:
    rows = graph.query("MATCH (x:Fix {id: $id}) RETURN x.status", {"id": fid}).result_set
    if not rows:
        return None
    return next((f for f in list_fixes(graph, [rows[0][0] or "open"]) if f["id"] == fid), None)


def totals(graph) -> dict[str, int]:
    out = dict.fromkeys(STATUSES, 0)
    for status, n in graph.query("MATCH (x:Fix) RETURN coalesce(x.status, 'open'), count(x)").result_set:
        out[status] = n
    return out


# --- Transitions ------------------------------------------------------------------------------------


def _require(graph, fid: str) -> dict:
    fix = get_fix(graph, fid)
    if fix is None:
        raise KeyError(fid)
    return fix


def approve(graph, fid: str, *, repo: str, user, dry_run: bool | None = None, transport=None) -> dict:
    """open or approved -> filed. Files the issue with the user's token, or in dry run records it."""
    from canon.fixes import issues

    fix = _require(graph, fid)
    if fix["status"] not in LIVE:
        raise TransitionError(f"This fix is {fix['status']}, so it cannot be approved.")
    if not fix["new"]:
        raise TransitionError("This fix has no checked correction to file.")
    repo = issues.check_repo(repo)
    dry = issues.dry_run() if dry_run is None else dry_run
    title, body = issues.issue_title(fix), issues.issue_body(fix)
    now = _now()
    graph.query(
        """MATCH (x:Fix {id: $id}) SET x.status = 'approved', x.approved_by = $by, x.approved_at = $now,
           x.issue_repo = $repo, x.issue_title = $title, x.issue_body = $body, x.issue_error = NULL, x.updated_at = $now""",
        {"id": fid, "by": user.login, "now": now, "repo": repo, "title": title, "body": body},
    )
    if dry:
        url = f"dry-run://github.com/{repo}/issues/{fid}"
    else:
        try:
            url = issues.file_issue(repo, title, body, token=user.token, transport=transport)["url"]
        except issues.FilingError as e:
            graph.query("MATCH (x:Fix {id: $id}) SET x.issue_error = $error", {"id": fid, "error": str(e)})
            raise
    graph.query(
        """MATCH (x:Fix {id: $id}) SET x.status = 'filed', x.issue_url = $url, x.dry_run = $dry, x.filed_at = $now,
           x.updated_at = $now""",
        {"id": fid, "url": url, "dry": dry, "now": now},
    )
    return _require(graph, fid)


def file_copy(graph, fid: str, *, repo: str, user, dry_run: bool | None = None, transport=None) -> dict:
    """Files a fix's issue in the user's own repository without changing the shared queue. For public workspaces,
    where a visitor may file a fix to try it, but only members decide what happens to the fix itself."""
    from canon.fixes import issues

    fix = _require(graph, fid)
    if fix["status"] not in LIVE or not fix["new"]:
        raise TransitionError("This fix has no checked correction to file.")
    repo = issues.check_repo(repo)
    dry = issues.dry_run() if dry_run is None else dry_run
    title, body = issues.issue_title(fix), issues.issue_body(fix)
    url = (
        f"dry-run://github.com/{repo}/issues/{fid}"
        if dry
        else issues.file_issue(repo, title, body, token=user.token, transport=transport)["url"]
    )
    issue = {"repo": repo, "url": url, "title": title, "body": body, "dry_run": dry, "error": None, "filed_at": _now()}
    return {**fix, "status": "filed", "issue": issue, "shared": False}


def dismiss(graph, fid: str, *, reason: str, user) -> dict:
    """open or approved -> dismissed, with the reason a person gave."""
    fix = _require(graph, fid)
    reason = " ".join((reason or "").split())
    if not reason:
        raise TransitionError("Say why this is not a fix.")
    if fix["status"] not in LIVE:
        raise TransitionError(f"This fix is {fix['status']}, so it cannot be dismissed.")
    now = _now()
    graph.query(
        """MATCH (x:Fix {id: $id}) SET x.status = 'dismissed', x.dismissed_by = $by, x.dismissed_at = $now,
           x.dismiss_reason = $reason, x.updated_at = $now""",
        {"id": fid, "by": user.login, "now": now, "reason": reason[:500]},
    )
    return _require(graph, fid)
