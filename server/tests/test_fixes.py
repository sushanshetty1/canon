import asyncio
import json

import httpx
import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from canon.api import fixes_routes
from canon.api.app import create_app
from canon.cloud.session import User
from canon.fixes import TransitionError, approve, build, dismiss, draft, get_fix, list_fixes
from canon.fixes.issues import FilingError, check_repo, dry_run, issue_body, issue_title
from canon.graph.writer import write_batch
from canon.types import Activity, Batch, Doc, Fact, Passage
from canon.verify.supersede import link

from kit import AUTHORITY, Kit

PAGE = "handbook:ai-products"
MCP_LINE = "The PostHog AI team [owns](/handbook/ownership) the MCP server, with Josh as the support contact."
PASSAGE = f"Current status\nMCP is in general availability. {MCP_LINE} We are working on tool discovery."
ME = User(id="1", login="dev", name="dev", token="t0ken")


def _page(kit, doc_id, title, text, facts, *, on="2026-09-23", kind="handbook", areas=(), author=None):
    """One page with one passage stating `facts`: [(id, subject, predicate, value, fact text)]."""
    kit.batch.docs.append(Doc(doc_id, kind, title, f"https://example.com/{doc_id.split(':', 1)[1]}", on, author, tuple(areas)))
    pid = f"{doc_id}#0"
    kit.batch.passages.append(Passage(pid, doc_id, text))
    for fid, subject, predicate, value, sentence in facts:
        kit.batch.facts.append(Fact(fid, subject, predicate, value, sentence, on, pid, AUTHORITY[kind]))
    if author:
        kit.batch.activity.append(Activity(author, doc_id, "AUTHORED", on))


def company(graph) -> Kit:
    """The MCP server moved from PostHog AI to Context & MCP on Sep 17; a handbook page edited Sep 23 still says
    PostHog AI."""
    kit = Kit(graph)
    kit.area("mcp-server", "MCP server").area("background-agents", "Background agents").area("notebooks", "Notebooks")
    kit.team("context-and-mcp", "Context & MCP", members=["richard"], leads=["richard"])
    kit.team("posthog-ai", "PostHog AI", members=["georgis"], leads=["georgis"])
    kit.team("surfaces", "Surfaces", members=["peter"], leads=["peter"])
    kit.team("data", "Data tools", members=["jonas"], leads=["jonas"])
    kit.fact("o1", "area:mcp-server", "owned_by", "team:posthog-ai", kind="ownership_map", on="2026-01-01",
             doc="ownership_map:c1", valid_to="2026-09-17", text="MCP server is owned by the PostHog AI team.")
    kit.fact("o2", "area:mcp-server", "owned_by", "team:context-and-mcp", kind="ownership_map", on="2026-09-17",
             doc="ownership_map:c2", text="MCP server is owned by the Context & MCP team.")
    kit.fact("o3", "area:notebooks", "owned_by", "team:data", kind="ownership_map", on="2026-02-01",
             doc="ownership_map:c3", text="Notebooks is owned by the Data tools team.")
    _page(kit, PAGE, "AI products", PASSAGE,
          [("h1", "area:mcp-server", "owned_by", "team:posthog-ai", "The PostHog AI team owns the MCP server.")],
          author="ian")
    return kit


def built(graph) -> Kit:
    kit = company(graph).write()
    link(graph)
    build(graph)
    return kit


class Model:
    """A stand-in drafter: the first answer for the passage, then strict rewrites in order."""

    def __init__(self, edits, strict=()):
        self.edits, self.strict, self.calls = edits, list(strict), []

    async def json(self, system, prompt, schema):
        self.calls.append(prompt)
        if "edits" in schema["properties"]:
            return {"edits": self.edits}
        return {"new": self.strict.pop(0) if self.strict else ""}


def entail_if(*good):
    seen = []

    async def entail(text, facts):
        seen.append((text, facts))
        return {"supported": text in good, "past": False}

    entail.seen = seen
    return entail


def _draft(graph, model, entail):
    return asyncio.run(draft(graph, model=model, entail=entail))


def _routed(graph, fid):
    rows = graph.query(
        "MATCH (:Fix {id: $id})-[r:ROUTED_TO]->(n) RETURN r.role, coalesce(n.slug, n.handle) ORDER BY r.role", {"id": fid}
    ).result_set
    return [tuple(r) for r in rows]


# --- Build and routing ------------------------------------------------------------------------------


def test_build_opens_a_fix_routed_to_the_team_that_owns_the_area_now(graph):
    built(graph)
    [fix] = list_fixes(graph)
    assert fix["status"] == "open" and fix["page"]["title"] == "AI products"
    assert [f["fact_id"] for f in fix["stale"]] == ["h1"] and [f["fact_id"] for f in fix["evidence"]] == ["o2"]
    assert _routed(graph, fix["id"]) == [("lead", "richard"), ("owner", "context-and-mcp")]
    assert fix["routed"][0] == {"kind": "team", "key": "context-and-mcp", "name": "Context & MCP", "role": "owner"}
    assert "Context & MCP owns MCP server" in fix["reason"] and "ownership map since Sep 17, 2026" in fix["reason"]


def test_a_page_about_an_area_goes_to_that_area_owner(graph):
    kit = company(graph)
    _page(kit, "handbook:notebooks-faq", "Notebooks FAQ", "The PostHog AI team owns the MCP server.",
          [("h2", "area:mcp-server", "owned_by", "team:posthog-ai", "The PostHog AI team owns the MCP server.")],
          areas=["notebooks"])
    kit.write()
    link(graph)
    build(graph)
    fix = next(f for f in list_fixes(graph) if f["page"]["id"] == "handbook:notebooks-faq")
    assert _routed(graph, fix["id"]) == [("owner", "data")]
    assert fix["reason"] == "Data tools owns Notebooks, which this page is about."


def test_without_an_owning_team_the_page_author_gets_it(graph):
    kit = Kit(graph)
    kit.fact("r1", "topic:friday-deploys", "decided", "no deploys on fridays", kind="rfc", on="2026-01-01")
    _page(kit, "handbook:deploys", "Deploys", "Deploy any day.",
          [("h3", "topic:friday-deploys", "decided", "deploy any day", "Deploys are fine any day.")],
          on="2026-03-01", author="alice")
    kit.write()
    link(graph)
    build(graph)
    [fix] = list_fixes(graph)
    assert _routed(graph, fix["id"]) == [("author", "alice")]
    assert "last author" in fix["reason"] and "Mar 1, 2026" in fix["reason"]


def test_build_is_idempotent(graph):
    built(graph)
    first = list_fixes(graph)
    again = build(graph)
    assert again["created"] == 0 and again["open"] == 1
    assert [f["id"] for f in list_fixes(graph)] == [f["id"] for f in first]
    assert len(_routed(graph, first[0]["id"])) == 2
    assert graph.query("MATCH (:Fix)-[r]->() RETURN count(r)").result_set[0][0] == 5  # ABOUT, EVIDENCE, ON, 2 ROUTED_TO


def test_a_fix_closes_itself_when_the_page_is_corrected_and_reopens_if_it_comes_back(graph):
    kit = built(graph)
    [fix] = list_fixes(graph)
    page = next(d for d in kit.batch.docs if d.id == PAGE)
    corrected = Passage(f"{PAGE}#1", PAGE, "The Context & MCP team owns the MCP server.")
    write_batch(graph, Batch(docs=[page], passages=[corrected]))
    link(graph)
    out = build(graph)
    assert out["resolved"] == 1 and out["open"] == 0
    assert get_fix(graph, fix["id"])["status"] == "resolved" and list_fixes(graph, ["open"]) == []

    write_batch(graph, Batch(docs=[page], passages=[Passage(f"{PAGE}#0", PAGE, PASSAGE)]))
    link(graph)
    assert build(graph)["reopened"] == 1 and get_fix(graph, fix["id"])["status"] == "open"


def test_a_dismissed_fix_stays_dismissed(graph):
    built(graph)
    [fix] = list_fixes(graph)
    dismiss(graph, fix["id"], reason="This page is being retired.", user=ME)
    assert build(graph)["created"] == 0
    assert get_fix(graph, fix["id"])["status"] == "dismissed"


# --- Drafting ---------------------------------------------------------------------------------------

NEW = "The Context & MCP team [owns](/handbook/ownership) the MCP server, with Josh as the support contact."


def test_draft_rewrites_only_the_stale_sentence_and_checks_it(graph):
    built(graph)
    model = Model([{"facts": [0], "old": MCP_LINE, "new": NEW}])
    entail = entail_if(NEW)
    assert _draft(graph, model, entail)["drafted"] == 1
    [fix] = list_fixes(graph)
    assert fix["old"] == MCP_LINE and fix["new"] == NEW and fix["checked"] == ["o2"]
    # The check read the evidence fact.
    text, facts = entail.seen[0]
    assert text == NEW and any(f.startswith("MCP server is owned by the Context & MCP team.") for f in facts)
    assert len(model.calls) == 1 and "Holds now: MCP server is owned by the Context & MCP team." in model.calls[0]
    # Drafted fixes are not drafted again.
    assert _draft(graph, Model([]), entail)["passages"] == 0


def test_a_draft_that_fails_the_check_gets_one_strict_try(graph):
    built(graph)
    strict = "The Context & MCP team owns the MCP server."
    model = Model([{"facts": [0], "old": MCP_LINE, "new": NEW}], strict=[strict])
    entail = entail_if(strict)
    assert _draft(graph, model, entail)["drafted"] == 1
    [fix] = list_fixes(graph)
    assert fix["new"] == strict and len(model.calls) == 2
    # The strict try is checked against the evidence alone.
    assert len(entail.seen[1][1]) == 1


def test_a_draft_that_is_not_verified_is_rejected(graph):
    built(graph)
    model = Model([{"facts": [0], "old": MCP_LINE, "new": "Richard owns the MCP server."}], strict=["Richard owns it."])
    assert _draft(graph, model, entail_if())["rejected"] == 1
    [fix] = list_fixes(graph)
    assert fix["new"] is None and fix["old"] == MCP_LINE and "did not pass the check" in fix["draft_error"]
    with pytest.raises(TransitionError):
        approve(graph, fix["id"], repo="me/docs", user=ME, dry_run=True)


def test_a_line_that_is_not_in_the_passage_is_rejected(graph):
    built(graph)
    model = Model([{"facts": [0], "old": "The MCP server belongs to PostHog AI.", "new": NEW}])
    assert _draft(graph, model, entail_if(NEW))["rejected"] == 1
    assert "not found" in list_fixes(graph)[0]["draft_error"]


def test_the_old_line_is_found_despite_spacing(graph):
    built(graph)
    model = Model([{"facts": [0], "old": "  " + MCP_LINE.replace(" the MCP", "  the\nMCP"), "new": NEW}])
    _draft(graph, model, entail_if(NEW))
    assert list_fixes(graph)[0]["old"] == MCP_LINE


def test_two_stale_facts_in_one_sentence_become_one_fix(graph):
    kit = company(graph)
    kit.fact("o4", "area:background-agents", "owned_by", "team:surfaces", kind="ownership_map", on="2026-09-20",
             doc="ownership_map:c4", text="Background agents is owned by the Surfaces team.")
    line = "PostHog AI builds the MCP server and the background agents."
    _page(kit, "handbook:team-structure", "Team structure", f"The PostHog AI team\n{line}", [
        ("t1", "area:mcp-server", "owned_by", "team:posthog-ai", "PostHog AI builds the MCP server."),
        ("t2", "area:background-agents", "owned_by", "team:posthog-ai", "PostHog AI builds the background agents."),
    ])
    kit.write()
    link(graph)
    assert build(graph)["created"] == 3
    new = "Context & MCP builds the MCP server and Surfaces builds the background agents."
    model = Model([{"facts": [0, 1], "old": line, "new": new}])

    async def entail(text, facts):  # the page with MCP_LINE gets no edit from this model
        return {"supported": True, "past": False}

    out = _draft(graph, model, entail)
    assert out["merged"] == 1 and out["drafted"] == 1
    [fix] = [f for f in list_fixes(graph) if f["page"]["id"] == "handbook:team-structure"]
    assert {f["fact_id"] for f in fix["stale"]} == {"t1", "t2"} and {f["fact_id"] for f in fix["evidence"]} == {"o2", "o4"}
    assert {k for _, k in _routed(graph, fix["id"])} == {"context-and-mcp", "richard", "surfaces", "peter"}
    assert build(graph)["created"] == 0  # the merged fact stays covered


# --- The issue --------------------------------------------------------------------------------------


def drafted(graph) -> dict:
    built(graph)
    _draft(graph, Model([{"facts": [0], "old": MCP_LINE, "new": NEW}]), entail_if(NEW))
    return list_fixes(graph)[0]


def test_issue_body(graph):
    fix = drafted(graph)
    body = issue_body(fix)
    assert "[AI products](https://example.com/ai-products) says something that has since changed." in body
    # The old line struck, its relative link made absolute; then the new line.
    assert "> ~~The PostHog AI team [owns](https://example.com/handbook/ownership) the MCP server, with Josh as the support contact.~~" in body
    assert "> The Context & MCP team [owns](https://example.com/handbook/ownership) the MCP server" in body
    assert "- MCP server is owned by the Context & MCP team. Source: [C2, 2026-09-17](https://example.com/ownership_map:c2)." in body
    assert "**Owner:** Context & MCP, led by Richard (richard). Context & MCP owns MCP server" in body
    assert "@" not in body
    assert body.rstrip().endswith("_Found by Canon, which checks every page against a graph that knows when each fact held._")
    assert issue_title(fix) == "AI products: MCP server is owned by the Context & MCP team"


def test_issue_never_mentions_anyone(graph):
    fix = drafted(graph)
    fix["new"] = "Ask @richard about the MCP server."
    fix["routed"] = [{"kind": "person", "key": "alice", "name": "alice", "role": "author"}]
    body = issue_body(fix)
    assert "@richard" not in body and "@⁠richard" in body and "**Owner:** alice." in body


def test_repo_must_be_owner_name_and_never_posthog():
    assert check_repo(" me/docs ") == "me/docs" and check_repo("https://github.com/me/docs") == "me/docs"
    for bad in ("docs", "me/", "PostHog/posthog.com", "posthog/posthog", "a b/c", "me/docs/extra"):
        with pytest.raises(ValueError):
            check_repo(bad)


def no_network():
    def handler(request):
        raise AssertionError(f"GitHub was called: {request.url}")

    return httpx.MockTransport(handler)


def test_dry_run_records_the_issue_and_calls_nobody(graph, monkeypatch):
    monkeypatch.delenv("CANON_ISSUES_DRY_RUN", raising=False)
    assert dry_run() is True
    fix = drafted(graph)
    out = approve(graph, fix["id"], repo="me/docs", user=ME, transport=no_network())
    assert out["status"] == "filed" and out["approved_by"] == "dev"
    assert out["issue"]["dry_run"] is True and out["issue"]["url"] == f"dry-run://github.com/me/docs/issues/{fix['id']}"
    assert out["issue"]["body"] == issue_body(fix) and out["issue"]["repo"] == "me/docs"
    with pytest.raises(TransitionError):
        approve(graph, fix["id"], repo="me/docs", user=ME)
    with pytest.raises(TransitionError):
        dismiss(graph, fix["id"], reason="no", user=ME)


def test_filing_for_real_uses_the_users_token(graph):
    fix = drafted(graph)
    seen = []

    def github(request):
        seen.append(request)
        assert request.headers["authorization"] == "Bearer t0ken"
        if request.method == "GET":
            return httpx.Response(200, json={"permissions": {"push": True}, "has_issues": True})
        return httpx.Response(201, json={"html_url": "https://github.com/me/docs/issues/7", "number": 7})

    out = approve(graph, fix["id"], repo="me/docs", user=ME, dry_run=False, transport=httpx.MockTransport(github))
    assert [(r.method, r.url.path) for r in seen] == [("GET", "/repos/me/docs"), ("POST", "/repos/me/docs/issues")]
    sent = json.loads(seen[1].content)
    assert sent == {"title": issue_title(fix), "body": issue_body(fix)}
    assert out["status"] == "filed" and out["issue"]["url"] == "https://github.com/me/docs/issues/7"
    assert out["issue"]["dry_run"] is False


def test_filing_needs_push_access(graph):
    fix = drafted(graph)
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json={"permissions": {"push": False}}))
    with pytest.raises(FilingError, match="cannot push"):
        approve(graph, fix["id"], repo="someone/else", user=ME, dry_run=False, transport=transport)
    after = get_fix(graph, fix["id"])
    assert after["status"] == "approved" and "cannot push" in after["issue"]["error"]
    # Approved but not filed can be tried again, here in dry run.
    assert approve(graph, fix["id"], repo="me/docs", user=ME, dry_run=True)["status"] == "filed"


def test_dismiss_needs_a_reason(graph):
    built(graph)
    [fix] = list_fixes(graph)
    with pytest.raises(TransitionError):
        dismiss(graph, fix["id"], reason="   ", user=ME)
    out = dismiss(graph, fix["id"], reason="  Page is   archived. ", user=ME)
    assert out["status"] == "dismissed" and out["dismissed"] == {"by": "dev", "at": out["dismissed"]["at"], "reason": "Page is archived."}


# --- API --------------------------------------------------------------------------------------------


def _client(graph, user=None):
    """The graph is served as "team" (private, `user` a member) and as "demo" (public)."""
    from canon.cloud import access

    app = create_app(graph_for=lambda w: graph if w in ("demo", "team") else None, ask_fn=lambda g, q: None)
    def role(request: Request) -> None:
        request.state.workspace_access = "public" if request.path_params.get("ws") == "demo" else "member"

    app.dependency_overrides[access.workspace_access] = role
    app.dependency_overrides[fixes_routes.signed_in] = lambda: user
    return TestClient(app)


def test_api_lists_fixes_with_counts(graph):
    drafted(graph)
    body = _client(graph).get("/api/w/demo/fixes").json()
    assert body["counts"]["open"] == 1 and body["dry_run"] is True
    [fix] = body["fixes"]
    assert fix["new"] == NEW and fix["passage"]["text"] == PASSAGE
    assert _client(graph).get("/api/w/demo/fixes?status=filed").json()["fixes"] == []
    assert _client(graph).get("/api/w/demo/fixes?status=nope").status_code == 422
    assert _client(graph).get("/api/w/nowhere/fixes").status_code == 404


def test_api_writes_need_a_signed_in_member(graph, monkeypatch):
    monkeypatch.setenv("CANON_ISSUES_DRY_RUN", "1")
    fix = drafted(graph)
    url = f"/api/w/team/fixes/{fix['id']}"
    assert _client(graph).post(f"{url}/approve", json={"repo": "me/docs"}).status_code == 401
    assert _client(graph).post(f"{url}/dismiss", json={"reason": "no"}).status_code == 401

    client = _client(graph, ME)
    assert client.post(f"{url}/approve", json={"repo": "PostHog/posthog.com"}).status_code == 422
    assert client.post("/api/w/team/fixes/fix-nope/approve", json={"repo": "me/docs"}).status_code == 404
    res = client.post(f"{url}/approve", json={"repo": "me/docs"})
    assert res.status_code == 200 and res.json()["status"] == "filed" and res.json()["issue"]["dry_run"] is True
    assert client.post(f"{url}/dismiss", json={"reason": "late"}).status_code == 409
    assert client.get("/api/w/team/fixes?status=filed").json()["counts"]["filed"] == 1


def test_api_dismiss(graph):
    built(graph)
    [fix] = list_fixes(graph)
    res = _client(graph, ME).post(f"/api/w/team/fixes/{fix['id']}/dismiss", json={"reason": "Archived page."})
    assert res.status_code == 200 and res.json()["dismissed"]["reason"] == "Archived page."


def test_public_workspace_files_a_copy_and_keeps_the_queue(graph, monkeypatch):
    monkeypatch.setenv("CANON_ISSUES_DRY_RUN", "1")
    fix = drafted(graph)
    client = _client(graph, ME)
    res = client.post(f"/api/w/demo/fixes/{fix['id']}/approve", json={"repo": "me/docs"})
    assert res.status_code == 200 and res.json()["issue"]["url"].startswith("dry-run://") and res.json()["shared"] is False
    assert get_fix(graph, fix["id"])["status"] == "open"
    assert client.post(f"/api/w/demo/fixes/{fix['id']}/dismiss", json={"reason": "no"}).status_code == 403
