"""Ingest a repository into a workspace graph, the first time or again: read, write, extract, link, judge.

The first run reads everything. A later run (a sync) starts from the commit and time the last one finished at,
which the graph keeps on `(:Source {repo, head, synced_at})`: it re-reads only the docs changed since that commit,
detaches the passages of docs that were deleted, and fetches only issues and pull requests updated since. The
CODEOWNERS history is short and always read whole, so an owner change anywhere in it is seen.

Extraction runs only on passages that have never been extracted (`Passage.extracted_at` is unset). Passage ids are
addressed by content, so a changed paragraph is a new passage and is extracted, and an unchanged one never is
again. Then the whole graph is linked through time and changed topics are judged for disputes.

`report(step=..., counts=..., progress=...)` is called as the run moves on, for the job's progress.
"""

import asyncio
from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, date, datetime
from pathlib import Path

from canon.extract.facts import EXTRACT_KINDS, Entities, Usage, extract, select_passages
from canon.graph.db import ensure_schema
from canon.graph.writer import write_batch, write_facts
from canon.sources.repo import RepoSource, load_repo
from canon.types import Batch, Doc, Passage

Report = Callable[..., None]

# The steps a run goes through, in order, with what the app shows for each.
STEPS = {
    "clone": "Reading the repository",
    "docs": "Reading documents",
    "codeowners": "Reading CODEOWNERS history",
    "activity": "Reading issues and pull requests",
    "people": "Reading contributors",
    "write": "Writing the graph",
    "extract": "Reading facts from passages",
    "link": "Linking facts through time",
    "judge": "Checking for disputes",
}


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


def entities_from_graph(graph, *, people: int = 80) -> Entities:
    """The areas, teams and the most active people the graph knows, for the extraction prompt."""
    areas = dict(graph.query("MATCH (a:Area) RETURN a.slug, coalesce(a.name, a.slug)").result_set)
    teams = dict(graph.query("MATCH (t:Team) RETURN t.slug, coalesce(t.name, t.slug)").result_set)
    rows = graph.query(
        """MATCH (p:Person) OPTIONAL MATCH (p)-[a:AUTHORED|REVIEWED|COMMENTED|DECIDED]->(:Document)
           WITH p.handle AS handle, coalesce(p.name, p.handle) AS name, count(a) AS n
           RETURN handle, name ORDER BY n DESC, handle LIMIT $limit""",
        {"limit": people},
    ).result_set
    return Entities(areas=areas, teams=teams, people={h: n for h, n in rows if h and not h.startswith("name:")})


def unextracted(graph) -> tuple[list[Passage], list[Doc]]:
    """Current passages of the documents worth extracting that no run has extracted yet."""
    rows = graph.query(
        """MATCH (d:Document)-[:HAS]->(p:Passage) WHERE d.kind IN $kinds AND p.extracted_at IS NULL
           RETURN d.id, d.kind, coalesce(d.title, ''), coalesce(d.url, ''), coalesce(d.updated_at, ''), d.decided_at,
                  p.id, p.text""",
        {"kinds": list(EXTRACT_KINDS)},
    ).result_set
    docs: dict[str, Doc] = {}
    passages = []
    for doc_id, kind, title, url, updated, decided, pid, text in rows:
        docs.setdefault(doc_id, Doc(doc_id, kind, title, url, updated, decided_at=decided))
        passages.append(Passage(pid, doc_id, text or ""))
    return passages, list(docs.values())


def ingest_repo(
    graph,
    repo: str,
    *,
    cache_root: Path,
    token: str | None = None,
    report: Report = lambda **_: None,
    source: Callable | None = None,
    extract_limit: int = 400,
    extract_model: str | None = None,
    extract_cache: Path | None = None,
    check=None,
    extract_client=None,
) -> dict:
    """Read `repo` into `graph`. `extract_model` None skips extraction and `check` None skips judging, so a run
    without a model key still loads documents, ownership and activity. Returns the counts."""
    ensure_schema(graph)
    state = source_state(graph)
    since_head = state["head"] if state and state["repo"] == repo else None
    since = state["synced_at"] if since_head else None
    started = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    report(step="clone", progress=0.02)
    src = source or RepoSource(repo, cache_root, token=token, since_head=since_head, since=since)
    head = src.prepare()

    read: dict[str, int] = {}
    steps = {"docs": "docs", "codeowners": "codeowners", "pulls": "activity", "issues": "activity", "contributors": "people"}

    def fetch(name: str):
        if name in steps:
            report(step=steps[name], counts=dict(read))
        rows = src(name)
        if isinstance(rows, list):
            read[name] = len(rows)
            report(counts=dict(read))
        return rows

    # Contributors are fetched first by load_repo; the order the app shows is docs first, so read in that order.
    pieces = {name: fetch(name) for name in ("meta", "docs", "codeowners", "pulls", "issues", "contributors")}
    batch = load_repo(repo, lambda name: pieces.get(name))
    gone = list(getattr(src, "removed", []))
    removed = [f"{kind}:{p}" for p in gone for kind in ("doc", "rfc")]

    report(step="write", counts=dict(read), progress=0.3)
    written = write_batch(graph, batch)
    remove_docs(graph, removed)
    report(counts={**read, **graph_counts(graph)})

    usage = Usage()
    extracted = 0
    if extract_model:
        passages, docs = unextracted(graph)
        entities = entities_from_graph(graph)
        worth = select_passages(Batch(docs=docs, passages=passages), entities)
        chosen = worth[:extract_limit]
        later = {p.id for p in worth[extract_limit:]}  # over this run's limit: left for the next one
        total, done = len(chosen), 0
        base = {**read, **graph_counts(graph)}

        def tick() -> None:
            nonlocal done
            done += 1
            report(counts={**base, "extracted": done, "to_extract": total}, progress=0.35 + 0.5 * done / max(total, 1))

        report(step="extract", counts={**base, "extracted": 0, "to_extract": total}, progress=0.35)
        if extract_client is None:
            import anthropic

            extract_client = anthropic.AsyncAnthropic(max_retries=0)  # one per run: a client belongs to one loop
        facts = asyncio.run(
            extract(chosen, docs, entities, model=extract_model, cache_dir=extract_cache, usage=usage,
                    on_passage=tick, client=extract_client)
        )
        write_facts(graph, facts)
        extracted = len(facts)
        # Passages the model answered for, or not worth asking about, are done. When the model stopped answering
        # (a spend limit) nothing is marked: answers so far are cached on disk, so the next run costs nothing.
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

    graph.query(
        "MERGE (s:Source {repo: $repo}) SET s.head = $head, s.synced_at = $at",
        {"repo": repo, "head": head, "at": started},
    )
    counts = {**read, **graph_counts(graph), "extracted_facts": extracted, "removed_docs": len(gone)}
    report(counts=counts, progress=1.0)
    return {"counts": counts, "written": written, "linked": linked, "judged": judged, "usage": asdict(usage)}
