"""Drafts the correction for each open fix: the stale sentence, rewritten from the fact that holds now.

For each passage with open, undrafted fixes, one model call copies the sentence that states each stale fact
(`old`, verbatim) and rewrites only that sentence (`new`). Two stale facts in one sentence get one edit, and their
fixes merge into one. The rewrite is then put through the claim check (`canon.verify.check`) citing the evidence
fact, plus the passage's own current facts for any words it keeps; it must come back verified. If it does not, the
model gets one stricter try that may state only the evidence fact, checked against the evidence alone. A draft that
still fails is rejected: the fix keeps its `old` line, gets `draft_error`, and has no `new` to file.

The model only writes text. Which facts are stale, what replaced them and whether the rewrite says so are the
graph's and the check's.
"""

import asyncio
import re
from datetime import UTC, datetime

from canon.fixes.queue import reroute
from canon.graph import read
from canon.llm import JsonModel
from canon.verify.check import Claim, Entail, check

OPEN = """
MATCH (x:Fix {status: 'open'})-[:ABOUT]->(f:Fact)
WHERE x.new IS NULL AND ($retry OR x.draft_error IS NULL)
MATCH (x)-[:EVIDENCE]->(e:Fact)
RETURN x.id, f.id, e.id, coalesce(x.passage_id, '')
"""
PASSAGE_FACTS = """
MATCH (f:Fact)-[:STATED_IN]->(:Passage {id: $pid})
WHERE f.valid_to IS NULL AND NOT (f)-[:SUPERSEDED_BY]->() AND NOT (f)-[:CONTRADICTS]-()
RETURN f.id ORDER BY f.id
"""

SYSTEM = """You correct out-of-date lines on a company's documentation page.

You get one passage of the page, the facts it states that are now out of date, and for each the fact that holds
now, from a more authoritative source. For each out-of-date fact:

- `old`: copy the one sentence of the passage that states it, exactly as written, character for character,
  including any Markdown links. A sentence, not the whole passage and not a heading.
- `new`: rewrite only that sentence so it states what holds now. Change as few words as you can and keep the
  rest of the sentence and its Markdown, but drop any part that the change makes untrue. Add no name, date, role
  or reason that the passage or the current fact does not give.

When several out-of-date facts are stated in one sentence, return one edit for that sentence that lists all of
them and corrects all of them. Plain sentences only: no em or en dashes."""

STRICT = """You correct one out-of-date sentence on a company's documentation page.

Rewrite the sentence so it says only what the current facts say, in the sentence's own style. Keep nothing from
the old sentence that the current facts do not state. One sentence, no em or en dashes."""

SCHEMA = {
    "type": "object",
    "properties": {
        "edits": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "facts": {"type": "array", "items": {"type": "integer"}},
                    "old": {"type": "string"},
                    "new": {"type": "string"},
                },
                "required": ["facts", "old", "new"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["edits"],
    "additionalProperties": False,
}
STRICT_SCHEMA = {
    "type": "object",
    "properties": {"new": {"type": "string"}},
    "required": ["new"],
    "additionalProperties": False,
}


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def locate(passage: str, old: str) -> str | None:
    """The passage's own text for `old`: exact, or the same words with different spacing. None if it is not there."""
    old = (old or "").strip()
    if not old:
        return None
    if old in passage:
        return old
    words = old.split()
    pattern = r"\s+".join(re.escape(w) for w in words)
    m = re.search(pattern, passage)
    return m.group(0) if m else None


def _clean(text: str) -> str:
    return " ".join((text or "").replace("—", ", ").replace("–", "-").split())


def _source(f: dict) -> str:
    return f"{f['title']}, {f['date']}" if f.get("date") else f.get("title") or "a source"


def prompt(title: str, passage: str, stale: list[dict], evidence: dict[str, list[dict]]) -> str:
    lines = [f"Page: {title}", "", "Passage:", passage, "", "Out of date:"]
    for i, f in enumerate(stale):
        now = "; ".join(f"{e['fact']} ({_source(e)})" for e in evidence[f["fact_id"]])
        lines.append(f"{i}. The passage says: {f['fact']}  Holds now: {now}")
    return "\n".join(lines)


async def _verified(graph, text: str, ids: list[str], entail: Entail) -> bool:
    checked = await check(graph, Claim(text, ids), entail=entail)
    return checked.verdict == "verified"


async def _draft_passage(graph, group: list[tuple[str, str, list[str]]], model: JsonModel, entail: Entail) -> dict:
    """`group`: (fix id, stale fact id, evidence ids) for one passage. Writes drafts; returns counts."""
    stale_ids = [f for _, f, _ in group]
    ev_ids = [e for _, _, es in group for e in es]
    facts = read.facts(graph, stale_ids + ev_ids)
    stale = [facts[f] for f in stale_ids if f in facts]
    if not stale:
        return {"drafted": 0, "rejected": 0, "merged": 0}
    passage = stale[0]["passage"] or ""
    evidence = {f: [facts[e] for e in es if e in facts] for _, f, es in group}
    fix_of = {f: x for x, f, _ in group}
    own = [r[0] for r in graph.query(PASSAGE_FACTS, {"pid": stale[0]["passage_id"]}).result_set]

    out = await model.json(SYSTEM, prompt(stale[0]["title"] or "", passage, stale, evidence), SCHEMA)
    counts = {"drafted": 0, "rejected": 0, "merged": 0}
    done: set[str] = set()
    for edit in out.get("edits", []):
        members = [stale[i]["fact_id"] for i in dict.fromkeys(edit.get("facts") or []) if 0 <= i < len(stale)]
        members = [f for f in members if f not in done]
        old = locate(passage, edit.get("old", ""))
        if not members or not old:
            continue
        done.update(members)
        primary = fix_of[members[0]]
        ev = list(dict.fromkeys(e["fact_id"] for f in members for e in evidence[f]))
        new = _clean(edit.get("new", ""))
        ok = bool(new) and new != _clean(old) and await _verified(graph, new, ev + own, entail)
        if not ok:
            now_lines = "\n".join(f"- {facts[e]['fact']}" for e in ev)
            strict = await model.json(STRICT, f"Old sentence: {old}\n\nCurrent facts:\n{now_lines}", STRICT_SCHEMA)
            new = _clean(strict.get("new", ""))
            ok = bool(new) and await _verified(graph, new, ev, entail)
        # Merge the other fixes on this sentence into the first.
        for f in members[1:]:
            other = fix_of[f]
            ids = {"primary": primary, "other": other}
            for rel in ("ABOUT", "EVIDENCE"):
                graph.query(f"MATCH (x:Fix {{id: $primary}}), (:Fix {{id: $other}})-[:{rel}]->(f:Fact) MERGE (x)-[:{rel}]->(f)", ids)
            graph.query("MATCH (o:Fix {id: $other}) DETACH DELETE o", ids)
            counts["merged"] += 1
        graph.query(
            """MATCH (x:Fix {id: $id}) SET x.old = $old, x.new = $new, x.checked = $checked, x.draft_error = $error,
               x.drafted_at = $now, x.updated_at = $now""",
            {
                "id": primary,
                "old": old,
                "new": new if ok else None,
                "checked": ev if ok else None,
                "error": None if ok else "The rewrite did not pass the check against the newer fact.",
                "now": _now(),
            },
        )
        if len(members) > 1:
            reroute(graph, primary)
        counts["drafted" if ok else "rejected"] += 1

    for _, f, _ in group:
        if f not in done:
            graph.query(
                "MATCH (x:Fix {id: $id}) SET x.draft_error = $error, x.updated_at = $now",
                {"id": fix_of[f], "error": "The line that states this fact was not found in the passage.", "now": _now()},
            )
            counts["rejected"] += 1
    return counts


async def draft(graph, *, model: JsonModel, entail: Entail, concurrency: int = 4, retry: bool = False) -> dict[str, int]:
    """Drafts every open fix without a correction. With `retry`, also those whose last draft was rejected."""
    groups: dict[str, dict[tuple[str, str], list[str]]] = {}
    for xid, fid, eid, pid in graph.query(OPEN, {"retry": retry}).result_set:
        groups.setdefault(pid, {}).setdefault((xid, fid), []).append(eid)
    semaphore = asyncio.Semaphore(concurrency)

    async def one(rows: dict):
        async with semaphore:
            group = sorted((x, f, sorted(es)) for (x, f), es in rows.items())
            return await _draft_passage(graph, group, model, entail)

    results = await asyncio.gather(*(one(rows) for _, rows in sorted(groups.items())), return_exceptions=True)
    total = {"passages": len(groups), "drafted": 0, "rejected": 0, "merged": 0, "failed": 0}
    for r in results:
        if isinstance(r, BaseException):
            total["failed"] += 1
        else:
            for k, v in r.items():
                total[k] += v
    return total
