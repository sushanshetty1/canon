"""Builds small graphs for tests: one document and one passage per fact unless told otherwise."""

from canon.graph.db import ensure_schema
from canon.graph.writer import write_batch
from canon.types import Area, Batch, Doc, Fact, Passage, Person, Team

AUTHORITY = {"ownership_map": 3, "team_page": 2, "rfc": 2, "handbook": 1, "pull": 1, "issue": 0, "forum": 0}


class Kit:
    def __init__(self, graph):
        self.graph = graph
        self.batch = Batch()
        ensure_schema(graph)

    def fact(self, fid, subject, predicate, value, *, kind="handbook", on="2026-01-01", doc=None, doc_updated=None,
             valid_to=None, text=None) -> Fact:
        doc_id = doc or f"{kind}:{fid}"
        if not any(d.id == doc_id for d in self.batch.docs):
            title = doc_id.split(":", 1)[1].replace("-", " ").capitalize()
            self.batch.docs.append(Doc(doc_id, kind, title, f"https://example.com/{doc_id}", doc_updated or on))
        index = sum(1 for p in self.batch.passages if p.doc_id == doc_id)
        text = text or f"{subject} {predicate} {value}."
        passage = Passage(f"{doc_id}#{index}", doc_id, text)
        fact = Fact(fid, subject, predicate, value, text, on, passage.id, AUTHORITY[kind], valid_to)
        self.batch.passages.append(passage)
        self.batch.facts.append(fact)
        return fact

    def team(self, slug, name, members=(), leads=()):
        self.batch.teams.append(Team(slug, name, tuple(members), tuple(leads)))
        for h in {*members, *leads}:
            if not any(p.handle == h for p in self.batch.people):
                self.batch.people.append(Person(h, h.replace("-", " ").title()))
        return self

    def area(self, slug, name):
        self.batch.areas.append(Area(slug, name))
        return self

    def write(self):
        write_batch(self.graph, self.batch)
        return self


def edges(graph, rel="SUPERSEDED_BY|RESTATES|CONTRADICTS") -> set[tuple]:
    rows = graph.query(f"MATCH (a:Fact)-[r:{rel}]->(b:Fact) RETURN type(r), a.id, b.id").result_set
    return {tuple(r) for r in rows}


def prop(graph, fid, name):
    return graph.query(f"MATCH (f:Fact {{id: $id}}) RETURN f.{name}", {"id": fid}).result_set[0][0]
