"""Writes connector batches and facts into a workspace graph.

Every write merges on an indexed key, so writing the same batch twice changes nothing. When a document comes back
with different passages, the passages that are gone are kept for history: they move from `HAS` to `HAD` and get
`removed_at`, so facts that cite them can still show where they came from.
"""

from dataclasses import asdict
from datetime import date

from canon.types import ENTITY_KEYS, Batch, Fact, entity

CHUNK = 500


def _run(graph, query: str, rows: list[dict]) -> None:
    for i in range(0, len(rows), CHUNK):
        graph.query(query, {"rows": rows[i : i + CHUNK]})


def write_batch(graph, batch: Batch) -> dict[str, int]:
    _run(
        graph,
        "UNWIND $rows AS r MERGE (p:Person {handle: r.handle}) SET p.name = r.name, p.role = r.role",
        [asdict(p) for p in batch.people],
    )
    _run(
        graph,
        "UNWIND $rows AS r MERGE (t:Team {slug: r.slug}) SET t.name = r.name",
        [{"slug": t.slug, "name": t.name} for t in batch.teams],
    )
    for rel, attr in (("MEMBER_OF", "members"), ("LEADS", "leads")):
        _run(
            graph,
            f"UNWIND $rows AS r MATCH (t:Team {{slug: r.team}}) MERGE (p:Person {{handle: r.handle}}) MERGE (p)-[:{rel}]->(t)",
            [{"team": t.slug, "handle": h} for t in batch.teams for h in getattr(t, attr)],
        )
    _run(graph, "UNWIND $rows AS r MERGE (a:Area {slug: r.slug}) SET a.name = r.name", [asdict(a) for a in batch.areas])

    _run(
        graph,
        """UNWIND $rows AS r MERGE (d:Document {id: r.id})
           SET d.kind = r.kind, d.title = r.title, d.url = r.url, d.updated_at = r.updated_at, d.author = r.author,
               d.decided_at = r.decided_at""",
        [asdict(d) for d in batch.docs],
    )
    # A document about an area (a pull request labelled `feature/notebooks`) links to it.
    _run(
        graph,
        "UNWIND $rows AS r MATCH (d:Document {id: r.doc}) MERGE (a:Area {slug: r.area}) MERGE (d)-[:ABOUT]->(a)",
        [{"doc": d.id, "area": a} for d in batch.docs for a in d.areas],
    )
    # Passages a document no longer has stay on record, detached from the current version.
    by_doc: dict[str, list[str]] = {}
    for p in batch.passages:
        by_doc.setdefault(p.doc_id, []).append(p.id)
    _run(
        graph,
        """UNWIND $rows AS r MATCH (d:Document {id: r.doc})-[h:HAS]->(p:Passage) WHERE NOT p.id IN r.keep
           MERGE (d)-[:HAD]->(p) SET p.removed_at = r.today DELETE h""",
        [{"doc": d, "keep": ids, "today": date.today().isoformat()} for d, ids in by_doc.items()],
    )
    _run(
        graph,
        """UNWIND $rows AS r MATCH (d:Document {id: r.doc_id}) MERGE (p:Passage {id: r.id})
           SET p.text = r.text, p.removed_at = NULL MERGE (d)-[:HAS]->(p)""",
        [asdict(p) for p in batch.passages],
    )
    for rel in ("AUTHORED", "REVIEWED", "COMMENTED", "DECIDED"):
        _run(
            graph,
            f"""UNWIND $rows AS r MATCH (d:Document {{id: r.doc_id}}) MERGE (p:Person {{handle: r.handle}})
                MERGE (p)-[e:{rel}]->(d) SET e.at = r.at""",
            [asdict(a) for a in batch.activity if a.rel == rel],
        )
    facts = write_facts(graph, batch.facts)
    return {
        "people": len(batch.people),
        "teams": len(batch.teams),
        "areas": len(batch.areas),
        "documents": len(batch.docs),
        "passages": len(batch.passages),
        "activity": len(batch.activity),
        "facts": facts,
    }


def write_facts(graph, facts: list[Fact]) -> int:
    _run(
        graph,
        """UNWIND $rows AS r MERGE (f:Fact {id: r.id})
           SET f.subject = r.subject, f.predicate = r.predicate, f.value = r.value, f.text = r.text,
               f.valid_from = r.valid_from, f.valid_to = r.valid_to, f.authority = r.authority, f.passage_id = r.passage_id
           WITH f, r MATCH (p:Passage {id: r.passage_id}) MERGE (f)-[:STATED_IN]->(p)""",
        [asdict(f) for f in facts],
    )
    # Link each fact to the entities it is about, and to the entity it names as its value.
    for rel, attr in (("ABOUT", "subject"), ("VALUE", "value")):
        groups: dict[str, list[dict]] = {}
        for f in facts:
            parsed = entity(getattr(f, attr))
            if parsed:
                label, _, key = parsed
                groups.setdefault(label, []).append({"id": f.id, "key": key})
        for label, rows in groups.items():
            prop = ENTITY_KEYS[label]
            _run(
                graph,
                f"UNWIND $rows AS r MATCH (f:Fact {{id: r.id}}) MERGE (e:{label} {{{prop}: r.key}}) MERGE (f)-[:{rel}]->(e)",
                rows,
            )
    return len(facts)
