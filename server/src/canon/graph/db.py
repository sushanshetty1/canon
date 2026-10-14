"""Connection, per-workspace graph names and the indexes every workspace graph needs.

Each workspace (one company) is its own FalkorDB graph, named `canon_<slug>`, so tenants never share nodes and
a workspace is deleted by deleting one graph. The accounts graph `canon_accounts` holds users and workspaces.
"""

import re

from falkordb import FalkorDB

from canon.config import settings

ACCOUNTS_GRAPH = "canon_accounts"
_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}$")

# Range indexes on every property nodes are looked up by.
INDEXES = [
    ("Person", "handle"),
    ("Team", "slug"),
    ("Area", "slug"),
    ("Document", "id"),
    ("Passage", "id"),
    ("Fact", "id"),
    ("Decision", "id"),
    ("Change", "sha"),
    ("Fix", "id"),
]


def connect(host: str | None = None, port: int | None = None) -> FalkorDB:
    s = settings()
    return FalkorDB(host=host or s.falkordb_host, port=port or s.falkordb_port)


def workspace_graph_name(slug: str) -> str:
    if not _SLUG.match(slug):
        raise ValueError(f"A workspace slug is lowercase letters, digits and dashes: {slug!r}")
    return f"canon_{slug}"


def workspace_graph(db: FalkorDB, slug: str):
    return db.select_graph(workspace_graph_name(slug))


def ensure_schema(graph) -> None:
    """Create the range and full-text indexes. Safe to run again: an index that already exists is left alone."""
    statements = [f"CREATE INDEX FOR (n:{label}) ON (n.{prop})" for label, prop in INDEXES]
    # Full-text search over passages: the first step of retrieval, before the graph takes over.
    statements.append("CREATE FULLTEXT INDEX FOR (n:Passage) ON (n.text)")
    for statement in statements:
        try:
            graph.query(statement)
        except Exception as e:
            if "already indexed" not in str(e).lower():
                raise
