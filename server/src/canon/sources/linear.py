"""Linear, through a personal API key and its GraphQL API.

- **Teams** become `(:Team)`, with their members.
- **Projects** become areas, each with a short `team_page` document (its description, lead, status and teams). The
  project lead owns the area: an `owned_by` fact, authority 2, stated by that document.
- **Issues** become `linear_issue` documents: the description, then each comment (`Name on 2026-10-01: ...`), then
  the issue's history. An issue is about its project's area. The creator and assignee authored it, commenters
  commented on it.
- **History** is a dated record of what changed: every state change and reassignment is a line of its own
  (`On 2026-10-02 Ana moved ENG-12 from Todo to In Progress`). Who the issue was assigned to, and when, also becomes
  windowed `contact_for` facts (subject `topic:<issue id>`), so a reassignment closes the old fact and links the
  new one to it, the way the ownership map's history does.

Incremental: issues are filtered by `updatedAt > cursor`, newest first, at most `max_issues` per sync, 50 a page.
Linear's complexity-based rate limit answers `RATELIMITED`; the client waits for the reset it names.
"""

import time
from collections.abc import Callable

import httpx

from canon.sources.client import Client, SourceError, capped, retry_after
from canon.sources.connector import Report
from canon.sources.identity import People, SourceResult
from canon.sources.ownership import owner_windows
from canon.sources.text import day, fact_id, passages_of, slugify, split_passages
from canon.types import Activity, Area, Batch, Doc, Fact, Team

API = "https://api.linear.app/graphql"
USER = "id name displayName email"

VIEWER = "query { viewer { id name } organization { name urlKey } }"
TEAMS = f"""query Teams($after: String) {{
  teams(first: 50, after: $after) {{
    nodes {{ id key name description members(first: 100) {{ nodes {{ {USER} }} }} }}
    pageInfo {{ hasNextPage endCursor }}
  }}
}}"""
PROJECTS = f"""query Projects($after: String) {{
  projects(first: 50, after: $after) {{
    nodes {{ id name description url createdAt updatedAt status {{ name }} lead {{ {USER} }} teams {{ nodes {{ key name }} }} }}
    pageInfo {{ hasNextPage endCursor }}
  }}
}}"""
ISSUES = f"""query Issues($after: String, $filter: IssueFilter) {{
  issues(first: 50, after: $after, filter: $filter, orderBy: updatedAt) {{
    nodes {{
      id identifier title description url createdAt updatedAt
      state {{ name type }}
      team {{ key name }}
      project {{ id name }}
      creator {{ {USER} }}
      assignee {{ {USER} }}
      comments(first: 50) {{ nodes {{ body createdAt user {{ {USER} }} }} }}
      history(first: 50) {{ nodes {{ createdAt actor {{ {USER} }} fromState {{ name }} toState {{ name }} fromAssignee {{ {USER} }} toAssignee {{ {USER} }} }} }}
    }}
    pageInfo {{ hasNextPage endCursor }}
  }}
}}"""


def _rate_limited(r: httpx.Response) -> float | None:
    """Linear says it is rate limiting with a 429, or with a 400 whose error code is RATELIMITED."""
    if r.status_code == 429:
        return _reset_wait(r)
    if r.status_code == 400:
        try:
            errors = r.json().get("errors") or []
        except ValueError:
            return None
        if any(((e.get("extensions") or {}).get("code") == "RATELIMITED") for e in errors):
            return _reset_wait(r)
    return None


def _reset_wait(r: httpx.Response) -> float:
    reset = r.headers.get("x-ratelimit-requests-reset") or r.headers.get("x-ratelimit-complexity-reset")
    if reset:
        try:
            return max(1.0, float(reset) / 1000 - time.time())  # a unix time in milliseconds
        except ValueError:
            pass
    return retry_after(r, 10.0)


class LinearConnector:
    kind = "linear"
    label = "Linear"

    def __init__(self, token: str, config: dict | None = None, *, http: Callable | None = None,
                 sleep: Callable[[float], None] = time.sleep):
        self.config = config or {}
        # A personal API key goes in the header as is; only OAuth tokens take "Bearer".
        self.client = Client("Linear", http=http, sleep=sleep, rate_limited=_rate_limited,
                             headers={"Authorization": token, "Content-Type": "application/json"})
        self.max_issues = capped(self.config, "max_issues", 500, 3000)
        self.max_projects = capped(self.config, "max_projects", 100, 500)
        self.max_teams = capped(self.config, "max_teams", 50, 200)
        self.people = People("linear")

    def gql(self, query: str, variables: dict | None = None) -> dict:
        r = self.client.request("POST", API, json={"query": query, "variables": variables or {}})
        try:
            body = r.json()
        except ValueError:
            body = {}
        errors = body.get("errors") or []
        if r.status_code == 401 or any((e.get("extensions") or {}).get("code") == "AUTHENTICATION_ERROR" for e in errors):
            raise SourceError("Linear did not accept this API key. Make a new personal API key and paste it again.", status=401)
        if r.status_code != 200 or (errors and not body.get("data")):
            message = (errors[0].get("message") if errors else "") or f"status {r.status_code}"
            raise SourceError(f"Linear answered with an error ({message[:120]}).", status=r.status_code)
        return body.get("data") or {}

    def check(self) -> dict:
        data = self.gql(VIEWER)
        org = data.get("organization") or {}
        return {"organization": org.get("name") or "", "url_key": org.get("urlKey") or ""}

    def _nodes(self, query: str, key: str, limit: int, variables: dict | None = None):
        after = None
        got = 0
        while True:
            data = self.gql(query, {**(variables or {}), "after": after})
            conn = data.get(key) or {}
            for node in conn.get("nodes") or []:
                yield node
                got += 1
                if got >= limit:
                    return
            info = conn.get("pageInfo") or {}
            if not info.get("hasNextPage") or not info.get("endCursor"):
                return
            after = info["endCursor"]

    def user(self, u: dict | None) -> str | None:
        if not u or not u.get("id"):
            return None
        return self.people.add(u["id"], u.get("name") or u.get("displayName"), u.get("email"))

    def read(self, *, cursor: str | None, report: Report) -> SourceResult:
        notes: list[str] = []
        batch = Batch()
        report(step="read_linear", done=0, total=3)
        self.check()
        for t in self._nodes(TEAMS, "teams", self.max_teams):
            members = tuple(h for h in (self.user(m) for m in (t.get("members") or {}).get("nodes") or []) if h)
            batch.teams.append(Team(slugify(t.get("name") or t.get("key") or t["id"]), t.get("name") or t.get("key"), members))
        report(step="read_linear", done=1, total=3)
        projects: dict[str, str] = {}  # project id -> area slug
        for p in self._nodes(PROJECTS, "projects", self.max_projects):
            projects[p["id"]] = self._project(batch, p)
        report(step="read_linear", done=2, total=3)

        filt = {"updatedAt": {"gt": cursor}} if cursor else None
        issues = list(self._nodes(ISSUES, "issues", self.max_issues + 1, {"filter": filt}))
        if len(issues) > self.max_issues:
            notes.append(f"Read the {self.max_issues} most recently updated issues (max_issues).")
            issues = issues[: self.max_issues]
        newest = cursor
        for i, issue in enumerate(issues):
            if i % 25 == 0:
                report(step="read_linear", done=2 + i / max(len(issues), 1), total=3)
            self._issue(batch, issue, projects)
            if not newest or (issue.get("updatedAt") or "") > newest:
                newest = issue.get("updatedAt")
        report(step="read_linear", done=3, total=3)
        batch.people = self.people.people
        batch.activity = list(dict.fromkeys(batch.activity))
        return SourceResult(batch=batch, cursor=newest, notes=notes, people_props=self.people.props)

    def _project(self, batch: Batch, p: dict) -> str:
        name = p.get("name") or "Project"
        slug = slugify(name)[:60] or p["id"]
        batch.areas.append(Area(slug, name))
        doc_id = f"linear:project:{p['id']}"
        lead = self.user(p.get("lead"))
        lead_name = (p.get("lead") or {}).get("name") or (p.get("lead") or {}).get("displayName")
        teams = ", ".join(t.get("name") or t.get("key") or "" for t in (p.get("teams") or {}).get("nodes") or [])
        head = [f"{name} is a Linear project."]
        if lead_name:
            head.append(f"Project lead: {lead_name}.")
        if teams:
            head.append(f"Teams: {teams}.")
        if (p.get("status") or {}).get("name"):
            head.append(f"Status: {p['status']['name']}.")
        texts = [" ".join(head), *split_passages(p.get("description") or "")]
        passages = passages_of(doc_id, texts)
        updated = day(p.get("updatedAt"))
        batch.docs.append(Doc(doc_id, "team_page", f"{name} (Linear project)", p.get("url") or "", updated,  # type: ignore[arg-type]
                              author=lead, areas=(slug,)))
        batch.passages += passages
        if lead:
            subject, value = f"area:{slug}", f"person:{lead}"
            batch.facts.append(Fact(
                id=fact_id(subject, "owned_by", value, passages[0].id), subject=subject, predicate="owned_by",
                value=value, text=f"{name} is led by {lead_name}.", valid_from=day(p.get("createdAt")) or updated,
                passage_id=passages[0].id, authority=2,
            ))
            batch.activity.append(Activity(lead, doc_id, "AUTHORED", updated))
        return slug

    def _issue(self, batch: Batch, issue: dict, projects: dict[str, str]) -> None:
        ident = issue.get("identifier") or issue["id"]
        doc_id = f"linear:{ident.lower()}"
        title = f"{ident} {issue.get('title') or ''}".strip()
        state = (issue.get("state") or {}).get("name")
        creator = self.user(issue.get("creator"))
        assignee = self.user(issue.get("assignee"))
        project = issue.get("project") or {}
        area = projects.get(project.get("id") or "")
        if project.get("name") and not area:
            area = slugify(project["name"])[:60]
            batch.areas.append(Area(area, project["name"]))
        head = [f"{title}."]
        if state:
            head.append(f"Status: {state}.")
        if (issue.get("assignee") or {}).get("name"):
            head.append(f"Assigned to {issue['assignee']['name']}.")
        if project.get("name"):
            head.append(f"Project: {project['name']}.")
        texts = [" ".join(head), *split_passages(issue.get("description") or "")]
        commenters = []
        for c in (issue.get("comments") or {}).get("nodes") or []:
            who = self.user(c.get("user"))
            name = (c.get("user") or {}).get("name") or "Someone"
            body = (c.get("body") or "").strip()
            if body:
                texts += [f"{name} on {day(c.get('createdAt'))}: {piece}" for piece in split_passages(body)]
            if who:
                commenters.append((who, day(c.get("createdAt"))))
        # History: one line per change, oldest first. Each reassignment is its own passage, so the fact that
        # says who had the issue from then on cites exactly the line that says so.
        history = sorted((issue.get("history") or {}).get("nodes") or [], key=lambda h: h.get("createdAt") or "")
        assigned: list[tuple[str, str, str | None]] = []  # (day, passage text, handle or None)
        for h in history:
            when = day(h.get("createdAt"))
            actor = (h.get("actor") or {}).get("name") or "Someone"
            if h.get("toState") or h.get("fromState"):
                texts.append(f"On {when} {actor} moved {ident} from {(h.get('fromState') or {}).get('name') or 'nothing'} "
                             f"to {(h.get('toState') or {}).get('name') or 'nothing'}.")
            if h.get("toAssignee") or h.get("fromAssignee"):
                to = h.get("toAssignee")
                line = (f"On {when} {ident} was assigned to {to.get('name') or to.get('displayName')}." if to
                        else f"On {when} {ident} was unassigned.")
                texts.append(line)
                assigned.append((when, line, self.user(to) if to else None))
        passages = passages_of(doc_id, texts)
        updated = day(issue.get("updatedAt"))
        batch.docs.append(Doc(doc_id, "linear_issue", title, issue.get("url") or "", updated,  # type: ignore[arg-type]
                              author=creator, areas=(area,) if area else ()))
        batch.passages += passages
        if creator:
            batch.activity.append(Activity(creator, doc_id, "AUTHORED", day(issue.get("createdAt"))))
        if assignee:
            batch.activity.append(Activity(assignee, doc_id, "AUTHORED", updated))
        for who, when in commenters:
            batch.activity.append(Activity(who, doc_id, "COMMENTED", when))
        by_text = {p.text: p.id for p in passages}
        subject = f"topic:{slugify(ident)}"
        versions = [(when, by_text[line], {"assignee": (h,) if h else ()}) for when, line, h in assigned if line in by_text]
        if not versions and assignee:  # assigned when it was made, so its history has no reassignment
            versions = [(day(issue.get("createdAt")) or updated, passages[0].id, {"assignee": (assignee,)})]
        for w in owner_windows(versions):
            value = f"person:{w.owner}"
            name = next((p.name for p in self.people.by_id.values() if p.handle == w.owner), w.owner)
            batch.facts.append(Fact(
                id=fact_id(subject, "contact_for", value, w.passage_id), subject=subject, predicate="contact_for",
                value=value, text=f"{name} is the person to ask about {ident}.", valid_from=w.start,
                passage_id=w.passage_id, authority=1, valid_to=w.end,
            ))
