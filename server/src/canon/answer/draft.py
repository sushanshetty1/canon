"""Evidence to a draft answer: one claim per sentence, each citing the facts behind it.

The drafter writes; it does not decide. Whether a fact is current or disputed comes labelled from the graph, and
every claim it returns is checked again before anyone sees it.
"""

from canon.answer.retrieve import Evidence
from canon.llm import JsonModel
from canon.verify.check import Claim

SYSTEM = """You answer questions about a company from the facts given, and nothing else.

Write the answer as a short list of claims, in reading order, one plain sentence each. Each claim cites the ids
of the facts that say it.

- Cite only ids from the list. Never cite a fact for something it does not say.
- Answer from current facts. Mention a replaced or out-of-date fact only to say what changed, and then cite both
  the old fact and the current one.
- When current facts are marked as disputed, say that the sources disagree and cite both sides.
- If the facts do not answer the question, return no claims. Never guess or use outside knowledge.
- At most six claims. No headings, lists or markdown. Do not use em or en dashes."""

SCHEMA = {
    "type": "object",
    "properties": {
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"text": {"type": "string"}, "fact_ids": {"type": "array", "items": {"type": "string"}}},
                "required": ["text", "fact_ids"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["claims"],
    "additionalProperties": False,
}


def _line(f: dict) -> str:
    if f["current"] and f["disputed_with"]:
        status = f"current, disputed by {', '.join(f['disputed_with'])}"
    elif f["current"]:
        status = "current"
    elif f["stale"]:
        status = f"out of date: a more authoritative source says otherwise, see {f['replaced_by']}"
    elif f["replaced_by"]:
        status = f"replaced by {f['replaced_by']}"
    else:
        status = f"no longer stated (ended {f['valid_to']})"
    held = f"{f['valid_from']} to {f['valid_to']}" if f["valid_to"] else f"since {f['valid_from']}"
    s = f["source"]
    return f"[{f['id']}] ({status}; held {held}; {s['kind']} \"{s['title']}\", {s['date']}) {f['text']}"


def prompt(question: str, evidence: Evidence) -> str:
    facts = "\n".join(_line(f) for f in evidence.facts)
    return f"Facts:\n{facts}\n\nQuestion: {question}"


async def draft(question: str, evidence: Evidence, *, model: JsonModel) -> list[Claim]:
    out = await model.json(SYSTEM, prompt(question, evidence), SCHEMA)
    return [Claim(c["text"].strip(), list(c.get("fact_ids") or [])) for c in out.get("claims", []) if c.get("text", "").strip()]
