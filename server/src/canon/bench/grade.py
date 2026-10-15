"""Grading, the same for both systems, by a judge that is not part of either.

- **Correct**: the answer names a gold name as the answer (current owner, previous owner, lead).
- **Stale stated as fact**: the answer presents a name from `stale` as true now.
- **Answered**: the answer says anything at all.
- **Citation support**: for every sentence shown, does the text it cites state it? Judged sentence by sentence.

A plain string check runs beside the judge (does the answer contain a gold name) and is reported too, so the judge
can be audited.
"""

import asyncio
import re

from canon.llm import JsonModel

ANSWER_SYSTEM = """You grade an answer to a question about a company against the known right answer.

correct = true if the answer gives one of the right names as the answer to the question (spelling and casing may
differ; a team name with or without "team" counts).
states_stale = true if the answer presents any of the outdated names as true now (as the current owner, for
example). Mentioning an outdated name as history ("used to", "before", "previously") is not stating it as current.
answered = false only if the answer gives no answer at all."""

ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "why": {"type": "string"},
        "correct": {"type": "boolean"},
        "states_stale": {"type": "boolean"},
        "answered": {"type": "boolean"},
    },
    "required": ["why", "correct", "states_stale", "answered"],
    "additionalProperties": False,
}

SUPPORT_SYSTEM = """You check whether the cited text states a sentence. supported = true only if everything the
sentence claims is stated in the cited text. Different wording is fine; added names, dates or claims are not."""

SUPPORT_SCHEMA = {
    "type": "object",
    "properties": {"supported": {"type": "boolean"}},
    "required": ["supported"],
    "additionalProperties": False,
}


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def mentions(text: str, names: list[str]) -> bool:
    hay = f" {_norm(text)} "
    return any(f" {_norm(n)} " in hay for n in names if _norm(n))


async def grade_answer(q: dict, text: str, judge: JsonModel) -> dict:
    if not text.strip():
        return {"why": "No answer.", "correct": False, "states_stale": False, "answered": False, "string_match": False}
    prompt = (
        f"Question: {q['question']}\nRight answers: {', '.join(q['gold'])}\n"
        f"Outdated answers: {', '.join(q['stale']) or 'none'}\n\nAnswer:\n{text}"
    )
    out = await judge.json(ANSWER_SYSTEM, prompt, ANSWER_SCHEMA)
    out["string_match"] = mentions(text, q["gold"])
    return out


async def support(sentences: list[dict], judge: JsonModel) -> list[bool]:
    async def one(s: dict) -> bool:
        if not s["sources"]:
            return False
        cited = "\n---\n".join(s["sources"])
        out = await judge.json(SUPPORT_SYSTEM, f"Cited text:\n{cited}\n\nSentence: {s['text']}", SUPPORT_SCHEMA)
        return bool(out.get("supported"))

    return list(await asyncio.gather(*(one(s) for s in sentences)))
