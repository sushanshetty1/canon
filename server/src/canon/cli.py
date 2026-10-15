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

    fixes = sub.add_parser("fixes", help="build the fix queue for a workspace and draft its corrections")
    fixes.add_argument("workspace")
    fixes.add_argument("--no-draft", action="store_true", help="build and route only, call no model")
    fixes.add_argument("--retry", action="store_true", help="draft again the fixes whose last draft was rejected")
    people = sub.add_parser("people", help="recompute who knows each area and its bus factor")
    people.add_argument("workspace")
    decisions = sub.add_parser("decisions", help="build decisions from the cached RFCs and pull requests")
    decisions.add_argument("workspace")
    decisions.add_argument("--no-model", action="store_true", help="find replacements by reference only, call no model")
    decisions.add_argument("--offline", action="store_true", help="use only cached pull requests, search GitHub for none")

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
    if args.command == "fixes":
        from canon.graph.db import connect, workspace_graph, workspace_graph_name

        db = connect()
        if workspace_graph_name(args.workspace) not in db.list_graphs():
            print(f"No workspace {args.workspace}.")
            return 1
        return run_fixes(workspace_graph(db, args.workspace), draft=not args.no_draft, retry=args.retry)
    if args.command == "seed":
        from canon.demo_seed import seed as seed_graph
        from canon.graph.db import connect, workspace_graph, workspace_graph_name

        db = connect()
        if args.reset and workspace_graph_name(args.workspace) in db.list_graphs():
            workspace_graph(db, args.workspace).delete()
        counts = seed_graph(workspace_graph(db, args.workspace))
        print(f"Seeded workspace {args.workspace}: " + ", ".join(f"{k} {v}" for k, v in counts.items()))
        return 0
    if args.command == "people":
        return people_command(args.workspace)
    if args.command == "decisions":
        from canon.graph.db import connect, workspace_graph, workspace_graph_name

        db = connect()
        if workspace_graph_name(args.workspace) not in db.list_graphs():
            print(f"No workspace {args.workspace}.")
            return 1
        print(build_decisions(workspace_graph(db, args.workspace), model=not args.no_model, offline=args.offline))
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
            f"cache write {usage.cache_write_tokens}; about ${usage.cost_usd(settings().extract_model):.2f}"
        )
        if usage.stopped:
            print(f"The model stopped answering ({usage.stopped}); {usage.skipped} passages were not sent. "
                  "Run again later: cached passages cost nothing.")
        if usage.dropped:
            print("Dropped by validation:", ", ".join(f"{k} {n}" for k, n in sorted(usage.dropped.items())))

    from canon.llm import check_model
    from canon.verify.conflicts import judge
    from canon.verify.supersede import link

    print("Linked:", ", ".join(f"{k} {v}" for k, v in link(graph).items()))
    if not args.skip_extract:
        # Which current process and policy statements conflict is a question of meaning: a model reads each topic.
        print("Judged:", ", ".join(f"{k} {v}" for k, v in asyncio.run(judge(graph, check_model())).items()))
    print(build_decisions(graph, model=not args.skip_extract, offline=False))
    _print_people(graph)
    # The pages that now say something out of date become the fix queue.
    run_fixes(graph, draft=not args.skip_extract, show=False)
    return 0


def render_fix(fix: dict) -> str:
    owner = ", ".join(f"{r['name']} ({r['role']})" for r in fix["routed"]) or "nobody"
    lines = [f"{fix['page']['title']}  {fix['page']['url']}"]
    if fix["old"]:
        lines.append(_wrap(f"Old: {fix['old']}", 2))
    lines.append(_wrap(f"New: {fix['new']}" if fix["new"] else f"No draft: {fix['draft_error'] or 'not drafted yet'}", 2))
    lines.append(_wrap(f"To: {owner}. {fix['reason'] or ''}".rstrip(), 2))
    return "\n".join(lines)


def run_fixes(graph, *, draft: bool = True, retry: bool = False, show: bool = True) -> int:
    """Build the fix queue, then draft its corrections when a model key is set."""
    import asyncio

    from canon.config import settings
    from canon.fixes import build, list_fixes, totals
    from canon.fixes import draft as draft_fixes

    print("Fixes:", ", ".join(f"{k} {v}" for k, v in build(graph).items()))
    if draft and not settings().anthropic_api_key:
        print("Drafting needs ANTHROPIC_API_KEY; the fixes are built but not drafted.")
    elif draft:
        from canon.llm import answer_model, check_model
        from canon.verify.check import make_entail

        drafted = asyncio.run(draft_fixes(graph, model=answer_model(), entail=make_entail(check_model()), retry=retry))
        print("Drafted:", ", ".join(f"{k} {v}" for k, v in drafted.items()))
    print("Queue:", ", ".join(f"{k} {v}" for k, v in totals(graph).items()))
    if show:
        for fix in list_fixes(graph, ("open", "approved")):
            print()
            print(render_fix(fix))
    return 0


def _print_people(graph) -> None:
    from canon.people import recompute

    result = recompute(graph)
    print("Expertise:", ", ".join(f"{k} {v}" for k, v in result["expertise"].items()))
    print("Bus factor:", ", ".join(f"{k} {v}" for k, v in result["bus_factor"].items()))


def people_command(workspace: str) -> int:
    """Recompute expertise and bus factor for a workspace, then print the riskiest areas."""
    from canon.graph.db import connect, workspace_graph, workspace_graph_name
    from canon.people.bus_factor import org_view

    db = connect()
    if workspace_graph_name(workspace) not in db.list_graphs():
        print(f"No workspace {workspace}.")
        return 1
    graph = workspace_graph(db, workspace)
    _print_people(graph)
    risky = [a for a in org_view(graph) if a["bus_factor"]][:10]
    if risky:
        print("\nRiskiest areas:")
        for a in risky:
            owners = ", ".join(t["name"] for t in a["owners"]) or "no owner"
            people = ", ".join(p["handle"] for p in a["depends_on"])
            print(f"  {a['bus_factor']}  {a['name']} ({owners}): {people}")
    return 0


def build_decisions(graph, *, model: bool, offline: bool) -> str:
    """Decisions from the cached RFCs, the cached pull requests and the pull requests that link an RFC. Replacement
    candidates go to the check model unless `model` is off."""
    import json

    from canon.config import settings
    from canon.decisions.build import build, linked_pulls, rfc_proposals
    from canon.llm import check_model
    from canon.sources.cache import data_dir

    root = data_dir() / "raw" / "posthog"
    read = lambda name: json.loads((root / f"{name}.json").read_text()) if (root / f"{name}.json").exists() else []  # noqa: E731
    rfcs = read("rfcs")
    if not rfcs:
        return "Decisions: no cached RFCs."
    pulls = read("pulls")
    if offline:
        rfcs += read("rfc_proposals")
        pulls += read("rfc_pulls")
    else:
        # GitHub, once: RFC pull requests that never merged, and pull requests elsewhere that link an RFC.
        try:
            rfcs += rfc_proposals(root, {r["path"] for r in rfcs})
            pulls += linked_pulls(root, rfcs)
        except Exception as e:  # no network or no token: what is cached still counts
            print(f"Could not read RFC proposals or linking pull requests from GitHub ({type(e).__name__}).")
    judge = check_model() if model and settings().anthropic_api_key else None
    counts = build(graph, rfcs, pulls, model=judge)
    return "Decisions: " + ", ".join(f"{k} {v}" for k, v in counts.items())
