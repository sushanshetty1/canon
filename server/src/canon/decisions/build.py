"""Writes decisions into a workspace graph from the cached RFCs and pull requests.

`build(graph, rfcs, pulls, model=None)`:

1. One `Decision` per RFC, with its status, dates and summary. RFCs on the main branch are documents the connector
   wrote; a proposal that never merged (`rfc_proposals`) is added as a document here, linked to its pull request.
2. `DECIDED` from the people who approved its pull request, else the person who merged it. Only people already in
   the graph (PostHog's published staff) are linked.
3. `IMPLEMENTED_BY` for merged pull requests whose body links the RFC or names it by title. A linking pull request
   that is not in the graph yet is added as a document.
4. `SUPERSEDED_BY`:
   - by reference, when a later accepted RFC links an earlier one with replacement words beside the link
     ("I'm folding the Twig proposal into this"; `by: 'reference'`);
   - by a model, asked once per pair, when a later accepted RFC shares an area with an earlier one, or links it
     without saying how (`by: 'model'`, with its reason). Pairs it has judged are remembered on the later decision,
     so a second run asks nothing.
   Only an accepted RFC replaces anything: a proposal still open, or one that closed, changed nothing.
5. `ABOUT` the areas the RFC's title and body name.
6. Dated facts each decision states in its RFC (accepted, proposed, rejected, retired, replaced), so the claim
   check can verify a sentence about a decision like any other.

Running it twice changes nothing.
"""

import asyncio
import re
import time
from dataclasses import dataclass, field
from itertools import combinations
from pathlib import Path

from canon.decisions import rfc as R
from canon.graph.writer import write_batch, write_facts
from canon.llm import JsonModel
from canon.sources.cache import Cache
from canon.sources.posthog import clean_mdx, frontmatter, passages_of, split_passages
from canon.types import Activity, Batch, Doc, Fact

RFC_AUTHORITY = 2
DECISION_KINDS = ("rfc", "adr")  # PostHog's RFCs, and any repository's decision records
MAX_PAIRS = 120  # model questions per run at most
JUDGE_CHARS = 2400

JUDGE_SYSTEM = """You compare two RFCs from one company. The second was proposed after the first.

Decide whether the second RFC replaces the first: once the second is accepted, the first one's decision no longer
holds, because the second changes or reverses it, or redoes the same thing a new way. It does not replace the first
if it builds on it, extends it, follows it up, covers a different part of the product, or is a companion written at
the same time. Most pairs do not replace each other.

Write `why` first, in one short plain sentence that names both RFCs. Then set `replaces`."""

JUDGE_SCHEMA = {
    "type": "object",
    "properties": {"why": {"type": "string"}, "replaces": {"type": "boolean"}},
    "required": ["why", "replaces"],
    "additionalProperties": False,
}

_NAME = r"[A-Z][\w'.-]+(?:\s+[A-Z][\w'.-]+)*"
_AUTHOR_TAIL = re.compile(
    "|".join([
        rf"\s*[,(&]\s*(by\s+)?@?{_NAME}\)?\s*$",  # ", by Michael Matloka", "(Ben White)", "& Paul D'Ambra"
        r"\s*(&|by)\s+@[\w-]+\s*$",  # "by @raquelmsmith", "& @pauldambra"
        rf"\s+[-\u2013\u2014]\s+[A-Z][\w'.-]+(\s+[A-Z][\w'.-]+)+(\s*/\s*{_NAME})*\s*$",  # " - Emanuele Capparelli / Raquel Smith"
        r"\s+#[\w-]+\s*$",
    ])
)


def short_title(title: str) -> str:
    """The RFC's title without the "RFC:" prefix, a trailing author or a hashtag."""
    t = re.sub(r"^RFC:\s*(\[[^\]]{1,12}\]\s*)?", "", title or "")
    t = R._plain(re.sub(r"\s+#[\w-]+\s*$", "", t))
    for _ in range(2):
        cut = _AUTHOR_TAIL.sub("", t).strip(" ,-")
        if len(cut) >= 6:
            t = cut
    return t[:1].upper() + t[1:]


@dataclass
class Plan:
    rfc: R.Rfc
    title: str
    url: str
    status: str
    summary: str
    areas: list[str]
    people: list[tuple[str, str, str]]  # handle, how, at
    pulls: list[tuple[dict, str]]
    passage: str | None = None  # the passage that opens the RFC, where its decision facts are stated
    replaced_by: list[tuple[str, str, str]] = field(default_factory=list)  # target, reason, by
    replaced_at: str | None = None


def _when(p: Plan) -> tuple[str, str, str]:
    return (p.rfc.proposed_at or p.rfc.decided_at or "", p.rfc.decided_at or "", p.rfc.id)


def _rows(graph, query: str, params: dict | None = None) -> list:
    return graph.query(query, params or {}).result_set


def proposal_title(rfc: R.Rfc) -> str:
    """A proposal's title as the connector titles an RFC: its first heading, else its pull request's title."""
    m = re.search(r"^#\s+(.+)$", rfc.text, re.M)
    title = re.sub(r"^((request for comments|rfc)\s*[:-]\s*)+", "", (m.group(1) if m else "").strip(), flags=re.I)
    if not title or title.startswith("*"):
        title = re.sub(r"^\[?rfc\]?\s*[:-]?\s*", "", rfc.pr_title or "", flags=re.I).strip()
    if not title or title.lower().startswith(("create ", "add ")):
        stem = re.sub(r"^\d{4}-\d{2}(-\d{2})?-", "", rfc.stem).replace("-", " ")
        title = stem[:1].upper() + stem[1:]
    return f"RFC: {title}"


def write_proposals(graph, rfc_rows: list[dict]) -> int:
    """Proposals the graph does not hold yet, as RFC documents with their passages."""
    rows = [R.from_row(r) for r in rfc_rows if r.get("proposal")]
    if not rows:
        return 0
    have = {d for (d,) in _rows(graph, "MATCH (d:Document {kind: 'rfc'}) RETURN d.id")}
    staff = {h for (h,) in _rows(graph, "MATCH (p:Person) RETURN p.handle")}
    batch = Batch()
    for rfc, row in zip(rows, [r for r in rfc_rows if r.get("proposal")]):
        if rfc.doc_id in have:
            continue
        _, body = frontmatter(rfc.text)
        author = ((row.get("pr") or {}).get("author") or "").lower() or None
        updated = rfc.closed_at or R.day(row.get("updated_at")) or rfc.proposed_at or ""
        batch.docs.append(Doc(rfc.doc_id, "rfc", proposal_title(rfc), rfc.url or "", updated, author))
        batch.passages += passages_of(rfc.doc_id, split_passages(clean_mdx(body, {})))
        if author in staff and rfc.proposed_at:
            batch.activity.append(Activity(author, rfc.doc_id, "AUTHORED", rfc.proposed_at))
    if batch.docs:
        write_batch(graph, batch)
    return len(batch.docs)


def plan(graph, rfc_rows: list[dict], pulls: list[dict]) -> dict[str, Plan]:
    kinds = {"kinds": list(DECISION_KINDS)}
    docs = {d: (t, u) for d, t, u in _rows(graph, "MATCH (d:Document) WHERE d.kind IN $kinds RETURN d.id, d.title, d.url", kinds)}
    areas = dict(_rows(graph, "MATCH (a:Area) RETURN a.slug, coalesce(a.name, a.slug)"))
    staff = {h for (h,) in _rows(graph, "MATCH (p:Person) RETURN p.handle")}
    passages: dict[str, list[tuple[str, str]]] = {}
    for d, pid, text in _rows(
        graph, "MATCH (d:Document)-[:HAS]->(p:Passage) WHERE d.kind IN $kinds RETURN d.id, p.id, p.text", kinds
    ):
        passages.setdefault(d, []).append((pid, text or ""))
    plans: dict[str, Plan] = {}
    for row in rfc_rows:
        rfc = R.from_row(row)
        if rfc.doc_id not in docs:
            continue
        status = R.status_of(rfc)
        if rfc.state == "main" and status in ("proposed", "withdrawn"):
            rfc.decided_at = None  # a record on the branch that says it is still a proposal decided nothing yet
        title, url = docs[rfc.doc_id]
        short = short_title(title)
        # Only an RFC that landed was decided; approving a pull request that then closed decided nothing.
        landed = rfc.state in ("merged", "main")
        people = [(h, "approved", at) for h, at in rfc.approvers if h in staff] if landed else []
        if not people and landed and rfc.merged_by in staff:
            people = [(rfc.merged_by, "merged", rfc.decided_at or "")]
        plans[rfc.id] = Plan(
            rfc=rfc,
            title=short,
            url=url,
            status=status,
            summary=R.summary_of(rfc.text),
            areas=R.areas_of(short, rfc.text, areas),
            people=people,
            pulls=R.implemented_by(rfc, short, pulls),
            passage=_opening(rfc.text, passages.get(rfc.doc_id, [])),
        )
    return plans


def _opening(text: str, passages: list[tuple[str, str]]) -> str | None:
    """The passage that comes first in the RFC's text."""
    flat = " ".join(text.split())

    def at(p: tuple[str, str]) -> int:
        words = " ".join(p[1].split()[:6])
        i = flat.find(words) if words else -1
        return i if i >= 0 else 10**9

    return min(passages, key=lambda p: (at(p), p[0]))[0] if passages else None


def _orient(a: Plan, b: Plan) -> tuple[Plan, Plan]:
    """(earlier, later)."""
    return (a, b) if _when(a) <= _when(b) else (b, a)


def candidates(plans: dict[str, Plan]) -> tuple[dict[tuple[str, str], str], dict[tuple[str, str], str]]:
    """Replacements stated by reference, and the (earlier, later) pairs a model should read, with what links them."""
    known = {p.rfc.id: p.rfc for p in plans.values()}
    stated: dict[tuple[str, str], str] = {}
    ask: dict[tuple[str, str], str] = {}
    for p in plans.values():
        for ref in R.references(p.rfc, known):
            earlier, later = _orient(p, plans[ref.target])
            if later.status not in ("accepted", "retired"):
                continue  # a proposal replaces nothing until it is accepted
            # "This replaces X" in the later record, or "superseded by Y" in the earlier one: both state it.
            if ref.replaces and ((later is p) != ref.passive):
                stated[(earlier.rfc.id, later.rfc.id)] = ref.context
            else:
                ask.setdefault((earlier.rfc.id, later.rfc.id), f"One links the other: {ref.context}")
    live = [p for p in plans.values() if p.status != "rejected"]
    for a, b in combinations(live, 2):
        shared = sorted(set(a.areas) & set(b.areas))
        if shared:
            earlier, later = _orient(a, b)
            if later.status not in ("accepted", "retired"):
                continue
            ask.setdefault((earlier.rfc.id, later.rfc.id), f"Both are about {', '.join(shared)}.")
    for key in stated:
        ask.pop(key, None)
    return stated, ask


def _brief(p: Plan) -> str:
    when = f"proposed {p.rfc.proposed_at}" + (f", accepted {p.rfc.decided_at}" if p.rfc.decided_at else "")
    text = re.sub(r"\n{3,}", "\n\n", p.rfc.text)[:JUDGE_CHARS]
    return f'"{p.title}" ({when})\n{text}'


async def judge(pairs: dict[tuple[str, str], str], plans: dict[str, Plan], model: JsonModel, *, concurrency: int = 6):
    """For each (earlier, later) pair: (replaces, why), or None when the model could not answer."""
    semaphore = asyncio.Semaphore(concurrency)

    async def one(key: tuple[str, str]):
        earlier, later = plans[key[0]], plans[key[1]]
        prompt = f"Why they were paired: {pairs[key]}\n\nFirst RFC: {_brief(earlier)}\n\nSecond RFC: {_brief(later)}"
        async with semaphore:
            try:
                out = await model.json(JUDGE_SYSTEM, prompt, JUDGE_SCHEMA)
            except Exception:
                return key, None
        return key, (out.get("replaces") is True, " ".join(str(out.get("why") or "").split()))

    return dict(await asyncio.gather(*(one(k) for k in pairs)))


def _decision_facts(plans: dict[str, Plan]) -> list[Fact]:
    facts = []
    for p in plans.values():
        r, subject, name = p.rfc, f"decision:{p.rfc.id}", f'The "{p.title}" RFC'
        passage = p.passage
        if not passage:
            continue
        if p.status == "proposed" and r.proposed_at:
            facts.append(Fact(f"{subject}:proposed", subject, "decided", "proposed",
                              f"{name} was proposed on {r.proposed_at} and has not been accepted.",
                              r.proposed_at, passage, RFC_AUTHORITY))
        if p.status == "withdrawn" and r.closed_at:
            facts.append(Fact(f"{subject}:withdrawn", subject, "decided", "withdrawn",
                              f"{name} was proposed on {r.proposed_at} and closed on {r.closed_at} without being accepted.",
                              r.closed_at, passage, RFC_AUTHORITY))
        if p.status == "superseded" and r.state in ("open", "closed") and r.proposed_at:
            facts.append(Fact(f"{subject}:proposed", subject, "decided", "proposed", f"{name} was proposed on {r.proposed_at}.",
                              r.proposed_at, passage, RFC_AUTHORITY, valid_to=p.replaced_at))
        if p.status == "rejected":
            facts.append(Fact(f"{subject}:rejected", subject, "decided", "rejected", f"{name} was rejected.",
                              r.decided_at or r.proposed_at or "", passage, RFC_AUTHORITY))
        if p.status == "retired":
            facts.append(Fact(f"{subject}:retired", subject, "decided", "retired",
                              f"{name} says it is out of date and does not describe how things work now.",
                              r.updated_at or r.decided_at or "", passage, RFC_AUTHORITY))
        if r.decided_at and p.status in ("accepted", "superseded"):
            facts.append(Fact(f"{subject}:accepted", subject, "decided", "accepted", f"{name} was accepted on {r.decided_at}.",
                              r.decided_at, passage, RFC_AUTHORITY, valid_to=p.replaced_at))
        if p.status == "superseded" and p.replaced_at:
            target = plans[p.replaced_by[0][0]]
            facts.append(Fact(f"{subject}:replaced", subject, "decided", f"replaced by decision:{target.rfc.id}",
                              f'{name} was replaced by the "{target.title}" RFC on {p.replaced_at}.',
                              p.replaced_at, target.passage or passage, RFC_AUTHORITY))
    return [f for f in facts if f.valid_from]


def build(graph, rfc_rows: list[dict], pulls: list[dict], *, model: JsonModel | None = None) -> dict[str, int]:
    write_proposals(graph, rfc_rows)
    plans = plan(graph, rfc_rows, pulls)
    stated, pairs = candidates(plans)

    # What the model said before stays: the pairs each later decision was judged against, and its edges.
    judged = {d: set(j or []) for d, j in _rows(graph, "MATCH (d:Decision) RETURN d.id, d.judged")}
    kept = {
        (a, b): why
        for a, b, why in _rows(
            graph, "MATCH (a:Decision)-[e:SUPERSEDED_BY {by: 'model'}]->(b:Decision) RETURN a.id, b.id, e.reason"
        )
        if (a, b) in pairs
    }
    todo = {k: v for k, v in pairs.items() if k[0] not in judged.get(k[1], set())}
    asked = 0
    if model is not None and todo:
        todo = dict(sorted(todo.items())[:MAX_PAIRS])
        answers = asyncio.run(judge(todo, plans, model))
        for key, answer in answers.items():
            if answer is None:
                continue
            asked += 1
            judged.setdefault(key[1], set()).add(key[0])
            replaces, why = answer
            if replaces:
                kept[key] = why
            else:
                kept.pop(key, None)

    edges = {k: (v, "reference") for k, v in stated.items()}
    for k, why in kept.items():
        edges.setdefault(k, (why, "model"))
    # A cycle would leave nothing current: keep the stated edge, or the one the later decision makes.
    for (a, b) in list(edges):
        if (b, a) in edges and edges[(a, b)][1] == "model":
            edges.pop((a, b))

    for (a, b), (why, by) in sorted(edges.items()):
        plans[a].replaced_by.append((b, why, by))
    for p in plans.values():
        if p.replaced_by and p.status != "rejected":
            p.status = "superseded"
            dates = [plans[b].rfc.decided_at or plans[b].rfc.proposed_at for b, _, _ in p.replaced_by]
            p.replaced_at = min(d for d in dates if d) if any(dates) else None
            p.replaced_by.sort(key=lambda e: plans[e[0]].rfc.decided_at or "")
        elif p.status == "superseded":
            p.status = "retired"  # it says it was superseded, but names nothing Canon can find: it no longer holds

    _write(graph, plans, judged)
    statuses = [p.status for p in plans.values()]
    return {
        "decisions": len(plans),
        **{s: statuses.count(s) for s in R.STATUSES if statuses.count(s)},
        "superseded_by": len(edges),
        "implemented_by": sum(len(p.pulls) for p in plans.values()),
        "decided_by": sum(len(p.people) for p in plans.values()),
        "about": sum(len(p.areas) for p in plans.values()),
        "judged": asked,
    }


def _write(graph, plans: dict[str, Plan], judged: dict[str, set[str]]) -> None:
    ids = sorted(plans)
    rows = [
        {
            "id": p.rfc.id,
            "doc": p.rfc.doc_id,
            "title": p.title,
            "status": p.status,
            "proposed_at": p.rfc.proposed_at,
            "decided_at": p.rfc.decided_at,
            "closed_at": p.rfc.closed_at,
            "state": p.rfc.state,
            "replaced_at": p.replaced_at,
            "summary": p.summary,
            "url": p.url,
            "rfc_pr": p.rfc.pr_number,
            "judged": sorted(judged.get(p.rfc.id, set())) or None,
        }
        for p in plans.values()
    ]
    graph.query(
        """UNWIND $rows AS r MERGE (d:Decision {id: r.id})
           SET d.title = r.title, d.status = r.status, d.proposed_at = r.proposed_at, d.decided_at = r.decided_at,
               d.replaced_at = r.replaced_at, d.summary = r.summary, d.url = r.url, d.rfc_pr = r.rfc_pr,
               d.closed_at = r.closed_at, d.state = r.state,
               d.judged = r.judged
           WITH d, r MATCH (doc:Document {id: r.doc}) MERGE (d)-[:PROPOSED_IN]->(doc)""",
        {"rows": rows},
    )
    # Decisions whose RFC is gone, and every derived edge, are rebuilt from the plan.
    graph.query("MATCH (d:Decision) WHERE NOT d.id IN $ids DETACH DELETE d", {"ids": ids})
    graph.query("MATCH (:Person)-[e:DECIDED]->(:Decision) DELETE e")
    graph.query("MATCH (:Decision)-[e:IMPLEMENTED_BY|ABOUT|SUPERSEDED_BY]->() DELETE e")

    new_docs = _pull_docs(graph, plans)
    if new_docs.docs:
        write_batch(graph, new_docs)
    graph.query(
        """UNWIND $rows AS r MATCH (d:Decision {id: r.id}) MATCH (p:Person {handle: r.handle})
           MERGE (p)-[e:DECIDED]->(d) SET e.how = r.how, e.at = r.at""",
        {"rows": [{"id": p.rfc.id, "handle": h, "how": how, "at": at} for p in plans.values() for h, how, at in p.people]},
    )
    graph.query(
        """UNWIND $rows AS r MATCH (d:Decision {id: r.id}) MATCH (doc:Document {id: r.doc})
           MERGE (d)-[e:IMPLEMENTED_BY]->(doc) SET e.how = r.how""",
        {"rows": [{"id": p.rfc.id, "doc": R.pull_id(pr), "how": how} for p in plans.values() for pr, how in p.pulls]},
    )
    graph.query(
        "UNWIND $rows AS r MATCH (d:Decision {id: r.id}) MATCH (a:Area {slug: r.area}) MERGE (d)-[:ABOUT]->(a)",
        {"rows": [{"id": p.rfc.id, "area": a} for p in plans.values() for a in p.areas]},
    )
    graph.query(
        """UNWIND $rows AS r MATCH (a:Decision {id: r.a}), (b:Decision {id: r.b})
           MERGE (a)-[e:SUPERSEDED_BY]->(b) SET e.reason = r.reason, e.by = r.by""",
        {"rows": [{"a": p.rfc.id, "b": b, "reason": why, "by": by} for p in plans.values() for b, why, by in p.replaced_by]},
    )

    facts = _decision_facts(plans)
    keep = [f.id for f in facts]
    graph.query("MATCH (f:Fact) WHERE f.subject STARTS WITH 'decision:' AND NOT f.id IN $ids DETACH DELETE f", {"ids": keep})
    write_facts(graph, facts)
    # An accepted decision that was replaced links to the fact that says so, as `supersede.link` would.
    chain = [
        {"a": f"decision:{p.rfc.id}:{first}", "b": f"decision:{p.rfc.id}:replaced"}
        for p in plans.values()
        for first in ("accepted", "proposed")
        if p.status == "superseded" and f"decision:{p.rfc.id}:replaced" in keep and f"decision:{p.rfc.id}:{first}" in keep
    ]
    graph.query(
        """MATCH (a:Fact)-[e:SUPERSEDED_BY]->(:Fact) WHERE a.subject STARTS WITH 'decision:' DELETE e""",
    )
    graph.query(
        """UNWIND $rows AS r MATCH (a:Fact {id: r.a}), (b:Fact {id: r.b})
           MERGE (a)-[e:SUPERSEDED_BY]->(b) SET e.reason = 'newer'""",
        {"rows": chain},
    )


def _pull_docs(graph, plans: dict[str, Plan]) -> Batch:
    """Linking pull requests the graph does not hold yet, as documents with one passage each."""
    wanted = {R.pull_id(pr): pr for p in plans.values() for pr, _ in p.pulls}
    if not wanted:
        return Batch()
    have = {d for (d,) in _rows(graph, "MATCH (d:Document) WHERE d.id IN $ids RETURN d.id", {"ids": list(wanted)})}
    staff = {h for (h,) in _rows(graph, "MATCH (p:Person) RETURN p.handle")}
    batch = Batch()
    for doc_id, pr in sorted(wanted.items()):
        if doc_id in have:
            continue
        author = (pr.get("author") or "").lower() or None
        batch.docs.append(Doc(doc_id, "pull", pr["title"], pr["url"], R.day(pr.get("merged_at")) or "", author))
        batch.passages += passages_of(doc_id, [f"{pr['title']}\n{(pr.get('body') or '').strip()[:600]}".strip()])
        if author in staff and pr.get("created_at"):
            batch.activity.append(Activity(author, doc_id, "AUTHORED", R.day(pr["created_at"]) or ""))
    return batch


# ----- pull requests that link an RFC, from GitHub search ---------------------------------------------------------

_SEARCH_PAUSE = 2.2  # the search API allows 30 requests a minute


def linked_pulls(cache_dir: Path, rfc_rows: list[dict], *, github=None) -> list[dict]:
    """Pull requests anywhere in PostHog's GitHub that link an RFC by file name or by its pull request, cached as
    `rfc_pulls.json`. The RFC repository's own pull requests (the proposals) are left out."""

    def read() -> list[dict]:
        from canon.sources.github import GitHub

        gh = github or GitHub()
        found: dict[tuple[str, int], dict] = {}
        for row in rfc_rows:
            rfc = R.from_row(row)
            queries = [f'"{rfc.stem}" is:pr org:PostHog']
            if rfc.pr_number:
                queries.append(f'"requests-for-comments-public/pull/{rfc.pr_number}" is:pr org:PostHog')
            for q in queries:
                items = gh.get("/search/issues", q=q, per_page=50).json().get("items", [])
                for i in items:
                    repo = i["repository_url"].split("/repos/", 1)[1]
                    if repo.endswith("requests-for-comments-public") or not R.links_rfc(rfc, i.get("body") or ""):
                        continue
                    found[(repo, i["number"])] = {
                        "repo": repo,
                        "number": i["number"],
                        "title": i["title"],
                        "body": (i.get("body") or "")[:4000],
                        "url": i["html_url"],
                        "created_at": i.get("created_at"),
                        "merged_at": (i.get("pull_request") or {}).get("merged_at"),
                        "author": ((i.get("user") or {}).get("login") or "").lower() or None,
                    }
                time.sleep(_SEARCH_PAUSE)
        return sorted(found.values(), key=lambda r: (r["repo"], r["number"]))

    return Cache(Path(cache_dir)).json("rfc_pulls", read)


_PROPOSALS = """
query($owner: String!, $name: String!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    pullRequests(first: 50, after: $cursor, states: [OPEN, CLOSED], orderBy: {field: CREATED_AT, direction: ASC}) {
      pageInfo { hasNextPage endCursor }
      nodes {
        number title url state createdAt closedAt headRefOid
        author { login __typename }
        files(first: 30) { nodes { path changeType } }
        reviews(first: 40) { nodes { author { login __typename } state submittedAt } }
      }
    }
  }
}"""


def rfc_proposals(cache_dir: Path, known_paths: set[str], *, github=None) -> list[dict]:
    """RFC pull requests that never merged, open or closed, each with the RFC file it adds, cached as
    `rfc_proposals.json`. Files already on the main branch are left to the connector."""

    def read() -> list[dict]:
        import base64

        from canon.sources.github import GitHub
        from canon.sources.posthog import RFC_REPO, _login

        gh = github or GitHub()
        owner, name = RFC_REPO.split("/")
        rows, cursor = [], None
        while True:
            conn = gh.graphql(_PROPOSALS, {"owner": owner, "name": name, "cursor": cursor})["repository"]["pullRequests"]
            for n in conn["nodes"]:
                added = [f["path"] for f in n["files"]["nodes"] if f["changeType"] == "ADDED"
                         and f["path"].startswith("requests-for-comments/") and f["path"].endswith(".md")]
                for path in added:
                    if path in known_paths:
                        continue
                    blob = gh.get(f"/repos/{RFC_REPO}/contents/{path}", ref=n["headRefOid"]).json()
                    text = base64.b64decode(blob.get("content") or "").decode("utf-8", errors="replace")
                    rows.append({
                        "path": path,
                        "text": text,
                        "created_at": n["createdAt"],
                        "updated_at": n["closedAt"] or n["createdAt"],
                        "proposal": {"state": n["state"], "closed_at": n["closedAt"], "url": n["url"], "title": n["title"]},
                        "pr": {
                            "number": n["number"],
                            "author": _login(n["author"]),
                            "created_at": n["createdAt"],
                            "merged_at": None,
                            "merged_by": None,
                            "reviews": [
                                {"author": _login(r["author"]), "state": r["state"], "at": r["submittedAt"]}
                                for r in n["reviews"]["nodes"] if _login(r["author"]) and r["submittedAt"]
                            ],
                            "comments": [],
                        },
                    })
            if not conn["pageInfo"]["hasNextPage"]:
                return rows
            cursor = conn["pageInfo"]["endCursor"]

    return Cache(Path(cache_dir)).json("rfc_proposals", read)
