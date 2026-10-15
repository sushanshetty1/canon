"""The baselines: the standard pipeline most company-brain tools run. Give passages to the same model and ask for an
answer with a citation after each sentence.

- **same evidence** (the main comparison): the baseline gets exactly the passages behind the facts Canon retrieved,
  in Canon's order, with each document's title and date. That includes the passages Canon only found by following
  `SUPERSEDED_BY` to the current fact, which is generous to the baseline. The only thing it lacks is the graph's
  account of time and the check.
- **search**: plain full-text search over every passage, top 8, as a search-and-summarise product would do.
"""

import asyncio

from canon.answer.retrieve import retrieve, search_terms
from canon.llm import JsonModel

SEARCH = """
CALL db.idx.fulltext.queryNodes('Passage', $q) YIELD node, score
MATCH (d:Document)-[:HAS]->(node)
RETURN node.id, node.text, d.title, d.url, coalesce(d.updated_at, ''), score ORDER BY score DESC LIMIT $k
"""

SYSTEM = """You answer questions about a company using only the passages given. Write a short answer, one claim per
sentence, and cite the passages each sentence relies on by number. If the passages do not answer the question, return
no sentences."""

SCHEMA = {
    "type": "object",
    "properties": {
        "sentences": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"text": {"type": "string"}, "cites": {"type": "array", "items": {"type": "integer"}}},
                "required": ["text", "cites"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["sentences"],
    "additionalProperties": False,
}


def search(graph, question: str, k: int = 8) -> list[dict]:
    terms = search_terms(question)
    if not terms:
        return []
    rows = graph.query(SEARCH, {"q": "|".join(terms), "k": k}).result_set
    return [{"id": i, "text": t, "title": ti, "url": u, "date": d} for i, t, ti, u, d, _ in rows]


def same_evidence(graph, question: str, k: int = 16) -> list[dict]:
    seen: dict[str, dict] = {}
    for f in retrieve(graph, question).facts:
        src = f["source"]
        if src.get("passage") and src["passage"] not in seen and len(seen) < k:
            seen[src["passage"]] = {"id": src["doc_id"], "text": src["passage"], "title": src["title"], "url": src["url"], "date": src.get("date") or ""}
    return list(seen.values())


async def answer(graph, question: str, *, model: JsonModel, mode: str = "same", k: int = 8) -> dict:
    passages = await asyncio.to_thread(same_evidence, graph, question) if mode == "same" else await asyncio.to_thread(search, graph, question, k)
    if not passages:
        return {"sentences": [], "passages": []}
    listed = "\n\n".join(f"[{n}] {p['title']} ({p['date'][:10]})\n{p['text']}" for n, p in enumerate(passages, 1))
    out = await model.json(SYSTEM, f"Passages:\n\n{listed}\n\nQuestion: {question}", SCHEMA)
    sentences = []
    for s in out.get("sentences", []):
        cited = [passages[n - 1] for n in s.get("cites", []) if 1 <= n <= len(passages)]
        sentences.append({"text": s.get("text", ""), "sources": [f"{p['title']} ({p['date'][:10]}): {p['text']}" for p in cited]})
    return {"sentences": sentences, "passages": passages}
