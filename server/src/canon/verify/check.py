"""The check: every claim of an answer against the graph, before anyone sees it.

Verdicts, in order:

1. The claim cites no fact, or none of its fact ids exist: `unsupported`.
2. The entailment check finds the claim says more than its facts: `unsupported`.
3. A cited fact is no longer current (replaced, a stale restatement, or closed): `stale`, with `newer` holding the
   end of its `SUPERSEDED_BY` chain. Two kinds of sentence about replaced facts are history, not stale claims:
   a replaced fact cited together with a current fact that says what replaced it ("Notebooks moved from Product
   analytics to Data tools"), and a sentence the entailment check reads as placing its facts in the past, with
   the dates the graph gives them ("Platform Features owned notebooks until June"). Both are verified.
4. A cited fact has a current `CONTRADICTS` partner: `disputed`, with `conflicting` holding the partner.
5. Otherwise: `verified`.

Rules 1, 3, 4 and 5 are graph queries (`check_graph`). Only rule 2 asks a model: whether the sentence says what the
facts say, and whether it speaks about the past or the present. The model is told what the graph found (a fact's dates, that it was replaced or is out of date,
that sources disagree) so a sentence reporting that can pass; it never decides any of it.
"""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from canon.graph import read
from canon.llm import JsonModel
from canon.types import Verdict

# Whether the sentence says what its facts say, and optionally whether it speaks about the past:
# `True`/`False`, or `{"supported": bool, "past": bool}`.
Entail = Callable[[str, list[str]], Awaitable[bool | dict]]


@dataclass
class Claim:
    text: str
    fact_ids: list[str] = field(default_factory=list)


@dataclass
class Checked:
    claim: Claim
    verdict: Verdict
    sources: list[dict] = field(default_factory=list)
    newer: list[dict] = field(default_factory=list)
    conflicting: list[dict] = field(default_factory=list)

    def event(self, index: int) -> dict:
        return {
            "type": "verdict",
            "index": index,
            "verdict": self.verdict,
            "sources": self.sources,
            "newer": self.newer,
            "conflicting": self.conflicting,
        }


def _key(f: dict) -> tuple:
    return f["subject"], f["predicate"], " ".join(str(f["value"] or "").lower().split())


def check_graph(graph, claim: Claim) -> Checked:
    found = read.facts(graph, claim.fact_ids)
    if not found:
        return Checked(claim, "unsupported")
    sources = [found[i] for i in dict.fromkeys(claim.fact_ids) if i in found]

    replaced = [f for f in sources if not f["current"]]
    if replaced:
        ends = read.chain_ends(graph, [f["fact_id"] for f in replaced])
        end_facts = read.facts(graph, ends.values())
        cited_now = {_key(f) for f in sources if f["current"]}

        def history(f: dict) -> bool:  # cited next to a current fact saying what replaced it
            end = end_facts.get(ends.get(f["fact_id"]))
            return end is not None and _key(end) in cited_now

        out_of_date = [f for f in replaced if not history(f)]
        if out_of_date:
            newer = [end_facts[e] for e in dict.fromkeys(ends.get(f["fact_id"]) for f in out_of_date) if e in end_facts]
            return Checked(claim, "stale", sources, newer=newer)

    partners = read.conflicts(graph, [f["fact_id"] for f in sources if f["current"]])
    if partners:
        ids = list(dict.fromkeys(c for cs in partners.values() for c in cs))
        conflicting = read.facts(graph, ids)
        return Checked(claim, "disputed", sources, conflicting=[conflicting[i] for i in ids if i in conflicting])
    return Checked(claim, "verified", sources)


def statement(f: dict) -> str:
    """A fact as the entailment check reads it: the sentence, with the dates it held and where it is written."""
    held = f"from {f['valid_from']} to {f['valid_to']}" if f["valid_to"] else f"from {f['valid_from']}"
    if f["stale"]:
        held += "; this page is out of date: a more authoritative source said otherwise first"
    elif f["superseded_by"]:
        held += "; later replaced by a newer source"
    return f"{f['fact']} (held {held}; source: {f['kind']} {f['title']}, {f['date']})"


async def check(graph, claim: Claim, *, entail: Entail) -> Checked:
    checked = await asyncio.to_thread(check_graph, graph, claim)
    if checked.verdict == "unsupported":
        return checked
    facts = [statement(f) for f in checked.sources]
    if checked.conflicting:  # the dispute is the graph's finding, so a sentence may report it
        facts += [statement(c) for c in checked.conflicting]
        facts.append("The graph records that these current sources disagree.")
    found = await entail(claim.text, facts)
    supported, past = (found.get("supported"), found.get("past")) if isinstance(found, dict) else (found, False)
    if not supported:
        return Checked(claim, "unsupported", checked.sources)
    if checked.verdict == "stale" and past and not any(f["stale"] for f in checked.sources):
        # A true sentence about how things were. A page that was already wrong when written is still out of date.
        return Checked(claim, "verified", checked.sources, newer=checked.newer)
    return checked


ENTAIL_SYSTEM = """You check one sentence against the facts given for it.

Answer supported = true only when everything the sentence states is stated by the facts, read with their dates.
Different wording is fine. The sentence is not supported if it adds a name, number, date, reason, comparison or
claim that the facts do not give, or if it says something changed when the facts do not show both the before and
the after. Judge only what the facts say, not whether they are still true.

Answer past = true when the sentence describes how things were at an earlier time, and makes that time clear (a
date, "previously", "until", "used to", "was"), rather than how things are now."""

ENTAIL_SCHEMA = {
    "type": "object",
    "properties": {"supported": {"type": "boolean"}, "past": {"type": "boolean"}},
    "required": ["supported", "past"],
    "additionalProperties": False,
}


def make_entail(model: JsonModel) -> Entail:
    async def entail(text: str, facts: list[str]) -> dict:
        listed = "\n".join(f"- {f}" for f in facts)
        out = await model.json(ENTAIL_SYSTEM, f"Facts:\n{listed}\n\nSentence: {text}", ENTAIL_SCHEMA)
        return {"supported": bool(out.get("supported")), "past": bool(out.get("past"))}

    return entail
