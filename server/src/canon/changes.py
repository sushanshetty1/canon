"""Catch me up: what changed in a workspace since a date, and a checked brief of it.

`changes(graph, since, area=None, team=None)` returns typed changes, each with the facts behind it and its sources:

- `ownership`: an area's owners changed in the ownership map (owned_by facts that start or end after `since`,
  grouped by area and day, so a co-owner restated in the new list is not a change);
- `decision`: a decision was accepted, proposed, or replaced by a later one;
- `page`: a page's facts changed: passages removed, or facts closed;
- `stale`: a page became out of date (a more authoritative source changed under it);
- `dispute`: two current sources started to disagree.

All of it is Cypher over the graph. `brief(...)` drafts a short summary from those facts with the model and checks
every sentence with `canon.verify.check`, streaming the same events as `canon.answer.ask`, so the web reads it with
the same code.
"""

import asyncio
from collections.abc import AsyncIterator
from datetime import date

from canon.answer.ask import VERDICTS, _checked
from canon.answer.draft import SCHEMA, _line
from canon.answer.retrieve import Evidence, _shape
from canon.graph import read
from canon.llm import JsonModel, answer_model, check_model
from canon.verify.check import Claim, Entail, make_entail

KINDS = ("ownership", "decision", "page", "stale", "dispute")

OWNERSHIP = """
MATCH (f:Fact {predicate: 'owned_by'}) WHERE f.authority >= 3 AND f.subject STARTS WITH 'area:'
  AND (f.valid_from > $since OR (f.valid_to IS NOT NULL AND f.valid_to > $since))
OPTIONAL MATCH (f)-[:STATED_IN]->(:Passage)<-[:HAS|HAD]-(d:Document)
RETURN f.id, f.subject, f.value, f.valid_from, f.valid_to, d.id, d.title, d.url, d.kind, d.updated_at
"""
# A day's ownership commit both closes the old list and states the new one. Fact windows are what tell.

DECISIONS = """
MATCH (d:Decision)
WHERE (d.decided_at IS NOT NULL AND d.decided_at > $since) OR (d.proposed_at IS NOT NULL AND d.proposed_at > $since)
   OR (d.replaced_at IS NOT NULL AND d.replaced_at > $since)
OPTIONAL MATCH (d)-[:PROPOSED_IN]->(doc:Document)
RETURN d.id, d.title, d.status, d.proposed_at, d.decided_at, d.replaced_at, doc.id, doc.title, doc.url, doc.updated_at
"""
REPLACEMENTS = """
MATCH (a:Decision)-[e:SUPERSEDED_BY]->(b:Decision) WHERE a.id IN $ids OR b.id IN $ids
RETURN a.id, a.title, b.id, b.title, e.reason
"""
DECISION_AREAS = "MATCH (d:Decision)-[:ABOUT]->(a:Area) RETURN d.id, a.slug"

PAGES = """
MATCH (f:Fact)-[:STATED_IN]->(p:Passage)<-[:HAS|HAD]-(d:Document)
WHERE f.valid_to IS NOT NULL AND f.valid_to > $since AND d.kind <> 'ownership_map' AND NOT f.subject STARTS WITH 'decision:'
RETURN d.id, d.title, d.url, d.kind, d.updated_at, f.id, f.subject, f.value, f.valid_to, p.removed_at
"""
STALE = """
MATCH (f:Fact {stale: true})-[:SUPERSEDED_BY]->(h:Fact)
MATCH (f)-[:STATED_IN]->(:Passage)<-[:HAS]-(d:Document)
WHERE f.valid_from > $since OR h.valid_from > $since
OPTIONAL MATCH (h)-[:STATED_IN]->(:Passage)<-[:HAS|HAD]-(hd:Document)
RETURN d.id, d.title, d.url, d.kind, d.updated_at, f.id, f.subject, f.value, f.valid_from, h.id, h.value,
       h.valid_from, hd.id, hd.title, hd.url, hd.kind, hd.updated_at
"""
DISPUTES = """
MATCH (a:Fact)-[r:CONTRADICTS]->(b:Fact)
WHERE a.valid_to IS NULL AND b.valid_to IS NULL AND (a.valid_from > $since OR b.valid_from > $since)
OPTIONAL MATCH (a)-[:STATED_IN]->(:Passage)<-[:HAS]-(da:Document)
OPTIONAL MATCH (b)-[:STATED_IN]->(:Passage)<-[:HAS]-(db:Document)
RETURN a.id, a.subject, a.text, a.valid_from, b.id, b.text, b.valid_from, r.why,
       da.id, da.title, da.url, da.kind, da.updated_at, db.id, db.title, db.url, db.kind, db.updated_at
"""
NAMES = """
MATCH (e) WHERE (e:Area OR e:Team OR e:Person)
RETURN CASE WHEN e:Area THEN 'area:' + e.slug WHEN e:Team THEN 'team:' + e.slug ELSE 'person:' + e.handle END,
       coalesce(e.name, e.slug, e.handle)
"""
TEAM_AREAS = """
MATCH (f:Fact {predicate: 'owned_by', value: $team}) WHERE f.subject STARTS WITH 'area:'
  AND (f.valid_to IS NULL OR f.valid_to > $since)
RETURN DISTINCT f.subject
"""
DOC_AREAS = "MATCH (d:Document)-[:ABOUT]->(a:Area) WHERE d.id IN $ids RETURN d.id, a.slug"


def _source(doc_id, title, url, kind, updated) -> dict | None:
    if not doc_id:
        return None
    return {"doc_id": doc_id, "title": title, "url": url, "kind": kind, "date": updated}


def _names(graph) -> dict[str, str]:
    return dict(graph.query(NAMES).result_set)


def _label(key: str, names: dict[str, str]) -> str:
    if key in names:
        return names[key]
    bare = str(key).split(":", 1)[-1].removeprefix("name:").replace("-", " ").strip()
    return bare[:1].upper() + bare[1:]


def _join(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def _ownership(graph, since: str, names: dict[str, str]) -> list[dict]:
    by_area: dict[str, dict[str, dict]] = {}
    for fid, subject, value, vf, vt, *doc in graph.query(OWNERSHIP, {"since": since}).result_set:
        days = by_area.setdefault(subject, {})
        if vf and vf > since:
            day = days.setdefault(vf, {"started": {}, "ended": {}, "source": None})
            day["started"][value] = fid
            day["source"] = day["source"] or _source(*doc)
        if vt and vt > since:
            days.setdefault(vt, {"started": {}, "ended": {}, "source": None})["ended"][value] = fid
    out = []
    for subject, days in by_area.items():
        area = _label(subject, names)
        for day, d in sorted(days.items()):
            new = [v for v in d["started"] if v not in d["ended"]]
            gone = [v for v in d["ended"] if v not in d["started"]]
            if not new and not gone:
                continue  # the list was restated, the owners stayed
            new_names, gone_names = [_label(v, names) for v in new], [_label(v, names) for v in gone]
            if new and gone:
                title = f"{area} moved from {_join(gone_names)} to {_join(new_names)}"
            elif new:
                title = f"{_join(new_names)} now {'own' if len(new) > 1 else 'owns'} {area}"
            else:
                title = f"{_join(gone_names)} no longer {'own' if len(gone) > 1 else 'owns'} {area}"
            out.append({
                "kind": "ownership",
                "date": day,
                "title": title,
                "area": subject.removeprefix("area:"),
                "entities": [subject, *new, *gone],
                "fact_ids": [*(d["started"][v] for v in new), *(d["ended"][v] for v in gone)],
                "sources": [s for s in [d["source"]] if s],
            })
    return out


def _decisions(graph, since: str) -> list[dict]:
    rows = graph.query(DECISIONS, {"since": since}).result_set
    if not rows:
        return []
    areas: dict[str, list[str]] = {}
    for did, slug in graph.query(DECISION_AREAS).result_set:
        areas.setdefault(did, []).append(slug)
    ids = [r[0] for r in rows]
    replaced: dict[str, tuple[str, str]] = {}
    for a, _, b, b_title, _ in graph.query(REPLACEMENTS, {"ids": ids}).result_set:
        replaced.setdefault(a, (b, b_title))
    out = []
    for did, title, status, proposed, decided, replaced_at, *doc in rows:
        source = _source(doc[0], doc[1], doc[2], "rfc", doc[3])
        base = {"kind": "decision", "decision_id": did, "areas": areas.get(did, []),
                "entities": [f"area:{a}" for a in areas.get(did, [])], "sources": [source] if source else []}
        subject = f"decision:{did}"
        if decided and decided > since:
            out.append({**base, "date": decided, "title": f"Accepted: {title}", "fact_ids": [f"{subject}:accepted"]})
        elif status == "proposed" and proposed and proposed > since:
            out.append({**base, "date": proposed, "title": f"Proposed: {title}", "fact_ids": [f"{subject}:proposed"]})
        if replaced_at and replaced_at > since and did in replaced:
            out.append({**base, "date": replaced_at, "title": f"{title} was replaced by {replaced[did][1]}",
                        "replaced_by": replaced[did][0], "fact_ids": [f"{subject}:accepted", f"{subject}:replaced"]})
    return out


def _pages(graph, since: str) -> list[dict]:
    docs: dict[str, dict] = {}
    for doc_id, title, url, kind, updated, fid, subject, value, vt, removed in graph.query(PAGES, {"since": since}).result_set:
        d = docs.setdefault(doc_id, {"source": _source(doc_id, title, url, kind, updated), "facts": {}, "removed": 0, "date": vt,
                                     "entities": set()})
        d["facts"][fid] = vt
        d["removed"] += 1 if removed else 0
        d["date"] = max(d["date"], vt)
        d["entities"].update(e for e in (subject, value) if e)
    out = []
    for doc_id, d in docs.items():
        n = len(d["facts"])
        what = f"{n} fact{'s' if n != 1 else ''} no longer stated" if d["removed"] else f"{n} fact{'s' if n != 1 else ''} replaced"
        out.append({
            "kind": "page",
            "date": d["date"],
            "title": f"{d['source']['title']}: {what}",
            "entities": sorted(d["entities"]),
            "fact_ids": sorted(d["facts"], key=lambda f: d["facts"][f])[:6],
            "sources": [d["source"]],
        })
    return out


def _stale(graph, since: str, names: dict[str, str]) -> list[dict]:
    docs: dict[str, dict] = {}
    for row in graph.query(STALE, {"since": since}).result_set:
        doc_id, title, url, kind, updated, fid, subject, value, vf, hid, hvalue, hvf, *hdoc = row
        d = docs.setdefault(doc_id, {"source": _source(doc_id, title, url, kind, updated), "pairs": [], "date": "", "entities": set(),
                                     "newer": {}})
        d["pairs"].append((fid, hid, subject, value, hvalue))
        d["date"] = max(d["date"], vf or "", hvf or "")
        d["entities"].update(e for e in (subject, value, hvalue) if e)
        newer = _source(*hdoc)
        if newer:
            d["newer"][newer["doc_id"]] = newer
    out = []
    for d in docs.values():
        fid, hid, subject, value, hvalue = d["pairs"][0]
        claim = f"says {_label(value, names)}, the {('ownership map' if str(subject).startswith('area:') else 'newer source')} says {_label(hvalue, names)}"
        out.append({
            "kind": "stale",
            "date": d["date"],
            "title": f"{d['source']['title']} is out of date",
            "detail": f"About {_label(subject, names)}: it {claim}.",
            "entities": sorted(d["entities"]),
            "fact_ids": [x for f, h, *_ in d["pairs"][:3] for x in (f, h)],
            "sources": [d["source"], *d["newer"].values()],
        })
    return out


def _disputes(graph, since: str, names: dict[str, str]) -> list[dict]:
    out = []
    for row in graph.query(DISPUTES, {"since": since}).result_set:
        aid, subject, atext, avf, bid, btext, bvf, why, *docs = row
        sources = [s for s in (_source(*docs[:5]), _source(*docs[5:])) if s]
        out.append({
            "kind": "dispute",
            "date": max(avf or "", bvf or ""),
            "title": f"Two sources disagree on {_label(subject, names).lower()}",
            "detail": why or f"{atext} / {btext}",
            "entities": [subject],
            "fact_ids": [aid, bid],
            "sources": sources,
        })
    return out


def _scope(graph, since: str, area: str | None, team: str | None) -> set[str] | None:
    if not area and not team:
        return None
    keys: set[str] = set()
    if area:
        keys.add(f"area:{area}")
    if team:
        keys.add(f"team:{team}")
        keys |= {r[0] for r in graph.query(TEAM_AREAS, {"team": f"team:{team}", "since": since}).result_set}
    return keys


def changes(graph, since: str, *, area: str | None = None, team: str | None = None) -> dict:
    """Every change since `since` (an ISO date), newest first, optionally only those about an area or a team."""
    names = _names(graph)
    found = [*_ownership(graph, since, names), *_decisions(graph, since), *_pages(graph, since),
             *_stale(graph, since, names), *_disputes(graph, since, names)]
    scope = _scope(graph, since, area, team)
    if scope is not None:
        doc_areas: dict[str, set[str]] = {}
        doc_ids = list({s["doc_id"] for c in found for s in c["sources"]})
        for doc_id, slug in graph.query(DOC_AREAS, {"ids": doc_ids}).result_set:
            doc_areas.setdefault(doc_id, set()).add(f"area:{slug}")

        def inside(c: dict) -> bool:
            keys = set(c.get("entities", []))
            for s in c["sources"]:
                keys |= doc_areas.get(s["doc_id"], set())
            return bool(keys & scope)

        found = [c for c in found if inside(c)]
    found.sort(key=lambda c: (c["date"], KINDS.index(c["kind"]) * -1, c["title"]), reverse=True)
    for i, c in enumerate(found):
        c["id"] = f"{c['kind']}-{i}"
        c.setdefault("detail", "")
        c.pop("entities", None)
    counts = {k: sum(1 for c in found if c["kind"] == k) for k in KINDS}
    return {"since": since, "today": date.today().isoformat(), "area": area, "team": team, "counts": counts, "changes": found}


# ----- the brief -------------------------------------------------------------------------------------------------

MAX_FACTS = 30
PRIORITY = {"ownership": 0, "decision": 1, "stale": 2, "dispute": 3, "page": 4}

BRIEF_SYSTEM = """You write a short catch-up brief for someone who has been away. It says what changed at the company
since the date given, from the facts given and nothing else.

Write the brief as claims in reading order, one plain sentence each, each citing the ids of the facts that say it.

- Lead with what matters most: who owns what now, decisions made or replaced, pages that are now out of date, and
  places where sources disagree.
- When something changed, say what it was before and what it is now, and cite both the old fact and the new one.
- Group related changes into one sentence when the facts allow it, such as several areas moving to one team.
- Give dates the facts give, written as words ("September 15"). Never guess or use outside knowledge, and never
  cite a fact for something it does not say.
- Keep each sentence short: one change, or one group of like changes, in at most 30 words.
- At most six claims. No headings, lists or markdown. Do not use em or en dashes."""


def evidence_for(graph, change_list: list[dict]) -> Evidence:
    """The facts behind the changes, most important kinds first, labelled the way the drafter reads them."""
    ordered = sorted(change_list, key=lambda c: (PRIORITY[c["kind"]], c["date"]), reverse=False)
    ids: list[str] = []
    # Round-robin over kinds so one busy kind (ownership) cannot crowd the others out.
    queues = {k: [c for c in ordered if c["kind"] == k] for k in PRIORITY}
    while len(ids) < MAX_FACTS and any(queues.values()):
        for k in sorted(PRIORITY, key=PRIORITY.get):
            if queues[k] and len(ids) < MAX_FACTS:
                for fid in queues[k].pop(0)["fact_ids"]:
                    if fid not in ids:
                        ids.append(fid)
    found = read.facts(graph, ids)
    ends = read.chain_ends(graph, [i for i in ids if i in found and not found[i]["current"]])
    partners = read.conflicts(graph, [i for i in ids if i in found and found[i]["current"]])
    extra = [i for i in dict.fromkeys([*ends.values(), *(c for cs in partners.values() for c in cs)]) if i not in found]
    found.update(read.facts(graph, extra))
    ids += [i for i in extra if i not in ids]
    return Evidence(facts=[_shape(found[i], ends.get(i), partners.get(i)) for i in ids if i in found])


async def draft_brief(since: str, evidence: Evidence, *, model: JsonModel) -> list[Claim]:
    facts = "\n".join(_line(f) for f in evidence.facts)
    prompt = f"Facts:\n{facts}\n\nWhat changed since {since}? Today is {date.today().isoformat()}."
    out = await model.json(BRIEF_SYSTEM, prompt, SCHEMA)
    return [Claim(c["text"].strip(), list(c.get("fact_ids") or [])) for c in out.get("claims", []) if c.get("text", "").strip()]


async def brief(
    graph, since: str, *, area: str | None = None, team: str | None = None,
    model: JsonModel | None = None, entail: Entail | None = None,
) -> AsyncIterator[dict]:
    """The catch-up brief as Ask events: `evidence`, `claim`s, `verdict`s, `done`; or `empty` with nobody to ask."""
    found = await asyncio.to_thread(changes, graph, since, area=area, team=team)
    evidence = await asyncio.to_thread(evidence_for, graph, found["changes"])
    yield {"type": "evidence", "facts": len(evidence.facts), "documents": evidence.documents}
    claims = await draft_brief(since, evidence, model=model or answer_model()) if evidence.facts else []
    if not claims:
        yield {"type": "empty", "ask": []}
        return
    for i, claim in enumerate(claims):
        yield {"type": "claim", "index": i, "text": claim.text, "fact_ids": claim.fact_ids}
    entail = entail or make_entail(check_model())
    tasks = [asyncio.create_task(_checked(i, graph, c, entail)) for i, c in enumerate(claims)]
    counts = dict.fromkeys(VERDICTS, 0)
    try:
        for next_done in asyncio.as_completed(tasks):
            index, checked, ok = await next_done
            counts[checked.verdict] += 1
            event = checked.event(index)
            if not ok:
                event["error"] = "The check could not run for this sentence."
            yield event
    finally:
        for t in tasks:
            t.cancel()
    yield {"type": "done", "counts": counts}
