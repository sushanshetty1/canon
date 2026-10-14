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

    ask = sub.add_parser("ask", help="ask a question and print each claim with its verdict")
    ask.add_argument("question")
    ask.add_argument("--workspace", default="posthog")

    seed = sub.add_parser("seed", help="load the small Kestrel demo company into a workspace")
    seed.add_argument("workspace")
    seed.add_argument("--reset", action="store_true", help="delete the workspace graph first")

    args = parser.parse_args(argv)
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
