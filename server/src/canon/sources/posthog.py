"""The PostHog connector: PostHog's public handbook, team pages, ownership map, RFCs, issues, pull requests and forum.

It works in two steps. A source fetches raw data by name (`"handbook"`, `"ownership_history"`, `"pulls"`, ...) and
caches it under `/data/raw/posthog/`; tests pass a `fetch` callable over small recorded fixtures instead. Then
`load_posthog` turns the raw data into one `Batch`.

The ownership map (`src/hooks/useFeatureOwnership.tsx` in `PostHog/posthog.com`) is the authority on who owns what.
Its git history gives every area's owner with the window it held: each commit is a document, and each time an
area's owner list changes, the commit states one fact per owner in the new list and closes the facts of the old
list. Co-owners are stated together in one passage. Handbook pages that still name an older owner are what the
check later finds out of date.

Public data only: people keep a name, a role and a GitHub handle. No emails, avatars or locations are kept.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx

from canon.people.attribution import Attributor
from canon.sources import github as gh
from canon.sources.cache import Cache
from canon.sources.ownership import owned_by_facts, owner_windows
from canon.sources.text import clean_mdx, frontmatter, passages_of, slugify, split_passages
from canon.sources.text import day as _day
from canon.types import Activity, Area, Batch, Doc, Fact, Passage, Person, Team

__all__ = ["clean_mdx", "frontmatter", "load_posthog", "parse_ownership", "slugify", "split_passages"]

SITE_REPO = "PostHog/posthog.com"
RFC_REPO = "PostHog/requests-for-comments-public"
MAIN_REPO = "PostHog/posthog"
OWNERSHIP_PATH = "src/hooks/useFeatureOwnership.tsx"
STRAPI = "https://better-animal-d658c56969.strapiapp.com/api"
SITE = "https://posthog.com"

Fetch = Callable[[str], Any]


# ----- the ownership map -----------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Feature:
    slug: str
    name: str
    owners: tuple[str, ...]
    labels: tuple[str, ...]


def _matching_brace(text: str, start: int) -> int:
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return i
    return -1


_ENTRY = re.compile(r"(?:'([^']+)'|\"([^\"]+)\"|([A-Za-z_$][\w$]*))\s*:\s*\{")
_QUOTED = re.compile(r"'([^']*)'|\"([^\"]*)\"")


def parse_ownership(source: str) -> dict[str, Feature] | None:
    """`FEATURE_DATA` from one version of the ownership map. None when the file has no such object."""
    m = re.search(r"FEATURE_DATA\s*(?::[^=]+)?=\s*\{", source)
    if not m:
        return None
    start = m.end() - 1
    end = _matching_brace(source, start)
    block = source[start + 1 : end]
    features: dict[str, Feature] = {}
    pos = 0
    while True:
        e = _ENTRY.search(block, pos)
        if not e:
            break
        body_end = _matching_brace(block, e.end() - 1)
        body = block[e.end() : body_end]
        pos = body_end + 1
        slug = e.group(1) or e.group(2) or e.group(3)
        name_m = re.search(r"\bfeature:\s*(?:'((?:[^'\\]|\\.)*)'|\"((?:[^\"\\]|\\.)*)\")", body)
        owner_m = re.search(r"\bowner:\s*\[(.*?)\]", body, re.S)
        if not name_m or not owner_m:
            continue
        name = (name_m.group(1) or name_m.group(2) or slug).replace("\\'", "'")
        owners = tuple(o for a, b in _QUOTED.findall(owner_m.group(1)) if (o := (a or b).strip()))
        label_m = re.search(r"\blabel:\s*(false|\[.*?\]|'[^']*'|\"[^\"]*\")", body, re.S)
        if not label_m:
            labels: tuple[str, ...] = (f"feature/{slugify(name)}",)  # the site's own default
        elif label_m.group(1) == "false":
            labels = ()
        else:
            labels = tuple(a or b for a, b in _QUOTED.findall(label_m.group(1)))
        features[slug] = Feature(slug, name, owners, labels)
    return features


def _owner_text(area: str, team: str) -> str:
    return f"{area} is owned by the {team} team."


@dataclass
class Ownership:
    docs: list[Doc]
    passages: list[Passage]
    facts: list[Fact]
    activity: list[tuple[str, str, str, str]]  # (author name, author handle, doc id, at)
    current: dict[str, Feature]
    names: dict[str, str]  # area slug -> latest name
    label_to_area: dict[str, str]
    owner_slugs: set[str]


def ownership_history(versions: list[dict], team_name: Callable[[str], str]) -> Ownership:
    """Walk the map's versions oldest first and turn owner changes into dated, windowed `owned_by` facts.

    A window closes the day its area's owner list changes; the new list opens new windows from that commit.

    Each version is `{"sha", "date", "author_name", "author_handle", "text"}`.
    """
    out = Ownership([], [], [], [], {}, {}, {}, set())
    previous: dict[str, Feature] = {}
    owner_versions: list[tuple[str, str, dict[str, tuple[str, ...]]]] = []

    for v in versions:
        current = parse_ownership(v["text"])
        if current is None:
            continue
        day = _day(v["date"])
        lines: list[str] = []
        changed: list[str] = []  # area names, for the document's title
        for slug in sorted(set(previous) | set(current)):
            before, after = previous.get(slug), current.get(slug)
            if before == after:
                continue
            changed.append((after or before).name)
            if before is None:
                owners = ", ".join(after.owners) or "no team"
                lines.append(f"{after.name} ({slug}) added, owned by {owners}.")
            elif after is None:
                lines.append(f"{before.name} ({slug}) removed from the map.")
            elif before.owners != after.owners:
                lines.append(
                    f"{after.name} ({slug}): owner changed from {', '.join(before.owners) or 'no team'}"
                    f" to {', '.join(after.owners) or 'no team'}."
                )
            elif before.name != after.name:
                lines.append(f"{slug}: renamed from {before.name} to {after.name}.")
            else:
                lines.append(f"{after.name} ({slug}): labels changed to {', '.join(after.labels) or 'none'}.")
        if not lines:
            continue

        doc = Doc(
            id=f"ownership_map:{v['sha'][:10]}",
            kind="ownership_map",
            title="Ownership map: " + (changed[0] if len(changed) == 1 else f"{changed[0]} and {len(changed) - 1} more"),
            url=f"https://github.com/{SITE_REPO}/commit/{v['sha']}",
            updated_at=day,
            author=v.get("author_handle"),
        )
        passage = passages_of(doc.id, ["\n".join(lines)])[0]
        out.docs.append(doc)
        out.passages.append(passage)
        out.activity.append((v.get("author_name") or "", v.get("author_handle") or "", doc.id, day))
        owner_versions.append((day, passage.id, {slug: f.owners for slug, f in current.items()}))
        previous = current
        for slug, f in current.items():
            out.names[slug] = f.name
            out.owner_slugs.update(f.owners)
            for label in f.labels:
                out.label_to_area[label] = slug

    out.current = previous
    out.facts = owned_by_facts(
        owner_windows(owner_versions),
        value=lambda team: f"team:{team}",
        text=lambda w: _owner_text(out.names.get(w.area, w.area), team_name(w.owner)),
    )
    return out


# ----- people and teams ------------------------------------------------------------------------------------------


def _handle(profile: dict) -> str:
    url = (profile.get("github") or "").strip().rstrip("/")
    if url:
        return url.rsplit("/", 1)[-1].lstrip("@").lower()
    name = f"{profile.get('firstName') or ''} {profile.get('lastName') or ''}".strip()
    return f"name:{slugify(name)}"


def _attrs(row: dict) -> dict:
    return row.get("attributes", row)


def people_and_teams(strapi_teams: list[dict]) -> tuple[dict[str, Person], dict[str, dict]]:
    """Strapi teams to people (handle, name, role) and team rows (slug, name, members, leads)."""
    people: dict[str, Person] = {}
    teams: dict[str, dict] = {}
    for row in strapi_teams:
        t = _attrs(row)
        if not t.get("slug"):
            continue
        members, leads = [], []
        for p in (t.get("profiles") or {}).get("data") or []:
            a = _attrs(p)
            handle = _handle(a)
            name = f"{a.get('firstName') or ''} {a.get('lastName') or ''}".strip() or handle
            people.setdefault(handle, Person(handle, name, a.get("companyRole") or None))
            members.append(handle)
        for p in (t.get("leadProfiles") or {}).get("data") or []:
            leads.append(_handle(_attrs(p)))
        teams[t["slug"]] = {"name": t.get("name") or t["slug"], "members": members, "leads": leads}
    return people, teams


# ----- the batch -------------------------------------------------------------------------------------------------


def _handbook_url(path: str) -> str:
    rel = re.sub(r"\.mdx?$", "", path.removeprefix("contents/"))
    return f"{SITE}/{rel.removesuffix('/index')}"


_WORDS = {"ai": "AI", "llm": "LLM", "mcp": "MCP", "posthog": "PostHog", "cs": "CS", "ux": "UX", "na": "NA", "eu": "EU"}


def _title(slug: str) -> str:
    """A readable name from a slug, for teams that only appear in old versions of the ownership map."""
    words = [_WORDS.get(w, w) for w in slug.replace("_", "-").split("-") if w]
    if not words:
        return slug
    return " ".join([words[0][:1].upper() + words[0][1:], *words[1:]])


def _snippet(title: str, body: str | None, limit: int = 600) -> str:
    body = re.sub(r"<!--.*?-->", "", body or "", flags=re.S).strip()
    return f"{title}\n{body[:limit]}".strip()


def load_posthog(
    cache_dir: Path,
    *,
    issues_since: str = "2025-10-01",
    max_pulls: int = 1500,
    fetch: Fetch | None = None,
) -> Batch:
    """Everything PostHog publishes about how it works, as one batch for the graph writer."""
    fetch = fetch or LiveSource(cache_dir, issues_since=issues_since, max_pulls=max_pulls)
    batch = Batch()

    # People and teams first: every other source maps names and handles onto them.
    people, strapi_teams = people_and_teams(fetch("strapi_teams") or [])
    by_name = {p.name.lower(): p.handle for p in people.values()}

    def who(name: str | None, handle: str | None) -> str | None:
        """A commit's author as a handle: from the noreply email when there was one, else by published name."""
        if handle:
            return None if handle.endswith("[bot]") else handle.lower()
        return by_name.get((name or "").strip().lower())

    team_pages = fetch("team_pages") or []
    page_titles: dict[str, str] = {}
    for f in team_pages:
        slug = f["path"].split("/")[2]
        if f["path"].endswith("/index.mdx"):
            page_titles[slug] = frontmatter(f["text"])[0].get("title") or slug

    def team_name(slug: str) -> str:
        if slug in strapi_teams:
            return strapi_teams[slug]["name"]
        return page_titles.get(slug) or _title(slug)

    own = ownership_history(fetch("ownership_history") or [], team_name)
    team_names = {slug: team_name(slug) for slug in set(strapi_teams) | set(page_titles) | own.owner_slugs}

    batch.people = sorted(people.values(), key=lambda p: p.handle)
    batch.teams = [
        Team(
            slug,
            name,
            tuple(strapi_teams.get(slug, {}).get("members", ())),
            tuple(strapi_teams.get(slug, {}).get("leads", ())),
        )
        for slug, name in sorted(team_names.items())
    ]
    batch.areas = [Area(slug, name) for slug, name in sorted(own.names.items())]
    staff = set(people)

    def act(handle: str | None, doc_id: str, rel: str, at: str | None) -> None:
        if handle and handle.lower() in staff and at:
            batch.activity.append(Activity(handle.lower(), doc_id, rel, _day(at)))  # type: ignore[arg-type]

    # The ownership map: documents per commit, and the windowed facts.
    batch.docs += own.docs
    batch.passages += own.passages
    batch.facts += own.facts
    for name, handle, doc_id, at in own.activity:
        act(who(name, handle), doc_id, "AUTHORED", at)

    # Handbook and team pages.
    for kind, files in (("handbook", fetch("handbook") or []), ("team_page", team_pages)):
        for f in files:
            meta, body = frontmatter(f["text"])
            text = clean_mdx(body, team_names)
            if not text:
                continue
            path = f["path"]
            if kind == "team_page":
                slug = path.split("/")[2]
                section = Path(path).stem
                title = team_name(slug) + ("" if section == "index" else f" team: {section}")
                url = f"{SITE}/teams/{slug}"
            else:
                title = meta.get("title") or Path(path).stem.replace("-", " ").capitalize()
                url = _handbook_url(path)
            author = who(f.get("author_name"), f.get("author_handle"))
            doc = Doc(f"{kind}:{path}", kind, title, url, _day(f["updated_at"]), author)  # type: ignore[arg-type]
            batch.docs.append(doc)
            batch.passages += passages_of(doc.id, split_passages(text))
            act(author, doc.id, "AUTHORED", f["updated_at"])
            act(who(f.get("first_author_name"), f.get("first_author_handle")), doc.id, "AUTHORED", f.get("created_at"))

    # RFCs: decided on the date their pull request merged.
    for f in fetch("rfcs") or []:
        meta, body = frontmatter(f["text"])
        text = clean_mdx(body, team_names)
        if not text:
            continue
        m = re.search(r"^#\s+(.+)$", text, re.M)
        title = re.sub(r"^((request for comments|rfc)\s*[:-]\s*)+", "", (m.group(1) if m else "").strip(), flags=re.I)
        if not title or title.startswith("*"):  # a heading left as the template's placeholder
            title = _title(re.sub(r"^\d{4}-\d{2}-\d{2}-", "", Path(f["path"]).stem))
        pr = f.get("pr") or {}
        author = (pr.get("author") or who(f.get("author_name"), f.get("author_handle")) or "").lower() or None
        doc = Doc(
            id=f"rfc:{f['path']}",
            kind="rfc",
            title=f"RFC: {title}",
            url=f"https://github.com/{RFC_REPO}/blob/main/{f['path']}",
            updated_at=_day(f["updated_at"]),
            author=author,
            decided_at=_day(pr.get("merged_at") or f.get("created_at")) or None,
        )
        batch.docs.append(doc)
        batch.passages += passages_of(doc.id, split_passages(text))
        act(author, doc.id, "AUTHORED", pr.get("created_at") or f.get("created_at"))
        act(pr.get("merged_by"), doc.id, "DECIDED", pr.get("merged_at"))
        for r in pr.get("reviews") or []:
            act(r["author"], doc.id, "REVIEWED" if r["state"] in ("APPROVED", "CHANGES_REQUESTED") else "COMMENTED", r["at"])
        for c in pr.get("comments") or []:
            act(c["author"], doc.id, "COMMENTED", c["at"])

    # Pull requests and issues: activity and evidence. `feature/*` labels name the area, and so do the directories
    # a pull request changed.
    attributor = Attributor(own.names)
    pull_files: dict[str, list[str]] = fetch("pull_files") or {}
    for kind, rows in (("pull", fetch("pulls") or []), ("issue", fetch("issues") or [])):
        for r in rows:
            areas_set = {own.label_to_area[l] for l in r.get("labels", []) if l in own.label_to_area}
            if kind == "pull":
                areas_set.update(attributor.areas_for(pull_files.get(str(r["number"]), ())))
            areas = tuple(sorted(areas_set))
            at = r.get("merged_at") or r.get("created_at")
            doc = Doc(
                id=f"{kind}:{r['number']}",
                kind=kind,  # type: ignore[arg-type]
                title=r["title"],
                url=r["url"],
                updated_at=_day(at),
                author=(r.get("author") or "").lower() or None,
                areas=areas,
            )
            batch.docs.append(doc)
            batch.passages += passages_of(doc.id, [_snippet(r["title"], r.get("body"))])
            act(r.get("author"), doc.id, "AUTHORED", r.get("created_at"))
            for rev in r.get("reviews") or []:
                rel = "REVIEWED" if rev["state"] in ("APPROVED", "CHANGES_REQUESTED") else "COMMENTED"
                act(rev["author"], doc.id, rel, rev["at"])
            for c in r.get("comments") or []:
                act(c["author"], doc.id, "COMMENTED", c["at"])

    # Forum threads: what users ask, as evidence. No people from the forum are kept.
    for q in fetch("forum") or []:
        title = q["subject"] + (" (resolved)" if q.get("resolved") else "")
        doc = Doc(f"forum:{q['id']}", "forum", title, f"{SITE}/questions/{q['permalink']}", _day(q["created_at"]))
        batch.docs.append(doc)
        batch.passages += passages_of(doc.id, [_snippet(q["subject"], q.get("body"))])

    batch.activity = sorted(set(batch.activity), key=lambda a: (a.doc_id, a.handle, a.rel, a.at))
    return batch


# ----- the live source -------------------------------------------------------------------------------------------

_PULLS = """
query($owner: String!, $name: String!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    pullRequests(states: MERGED, first: 50, after: $cursor, orderBy: {field: UPDATED_AT, direction: DESC}) {
      pageInfo { hasNextPage endCursor }
      nodes {
        number title bodyText url createdAt mergedAt updatedAt
        author { login __typename }
        mergedBy { login }
        labels(first: 20) { nodes { name } }
        reviews(first: 30) { nodes { author { login __typename } state submittedAt } }
      }
    }
  }
}"""

_ISSUES = """
query($owner: String!, $name: String!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    issues(first: 50, after: $cursor, orderBy: {field: CREATED_AT, direction: DESC}) {
      pageInfo { hasNextPage endCursor }
      nodes {
        number title bodyText url createdAt closedAt
        author { login __typename }
        labels(first: 20) { nodes { name } }
        comments(first: 20) { nodes { author { login __typename } createdAt } }
      }
    }
  }
}"""

_RFC_PULLS = """
query($owner: String!, $name: String!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    pullRequests(first: 50, after: $cursor, orderBy: {field: CREATED_AT, direction: ASC}) {
      pageInfo { hasNextPage endCursor }
      nodes {
        number createdAt mergedAt
        author { login __typename }
        mergedBy { login }
        files(first: 30) { nodes { path } }
        reviews(first: 40) { nodes { author { login __typename } state submittedAt } }
        comments(first: 40) { nodes { author { login __typename } createdAt } }
      }
    }
  }
}"""


_login = gh.login_of


class LiveSource:
    """Fetches PostHog's raw data from git, GitHub and the site's public API, caching each piece."""

    def __init__(self, cache_dir: Path, *, issues_since: str = "2025-10-01", max_pulls: int = 1500):
        self.root = Path(cache_dir)
        self.cache = Cache(self.root)
        self.issues_since = issues_since
        self.max_pulls = max_pulls
        self._github: gh.GitHub | None = None

    @property
    def github(self) -> gh.GitHub:
        if self._github is None:
            self._github = gh.GitHub()
        return self._github

    def __call__(self, name: str) -> Any:
        return getattr(self, f"_{name}")()

    # -- posthog.com, from a blob-less sparse clone --

    def _site(self) -> Path:
        return gh.clone(
            f"https://github.com/{SITE_REPO}.git",
            self.root / "posthog.com",
            sparse=["contents/handbook", "contents/teams", "src/hooks"],
        )

    def _files(self, prefix: str, pattern: str) -> list[dict]:
        repo = self._site()
        commits = gh.first_and_last_commits(repo, prefix)
        rows = []
        for file in sorted((repo / prefix).glob(pattern)):
            path = str(file.relative_to(repo))
            if path not in commits:
                continue
            first, last = commits[path]
            rows.append(
                {
                    "path": path,
                    "text": file.read_text(errors="replace"),
                    "created_at": first.date,
                    "updated_at": last.date,
                    "author_name": last.name,
                    "author_handle": gh.handle_from_email(last.email),
                    "first_author_name": first.name,
                    "first_author_handle": gh.handle_from_email(first.email),
                }
            )
        return rows

    def _handbook(self) -> list[dict]:
        return self.cache.json("handbook", lambda: self._files("contents/handbook", "**/*.md*"))

    def _team_pages(self) -> list[dict]:
        return self.cache.json("team_pages", lambda: self._files("contents/teams", "*/*.mdx"))

    def _ownership_history(self) -> list[dict]:
        def read() -> list[dict]:
            repo = self._site()
            return [
                {
                    "sha": c.sha,
                    "date": c.date,
                    "author_name": c.name,
                    "author_handle": gh.handle_from_email(c.email),
                    "text": gh.show(repo, c.sha, OWNERSHIP_PATH),
                }
                for c in gh.file_history(repo, OWNERSHIP_PATH)
            ]

        return self.cache.json("ownership_history", read)

    # -- the site's public API --

    def _strapi(self, path: str, params: list[tuple[str, str]]) -> dict:
        r = httpx.get(f"{STRAPI}/{path}?{urlencode(params)}", timeout=60)  # not the GitHub client: no token here
        r.raise_for_status()
        return r.json()

    def _strapi_teams(self) -> list[dict]:
        fields = [("fields[0]", "name"), ("fields[1]", "slug"), ("pagination[pageSize]", "100")]
        for i, f in enumerate(("firstName", "lastName", "companyRole", "github")):
            fields.append((f"populate[profiles][fields][{i}]", f))
        for i, f in enumerate(("firstName", "lastName", "github")):
            fields.append((f"populate[leadProfiles][fields][{i}]", f))
        return self.cache.json("strapi_teams", lambda: self._strapi("teams", fields)["data"])

    def _forum(self) -> list[dict]:
        since = (date.today() - timedelta(days=365)).isoformat()

        def read() -> list[dict]:
            rows, page = [], 1
            while True:
                params = [
                    ("filters[createdAt][$gte]", since),
                    ("sort", "createdAt:desc"),
                    ("pagination[page]", str(page)),
                    ("pagination[pageSize]", "100"),
                ] + [(f"fields[{i}]", f) for i, f in enumerate(("subject", "permalink", "resolved", "body", "createdAt"))]
                body = self._strapi("questions", params)
                for q in body["data"]:
                    a = _attrs(q)
                    rows.append(
                        {
                            "id": q["id"],
                            "subject": a.get("subject") or "",
                            "permalink": a.get("permalink") or str(q["id"]),
                            "resolved": bool(a.get("resolved")),
                            "body": (a.get("body") or "")[:1200],
                            "created_at": a.get("createdAt"),
                        }
                    )
                meta = body["meta"]["pagination"]
                if page >= meta["pageCount"]:
                    return rows
                page += 1

        return self.cache.json("forum", read)

    # -- GitHub: RFCs, pull requests, issues --

    def _paged(self, query: str, repo: str, key: str, keep: Callable[[dict], bool | None]) -> list[dict]:
        return self.github.paged(query, repo, key, keep)

    def _pulls(self) -> list[dict]:
        def read() -> list[dict]:
            count = 0

            def keep(n: dict) -> bool | None:
                nonlocal count
                if count >= self.max_pulls or (n["updatedAt"] or "") < self.issues_since:
                    return None
                ok = (n["mergedAt"] or "") >= self.issues_since
                count += ok
                return ok

            nodes = self._paged(_PULLS, MAIN_REPO, "pullRequests", keep)
            return [
                {
                    "number": n["number"],
                    "title": n["title"],
                    "body": (n["bodyText"] or "")[:1200],
                    "url": n["url"],
                    "created_at": n["createdAt"],
                    "merged_at": n["mergedAt"],
                    "author": _login(n["author"]),
                    "labels": [l["name"] for l in n["labels"]["nodes"]],
                    "reviews": [
                        {"author": _login(r["author"]), "state": r["state"], "at": r["submittedAt"]}
                        for r in n["reviews"]["nodes"]
                        if _login(r["author"]) and r["submittedAt"]
                    ],
                }
                for n in nodes
            ]

        return self.cache.json("pulls", read)

    def _issues(self) -> list[dict]:
        def read() -> list[dict]:
            count = 0

            def keep(n: dict) -> bool | None:
                nonlocal count
                if count >= self.max_pulls or n["createdAt"] < self.issues_since:
                    return None
                count += 1
                return True

            nodes = self._paged(_ISSUES, MAIN_REPO, "issues", keep)
            return [
                {
                    "number": n["number"],
                    "title": n["title"],
                    "body": (n["bodyText"] or "")[:1200],
                    "url": n["url"],
                    "created_at": n["createdAt"],
                    "closed_at": n["closedAt"],
                    "author": _login(n["author"]),
                    "labels": [l["name"] for l in n["labels"]["nodes"]],
                    "comments": [
                        {"author": _login(c["author"]), "at": c["createdAt"]}
                        for c in n["comments"]["nodes"]
                        if _login(c["author"])
                    ],
                }
                for n in nodes
            ]

        return self.cache.json("issues", read)

    def _rfcs(self) -> list[dict]:
        def read() -> list[dict]:
            repo = gh.clone(f"https://github.com/{RFC_REPO}.git", self.root / "rfcs")
            pulls = self._paged(_RFC_PULLS, RFC_REPO, "pullRequests", lambda n: True)
            by_path: dict[str, dict] = {}
            for n in pulls:  # oldest first: the first merged pull request that touched a file decided it
                for f in n["files"]["nodes"]:
                    current = by_path.get(f["path"])
                    if current is None or (not current.get("merged_at") and n["mergedAt"]):
                        by_path[f["path"]] = {
                            "number": n["number"],
                            "author": _login(n["author"]),
                            "created_at": n["createdAt"],
                            "merged_at": n["mergedAt"],
                            "merged_by": _login(n["mergedBy"]),
                            "reviews": [
                                {"author": _login(r["author"]), "state": r["state"], "at": r["submittedAt"]}
                                for r in n["reviews"]["nodes"]
                                if _login(r["author"]) and r["submittedAt"]
                            ],
                            "comments": [
                                {"author": _login(c["author"]), "at": c["createdAt"]}
                                for c in n["comments"]["nodes"]
                                if _login(c["author"])
                            ],
                        }
            commits = gh.first_and_last_commits(repo, "requests-for-comments")
            rows = []
            for file in sorted((repo / "requests-for-comments").glob("*.md")):
                path = str(file.relative_to(repo))
                if path not in commits:
                    continue
                first, last = commits[path]
                rows.append(
                    {
                        "path": path,
                        "text": file.read_text(errors="replace"),
                        "created_at": first.date,
                        "updated_at": last.date,
                        "author_name": first.name,
                        "author_handle": gh.handle_from_email(first.email),
                        "pr": by_path.get(path),
                    }
                )
            return rows

        return self.cache.json("rfcs", read)

    def _pull_files(self) -> dict[str, list[str]]:
        """The paths each cached pull request changed (the first 100), keyed by number, for area attribution."""

        def read() -> dict[str, list[str]]:
            numbers = [r["number"] for r in self._pulls()]
            owner, name = MAIN_REPO.split("/")
            out: dict[str, list[str]] = {}
            for i in range(0, len(numbers), _FILES_PER_QUERY):
                chunk = numbers[i : i + _FILES_PER_QUERY]
                fields = " ".join(
                    f"p{n}: pullRequest(number: {n}) {{ files(first: 100) {{ nodes {{ path }} }} }}" for n in chunk
                )
                query = (
                    "query($owner: String!, $name: String!) "
                    f"{{ repository(owner: $owner, name: $name) {{ {fields} }} }}"
                )
                repo = self.github.graphql(query, {"owner": owner, "name": name})["repository"]
                for n in chunk:
                    node = repo.get(f"p{n}") or {}
                    out[str(n)] = [f["path"] for f in ((node.get("files") or {}).get("nodes") or [])]
            return out

        return self.cache.json("pull_files", read)


_FILES_PER_QUERY = 25  # pull requests per GraphQL query; each asks for up to 100 paths
