"""Run one connector into a workspace graph: read, write, extract, link, judge.

The same steps a repository goes through (`canon.ingest`), for any `Connector`:

1. `connector.read(cursor=..., report=...)` returns a batch and where the next sync starts.
2. The batch is written. Its documents are tagged with the connection that read them (`d.connection`), so a
   connection can be removed with or without its documents. Structured facts keep the day they were first seen.
3. Passages never extracted are read for facts by the extract model, at most `extract_limit` a run (the rest wait
   for the next sync), then the whole graph is linked through time and changed topics judged for disputes.

`report(step=..., counts=..., progress=...)` is the job's progress, as for a repository.
"""

import asyncio
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path

from canon.extract.facts import Usage, extract, select_passages
from canon.graph.db import ensure_schema
from canon.graph.writer import write_batch, write_facts
from canon.ingest import entities_from_graph, graph_counts, remove_docs, unextracted
from canon.sources.connector import Connector
from canon.types import Batch

# What the app shows for each step of a connector's sync, beside the repository's steps in `canon.ingest.STEPS`.
SYNC_STEPS = {
    "connect": "Checking the connection",
    "read_slack": "Reading Slack channels",
    "read_notion": "Reading Notion pages",
    "read_linear": "Reading Linear issues",
    "read_jira": "Reading Jira issues",
    "read_confluence": "Reading Confluence pages",
    "read_upload": "Reading files",
    "write": "Writing the graph",
    "extract": "Reading facts from passages",
    "link": "Linking facts through time",
    "judge": "Checking for disputes",
}

PERSON_PROPS = ("slack_id", "notion_id", "linear_id", "jira_id", "confluence_id")


def _keep_first_dates(graph, batch: Batch) -> None:
    """A structured fact read again keeps the day it was first seen, so a source that cannot date a fact (a Jira
    project's lead) does not move it forward on every sync."""
    if not batch.facts:
        return
    rows = graph.query(
        "UNWIND $ids AS id MATCH (f:Fact {id: id}) RETURN f.id, f.valid_from", {"ids": [f.id for f in batch.facts]}
    ).result_set
    first = {fid: since for fid, since in rows if since}
    batch.facts = [replace(f, valid_from=first[f.id]) if first.get(f.id, "9") < f.valid_from else f for f in batch.facts]


def connection_counts(graph, connection_id: str) -> dict[str, int]:
    one = lambda q: graph.query(q, {"id": connection_id}).result_set[0][0]  # noqa: E731
    return {
        "documents": one("MATCH (d:Document {connection: $id}) WHERE d.removed_at IS NULL RETURN count(d)"),
        "passages": one("MATCH (d:Document {connection: $id})-[:HAS]->(p:Passage) RETURN count(p)"),
        "facts": one("MATCH (d:Document {connection: $id})-[:HAS]->(:Passage)<-[:STATED_IN]-(f:Fact) RETURN count(DISTINCT f)"),
        "people": one("MATCH (d:Document {connection: $id})<-[:AUTHORED|COMMENTED|REVIEWED|DECIDED]-(p:Person) RETURN count(DISTINCT p)"),
    }


def run_connector(
    graph,
    connector: Connector,
    *,
    cursor: str | None = None,
    connection_id: str | None = None,
    report=lambda **_: None,
    extract_model: str | None = None,
    extract_cache: Path | None = None,
    check=None,
    extract_limit: int = 200,
    extract_client=None,
) -> dict:
    """Read `connector` into `graph`. `extract_model` None skips extraction and `check` None skips judging.
    Returns the counts, the cursor for the next sync and the connector's notes."""
    ensure_schema(graph)
    started = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    def reading(step: str | None = None, done: float | None = None, total: float | None = None, **_) -> None:
        progress = 0.02 + 0.26 * min(1.0, done / total) if done is not None and total else None
        report(step=step, progress=progress)

    result = connector.read(cursor=cursor, report=reading)
    batch = result.batch
    read = {"documents": len(batch.docs), "passages": len(batch.passages), "people": len(batch.people)}

    report(step="write", counts=dict(read), progress=0.3)
    _keep_first_dates(graph, batch)
    written = write_batch(graph, batch)
    if connection_id:
        graph.query(
            "UNWIND $ids AS id MATCH (d:Document {id: id}) SET d.connection = $conn, d.source = $kind, d.removed_at = NULL, d.removed = NULL",
            {"ids": [d.id for d in batch.docs], "conn": connection_id, "kind": connector.kind},
        )
    props = getattr(result, "people_props", {}) or {}
    rows = [{"handle": h, **{k: v.get(k) for k in PERSON_PROPS}} for h, v in props.items()]
    if rows:
        sets = ", ".join(f"p.{k} = coalesce(r.{k}, p.{k})" for k in PERSON_PROPS)
        graph.query(f"UNWIND $rows AS r MATCH (p:Person {{handle: r.handle}}) SET {sets}", {"rows": rows})
    removed = list(getattr(result, "removed", []) or [])
    remove_docs(graph, removed)

    usage = Usage()
    extracted = 0
    if extract_model:
        passages, docs = unextracted(graph)
        entities = entities_from_graph(graph)
        worth = select_passages(Batch(docs=docs, passages=passages), entities)
        chosen = worth[:extract_limit]
        later = {p.id for p in worth[extract_limit:]}
        total, done = len(chosen), 0
        base = {**read, **graph_counts(graph)}

        def tick() -> None:
            nonlocal done
            done += 1
            report(counts={**base, "extracted": done, "to_extract": total}, progress=0.35 + 0.5 * done / max(total, 1))

        report(step="extract", counts={**base, "extracted": 0, "to_extract": total}, progress=0.35)
        if extract_client is None:
            import anthropic

            extract_client = anthropic.AsyncAnthropic(max_retries=0)
        facts = asyncio.run(
            extract(chosen, docs, entities, model=extract_model, cache_dir=extract_cache, usage=usage,
                    on_passage=tick, client=extract_client)
        )
        write_facts(graph, facts)
        extracted = len(facts)
        if not usage.stopped:
            graph.query("UNWIND $ids AS id MATCH (p:Passage {id: id}) SET p.extracted_at = $at",
                        {"ids": [p.id for p in passages if p.id not in later], "at": started})

    report(step="link", progress=0.88, counts={**read, **graph_counts(graph)})
    from canon.verify.supersede import link

    linked = link(graph)
    judged: dict = {}
    if check is not None:
        report(step="judge", progress=0.94)
        from canon.verify.conflicts import judge

        judged = asyncio.run(judge(graph, check))

    counts = {**read, **graph_counts(graph), "extracted_facts": extracted, "removed_docs": len(removed)}
    report(counts=counts, progress=1.0)
    return {
        "counts": counts,
        "cursor": result.cursor,
        "notes": list(result.notes),
        "written": written,
        "linked": linked,
        "judged": judged,
        "usage": asdict(usage),
        "connection": connection_counts(graph, connection_id) if connection_id else None,
    }
