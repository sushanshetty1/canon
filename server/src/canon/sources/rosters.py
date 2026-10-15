"""Team rosters as sourced facts.

Connectors write who leads and who belongs to a team as graph edges (`LEADS`, `MEMBER_OF`), straight from structured
records such as PostHog's published team list. Ask answers from facts with a source, so this turns each team's
roster into one document with one passage, and its leads and members into facts stated in it (kind `roster`, authority 2, like a
team page). People are named by their public GitHub handle only; people without one are left out of the text.

Run after a connector has written its batch. Idempotent.
"""

import hashlib
from datetime import date

from canon.graph.writer import write_batch
from canon.types import Batch, Doc, Fact, Passage

ROSTERS = """
MATCH (t:Team)
OPTIONAL MATCH (l:Person)-[:LEADS]->(t)
OPTIONAL MATCH (m:Person)-[:MEMBER_OF]->(t)
RETURN t.slug, coalesce(t.name, t.slug), collect(DISTINCT l.handle), collect(DISTINCT m.handle)
"""


def _public(handles: list[str]) -> list[str]:
    return sorted(h for h in handles if h and not h.startswith("name:"))


def roster_batch(graph, *, team_url: str, as_of: str | None = None) -> Batch:
    """`team_url` is a format string for a team's public page, e.g. "https://posthog.com/teams/{slug}"."""
    as_of = as_of or date.today().isoformat()
    batch = Batch()
    for slug, name, leads, members in graph.query(ROSTERS).result_set:
        leads, members = _public(leads), _public(members)
        if not leads and not members:
            continue
        doc = Doc(f"roster:{slug}", "roster", f"{name} team roster", team_url.format(slug=slug), as_of)
        lines = []
        if leads:
            lines.append(f"{name} is led by {', '.join(leads)}.")
        if members:
            lines.append(f"Members of {name}: {', '.join(members)}.")
        text = " ".join(lines)
        passage = Passage(f"{doc.id}#{hashlib.sha1(text.encode()).hexdigest()[:10]}", doc.id, text)
        batch.docs.append(doc)
        batch.passages.append(passage)
        for predicate, handles, sentence in (
            ("leads", leads, "{h} leads the {name} team."),
            ("member_of", members, "{h} is a member of the {name} team."),
        ):
            for h in handles:
                fid = hashlib.sha1(f"person:{h}|{predicate}|team:{slug}|{passage.id}".encode()).hexdigest()[:16]
                batch.facts.append(
                    Fact(fid, f"person:{h}", predicate, f"team:{slug}", sentence.format(h=h, name=name), as_of, passage.id, 2)
                )
    return batch


def write_rosters(graph, *, team_url: str, as_of: str | None = None) -> int:
    batch = roster_batch(graph, team_url=team_url, as_of=as_of)
    write_batch(graph, batch)
    return len(batch.facts)
