"""`python -m canon.bench questions` writes the question set; `python -m canon.bench run --name <run>` runs it.

The judge is `CANON_JUDGE_MODEL`, or the check model when that is not set.
"""

import argparse
import asyncio
import json
import os

from canon.bench import questions as qs
from canon.bench.run import run
from canon.config import settings
from canon.graph.db import connect, workspace_graph
from canon.llm import Claude, answer_model
from canon.sources.cache import REPO_ROOT

BENCH = REPO_ROOT / "bench"


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m canon.bench")
    sub = parser.add_subparsers(dest="command", required=True)
    q = sub.add_parser("questions", help="build the question set from the graph's dated records")
    q.add_argument("--workspace", default="posthog")
    r = sub.add_parser("run", help="answer every question with Canon and the baseline, and grade both")
    r.add_argument("--workspace", default="posthog")
    r.add_argument("--name", required=True)
    r.add_argument("--limit", type=int, default=None)
    r.add_argument("--concurrency", type=int, default=4)
    args = parser.parse_args()

    graph = workspace_graph(connect(), args.workspace)
    if args.command == "questions":
        built = qs.build(graph)
        qs.save(built, BENCH / "questions.json")
        counts: dict[str, int] = {}
        for item in built:
            counts[item["category"]] = counts.get(item["category"], 0) + 1
        print(f"{len(built)} questions:", ", ".join(f"{k} {v}" for k, v in sorted(counts.items())))
        return 0

    questions = qs.load(BENCH / "questions.json")[: args.limit]
    judge = Claude(os.environ.get("CANON_JUDGE_MODEL") or settings().check_model, effort="low", max_tokens=4000)
    summary = asyncio.run(
        run(graph, questions, BENCH / "results" / args.name, model=answer_model(), judge=judge, name=args.name, concurrency=args.concurrency)
    )
    print(json.dumps({k: v["all"] for k, v in summary.items() if k != "meta"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
