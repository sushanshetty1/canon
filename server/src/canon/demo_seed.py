"""A small made-up company, Kestrel, for demos before a real ingest: `canon seed demo`.

It has what Canon is built to catch:

- session replay moved from Product analytics to Replay in June, and a handbook page edited in August still names
  Product analytics (a stale page);
- notebooks moved to Data tools in September, replacing an older handbook page;
- two current handbook pages disagree about deploying on Fridays (a dispute);
- billing has an owner and a lead but nothing else written down, for the "who to ask" case.

Every URL is under example.com. The people are invented.
"""

import hashlib

from canon.graph.db import ensure_schema
from canon.graph.writer import write_batch
from canon.types import Activity, Area, Batch, Doc, Fact, Passage, Person, Team
from canon.verify.supersede import link

AUTHORITY = {"ownership_map": 3, "team_page": 2, "rfc": 2, "handbook": 1, "pull": 1, "issue": 0, "forum": 0}
BASE = "https://kestrel.example.com"

PEOPLE = [
    ("name:mara-okafor", "Mara Okafor", "Engineering lead, Replay"),
    ("name:lea-fischer", "Lea Fischer", "Product engineer"),
    ("name:jonas-weber", "Jonas Weber", "Engineering lead, Data tools"),
    ("name:sam-adeyemi", "Sam Adeyemi", "Product engineer"),
    ("name:priya-raman", "Priya Raman", "Engineering lead, Product analytics"),
    ("name:tomas-silva", "Tomas Silva", "Engineering lead, Platform"),
    ("name:ines-carvalho", "Ines Carvalho", "Engineering lead, Billing"),
]
TEAMS = [
    ("replay", "Replay", ["name:mara-okafor", "name:lea-fischer"], ["name:mara-okafor"]),
    ("data-tools", "Data tools", ["name:jonas-weber", "name:sam-adeyemi"], ["name:jonas-weber"]),
    ("product-analytics", "Product analytics", ["name:priya-raman"], ["name:priya-raman"]),
    ("platform", "Platform", ["name:tomas-silva"], ["name:tomas-silva"]),
    ("billing", "Billing", ["name:ines-carvalho"], ["name:ines-carvalho"]),
]
AREAS = [("session-replay", "Session replay"), ("notebooks", "Notebooks"), ("feature-flags", "Feature flags"), ("billing", "Billing")]

# (doc id, kind, title, path, updated_at, author, [(passage text, [(subject, predicate, value, fact text, valid_to)])])
DOCS = [
    ("ownership_map:3f9c2a71d0", "ownership_map", "Ownership map: first owners", "ownership/commit/3f9c2a71d0", "2026-02-10",
     "name:tomas-silva", [(
         "session-replay: Product analytics. notebooks: Product analytics. feature-flags: Platform. billing: Billing.",
         [("area:session-replay", "owned_by", "team:product-analytics", "Product analytics owns session replay.", "2026-06-18"),
          ("area:notebooks", "owned_by", "team:product-analytics", "Product analytics owns notebooks.", "2026-09-02"),
          ("area:feature-flags", "owned_by", "team:platform", "Platform owns feature flags.", None),
          ("area:billing", "owned_by", "team:billing", "Billing owns billing.", None)])]),
    ("ownership_map:8b41e6c5f2", "ownership_map", "Ownership map: session replay moves to Replay", "ownership/commit/8b41e6c5f2",
     "2026-06-18", "name:mara-okafor", [(
         "session-replay: Product analytics changed to session-replay: Replay.",
         [("area:session-replay", "owned_by", "team:replay", "Replay owns session replay.", None)])]),
    ("ownership_map:c07d93ab14", "ownership_map", "Ownership map: notebooks move to Data tools", "ownership/commit/c07d93ab14",
     "2026-09-02", "name:jonas-weber", [(
         "notebooks: Product analytics changed to notebooks: Data tools.",
         [("area:notebooks", "owned_by", "team:data-tools", "Data tools owns notebooks.", None)])]),
    ("team_page:teams/replay", "team_page", "Replay team", "teams/replay", "2026-07-02", "name:mara-okafor", [(
        "The Replay team owns session replay, from the recorder in the browser to the player. Mara Okafor leads the team.",
        [("area:session-replay", "owned_by", "team:replay", "The Replay team owns session replay.", None),
         ("person:name:mara-okafor", "leads", "team:replay", "Mara Okafor leads the Replay team.", None)])]),
    ("team_page:teams/data-tools", "team_page", "Data tools team", "teams/data-tools", "2026-09-05", "name:jonas-weber", [(
        "Data tools builds notebooks and the SQL editor. Jonas Weber leads the team.",
        [("area:notebooks", "owned_by", "team:data-tools", "Data tools owns notebooks.", None),
         ("person:name:jonas-weber", "leads", "team:data-tools", "Jonas Weber leads the Data tools team.", None)])]),
    ("handbook:handbook/session-replay.md", "handbook", "Session replay", "handbook/session-replay", "2026-08-20",
     "name:priya-raman", [
         ("Session replay is owned by the Product analytics team. Questions about recordings go to #team-product-analytics.",
          [("area:session-replay", "owned_by", "team:product-analytics", "The Product analytics team owns session replay.", None)]),
         ("Recordings are kept for 30 days on the free plan and 90 days on paid plans.",
          [("topic:replay-retention", "policy", "30 days on free, 90 days on paid",
            "Session recordings are kept for 30 days on the free plan and 90 days on paid plans.", None)]),
     ]),
    ("handbook:handbook/notebooks.md", "handbook", "Notebooks", "handbook/notebooks", "2026-03-04", "name:priya-raman", [(
        "Notebooks are built and owned by Product analytics.",
        [("area:notebooks", "owned_by", "team:product-analytics", "Product analytics owns notebooks.", None)])]),
    ("handbook:handbook/engineering/deployments.md", "handbook", "Deployments", "handbook/engineering/deployments",
     "2026-09-10", "name:tomas-silva", [(
         "We do not deploy to production after 2pm on Fridays.",
         [("topic:friday-deploys", "decided", "no deploys after 2pm on fridays",
           "Nobody deploys to production after 2pm on Fridays.", None)])]),
    ("handbook:handbook/engineering/on-call.md", "handbook", "On-call", "handbook/engineering/on-call", "2026-09-24",
     "name:lea-fischer", [(
         "Deploys are fine on any day, Fridays included, as long as the on-call engineer approves.",
         [("topic:friday-deploys", "decided", "deploys any day with on-call approval",
           "Deploys are allowed on any day, including Fridays, with the on-call engineer's approval.", None)])]),
]
REVIEWS = [("name:lea-fischer", "ownership_map:8b41e6c5f2", "2026-06-17"), ("name:sam-adeyemi", "ownership_map:c07d93ab14", "2026-09-01")]


def fact_id(subject: str, predicate: str, value: str, passage_id: str) -> str:
    return hashlib.sha1(f"{subject}|{predicate}|{value}|{passage_id}".encode()).hexdigest()[:16]


def batch() -> Batch:
    b = Batch(
        people=[Person(*p) for p in PEOPLE],
        teams=[Team(slug, name, tuple(members), tuple(leads)) for slug, name, members, leads in TEAMS],
        areas=[Area(*a) for a in AREAS],
    )
    for doc_id, kind, title, path, updated, author, passages in DOCS:
        b.docs.append(Doc(doc_id, kind, title, f"{BASE}/{path}", updated, author))
        b.activity.append(Activity(author, doc_id, "AUTHORED", updated))
        for i, (text, facts) in enumerate(passages):
            pid = f"{doc_id}#{i}"
            b.passages.append(Passage(pid, doc_id, text))
            for subject, predicate, value, sentence, valid_to in facts:
                b.facts.append(Fact(fact_id(subject, predicate, value, pid), subject, predicate, value, sentence, updated,
                                    pid, AUTHORITY[kind], valid_to))
    b.activity += [Activity(h, d, "REVIEWED", at) for h, d, at in REVIEWS]
    return b


def seed(graph) -> dict[str, int]:
    ensure_schema(graph)
    counts = write_batch(graph, batch())
    return {**counts, **link(graph)}
