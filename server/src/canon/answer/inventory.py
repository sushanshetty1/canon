"""Questions about the workspace itself: what Canon reads, which sources are connected, which documents it has.

These are answered from the graph's structure (documents, their kinds, connections and when each was read), not
from extracted facts, so no model writes them. Each sentence is verified against the documents it names, and its
sources are those documents with their first passage.
"""

import re

from canon.sources.connector import group_of

# A question about the workspace's own contents, not about the company. Strong signals answer from the inventory
# straight away; weak ones only when no fact in the graph answers ("Which docs mention billing?" is about billing).
STRONG = re.compile(
    r"\b(what|which|list|show|how many)\b.*\b(sources?|connected|connections?|integrations?)\b"
    r"|\bwhat (do|does|can) (you|canon) (know|read|see|have)\b"
    r"|\bwhat('s| is) in (the|this|my) (graph|workspace)\b"
    r"|\bhow many (docs|documents|pages|files)\b",
    re.I,
)
WEAK = re.compile(r"\b(what|which|list|show)\b.*\b(docs?|documents?|files?|pages?|repos?|repositor(y|ies)|channels?)\b", re.I)

LABELS = {
    "handbook": ("handbook page", "handbook pages"),
    "team_page": ("team page", "team pages"),
    "doc": ("doc", "docs"),
    "wiki": ("wiki page", "wiki pages"),
    "notion_page": ("Notion page", "Notion pages"),
    "confluence_page": ("Confluence page", "Confluence pages"),
    "upload": ("uploaded file", "uploaded files"),
    "issue": ("issue", "issues"),
    "pull": ("pull request", "pull requests"),
    "linear_issue": ("Linear issue", "Linear issues"),
    "jira_issue": ("Jira issue", "Jira issues"),
    "forum": ("forum thread", "forum threads"),
    "discussion": ("discussion", "discussions"),
    "comment_thread": ("comment thread", "comment threads"),
    "slack_thread": ("Slack thread", "Slack threads"),
    "rfc": ("design doc", "design docs"),
    "adr": ("decision record", "decision records"),
    "release": ("release", "releases"),
    "ownership_map": ("ownership change", "ownership changes"),
    "roster": ("team roster", "team rosters"),
}
GROUP_ORDER = ("docs", "tickets", "chats", "decisions", "structure")

KINDS = "MATCH (d:Document) RETURN coalesce(d.kind, 'doc'), count(d)"
EXAMPLES = """
MATCH (d:Document {kind: $kind})
OPTIONAL MATCH (d)-[:HAS]->(p:Passage)
WITH d, collect(p.text)[0] AS first
RETURN d.id, coalesce(d.title, d.id), d.url, coalesce(d.updated_at, ''), first
ORDER BY coalesce(d.updated_at, '') DESC LIMIT $n
"""
CONNECTIONS = """
MATCH (c:Connection)
RETURN coalesce(c.kind, ''), coalesce(c.label, c.kind, ''), coalesce(c.last_synced_at, ''), coalesce(c.status, '')
"""


def is_inventory(question: str) -> bool:
    return bool(STRONG.search(question or ""))


def maybe_inventory(question: str) -> bool:
    return bool(STRONG.search(question or "") or WEAK.search(question or ""))


def _label(kind: str, n: int) -> str:
    one, many = LABELS.get(kind, (kind.replace("_", " "), kind.replace("_", " ") + "s"))
    return f"{n:,} {one if n == 1 else many}"


def _join(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def _source(row) -> dict:
    doc_id, title, url, date, first = row
    return {
        "fact_id": f"doc:{doc_id}",
        "fact": title,
        "subject": None,
        "predicate": "document",
        "value": None,
        "authority": None,
        "valid_from": date[:10] or None,
        "valid_to": None,
        "stale": False,
        "current": True,
        "superseded_by": None,
        "passage_id": None,
        "passage": (first or "")[:600] or None,
        "removed": False,
        "doc_id": doc_id,
        "title": title,
        "url": url,
        "kind": None,
        "date": date[:10] or None,
    }


def answer(graph) -> list[tuple[str, list[dict]]]:
    """Sentences about what the workspace holds, each with the documents that back it."""
    kinds = {k: n for k, n in graph.query(KINDS).result_set if n}
    if not kinds:
        return []
    total = sum(kinds.values())
    by_group: dict[str, list[tuple[str, int]]] = {}
    for kind, n in sorted(kinds.items(), key=lambda kv: -kv[1]):
        by_group.setdefault(group_of(kind), []).append((kind, n))

    def examples(kind: str, n: int = 3) -> list[dict]:
        rows = graph.query(EXAMPLES, {"kind": kind, "n": n}).result_set
        return [{**_source(r), "kind": kind} for r in rows]

    out: list[tuple[str, list[dict]]] = []
    parts = [_label(k, n) for g in GROUP_ORDER for k, n in by_group.get(g, [])]
    first_kind = max(kinds, key=kinds.get)
    out.append((f"Canon reads {total:,} documents in this workspace: {_join(parts)}.", examples(first_kind, 2)))

    for group in GROUP_ORDER:
        for kind, n in by_group.get(group, [])[:3]:
            docs = examples(kind)
            titles = [f"“{d['title']}”" for d in docs]
            more = f", and {n - len(titles):,} more" if n > len(titles) else ""
            noun = LABELS.get(kind, (kind, kind + "s"))[1]
            lead = "The" if n <= len(titles) else "The most recent"
            out.append((f"{lead} {noun} include {_join(titles)}{more}.", docs))
        if len(out) >= 6:
            break

    connections = graph.query(CONNECTIONS).result_set
    if connections:
        named = [f"{label} (read {synced[:10]})" if synced else label for _, label, synced, _ in connections]
        out.append((f"It is connected to {_join(named)}.", []))
    return out


async def events(graph, *, evidence: bool = True):
    rows = answer(graph)
    if evidence:
        documents = sum(n for _, n in graph.query(KINDS).result_set)
        yield {"type": "evidence", "facts": 0, "documents": documents}
    if not rows:
        yield {"type": "empty", "ask": []}
        return
    for i, (text, _) in enumerate(rows):
        yield {"type": "claim", "index": i, "text": text, "fact_ids": []}
    for i, (_, sources) in enumerate(rows):
        yield {"type": "verdict", "index": i, "verdict": "verified", "sources": sources, "newer": [], "conflicting": []}
    yield {"type": "done", "counts": {"verified": len(rows), "stale": 0, "disputed": 0, "unsupported": 0}}
