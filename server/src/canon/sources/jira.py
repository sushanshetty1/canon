"""Jira Cloud, through an account email and an API token.

- **Projects** (`/rest/api/3/project/search`, with their lead and description) become areas, each with a short
  `team_page` document. The project lead owns the area: an `owned_by` fact, authority 2.
- **Issues** (`/rest/api/3/search/jql`) become `jira_issue` documents: summary, status, assignee, the description
  and the comments, read from Atlassian Document Format into text. An issue is about its project's area. The
  reporter and assignee authored it; commenters commented on it.
- **People** by display name and account id; when Atlassian shares an email (it often hides it), it is only hashed
  for matching.

Incremental with JQL: `updated >= "<day before the cursor>" ORDER BY updated DESC`. Reading a day again is harmless
(writes are idempotent) and avoids the time zone JQL dates are read in. `config["projects"]` can narrow it to some
project keys. At most `max_issues` per sync, 50 a page.
"""

import re
import time
from collections.abc import Callable
from datetime import date, timedelta

from canon.sources.atlassian import credentials, site_url
from canon.sources.client import Client, SourceError, capped
from canon.sources.connector import Report
from canon.sources.identity import People, SourceResult
from canon.sources.richtext import adf_to_text
from canon.sources.text import day, fact_id, passages_of, slugify, split_passages
from canon.types import Activity, Area, Batch, Doc, Fact

FIELDS = "summary,description,status,assignee,reporter,created,updated,project,comment,issuetype"
_KEY = re.compile(r"^[A-Z][A-Z0-9_]{0,19}$")


class JiraConnector:
    kind = "jira"
    label = "Jira"

    def __init__(self, secret: dict, config: dict | None = None, *, http: Callable | None = None,
                 sleep: Callable[[float], None] = time.sleep):
        self.config = config or {}
        self.site = site_url(self.config.get("site"))
        email, token = credentials(secret.get("email"), secret.get("token"))
        self.client = Client("Jira", http=http, sleep=sleep, auth=(email, token), headers={"Accept": "application/json"})
        self.max_issues = capped(self.config, "max_issues", 500, 3000)
        self.max_projects = capped(self.config, "max_projects", 100, 500)
        self.max_comments = capped(self.config, "max_comments", 50, 200)
        self.lookback_days = capped(self.config, "lookback_days", 180, 3650)
        self.people = People("jira")

    def _json(self, path: str, **params):
        r = self.client.request("GET", f"{self.site}{path}", params=params)
        if r.status_code == 401:
            raise SourceError("Jira did not accept this email and API token.", status=401)
        if r.status_code == 403:
            raise SourceError("Jira refused access. The account needs permission to browse these projects.", status=403)
        if r.status_code == 404:
            raise SourceError(f"There is no Jira at {self.site.removeprefix('https://')}.", status=404)
        if r.status_code == 400:
            try:
                messages = r.json().get("errorMessages") or []
            except ValueError:
                messages = []
            raise SourceError(f"Jira could not run the search ({'; '.join(messages)[:160] or 'bad request'}).", status=400)
        if r.status_code != 200:
            raise SourceError(f"Jira answered with an error ({r.status_code}).", status=r.status_code)
        return r.json()

    def check(self) -> dict:
        me = self._json("/rest/api/3/myself")
        if not me.get("accountId"):
            raise SourceError("Jira did not accept this email and API token.", status=401)
        return {"account": me.get("displayName") or ""}

    def user(self, u: dict | None) -> str | None:
        if not u or not u.get("accountId") or u.get("accountType") == "app":
            return None
        return self.people.add(u["accountId"], u.get("displayName"), u.get("emailAddress"))

    def jql(self, cursor: str | None) -> str:
        keys = [k.strip().upper() for k in self.config.get("projects") or [] if _KEY.match(str(k).strip().upper())]
        clauses = [f"project in ({', '.join(keys)})"] if keys else []
        if cursor:
            since = (date.fromisoformat(cursor[:10]) - timedelta(days=1)).isoformat()
            clauses.append(f'updated >= "{since}"')
        else:
            clauses.append(f"updated >= -{self.lookback_days}d")
        return " AND ".join(clauses) + " ORDER BY updated DESC"

    def read(self, *, cursor: str | None, report: Report) -> SourceResult:
        notes: list[str] = []
        batch = Batch()
        report(step="read_jira", done=0, total=2)
        self.check()
        projects: dict[str, str] = {}
        start = 0
        while len(projects) < self.max_projects:
            page = self._json("/rest/api/3/project/search", expand="lead,description", startAt=start, maxResults=50)
            values = page.get("values") or []
            for p in values[: self.max_projects - len(projects)]:
                projects[p.get("key") or p.get("id")] = self._project(batch, p)
            if page.get("isLast", True) or not values:
                break
            start += len(values)
        report(step="read_jira", done=1, total=2)

        issues: list[dict] = []
        token = None
        query = self.jql(cursor)
        while len(issues) <= self.max_issues:
            params = {"jql": query, "fields": FIELDS, "maxResults": 50}
            if token:
                params["nextPageToken"] = token
            page = self._json("/rest/api/3/search/jql", **params)
            issues += page.get("issues") or []
            token = page.get("nextPageToken")
            if page.get("isLast", not token) or not token:
                break
        if len(issues) > self.max_issues:
            notes.append(f"Read the {self.max_issues} most recently updated issues (max_issues).")
            issues = issues[: self.max_issues]
        newest = cursor
        for i, issue in enumerate(issues):
            if i % 25 == 0:
                report(step="read_jira", done=1 + i / max(len(issues), 1), total=2)
            self._issue(batch, issue, projects)
            updated = (issue.get("fields") or {}).get("updated") or ""
            if not newest or updated > newest:
                newest = updated
        report(step="read_jira", done=2, total=2)
        batch.people = self.people.people
        batch.activity = list(dict.fromkeys(batch.activity))
        return SourceResult(batch=batch, cursor=newest, notes=notes, people_props=self.people.props)

    def _project(self, batch: Batch, p: dict) -> str:
        name = p.get("name") or p.get("key") or "Project"
        key = p.get("key") or str(p.get("id"))
        slug = slugify(name)[:60] or key.lower()
        batch.areas.append(Area(slug, name))
        doc_id = f"jira:project:{key.lower()}"
        lead = self.user(p.get("lead"))
        lead_name = (p.get("lead") or {}).get("displayName")
        head = f"{name} ({key}) is a Jira project." + (f" Project lead: {lead_name}." if lead_name else "")
        description = p.get("description") if isinstance(p.get("description"), str) else adf_to_text(p.get("description"))
        passages = passages_of(doc_id, [head, *split_passages(description or "")])
        batch.docs.append(Doc(doc_id, "team_page", f"{name} (Jira project)", f"{self.site}/browse/{key}",  # type: ignore[arg-type]
                              date.today().isoformat(), author=lead, areas=(slug,)))
        batch.passages += passages
        if lead:
            subject, value = f"area:{slug}", f"person:{lead}"
            batch.facts.append(Fact(
                id=fact_id(subject, "owned_by", value, passages[0].id), subject=subject, predicate="owned_by",
                value=value, text=f"{lead_name} leads the {name} project.", valid_from=date.today().isoformat(),
                passage_id=passages[0].id, authority=2,
            ))
        return slug

    def _issue(self, batch: Batch, issue: dict, projects: dict[str, str]) -> None:
        f = issue.get("fields") or {}
        key = issue.get("key") or str(issue.get("id"))
        doc_id = f"jira:{key.lower()}"
        title = f"{key} {f.get('summary') or ''}".strip()
        project = f.get("project") or {}
        area = projects.get(project.get("key") or "")
        if not area and project.get("name"):
            area = slugify(project["name"])[:60]
            batch.areas.append(Area(area, project["name"]))
        reporter = self.user(f.get("reporter"))
        assignee = self.user(f.get("assignee"))
        head = [f"{title}."]
        if (f.get("issuetype") or {}).get("name"):
            head.append(f"Type: {f['issuetype']['name']}.")
        if (f.get("status") or {}).get("name"):
            head.append(f"Status: {f['status']['name']}.")
        if (f.get("assignee") or {}).get("displayName"):
            head.append(f"Assigned to {f['assignee']['displayName']}.")
        if (f.get("reporter") or {}).get("displayName"):
            head.append(f"Reported by {f['reporter']['displayName']}.")
        texts = [" ".join(head), *split_passages(adf_to_text(f.get("description")))]
        comments = ((f.get("comment") or {}).get("comments") or [])[-self.max_comments :]
        for c in comments:
            who = self.user(c.get("author"))
            name = (c.get("author") or {}).get("displayName") or "Someone"
            body = adf_to_text(c.get("body"))
            if body:
                texts += [f"{name} on {day(c.get('created'))}: {piece}" for piece in split_passages(body)]
            if who:
                batch.activity.append(Activity(who, doc_id, "COMMENTED", day(c.get("created"))))
        passages = passages_of(doc_id, texts)
        updated = day(f.get("updated"))
        batch.docs.append(Doc(doc_id, "jira_issue", title, f"{self.site}/browse/{key}", updated,  # type: ignore[arg-type]
                              author=reporter, areas=(area,) if area else ()))
        batch.passages += passages
        if reporter:
            batch.activity.append(Activity(reporter, doc_id, "AUTHORED", day(f.get("created"))))
        if assignee:
            batch.activity.append(Activity(assignee, doc_id, "AUTHORED", updated))
