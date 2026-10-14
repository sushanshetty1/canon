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
    return 1
