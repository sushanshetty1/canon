"""The `canon` command."""

import argparse


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
