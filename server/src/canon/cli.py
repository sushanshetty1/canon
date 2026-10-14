"""The `canon` command."""

import argparse
import textwrap

LABELS = {"verified": "Verified", "stale": "Out of date", "disputed": "Disputed", "unsupported": "Unsupported"}
COUNTS = {"verified": "verified", "stale": "out of date", "disputed": "disputed", "unsupported": "unsupported"}


def _wrap(text: str, indent: int) -> str:
    pad = " " * indent
    return textwrap.fill(text, 100, initial_indent=pad, subsequent_indent=pad, break_long_words=False, break_on_hyphens=False)


def _where(s: dict) -> str:
    return f"{s['title']}, {s['date']}  {s['url']}"


def render(question: str, events: list[dict]) -> str:
    """Ask events as text: each claim with its verdict and where it comes from."""
    lines = [question, ""]
    claims = {e["index"]: e["text"] for e in events if e["type"] == "claim"}
    verdicts = {e["index"]: e for e in events if e["type"] == "verdict"}
    for e in events:
        if e["type"] == "evidence":
            lines += [f"Found {e['facts']} facts in {e['documents']} documents.", ""]
        elif e["type"] == "empty":
            lines.append("Canon found nothing written down that answers this.")
            for p in e["ask"]:
                lines.append(f"  Ask {p['name']} ({p['handle']}): {p['why']}")
        elif e["type"] == "error":
            lines.append(e["message"])
    for i, text in sorted(claims.items()):
        v = verdicts.get(i, {"verdict": "unsupported", "sources": [], "newer": [], "conflicting": []})
        label = LABELS[v["verdict"]]
        lines.append(f"  {label:<13}" + _wrap(text, 15).lstrip())
        if v["verdict"] == "unsupported":
            lines.append(_wrap("Nothing in the graph backs this, so it is left out of the answer.", 15))
        for s in v["sources"]:
            lines.append(_wrap(f"Source: {_where(s)}", 15))
        for n in v["newer"]:
            lines.append(_wrap(f"Now: {n['fact']} ({_where(n)})", 15))
        for c in v["conflicting"]:
            lines.append(_wrap(f"But: {c['fact']} ({_where(c)})", 15))
        lines.append("")
    done = next((e for e in events if e["type"] == "done"), None)
    if done:
        lines.append(", ".join(f"{n} {COUNTS[k]}" for k, n in done["counts"].items() if n) or "No claims.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="canon", description="Canon: the company brain that checks itself.")
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="run the API")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8790)

    schema = sub.add_parser("schema", help="create the indexes for a workspace graph")
    schema.add_argument("workspace")

    ingest = sub.add_parser("ingest", help="load a source into a workspace graph")
    ingest.add_argument("source", choices=["posthog"])
    ingest.add_argument("--workspace", default="posthog")
    ingest.add_argument("--skip-extract", action="store_true", help="write the connector's data, call no model")
    ingest.add_argument("--dry-run", action="store_true", help="fetch and count, write nothing, call no model")
    ingest.add_argument("--limit-extract", type=int, default=None, help="extract at most this many passages")
    ingest.add_argument("--concurrency", type=int, default=8)

    ask = sub.add_parser("ask", help="ask a question and print each claim with its verdict")
    ask.add_argument("question")
    ask.add_argument("--workspace", default="posthog")

    seed = sub.add_parser("seed", help="load the small Kestrel demo company into a workspace")
    seed.add_argument("workspace")
    seed.add_argument("--reset", action="store_true", help="delete the workspace graph first")

    args = parser.parse_args(argv)
    if args.command == "ingest":
        return ingest_posthog(args)
    if args.command == "serve":
        import uvicorn

        from canon.api.app import create_app

        uvicorn.run(create_app(), host=args.host, port=args.port)
        return 0
    if args.command == "schema":
        from canon.graph.db import connect, ensure_schema, workspace_graph

        ensure_schema(workspace_graph(connect(), args.workspace))
        print(f"Indexes ready for workspace {args.workspace}")
        return 0
    if args.command == "seed":
        from canon.demo_seed import seed as seed_graph
        from canon.graph.db import connect, workspace_graph, workspace_graph_name

        db = connect()
        if args.reset and workspace_graph_name(args.workspace) in db.list_graphs():
            workspace_graph(db, args.workspace).delete()
        counts = seed_graph(workspace_graph(db, args.workspace))
        print(f"Seeded workspace {args.workspace}: " + ", ".join(f"{k} {v}" for k, v in counts.items()))
        return 0
    if args.command == "ask":
        import asyncio

        from canon.answer.ask import ask as run
        from canon.config import settings
        from canon.graph.db import connect, workspace_graph, workspace_graph_name

        if not settings().anthropic_api_key:
            print("Answers need ANTHROPIC_API_KEY in the environment.")
            return 2
        db = connect()
        if workspace_graph_name(args.workspace) not in db.list_graphs():
            print(f"No workspace {args.workspace}. Load one with: canon seed {args.workspace}")
            return 1

        async def collect():
            return [e async for e in run(workspace_graph(db, args.workspace), args.question)]

        print(render(args.question, asyncio.run(collect())))
        return 0
    return 1


def ingest_posthog(args) -> int:
    """Connector, writer, extraction, writer, then the supersession linker when it is there."""
    import asyncio
    import importlib
    from collections import Counter

    from canon.config import settings
    from canon.extract.facts import Entities, Usage, extract, select_passages
    from canon.graph.db import connect, ensure_schema, workspace_graph
    from canon.graph.writer import write_batch, write_facts
    from canon.sources.cache import data_dir
    from canon.sources.posthog import load_posthog

    batch = load_posthog(data_dir() / "raw" / "posthog")
    kinds = Counter(d.kind for d in batch.docs)
    entities = Entities.from_batch(batch)
    worth = select_passages(batch, entities)
    chosen = worth[: args.limit_extract] if args.limit_extract is not None else worth
    current = sum(f.valid_to is None for f in batch.facts)
    print(f"Documents: {len(batch.docs)} ({', '.join(f'{k} {n}' for k, n in sorted(kinds.items()))})")
    print(f"Passages: {len(batch.passages)}, worth extracting: {len(worth)}, chosen: {len(chosen)}")
    print(f"People: {len(batch.people)}, teams: {len(batch.teams)}, areas: {len(batch.areas)}")
    print(f"Activity: {len(batch.activity)}, ownership facts: {len(batch.facts)} ({current} current)")
    if args.dry_run:
        return 0

    graph = workspace_graph(connect(), args.workspace)
    ensure_schema(graph)
    counts = write_batch(graph, batch)
    print("Written:", ", ".join(f"{k} {v}" for k, v in counts.items()))

    if not args.skip_extract:
        usage = Usage()
        facts = asyncio.run(
            extract(
                chosen,
                batch.docs,
                entities,
                model=settings().extract_model,
                concurrency=args.concurrency,
                cache_dir=data_dir() / "extract",
                usage=usage,
            )
        )
        write_facts(graph, facts)
        predicates = Counter(f.predicate for f in facts)
        print(f"Extracted facts: {len(facts)} ({', '.join(f'{k} {n}' for k, n in sorted(predicates.items()))})")
        print(
            f"Model calls: {usage.calls}, cached: {usage.cached}, failed: {usage.failed}; tokens in "
            f"{usage.input_tokens}, out {usage.output_tokens}, cache read {usage.cache_read_tokens}, "
            f"cache write {usage.cache_write_tokens}; about ${usage.cost_usd():.2f}"
        )
        if usage.dropped:
            print("Dropped by validation:", ", ".join(f"{k} {n}" for k, n in sorted(usage.dropped.items())))

    # The supersession linker is built alongside this; use it when it is there.
    try:
        supersede = importlib.import_module("canon.verify.supersede")
    except ImportError:
        print("Supersession linker not available: skipped")
    else:
        print("Linked:", ", ".join(f"{k} {v}" for k, v in supersede.link(graph).items()))
    return 0
