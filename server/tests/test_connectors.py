"""The API-token connectors against recorded responses: what each reads, its cursor, its caps, rate limits and the
errors it shows. Nothing here calls a real service."""

import json

import httpx
import pytest

from canon.sources.client import SourceError
from canon.sources.confluence import ConfluenceConnector
from canon.sources.identity import email_key
from canon.sources.jira import JiraConnector
from canon.sources.linear import LinearConnector
from canon.sources.notion import NotionConnector
from canon.sources.slack import SlackConnector
from recorded import Recorded

NOW = 1792065600.0  # 2026-10-15T12:00:00Z
ATL = {"email": "ana@kestrel.example", "token": "atl-good"}
SITE = {"site": "kestrel.atlassian.net"}


def quiet(**_):
    pass


@pytest.fixture
def api():
    return Recorded()


def slept():
    waits: list[float] = []
    return waits, waits.append


# ----- Slack -----------------------------------------------------------------------------------------------------


def test_slack_reads_threads_and_days_from_channels_the_bot_is_in(api):
    s = SlackConnector("xoxb-good", http=api.client, sleep=lambda _: None, now=lambda: NOW)
    result = s.read(cursor=None, report=quiet)
    b = result.batch
    docs = {d.id: d for d in b.docs}
    thread = docs["slack:t0kestrel:c0eng:1791968400.000100"]
    assert thread.kind == "slack_thread" and thread.title.startswith("#eng: Decision: Billing moves")
    assert thread.url == "https://kestrel-eng.slack.com/archives/C0ENG/p1791968400000100"
    assert thread.updated_at == "2026-10-14"
    # Loose messages are grouped by channel and day; the join message is not knowledge.
    assert "slack:t0kestrel:c0eng:2026-10-14" in docs and "slack:t0kestrel:c0eng:2026-10-13" in docs
    turns = [p for p in b.passages if p.doc_id == thread.id]
    joined = "\n".join(p.text for p in turns)
    # Each run is a conversation turn: who said it and when, with its author kept for the graph.
    assert turns[0].text.startswith("Ana Ruiz, 2026-10-14:\nDecision: Billing moves to the Payments team from November. @Ben Okafor owns")
    assert turns[0].author == email_key("ana@kestrel.example") and turns[0].at == "2026-10-14"
    assert "select * from invoices" not in joined  # code is dropped
    day = "\n".join(p.text for p in b.passages if p.doc_id.endswith(":2026-10-14"))
    # Ana's reminder and Ben's reply are separate runs; mentions and links read as words.
    assert "Ana Ruiz, 2026-10-14:\nReminder: the deploy freeze" in day and "Ben Okafor, 2026-10-14:\nThanks @Ana Ruiz" in day
    early = "\n".join(p.text for p in b.passages if p.doc_id.endswith(":2026-10-13"))
    assert "See the on-call page." in early and "has joined" not in early
    # A bot's message is read, but a bot is not a person.
    assert any(p.text.startswith("ci-bot, 2026-10-12:\nDeploy 412") and p.author is None for p in b.passages)
    # Channels the bot is not in, and archived ones, are not read.
    assert not any(":c0random:" in d or ":c0old:" in d for d in docs)


def test_slack_people_match_by_email_hash_and_never_store_email(api):
    s = SlackConnector("xoxb-good", http=api.client, sleep=lambda _: None, now=lambda: NOW)
    result = s.read(cursor=None, report=quiet)
    people = {p.handle: p.name for p in result.batch.people}
    assert people[email_key("ana@kestrel.example")] == "Ana Ruiz"
    assert people["slack:u0ben"] == "Ben Okafor"  # no email shared: the Slack id
    assert result.people_props[email_key("ana@kestrel.example")] == {"slack_id": "U0ANA"}
    assert "kestrel.example" not in json.dumps([p.__dict__ for p in result.batch.people])
    rels = {(a.handle, a.rel) for a in result.batch.activity if a.doc_id.endswith("1791968400.000100")}
    assert (email_key("ana@kestrel.example"), "AUTHORED") in rels and ("slack:u0ben", "COMMENTED") in rels


def test_slack_cursor_reads_only_recent_days_again(api):
    s = SlackConnector("xoxb-good", http=api.client, sleep=lambda _: None, now=lambda: NOW)
    first = s.read(cursor=None, report=quiet)
    state = json.loads(first.cursor)
    assert state["channels"]["C0ENG"] == "1791969600.000300"
    # A month later only the last week (whole days) is read again.
    later = SlackConnector("xoxb-good", {"rethread_days": 1}, http=api.client, sleep=lambda _: None, now=lambda: NOW + 30 * 86400)
    again = later.read(cursor=first.cursor, report=quiet)
    oldest = [c for c in api.calls if "conversations.history" in c[1] and "C0ENG" in c[1]][-1][1]
    assert "oldest=1791849600.000000" in oldest  # 2026-10-13T00:00Z: a day before the newest message, from midnight
    assert {d.id for d in again.batch.docs} >= {"slack:t0kestrel:c0eng:2026-10-14"}


def test_slack_caps_channels_and_notes_it(api):
    s = SlackConnector("xoxb-good", {"max_channels": 1}, http=api.client, sleep=lambda _: None, now=lambda: NOW)
    result = s.read(cursor=None, report=quiet)
    assert not any(":c0deploys:" in d.id for d in result.batch.docs)
    assert any("Read 1 of the 2 channels" in n for n in result.notes)
    assert any("groups:read" in n for n in result.notes)  # private channels need more scopes


def test_slack_waits_out_a_rate_limit(api):
    waits, sleep = slept()
    api.fail["conversations.history"] = [httpx.Response(429, headers={"Retry-After": "3"})]
    s = SlackConnector("xoxb-good", http=api.client, sleep=sleep, now=lambda: NOW)
    s.read(cursor=None, report=quiet)
    assert waits == [3.0]


def test_slack_stops_on_a_long_rate_limit_with_a_clear_message(api):
    api.fail["conversations.history"] = [httpx.Response(429, headers={"Retry-After": "900"})]
    s = SlackConnector("xoxb-good", http=api.client, sleep=lambda _: None, now=lambda: NOW)
    with pytest.raises(SourceError, match="Slack is rate limiting Canon"):
        s.read(cursor=None, report=quiet)


def test_slack_check_names_what_is_wrong(api):
    with pytest.raises(SourceError, match="did not accept this token"):
        SlackConnector("xoxb-bad", http=api.client).check()
    api.data["slack"]["auth.test.scopes"] = "channels:read"
    with pytest.raises(SourceError, match="missing the channels:history, users:read scopes"):
        SlackConnector("xoxb-good", http=api.client).check()


# ----- Notion ----------------------------------------------------------------------------------------------------


def test_notion_reads_pages_into_text_and_rows_into_owned_by_facts(api):
    n = NotionConnector("ntn_good", http=api.client, sleep=lambda _: None)
    result = n.read(cursor=None, report=quiet)
    docs = {d.id: d for d in result.batch.docs}
    page = docs["notion:1f2e3d4c00004000800000000000aaaa"]
    assert page.kind == "notion_page" and page.title == "Deploy policy" and page.updated_at == "2026-10-13"
    text = "\n".join(p.text for p in result.batch.passages if p.doc_id == page.id)
    assert text.startswith("When we deploy\nWe deploy every weekday") and "Friday deploys need approval from the Platform team." in text
    assert "- Anyone on call may roll back without asking." in text  # a nested block
    assert "API | Weekdays" in text and "make deploy" not in text
    row = docs["notion:5b6c7d8e00004000800000000000bbbb"]
    assert row.title == "Projects: Search relevance"
    row_text = "\n".join(p.text for p in result.batch.passages if p.doc_id == row.id)
    assert "Owner: Cal Diaz" in row_text and "Status: In progress" in row_text and "Due: 2026-11-30" in row_text
    assert "cal@kestrel.example" not in row_text  # email properties are not read
    (fact,) = result.batch.facts
    assert fact.subject == "area:search-relevance" and fact.predicate == "owned_by" and fact.authority == 2
    assert fact.value == f"person:{email_key('cal@kestrel.example')}"
    assert "Search relevance" in {a.name for a in result.batch.areas}
    # The creator and the last editor are people; a page's author is its creator.
    assert page.author == email_key("ana@kestrel.example")
    assert ("notion:u-ben", "AUTHORED") in {(a.handle, a.rel) for a in result.batch.activity if a.doc_id == page.id}
    assert result.cursor == "2026-10-13T08:30:00.000Z"


def test_notion_cursor_stops_at_pages_not_edited_since(api):
    n = NotionConnector("ntn_good", http=api.client, sleep=lambda _: None)
    result = n.read(cursor="2026-10-01T00:00:00.000Z", report=quiet)
    assert len(result.batch.docs) == 2  # the January page is older than the cursor
    assert not any("notion:aaaa" in d.id for d in result.batch.docs)
    assert sum("/search" in c[1] for c in api.calls) == 2  # it stopped on the second page


def test_notion_caps_pages(api):
    n = NotionConnector("ntn_good", {"max_pages": 1}, http=api.client, sleep=lambda _: None)
    result = n.read(cursor=None, report=quiet)
    assert len(result.batch.docs) == 1 and any("max_pages" in note for note in result.notes)


def test_notion_check_names_a_bad_token(api):
    with pytest.raises(SourceError, match="Notion did not accept the token"):
        NotionConnector("ntn_bad", http=api.client).check()
    assert NotionConnector("ntn_good", http=api.client).check() == {"workspace": "Kestrel"}


# ----- Linear ----------------------------------------------------------------------------------------------------


def test_linear_reads_teams_projects_issues_and_history(api):
    lin = LinearConnector("lin_api_good", http=api.client, sleep=lambda _: None)
    result = lin.read(cursor=None, report=quiet)
    b = result.batch
    ana, ben, cal = (email_key(f"{n}@kestrel.example") for n in ("ana", "ben", "cal"))
    teams = {t.slug: t for t in b.teams}
    assert set(teams["payments"].members) == {ana, ben}
    lead = next(f for f in b.facts if f.predicate == "owned_by")
    assert (lead.subject, lead.value, lead.authority) == ("area:billing-migration", f"person:{ben}", 2)
    docs = {d.id: d for d in b.docs}
    issue = docs["linear:pay-12"]
    assert issue.kind == "linear_issue" and issue.areas == ("billing-migration",) and issue.updated_at == "2026-10-14"
    text = "\n".join(p.text for p in b.passages if p.doc_id == issue.id)
    assert "Ben Okafor, 2026-10-02:\nBen handed this over to Cal" in text
    assert "On 2026-09-25 Ben Okafor moved PAY-12 from Todo to In Progress." in text
    # Reassignment is history: Ben's window closes the day Cal's opens.
    windows = sorted((f.value, f.valid_from, f.valid_to) for f in b.facts if f.subject == "topic:pay-12")
    assert windows == [(f"person:{ben}", "2026-09-21", "2026-10-02"), (f"person:{cal}", "2026-10-02", None)]
    # An issue assigned when it was made still says who has it.
    assert [(f.value, f.valid_to) for f in b.facts if f.subject == "topic:srch-7"] == [(f"person:{cal}", None)]
    rels = {(a.handle, a.rel) for a in b.activity if a.doc_id == issue.id}
    assert {(ana, "AUTHORED"), (cal, "AUTHORED"), (ben, "COMMENTED")} <= rels
    assert result.cursor == "2026-10-14T11:00:00.000Z"


def test_linear_cursor_filters_updated_issues(api):
    lin = LinearConnector("lin_api_good", http=api.client, sleep=lambda _: None)
    result = lin.read(cursor="2026-10-05T00:00:00.000Z", report=quiet)
    assert [d.id for d in result.batch.docs if d.kind == "linear_issue"] == ["linear:pay-12"]
    assert api.issue_filter == {"updatedAt": {"gt": "2026-10-05T00:00:00.000Z"}}
    assert result.cursor == "2026-10-14T11:00:00.000Z"


def test_linear_waits_for_its_rate_limit_reset(api):
    waits, sleep = slept()
    api.fail["api.linear.app"] = [httpx.Response(400, json={"errors": [{"message": "Rate limit exceeded", "extensions": {"code": "RATELIMITED"}}]},
                                                 headers={"Retry-After": "2"})]
    LinearConnector("lin_api_good", http=api.client, sleep=sleep).check()
    assert waits == [2.0]


def test_linear_check_names_a_bad_key(api):
    with pytest.raises(SourceError, match="Linear did not accept this API key"):
        LinearConnector("lin_api_bad", http=api.client).check()


# ----- Jira ------------------------------------------------------------------------------------------------------


def test_jira_reads_projects_and_issues_with_comments(api):
    j = JiraConnector(ATL, SITE, http=api.client, sleep=lambda _: None)
    result = j.read(cursor=None, report=quiet)
    b = result.batch
    docs = {d.id: d for d in b.docs}
    issue = docs["jira:ops-42"]
    assert issue.kind == "jira_issue" and issue.url == "https://kestrel.atlassian.net/browse/OPS-42"
    assert issue.areas == ("operations",) and issue.updated_at == "2026-10-11"
    text = "\n".join(p.text for p in b.passages if p.doc_id == issue.id)
    assert "Status: Done." in text and "two-week rotation from October" in text and "pagerduty" not in text
    assert "Eli Moss, 2026-10-01:\nAgreed. @Ana Ruiz will update the schedule." in text
    lead = next(f for f in b.facts if f.predicate == "owned_by")
    assert (lead.subject, lead.value, lead.authority) == ("area:operations", "person:jira:712020:aa11", 2)
    names = {p.handle: p.name for p in b.people}
    assert names[email_key("ana@kestrel.example")] == "Ana Ruiz" and "Automation for Jira" not in names.values()
    assert "updated >= -180d" in api.last_jql and api.last_jql.endswith("ORDER BY updated DESC")
    assert result.cursor == "2026-10-11T16:20:00.000+0000"


def test_jira_jql_starts_a_day_before_the_cursor_and_keeps_project_keys_safe(api):
    j = JiraConnector(ATL, {**SITE, "projects": ["OPS", "x) OR project = SECRET"]}, http=api.client, sleep=lambda _: None)
    j.read(cursor="2026-10-11T16:20:00.000+0000", report=quiet)
    assert api.last_jql == 'project in (OPS) AND updated >= "2026-10-10" ORDER BY updated DESC'


def test_jira_check_and_site_errors(api):
    with pytest.raises(SourceError, match="did not accept this email and API token"):
        JiraConnector({**ATL, "token": "nope"}, SITE, http=api.client).check()
    with pytest.raises(SourceError, match="Atlassian Cloud sites only"):
        JiraConnector(ATL, {"site": "https://169.254.169.254"}, http=api.client)
    with pytest.raises(SourceError, match="Atlassian Cloud sites only"):
        JiraConnector(ATL, {"site": "evil.example.com/.atlassian.net"}, http=api.client)
    assert JiraConnector(ATL, {"site": "kestrel"}, http=api.client).site == "https://kestrel.atlassian.net"


# ----- Confluence ------------------------------------------------------------------------------------------------


def test_confluence_reads_spaces_and_pages(api):
    c = ConfluenceConnector(ATL, SITE, http=api.client, sleep=lambda _: None)
    result = c.read(cursor=None, report=quiet)
    b = result.batch
    assert {a.slug for a in b.areas} == {"engineering", "people-ops"}
    docs = {d.id: d for d in b.docs}
    page = docs["confluence:101"]
    assert page.kind == "confluence_page" and page.updated_at == "2026-10-09" and page.areas == ("engineering",)
    assert page.url == "https://kestrel.atlassian.net/wiki/spaces/ENG/pages/101/Incident+response"
    text = "\n".join(p.text for p in b.passages if p.doc_id == page.id)
    assert text.startswith("Who responds\n") and "The Operations team owns incident response." in text
    assert "- Sev 1: within 5 minutes" in text and "pd trigger" not in text and "bash" not in text
    assert page.author == "confluence:712020:aa11"  # the owner; the last editor authored the latest version
    assert (email_key("ana@kestrel.example"), "AUTHORED") in {(a.handle, a.rel) for a in b.activity if a.doc_id == page.id}
    assert result.cursor == "2026-10-09T14:00:00.000Z"


def test_confluence_cursor_stops_at_older_versions(api):
    c = ConfluenceConnector(ATL, SITE, http=api.client, sleep=lambda _: None)
    result = c.read(cursor="2026-05-01T00:00:00.000Z", report=quiet)
    assert [d.id for d in result.batch.docs] == ["confluence:101"]


def test_confluence_follows_only_paths_on_its_own_site(api):
    api.data["confluence"]["spaces"][0]["_links"]["next"] = "https://evil.example.com/wiki/api/v2/spaces?cursor=x"
    c = ConfluenceConnector(ATL, SITE, http=api.client, sleep=lambda _: None)
    c.read(cursor=None, report=quiet)
    assert not any("evil.example.com" in call[1] for call in api.calls)
