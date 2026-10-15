"""Reading beyond pull requests: conversation passages, choosing them by signal, decision records, the repository's
wiki, discussions, comment threads and releases, uploaded Slack, Notion and Confluence exports, and the Sources view."""

import io
import json
import zipfile

import pytest
from fastapi.testclient import TestClient

from canon.api.app import create_app
from canon.decisions.build import build as build_decisions
from canon.extract.facts import Entities, choose, conversation_score, Mentions, to_facts
from canon.fixes import build as build_fixes
from canon.graph.db import ensure_schema
from canon.graph.writer import write_batch
from canon.ingest import ingest_upload
from canon.sources.repo import decision_kind, load_repo
from canon.sources.summary import summary
from canon.sources.text import Turn, turn_passages
from canon.sources.uploads import UploadError, parse, parse_pages, parse_slack, read_zip
from canon.types import Batch, Doc, Fact, Passage
from exports import confluence_zip, notion_zip, slack_zip
from cloud_kit import REPO, SLUG, make, sign_in, tc

ENTITIES = Entities(areas={"billing": "Billing"}, teams={"payments": "Payments", "platform": "Platform"}, people={"maya": "Maya"})


# ----- conversation passages ---------------------------------------------------------------------------------------


def test_turn_passages_say_who_said_it_and_when():
    turns = [
        Turn("maya", "2026-09-01T09:00:00Z", "We decided to stop Friday deploys.", "maya"),
        Turn("maya", "2026-09-01T09:01:00Z", "Hotfixes need approval.", "maya"),
        Turn("A community member", "2026-09-02T10:00:00Z", "Thanks!"),
        Turn("tomas", "2026-09-03T10:00:00Z", "", "tomas"),  # empty: dropped
    ]
    merged = turn_passages("slack_thread:x", turns, merge=True)
    assert [p.text for p in merged] == [
        "maya, 2026-09-01:\nWe decided to stop Friday deploys.\nHotfixes need approval.",
        "A community member, 2026-09-02:\nThanks!",
    ]
    assert [(p.author, p.at) for p in merged] == [("maya", "2026-09-01"), (None, "2026-09-02")]
    assert len(turn_passages("x", turns)) == 3  # without merging, each turn is its own passage
    assert turn_passages("x", [Turn("a", "2026-01-01", "Yes", "a", "Answer")])[0].text.startswith("a (Answer), 2026-01-01:")


def test_conversations_are_chosen_by_signal_within_a_budget():
    docs = [Doc("handbook:a", "handbook", "A", "u", "2026-01-01"), Doc("slack:t", "slack_thread", "T", "", "2026-09-01"),
            Doc("issue:1", "issue", "Bug", "u", "2026-09-01")]
    page = Passage("handbook:a#1", "handbook:a", "The Platform team owns the on-call rotation.")
    decided = Passage("slack:t#1", "slack:t", "maya, 2026-09-01:\nWe decided: going forward there are no deploys on Fridays for the Platform team.", "maya", "2026-09-01")
    moved = Passage("slack:t#2", "slack:t", "priya, 2026-09-03:\nRefunds moved to the Payments team; the Billing area is no longer theirs.", None, "2026-09-03")
    bug = Passage("issue:1#1", "issue:1", "The chart does not load when I click on it and the page is blank, please help.")
    short = Passage("slack:t#3", "slack:t", "maya, 2026-09-01:\nWe decided yes.", "maya", "2026-09-01")
    batch = Batch(docs=docs, passages=[page, decided, moved, bug, short])
    mentions = Mentions(ENTITIES)
    assert conversation_score(mentions, bug, ENTITIES.people) == 0  # a bug report has no signal
    assert conversation_score(mentions, short, ENTITIES.people) == 0  # too short to hold a fact
    # A known speaker outranks a stranger saying as much.
    assert conversation_score(mentions, decided, ENTITIES.people) > conversation_score(mentions, moved, ENTITIES.people) > 0

    chosen, later = choose(batch, ENTITIES, limit=10, conversations=1)
    assert [p.id for p in chosen] == ["handbook:a#1", "slack:t#1"]
    assert [p.id for p in later] == ["slack:t#2"]  # over the budget: next run
    chosen, later = choose(batch, ENTITIES, limit=1, conversations=1)
    assert [p.id for p in chosen] == ["slack:t#1"] and [p.id for p in later] == ["handbook:a#1", "slack:t#2"]


def test_a_fact_from_a_message_holds_from_the_day_it_was_said():
    doc = Doc("slack:t", "slack_thread", "T", "", "2026-09-30")
    passage = Passage("slack:t#1", "slack:t", "maya, 2026-09-01:\n...", "maya", "2026-09-01")
    row = {"subject": "topic:friday-deploys", "predicate": "policy", "value": "No deploys on Fridays", "text": "No deploys on Fridays."}
    (fact,) = to_facts([(passage, doc, row)])
    assert fact.valid_from == "2026-09-01" and fact.authority == 0


def test_writer_keeps_who_said_what(graph):
    ensure_schema(graph)
    batch = Batch(docs=[Doc("slack:t", "slack_thread", "T", "", "2026-09-01")],
                  passages=[Passage("slack:t#1", "slack:t", "maya, 2026-09-01:\nHi", "name:maya", "2026-09-01")])
    write_batch(graph, batch)
    rows = graph.query("MATCH (x:Person)-[s:SAID]->(p:Passage)<-[:HAS]-(d:Document) RETURN x.handle, s.at, p.at, d.read_at IS NOT NULL").result_set
    assert rows == [["name:maya", "2026-09-01", "2026-09-01", True]]


def test_stale_lines_in_chats_are_history_not_fixes(graph):
    from kit import Kit

    kit = Kit(graph).team("billing", "Billing").team("payments", "Payments").area("refunds", "Refunds")
    kit.fact("own", "area:refunds", "owned_by", "team:payments", kind="ownership_map", on="2026-01-01")
    kit.fact("page", "area:refunds", "owned_by", "team:billing", kind="handbook", on="2026-03-01")
    kit.fact("chat", "area:refunds", "owned_by", "team:billing", kind="issue", on="2026-04-01")
    kit.write()
    graph.query("MATCH (f:Fact) WHERE f.id IN ['page', 'chat'] SET f.stale = true")
    build_fixes(graph)
    on = graph.query("MATCH (:Fix)-[:ON]->(d:Document) RETURN d.kind").result_set
    assert on == [["handbook"]]


# ----- the repository: decision records, wiki, threads, discussions, releases ---------------------------------------


@pytest.mark.parametrize(
    "path, meta, kind",
    [
        ("docs/adr/0001-use-postgres.md", {}, "adr"),
        ("doc/adr/0002-x.md", {}, "adr"),
        ("docs/decisions/use-kafka.md", {}, "adr"),
        ("rfcs/0012-plugins.md", {}, "rfc"),
        ("rfc/text/0001.md", {}, "rfc"),
        ("docs/adr/README.md", {}, None),
        ("docs/notes/storage.md", {"type": "ADR"}, "adr"),
        ("docs/notes/plugins.md", {"title": "RFC: plugin API"}, "rfc"),
        ("docs/guide.md", {"title": "Getting started"}, None),
    ],
)
def test_decision_records_by_folder_or_frontmatter(path, meta, kind):
    assert decision_kind(path, meta) == kind


ADR_1 = """# 1. Use MySQL

## Status

Superseded by [ADR-0003](0003-use-postgres.md)

## Decision

We will use MySQL for the main database.
"""
ADR_2 = """---
status: proposed
---
# 2. Shard by tenant

We could shard the database by tenant.
"""
ADR_3 = """# 3. Use Postgres

## Status

Accepted

## Decision

We will use Postgres for the main database. It replaces ADR-0001.
"""


def repo_fetch(name):
    commit = lambda d, h="maya": [{"sha": "a" * 40, "date": d, "handle": h}]  # noqa: E731
    return {
        "meta": {"default_branch": "main"},
        "docs": [
            {"path": "docs/adr/0001-use-mysql.md", "text": ADR_1, "commits": commit("2026-01-05T00:00:00Z")},
            {"path": "docs/adr/0002-shard-by-tenant.md", "text": ADR_2, "commits": commit("2026-02-05T00:00:00Z")},
            {"path": "docs/adr/0003-use-postgres.md", "text": ADR_3, "commits": commit("2026-03-05T00:00:00Z")},
        ],
        "wiki": [{"path": "Release-checklist.md", "text": "# Release checklist\n\nThe release captain tags the build.",
                  "commits": commit("2026-04-01T00:00:00Z", "tomas")}],
        "issues": [{
            "number": 8, "title": "Flaky deploys", "body": "Deploys fail.", "url": "https://github.com/acme/app/issues/8",
            "created_at": "2026-05-05T00:00:00Z", "author": "dave",
            "comments": [
                {"author": "maya", "at": "2026-05-06T00:00:00Z", "body": "We moved deploys to the new runner going forward."},
                {"author": "tomas", "at": "2026-05-07T00:00:00Z", "body": ""},
            ],
        }],
        "discussions": [{
            "number": 3, "title": "Which database?", "body": "Postgres or MySQL?", "url": "https://github.com/acme/app/discussions/3",
            "created_at": "2026-02-01T00:00:00Z", "updated_at": "2026-02-03T00:00:00Z", "author": "dave",
            "answer": {"author": "maya", "at": "2026-02-02T00:00:00Z", "body": "Postgres. See ADR-0003."},
            "comments": [{"author": "maya", "at": "2026-02-02T00:00:00Z", "body": "Postgres. See ADR-0003."},
                         {"author": "tomas", "at": "2026-02-03T00:00:00Z", "body": "Agreed."}],
        }],
        "releases": [{"tag": "v2.0.0", "name": "Kestrel 2.0", "url": "https://github.com/acme/app/releases/tag/v2.0.0",
                      "published_at": "2026-06-01T00:00:00Z", "author": "tomas", "body": "## Changes\n\n- Postgres is the only database."}],
    }.get(name)


def test_load_repo_reads_wiki_threads_discussions_and_releases():
    batch = load_repo("acme/app", repo_fetch)
    docs = {d.id: d for d in batch.docs}
    assert docs["adr:docs/adr/0003-use-postgres.md"].kind == "adr"
    assert docs["adr:docs/adr/0003-use-postgres.md"].decided_at == "2026-03-05"
    wiki = docs["wiki:Release-checklist.md"]
    assert wiki.kind == "wiki" and wiki.url == "https://github.com/acme/app/wiki/Release-checklist"
    thread = docs["thread:issue:8"]
    assert thread.kind == "comment_thread" and thread.updated_at == "2026-05-06"
    said = [p for p in batch.passages if p.doc_id == "thread:issue:8"]
    assert [(p.author, p.at) for p in said] == [("maya", "2026-05-06")]
    assert said[0].text.startswith("maya, 2026-05-06:\nWe moved deploys")
    talk = [p.text.split("\n")[0] for p in batch.passages if p.doc_id == "discussion:3"]
    assert talk == ["dave, 2026-02-01:", "maya (Answer), 2026-02-02:", "tomas, 2026-02-03:"]  # the answer once
    assert docs["release:v2.0.0"].kind == "release" and docs["release:v2.0.0"].updated_at == "2026-06-01"
    acts = {(a.handle, a.doc_id, a.rel) for a in batch.activity}
    assert {("maya", "thread:issue:8", "COMMENTED"), ("dave", "discussion:3", "AUTHORED"), ("tomas", "release:v2.0.0", "AUTHORED")} <= acts


def test_decision_records_become_decisions_with_status_and_supersession(graph):
    ensure_schema(graph)
    write_batch(graph, load_repo("acme/app", repo_fetch))
    records = [
        {"path": d["path"], "doc_id": f"adr:{d['path']}", "text": d["text"], "created_at": d["commits"][0]["date"],
         "updated_at": d["commits"][0]["date"]}
        for d in repo_fetch("docs")
    ]
    build_decisions(graph, records, [])
    rows = graph.query("MATCH (d:Decision) RETURN d.id, d.status, d.decided_at ORDER BY d.id").result_set
    assert rows == [
        ["0001-use-mysql", "superseded", "2026-01-05"],
        ["0002-shard-by-tenant", "proposed", None],
        ["0003-use-postgres", "accepted", "2026-03-05"],
    ]
    edge = graph.query("MATCH (a:Decision)-[e:SUPERSEDED_BY]->(b:Decision) RETURN a.id, b.id, e.by").result_set
    assert edge == [["0001-use-mysql", "0003-use-postgres", "reference"]]


# ----- uploads -------------------------------------------------------------------------------------------------------


def _zip(files: dict[str, bytes], method=zipfile.ZIP_DEFLATED) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", method) as z:
        for name, data in files.items():
            z.writestr(name, data)
    return buf.getvalue()


def test_read_zip_refuses_what_is_not_safe():
    with pytest.raises(UploadError, match="not a zip"):
        read_zip(b"hello", (".json",))
    bomb = _zip({"a.json": b"0" * (8 * 1024 * 1024)})  # 8 MB of zeros packs into a few KB
    with pytest.raises(UploadError, match="far more than its size"):
        read_zip(bomb, (".json",))
    files = read_zip(_zip({"../evil.json": b"{}", "/abs.json": b"{}", "__MACOSX/x.json": b"{}", "ok.json": b"[]", "img.png": b"x"}), (".json",))
    assert list(files) == ["ok.json"]
    nested = _zip({"Export-Part-1.zip": _zip({"page.md": b"# Hi"})}, zipfile.ZIP_STORED)
    assert list(read_zip(nested, (".md",))) == ["Export-Part-1.zip/page.md"]


def test_slack_export_becomes_threads():
    batch = parse_slack(read_zip(slack_zip(wrap="Kestrel export"), (".json",)))
    docs = {d.id: d for d in batch.docs}
    assert {d.kind for d in batch.docs} == {"slack_thread"}
    assert len(batch.docs) == 2  # the deploys thread and the payments conversation; no DMs
    deploys = next(d for d in batch.docs if d.id.startswith("slack_thread") or d.id.startswith("slack:eng-deploys"))
    assert deploys.title.startswith("#eng-deploys: Proposal: should we stop deploying")
    assert deploys.updated_at == "2026-09-01" and deploys.url == ""
    texts = [p.text for p in batch.passages if p.doc_id == deploys.id]
    assert texts[0].startswith("Maya L, 2026-09-01:\nProposal")
    assert any(t.startswith("Tomas Okafor, 2026-09-01:\nAgreed. @Maya L") for t in texts)
    assert not any("joined" in t or "Deploy 412" in t or "private note" in t for t in [p.text for p in batch.passages])
    payments = docs[next(i for i in docs if "payments" in i)]
    ptexts = [p.text for p in batch.passages if p.doc_id == payments.id]
    assert "refunds &amp;" not in ptexts[0] and "#payments" in ptexts[0] and "the refunds doc" in ptexts[0]
    assert {p.handle: p.name for p in batch.people} == {"name:maya-l": "Maya L", "name:tomas-okafor": "Tomas Okafor", "name:priya": "Priya"}
    with pytest.raises(UploadError, match="not a Slack export"):
        parse("slack", _zip({"notes.json": b"[]"}))


def test_notion_and_confluence_pages_keep_their_dates():
    notion = parse_pages(read_zip(notion_zip(), (".md", ".html")), today="2026-10-15")
    pages = {d.title: d for d in notion.docs}
    assert {d.kind for d in notion.docs} == {"notion_page"}
    assert pages["On-call"].updated_at == "2026-08-14" and pages["Expenses"].updated_at == "2026-03-03"
    assert any("Platform team runs the on-call rotation" in p.text for p in notion.passages)

    confluence = parse_pages(read_zip(confluence_zip(), (".md", ".html")), today="2026-10-15")
    (page,) = confluence.docs  # the space index is not a page
    assert page.kind == "confluence_page" and page.title == "Release process" and page.updated_at == "2026-07-21"
    text = " ".join(p.text for p in confluence.passages)
    assert "ships every Tuesday" in text and "Document generated" not in text and "color: red" not in text


def test_an_upload_goes_through_the_shared_pipeline(graph):
    steps = []
    out = ingest_upload(graph, "slack", slack_zip(), filename="kestrel.zip", by="maya", report=lambda **kw: steps.append(kw.get("step")))
    assert [s for s in steps if s][:4] == ["read", "unpack", "upload", "write"] and "link" in steps
    assert out["counts"]["documents"] == 2 and out["notes"]
    conn = graph.query("MATCH (c:Connection) RETURN c.kind, c.label, c.status, c.config").result_set
    assert conn[0][:3] == ["upload", "Slack export", "done"]
    assert json.loads(conn[0][3]) == {"format": "slack", "filename": "kestrel.zip", "by": "maya", "documents": 2, "passages": 5, "people": 3}
    view = summary(graph)
    chats = next(f for f in view["families"] if f["key"] == "chats")
    assert chats["documents"] == 2 and chats["kinds"][0]["kind"] == "slack_thread" and chats["kinds"][0]["speakers"] == 3
    assert view["connections"][0]["kind"] == "upload"


# ----- the API -------------------------------------------------------------------------------------------------------


def test_upload_route(db, accounts_graph, made, graph):
    from canon.demo_seed import seed

    seed(graph)
    cloud, _ = make(db, accounts_graph, ingest=lambda g, repo, token, report: g.query("CREATE (:Document {id: 'doc:x'})") and {})
    graphs = {"demo": graph}
    app = create_app(cloud=cloud, graph_for=lambda ws: graphs.get(ws) or (cloud.graph(ws) if ws == SLUG else None))
    anon, alice = tc(app), tc(app)
    sign_in(alice)
    made.append(SLUG)
    assert alice.post("/api/workspaces", json={"repo": REPO}).status_code == 201

    files = {"file": ("kestrel.zip", slack_zip(), "application/zip")}
    assert anon.post(f"/api/w/{SLUG}/uploads", data={"kind": "slack"}, files=files).status_code == 401
    assert alice.post("/api/w/demo/uploads", data={"kind": "slack"}, files=files).status_code == 403
    assert alice.post(f"/api/w/{SLUG}/uploads", data={"kind": "pdf"}, files=files).status_code == 422
    bad = {"file": ("x.zip", b"not a zip", "application/zip")}
    assert alice.post(f"/api/w/{SLUG}/uploads", data={"kind": "slack"}, files=bad).status_code == 422
    huge = alice.post(f"/api/w/{SLUG}/uploads", content=b"x", headers={"content-length": str(60 * 1024 * 1024), "content-type": "multipart/form-data; boundary=b"})
    assert huge.status_code == 413

    res = alice.post(f"/api/w/{SLUG}/uploads", data={"kind": "slack"}, files=files)
    assert res.status_code == 202 and res.json()["job"]["kind"] == "upload"
    job = alice.get(f"/api/w/{SLUG}/jobs/latest").json()["job"]
    assert job["status"] == "done" and job["counts"]["threads"] == 2

    view = alice.get(f"/api/w/{SLUG}/sources").json()
    assert view["can_upload"] is True
    chats = next(f for f in view["families"] if f["key"] == "chats")
    assert chats["documents"] == 2
    assert anon.get("/api/w/demo/sources").json()["can_upload"] is False

    # A broken export fails the job with a sentence a person can act on.
    broken = {"file": ("x.zip", _zip({"notes.json": b"[]"}), "application/zip")}
    alice.post(f"/api/w/{SLUG}/uploads", data={"kind": "slack"}, files=broken)
    job = alice.get(f"/api/w/{SLUG}/jobs/latest").json()["job"]
    assert job["status"] == "failed" and "not a Slack export" in job["error"]
