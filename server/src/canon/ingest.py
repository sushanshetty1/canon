"""Ingest a repository into a workspace graph, the first time or again: read, write, extract, link, judge.

The first run reads everything. A later run (a sync) starts from the commit and time the last one finished at,
which the graph keeps on `(:Source {repo, head, synced_at})`: it re-reads only the docs changed since that commit,
detaches the passages of docs that were deleted, and fetches only issues, pull requests and discussions updated
since. The CODEOWNERS history, the wiki, releases and decision records are short and always read whole, so a change
anywhere in them is seen.

Extraction runs only on passages that have never been extracted (`Passage.extracted_at` is unset). Passage ids are
addressed by content, so a changed paragraph is a new passage and is extracted, and an unchanged one never is
again. Pages come first; tickets and chats with a signal get their own budget per run, and what is over it waits
for the next run. Then the whole graph is linked through time, decision records become decisions, and changed
topics are judged for disputes.

Every other source is a connector (`canon.sources.connector`) and goes through `ingest_connector`, the shared
pipeline: read, write, extract, link, decisions, judge, then people and fixes. An uploaded export is one such
connector (`canon.sources.uploads.ExportUpload`, kind "upload"). A repository run keeps its own reading (it syncs by
commit and time) and shares `extract_new` and `finish`; it is recorded as a connection of kind "github" too.

`report(step=..., counts=..., progress=...)` is called as the run moves on, for the job's progress.
"""

import asyncio
import json
from collections.abc import Callable
from dataclasses import asdict, replace
from datetime import UTC, date, datetime
from pathlib import Path

from canon.extract.facts import EXTRACT_KINDS, Entities, Usage, choose, extract
from canon.graph.db import ensure_schema
from canon.graph.writer import write_batch, write_facts
from canon.sources.repo import RepoSource, load_repo
from canon.types import Batch, Doc, Passage

Report = Callable[..., None]

# The steps a run goes through, in order, with what the app shows for each.
STEPS = {
    "clone": "Reading the repository",
    "docs": "Reading documents",
    "wiki": "Reading the wiki",
    "codeowners": "Reading CODEOWNERS history",
    "activity": "Reading issues and pull requests",
    "discussions": "Reading discussions",
    "releases": "Reading releases",
    "people": "Reading contributors",
    "read": "Reading the source",
    "connect": "Checking the connection",
    "read_slack": "Reading Slack channels",
    "read_notion": "Reading Notion pages",
    "read_linear": "Reading Linear issues",
    "read_jira": "Reading Jira issues",
    "read_confluence": "Reading Confluence pages",
    "read_upload": "Reading files",
    "unpack": "Unpacking the export",
    "upload": "Reading the export",
    "write": "Writing the graph",
    "extract": "Reading facts from passages",
    "link": "Linking facts through time",
    "decisions": "Building decisions",
    "judge": "Checking for disputes",
}
# Pieces a repository run reads, in the order the app shows them, with the step each belongs to.
PIECES = {
    "meta": None,
    "docs": "docs",
    "wiki": "wiki",
    "codeowners": "codeowners",
    "pulls": "activity",
    "issues": "activity",
    "discussions": "discussions",
    "releases": "releases",
    "contributors": "people",
}
EXTRACT_LIMIT = 400  # passages per run
CONVERSATION_BUDGET = 150  # of which at most this many come from tickets and chats


def source_state(graph) -> dict | None:
    rows = graph.query("MATCH (s:Source) RETURN s.repo, s.head, s.synced_at LIMIT 1").result_set
    return dict(zip(("repo", "head", "synced_at"), rows[0], strict=True)) if rows else None


def graph_counts(graph) -> dict[str, int]:
    one = lambda q: graph.query(q).result_set[0][0]  # noqa: E731
    return {
        "documents": one("MATCH (d:Document) RETURN count(d)"),
        "passages": one("MATCH (:Document)-[:HAS]->(p:Passage) RETURN count(p)"),
        "facts": one("MATCH (f:Fact) RETURN count(f)"),
        "people": one("MATCH (p:Person) RETURN count(p)"),
        "teams": one("MATCH (t:Team) RETURN count(t)"),
        "areas": one("MATCH (a:Area) RETURN count(a)"),
        "stale": one("MATCH (f:Fact {stale: true}) RETURN count(f)"),
    }


def remove_docs(graph, doc_ids: list[str]) -> None:
    """Docs deleted from the repository keep their passages for history, detached from the current version, so the
    facts they stated are closed by `link`."""
    if doc_ids:
        graph.query(
            """UNWIND $ids AS id MATCH (d:Document {id: id})-[h:HAS]->(p:Passage)
               MERGE (d)-[:HAD]->(p) SET p.removed_at = $today, d.removed = true DELETE h""",
            {"ids": doc_ids, "today": date.today().isoformat()},
        )


def entities_from_graph(graph, *, people: int = 80, speakers: int = 40) -> Entities:
    """The areas, teams and the most active people the graph knows, for the extraction prompt. People known only by
    name count when they have said something (a Slack member), so a chat can say one of them owns something."""
    areas = dict(graph.query("MATCH (a:Area) RETURN a.slug, coalesce(a.name, a.slug)").result_set)
    teams = dict(graph.query("MATCH (t:Team) RETURN t.slug, coalesce(t.name, t.slug)").result_set)
    rows = graph.query(
        """MATCH (p:Person) OPTIONAL MATCH (p)-[a:AUTHORED|REVIEWED|COMMENTED|DECIDED]->(:Document)
           WITH coalesce(p.handle, '') AS handle, coalesce(p.name, p.handle, '') AS name, count(a) AS n
           RETURN handle, name ORDER BY n DESC, handle LIMIT $limit""",
        {"limit": people},
    ).result_set
    found = {h: n for h, n in rows if h and not h.startswith("name:")}
    said = graph.query(
        """MATCH (p:Person)-[s:SAID]->(:Passage) WHERE p.handle STARTS WITH 'name:'
           WITH coalesce(p.handle, '') AS handle, coalesce(p.name, p.handle, '') AS name, count(s) AS n
           RETURN handle, name ORDER BY n DESC, handle LIMIT $limit""",
        {"limit": speakers},
    ).result_set
    found.update({h: n for h, n in said if h})
    return Entities(areas=areas, teams=teams, people=found)


def unextracted(graph) -> tuple[list[Passage], list[Doc]]:
    """Current passages of the documents worth extracting that no run has extracted yet."""
    rows = graph.query(
        """MATCH (d:Document)-[:HAS]->(p:Passage) WHERE d.kind IN $kinds AND p.extracted_at IS NULL
           RETURN d.id, d.kind, coalesce(d.title, ''), coalesce(d.url, ''), coalesce(d.updated_at, ''), d.decided_at,
                  p.id, p.text, p.author, p.at""",
        {"kinds": list(EXTRACT_KINDS)},
    ).result_set
    docs: dict[str, Doc] = {}
    passages = []
    for doc_id, kind, title, url, updated, decided, pid, text, author, at in rows:
        docs.setdefault(doc_id, Doc(doc_id, kind, title, url, updated, decided_at=decided))
        passages.append(Passage(pid, doc_id, text or "", author, at))
    return passages, list(docs.values())


def extract_new(
    graph,
    *,
    model: str,
    cache: Path | None,
    client=None,
    report: Report = lambda **_: None,
    base: dict | None = None,
    limit: int = EXTRACT_LIMIT,
    conversations: int = CONVERSATION_BUDGET,
    progress: tuple[float, float] = (0.35, 0.85),
) -> tuple[int, Usage]:
    """Extract facts from the passages no run has extracted yet, within this run's budget. Returns the number of
    facts and the model usage."""
    started = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    usage = Usage()
    passages, docs = unextracted(graph)
    entities = entities_from_graph(graph)
    chosen, over = choose(Batch(docs=docs, passages=passages), entities, limit=limit, conversations=conversations)
    later = {p.id for p in over}  # over this run's budget: left for the next one
    total, done = len(chosen), 0
    base = {**(base or {}), **graph_counts(graph)}
    lo, hi = progress

    def tick() -> None:
        nonlocal done
        done += 1
        report(counts={**base, "extracted": done, "to_extract": total}, progress=lo + (hi - lo) * done / max(total, 1))

    report(step="extract", counts={**base, "extracted": 0, "to_extract": total}, progress=lo)
    if client is None:
        import anthropic

        client = anthropic.AsyncAnthropic(max_retries=0)  # one per run: a client belongs to one loop
    facts = asyncio.run(extract(chosen, docs, entities, model=model, cache_dir=cache, usage=usage, on_passage=tick, client=client))
    write_facts(graph, facts)
    # Passages the model answered for, or not worth asking about, are done. When the model stopped answering
    # (a spend limit) nothing is marked: answers so far are cached on disk, so the next run costs nothing.
    if not usage.stopped:
        graph.query(
            "UNWIND $ids AS id MATCH (p:Passage {id: id}) SET p.extracted_at = $at",
            {"ids": [p.id for p in passages if p.id not in later], "at": started},
        )
    return len(facts), usage


def finish(graph, *, check=None, report: Report = lambda **_: None, counts: dict | None = None, decisions=None) -> dict:
    """Link facts through time, build decisions when `decisions(model)` is given, and judge disputes with `check`."""
    from canon.verify.supersede import link

    report(step="link", progress=0.88, counts={**(counts or {}), **graph_counts(graph)})
    out: dict = {"linked": link(graph), "decisions": {}, "judged": {}}
    if decisions is not None:
        report(step="decisions", progress=0.9)
        out["decisions"] = decisions(check)
    if check is not None:
        report(step="judge", progress=0.94)
        from canon.verify.conflicts import judge

        out["judged"] = asyncio.run(judge(graph, check))
    return out


def pull_rows(graph) -> list[dict]:
    """The workspace's merged pull requests as `canon.decisions` reads them, from the graph, so a sync that read only
    the newest pull requests still links every decision to all of its work."""
    rows = graph.query(
        """MATCH (d:Document {kind: 'pull'})-[:HAS]->(p:Passage)
           RETURN d.id, coalesce(d.title, ''), coalesce(d.url, ''), coalesce(d.updated_at, ''), coalesce(p.text, '')"""
    ).result_set
    return [
        {"doc_id": doc_id, "number": doc_id.split(":", 1)[1], "title": title, "url": url, "merged_at": updated, "body": text}
        for doc_id, title, url, updated, text in rows
    ]


def _calm(e: Exception) -> str:
    from canon.cloud.jobs import _calm as calm

    return calm(e)


PERSON_IDS = ("slack_id", "notion_id", "linear_id", "jira_id", "confluence_id")  # a person's id in each tool


def keep_first_dates(graph, batch: Batch) -> None:
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
    """What a connection has in the graph now: its documents, their passages, the facts they state, their people."""
    one = lambda q: graph.query(q, {"id": connection_id}).result_set[0][0]  # noqa: E731
    return {
        "documents": one("MATCH (d:Document {connection: $id}) WHERE d.removed_at IS NULL RETURN count(d)"),
        "passages": one("MATCH (d:Document {connection: $id})-[:HAS]->(p:Passage) RETURN count(p)"),
        "facts": one("MATCH (d:Document {connection: $id})-[:HAS]->(:Passage)<-[:STATED_IN]-(f:Fact) RETURN count(DISTINCT f)"),
        "people": one(
            """MATCH (d:Document {connection: $id})<-[:AUTHORED|COMMENTED|REVIEWED|DECIDED]-(p:Person)
               RETURN count(DISTINCT p)"""
        ),
    }


def ingest_connector(
    graph,
    connector,
    *,
    connection_id: str | None = None,
    config: dict | None = None,
    label: str | None = None,
    cursor: str | None = None,
    report: Report = lambda **_: None,
    extract_model: str | None = None,
    extract_cache: Path | None = None,
    check=None,
    extract_client=None,
    extract_limit: int = EXTRACT_LIMIT,
    conversation_budget: int = 250,
    decisions=None,
    refresh: bool = True,
) -> dict:
    """The pipeline every connector shares (`canon.sources.connector`): read, write, extract, link, decisions, judge,
    then refresh who knows what and the fix queue.

    The connection is kept as `(:Connection {id, kind, label, config, status, last_synced_at, last_tried_at, cursor,
    counts, notes, error})`: `reading` while it runs, then `done` with the connector's new cursor, or `failed` with a
    calm reason. `config` is JSON, merged into what the connection already keeps (a live connection's site and caps);
    the counts of what the connection has in the graph are added to it and kept as `counts`. A label already set (a
    connection named when it was made) is kept. Documents read are tagged with the connection (`d.connection`), so it
    can be removed with or without them; people get their id in the tool (`slack_id` ...); documents the source says
    are gone are detached, so their facts close. `decisions(model)` builds decisions after linking, when the source
    has decision records. `refresh` False skips people and fixes (a caller that runs them itself)."""
    import secrets

    ensure_schema(graph)
    started = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    cid = connection_id or f"{connector.kind}-{secrets.token_hex(5)}"
    rows = graph.query("MATCH (c:Connection {id: $id}) RETURN c.config", {"id": cid}).result_set
    try:
        kept = json.loads(rows[0][0] or "{}") if rows else {}
    except (TypeError, json.JSONDecodeError):
        kept = {}
    config = {**(kept if isinstance(kept, dict) else {}), **(config or {})}
    graph.query(
        """MERGE (c:Connection {id: $id}) SET c.kind = $kind, c.label = coalesce($label, c.label, $default),
           c.status = 'reading', c.error = NULL, c.config = $config, c.last_tried_at = $at""",
        {"id": cid, "kind": connector.kind, "label": label, "default": connector.label, "config": json.dumps(config),
         "at": started},
    )
    read: dict[str, int] = {}

    def progress(*, step: str | None = None, done: int | None = None, total: int | None = None, counts: dict | None = None,
                 **_) -> None:
        if counts:
            read.update(counts)
        if done is not None:
            read["read"] = done
        if total is not None:
            read["to_read"] = total
        share = 0.04 + 0.2 * min(1.0, done / total) if done is not None and total else None
        report(step=step if step in STEPS else ("read" if step else None), counts=dict(read), progress=share)

    try:
        report(step="read", progress=0.04)
        result = connector.read(cursor=cursor, report=progress)
        batch = result.batch
        found = {"documents": len(batch.docs), "passages": len(batch.passages), "people": len(batch.people)}
        report(step="write", counts={**read, **found}, progress=0.25)
        keep_first_dates(graph, batch)
        written = write_batch(graph, batch)
        graph.query(
            """UNWIND $ids AS id MATCH (d:Document {id: id})
               SET d.connection = $conn, d.source = $kind, d.removed_at = NULL, d.removed = NULL""",
            {"ids": [d.id for d in batch.docs], "conn": cid, "kind": connector.kind},
        )
        ids = getattr(result, "people_props", None) or {}
        if ids:
            sets = ", ".join(f"p.{k} = coalesce(r.{k}, p.{k})" for k in PERSON_IDS)
            graph.query(f"UNWIND $rows AS r MATCH (p:Person {{handle: r.handle}}) SET {sets}",
                        {"rows": [{"handle": h, **{k: v.get(k) for k in PERSON_IDS}} for h, v in ids.items()]})
        removed = list(getattr(result, "removed", None) or [])
        remove_docs(graph, removed)
        base = {**read, **found}
        report(counts={**base, **graph_counts(graph)})

        usage = Usage()
        extracted = 0
        if extract_model:
            extracted, usage = extract_new(
                graph, model=extract_model, cache=extract_cache, client=extract_client, report=report, base=base,
                limit=extract_limit, conversations=conversation_budget,
            )
        done = finish(graph, check=check, report=report, counts=base, decisions=decisions)
        if refresh:
            from canon.fixes import build as build_fixes
            from canon.people import recompute

            done["people"] = recompute(graph)
            done["fixes"] = build_fixes(graph)
    except Exception as e:
        graph.query(
            "MATCH (c:Connection {id: $id}) SET c.status = 'failed', c.error = $error",
            {"id": cid, "error": _calm(e)},
        )
        raise
    totals = connection_counts(graph, cid)
    graph.query(
        """MATCH (c:Connection {id: $id}) SET c.status = 'done', c.last_synced_at = $at, c.cursor = $cursor,
           c.error = NULL, c.notes = $notes, c.config = $config, c.counts = $counts""",
        {"id": cid, "at": started, "cursor": result.cursor, "notes": json.dumps(result.notes),
         "config": json.dumps({**config, **totals}), "counts": json.dumps(totals)},
    )
    counts = {**base, **graph_counts(graph), "extracted_facts": extracted, "removed_docs": len(removed)}
    report(counts=counts, progress=1.0)
    return {"connection": cid, "counts": counts, "written": written, "notes": result.notes, "cursor": result.cursor,
            "totals": totals, **done, "usage": asdict(usage)}


def ingest_upload(
    graph,
    kind: str,
    data: bytes,
    *,
    filename: str = "",
    by: str | None = None,
    report: Report = lambda **_: None,
    **pipeline,
) -> dict:
    """An uploaded export (`kind` "slack" or "pages") through the shared pipeline, as a connection of kind "upload"."""
    from canon.sources.uploads import ExportUpload

    upload = ExportUpload(kind, data, filename)
    config = {"format": kind, "filename": filename[:200], "by": by}
    return ingest_connector(graph, upload, config=config, report=report, **pipeline)


def ingest_repo(
    graph,
    repo: str,
    *,
    cache_root: Path,
    token: str | None = None,
    report: Report = lambda **_: None,
    source: Callable | None = None,
    extract_limit: int = EXTRACT_LIMIT,
    conversation_budget: int = CONVERSATION_BUDGET,
    extract_model: str | None = None,
    extract_cache: Path | None = None,
    check=None,
    extract_client=None,
) -> dict:
    """Read `repo` into `graph`. `extract_model` None skips extraction and `check` None skips judging, so a run
    without a model key still loads documents, ownership, decisions and activity. Returns the counts."""
    ensure_schema(graph)
    state = source_state(graph)
    since_head = state["head"] if state and state["repo"] == repo else None
    since = state["synced_at"] if since_head else None
    started = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    report(step="clone", progress=0.02)
    src = source or RepoSource(repo, cache_root, token=token, since_head=since_head, since=since)
    head = src.prepare()

    read: dict[str, int] = {}

    def fetch(name: str):
        if PIECES.get(name):
            report(step=PIECES[name], counts=dict(read))
        rows = src(name)
        if isinstance(rows, list):
            read[name] = len(rows)
            report(counts=dict(read))
        return rows

    # Contributors are fetched first by load_repo; the order the app shows is docs first, so read in that order.
    pieces = {name: fetch(name) for name in PIECES}
    batch = load_repo(repo, lambda name: pieces.get(name))
    gone = list(getattr(src, "removed", []))
    removed = [f"{kind}:{p}" for p in gone for kind in ("doc", "rfc", "adr")]

    report(step="write", counts=dict(read), progress=0.3)
    written = write_batch(graph, batch)
    remove_docs(graph, removed)
    report(counts={**read, **graph_counts(graph)})

    usage = Usage()
    extracted = 0
    if extract_model:
        extracted, usage = extract_new(
            graph, model=extract_model, cache=extract_cache, client=extract_client, report=report, base=read,
            limit=extract_limit, conversations=conversation_budget,
        )

    records = src("decision_records") or []

    def decisions(model):
        from canon.decisions.build import build

        return build(graph, records, pull_rows(graph), model=model) if records else {}

    done = finish(graph, check=check, report=report, counts=read, decisions=decisions)
    # Who knows each area and its bus factor, from the activity just written.
    from canon.people import recompute

    done["people"] = recompute(graph)
    graph.query(
        "MERGE (s:Source {repo: $repo}) SET s.head = $head, s.synced_at = $at",
        {"repo": repo, "head": head, "at": started},
    )
    # The repository is the workspace's GitHub connection, listed with any others on the Sources screen.
    graph.query(
        """MERGE (c:Connection {id: 'github'}) SET c.kind = 'github', c.label = 'GitHub', c.status = 'done',
           c.last_synced_at = $at, c.cursor = $head, c.error = NULL, c.config = $config""",
        {"at": started, "head": head, "config": json.dumps({"repo": repo})},
    )
    counts = {**read, **graph_counts(graph), "decision_records": len(records), "extracted_facts": extracted,
              "removed_docs": len(gone)}
    report(counts=counts, progress=1.0)
    return {"counts": counts, "written": written, **done, "usage": asdict(usage)}
