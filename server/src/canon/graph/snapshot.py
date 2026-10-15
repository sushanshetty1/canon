"""Graph snapshots: a workspace graph saved to a file and loaded on another FalkorDB, so a deployment starts with the
demo company already ingested and extracted (no fetching, no model calls at boot).

    python -m canon.graph.snapshot export posthog snapshots/posthog.graph
    python -m canon.graph.snapshot import posthog snapshots/posthog.graph [--replace]

A snapshot is the graph key's Redis `DUMP`, which FalkorDB serialises with its own module type.
"""

import argparse
import sys
from pathlib import Path

from canon.graph.db import connect, workspace_graph_name


def export(slug: str, path: Path) -> int:
    data = connect().connection.dump(workspace_graph_name(slug))
    if data is None:
        raise SystemExit(f"No graph for workspace {slug}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return len(data)


def load(slug: str, path: Path, *, replace: bool = False) -> bool:
    """Loads the snapshot. Without `replace`, a graph that already exists is left as it is. True when loaded."""
    db = connect()
    key = workspace_graph_name(slug)
    if db.connection.exists(key) and not replace:
        return False
    db.connection.restore(key, 0, path.read_bytes(), replace=True)
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m canon.graph.snapshot")
    parser.add_argument("action", choices=["export", "import"])
    parser.add_argument("workspace")
    parser.add_argument("path", type=Path)
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args(argv)
    if args.action == "export":
        print(f"Saved {args.workspace}: {export(args.workspace, args.path)} bytes")
    else:
        loaded = load(args.workspace, args.path, replace=args.replace)
        print(f"{'Loaded' if loaded else 'Kept the existing'} {args.workspace}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
