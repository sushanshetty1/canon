"""Runs the question set through Canon and the baseline with the same model, grades both, and writes the results.

What a reader is shown is what gets graded:
- Canon: its verified and disputed sentences, and for an out-of-date sentence the current fact it shows in its
  place. Sentences it removed as unsupported are not shown, so they are not graded.
- Baseline: every sentence it writes.

Results go to `bench/results/<name>/`: `answers.jsonl` (every question, both answers, every grade), `summary.json`,
and `report.md`.
"""

import asyncio
import json
import time
from pathlib import Path

from canon.answer.ask import ask
from canon.bench import baseline
from canon.bench.grade import grade_answer, support
from canon.config import settings
from canon.llm import JsonModel


async def canon_answer(graph, question: str) -> dict:
    claims: dict[int, str] = {}
    shown: list[dict] = []
    counts = {}
    async for e in ask(graph, question):
        if e["type"] == "claim":
            claims[e["index"]] = e["text"]
        elif e["type"] == "verdict":
            # Each cited passage with its document's title and date, as the baseline's citations are given.
            src = lambda fs: [f"{f['title']} ({(f.get('date') or '')[:10]}): {f['passage']}" for f in fs if f.get("passage")]  # noqa: E731
            if e["verdict"] in ("verified", "disputed"):
                sources = src(e["sources"]) + src(e.get("conflicting", []))
                shown.append({"index": e["index"], "text": claims[e["index"]], "sources": sources, "verdict": e["verdict"]})
            elif e["verdict"] == "stale":
                for n in e["newer"]:  # Canon shows the current fact in place of the out-of-date sentence
                    shown.append({"index": e["index"], "text": n["fact"], "sources": src([n]), "verdict": "replaced"})
        elif e["type"] == "done":
            counts = e["counts"]
    shown.sort(key=lambda s: s["index"])
    return {"sentences": shown, "counts": counts, "drafted": len(claims)}


async def run_one(graph, q: dict, *, model: JsonModel, judge: JsonModel, semaphore) -> dict:
    async with semaphore:
        t0 = time.monotonic()
        mine = await canon_answer(graph, q["question"])
        t1 = time.monotonic()
        theirs = await baseline.answer(graph, q["question"], model=model, mode="same")
        t2 = time.monotonic()
        searched = await baseline.answer(graph, q["question"], model=model, mode="search")
        t3 = time.monotonic()
        out = {"question": q}
        for name, ans, secs in (("canon", mine, t1 - t0), ("baseline", theirs, t2 - t1), ("search", searched, t3 - t2)):
            text = " ".join(s["text"] for s in ans["sentences"])
            grade = await grade_answer(q, text, judge)
            grade["supported"] = await support(ans["sentences"], judge)
            out[name] = {"text": text, "sentences": ans["sentences"], "grade": grade, "seconds": round(secs, 1)}
            if name == "canon":
                out[name]["counts"], out[name]["drafted"] = ans["counts"], ans["drafted"]
        return out


SYSTEMS = ("canon", "baseline", "search")
LABELS = {"canon": "Canon", "baseline": "Same evidence, no graph", "search": "Search and summarise"}


def summarise(rows: list[dict]) -> dict:
    def stats(name: str, subset: list[dict]) -> dict:
        n = len(subset) or 1
        grades = [r[name]["grade"] for r in subset]
        sentences = [ok for g in grades for ok in g["supported"]]
        return {
            "questions": len(subset),
            "correct": sum(g["correct"] for g in grades) / n,
            "stale_stated": sum(g["states_stale"] for g in grades) / n,
            "answered": sum(g["answered"] for g in grades) / n,
            "string_match": sum(g["string_match"] for g in grades) / n,
            "sentences": len(sentences),
            "citation_support": (sum(sentences) / len(sentences)) if sentences else None,
        }

    cats = sorted({r["question"]["category"] for r in rows})
    return {
        name: {"all": stats(name, rows), **{c: stats(name, [r for r in rows if r["question"]["category"] == c]) for c in cats}}
        for name in SYSTEMS
    }


def report(summary: dict, meta: dict) -> str:
    pct = lambda x: "n/a" if x is None else f"{round(100 * x)}%"  # noqa: E731
    lines = [
        f"# Canon against search-and-summarise ({meta['name']})",
        "",
        f"{meta['questions']} questions about PostHog, answered by every system with `{meta['answer_model']}`, graded by "
        f"`{meta['judge_model']}`. Run on {meta['date']}.",
        "",
        "| | " + " | ".join(LABELS[n] for n in SYSTEMS) + " |",
        "| --- |" + " --- |" * len(SYSTEMS),
    ]
    rows = [
        ("Correct answers", "correct"),
        ("Out-of-date answers stated as current", "stale_stated"),
        ("Sentences whose citation states them", "citation_support"),
        ("Answered at all", "answered"),
    ]
    for label, key in rows:
        lines.append(f"| {label} | " + " | ".join(pct(summary[n]["all"][key]) for n in SYSTEMS) + " |")
    lines += [
        "",
        "By category (correct / out of date stated as current):",
        "",
        "| Category | Questions | " + " | ".join(LABELS[n] for n in SYSTEMS) + " |",
        "| --- | --- |" + " --- |" * len(SYSTEMS),
    ]
    for cat, s in summary["canon"].items():
        if cat == "all":
            continue
        cells = " | ".join(f"{pct(summary[n][cat]['correct'])} / {pct(summary[n][cat]['stale_stated'])}" for n in SYSTEMS)
        lines.append(f"| {cat} | {s['questions']} | {cells} |")
    return "\n".join(lines) + "\n"


async def run(graph, questions: list[dict], out_dir: Path, *, model: JsonModel, judge: JsonModel, name: str, concurrency: int = 4) -> dict:
    semaphore = asyncio.Semaphore(concurrency)
    rows = await asyncio.gather(*(run_one(graph, q, model=model, judge=judge, semaphore=semaphore) for q in questions))
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "answers.jsonl").open("w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    s = settings()
    meta = {
        "name": name,
        "questions": len(questions),
        "answer_model": s.answer_model,
        "check_model": s.check_model,
        "judge_model": getattr(judge, "model", "?"),
        "date": time.strftime("%Y-%m-%d"),
    }
    summary = {"meta": meta, **summarise(rows)}
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    (out_dir / "report.md").write_text(report(summary, meta))
    return summary
