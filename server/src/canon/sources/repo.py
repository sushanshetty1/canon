"""A connector for any public GitHub repository: its Markdown docs, CODEOWNERS history, issues, pull requests and
contributors, as one `Batch`.

Like the PostHog connector it works in two steps. A source fetches raw pieces by name (`"meta"`, `"docs"`,
`"codeowners"`, `"pulls"`, `"issues"`, `"contributors"`); tests pass a callable over small fixtures instead. Then
`load_repo` turns them into a batch.

- **Docs.** Every Markdown and MDX file (not changelogs, licences or templates) is a document with its git history:
  dated by its last commit, authored by everyone who committed to it. Pages under a `rfcs/`, `adr/`, `decisions/`,
  `proposals/` or `design/` folder are design documents, decided on the day they were added.
- **CODEOWNERS.** The file's git history is the authority on who owns what (authority 3), exactly as PostHog's
  ownership map is: each commit that changes an owner list is a document, and each area's owners hold from that
  commit until the list changes again. An area is a CODEOWNERS path. `@org/team` owners are teams, `@handle`
  owners are people. Email owners are skipped: no emails are kept.
- **Issues and pull requests**, bounded and newest first. A pull request is about the areas whose CODEOWNERS paths
  its changed files fall under.
- **Contributors**, by GitHub handle and published name.

`RepoSource` reads a repository live from a blob-less sparse clone (only Markdown and CODEOWNERS files are ever
downloaded) and the GitHub API. With `since` it reads only what changed: docs touched between two commits, and
issues and pull requests updated after a time.
"""

import fnmatch
import os
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from canon.sources import github as gh
from canon.sources.ownership import owned_by_facts, owner_windows
from canon.sources.text import clean_mdx, day, frontmatter, passages_of, slugify, split_passages
from canon.types import Activity, Area, Batch, Doc, Person, Team

Fetch = Callable[[str], Any]

CODEOWNERS_PATHS = (".github/CODEOWNERS", "CODEOWNERS", "docs/CODEOWNERS")  # GitHub's order of precedence
DOC_SUFFIXES = (".md", ".mdx")
_SKIP_DOC = re.compile(
    r"(^|/)(node_modules|vendor|third_party|\.git)/"
    r"|(^|/)(CHANGELOG|CHANGES|HISTORY|LICENSE|LICENCE|NOTICE|COPYING)[^/]*$"
    r"|^\.github/(ISSUE_TEMPLATE|PULL_REQUEST_TEMPLATE|pull_request_template)",
    re.I,
)
_DECISIONS = re.compile(r"(^|/)(rfcs?|adrs?|decisions?|proposals?|design)/", re.I)
# Path segments that say nothing about what an area is, left out of its name.
_GENERIC = {"src", "lib", "pkg", "cmd", "internal", "app", "apps", "packages", "source", "sources", "main"}
WHOLE_REPO = "all"
MAX_DOCS = 400
MAX_DOC_BYTES = 200_000
MAX_DOC_AUTHORS = 20


def is_doc(path: str) -> bool:
    return path.lower().endswith(DOC_SUFFIXES) and not _SKIP_DOC.search(path)


# ----- CODEOWNERS ------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Rule:
    pattern: str
    owners: tuple[str, ...]  # "@org/team" or "@handle", lowercased


def parse_codeowners(text: str) -> list[Rule]:
    """The rules of one CODEOWNERS file, in file order. Owners that are emails are dropped."""
    rules = []
    for raw in text.splitlines():
        line = re.sub(r"(^|\s)#.*$", "", raw).strip()
        if not line or line.startswith("["):  # GitLab-style sections are not GitHub syntax
            continue
        pattern, *owners = line.split()
        rules.append(Rule(pattern, tuple(dict.fromkeys(o.lower() for o in owners if o.startswith("@") and len(o) > 1))))
    return rules


def matches(pattern: str, path: str) -> bool:
    """Whether a CODEOWNERS (gitignore-style) pattern covers a file path."""
    p = pattern.strip()
    directory = p.endswith("/")
    anchored = p.startswith("/") or "/" in p.strip("/")
    p = p.strip("/")
    if p in ("*", "**", ""):
        return True
    parts = PurePosixPath(path).parts
    starts = [0] if anchored else range(len(parts))
    for s in starts:
        tail = parts[s:]
        # A pattern names a file or a directory; a directory covers everything under it.
        for n in range(1, len(tail) + 1):
            if directory and n == len(tail):
                break
            if fnmatch.fnmatchcase("/".join(tail[:n]), p):
                return True
    return False


def area_for(path: str, rules: list[Rule]) -> str | None:
    """The area slug of the last rule that matches, as GitHub decides; None when no rule does."""
    for rule in reversed(rules):
        if matches(rule.pattern, path):
            return area_slug(rule.pattern)
    return None


def area_slug(pattern: str) -> str:
    return slugify(pattern.strip("/").replace("*", " ")) or WHOLE_REPO


def area_name(pattern: str) -> str:
    """A short readable name for a CODEOWNERS path: `pkg/cmd/codespace/` -> `codespace`, `*.go` -> `go files`."""
    p = pattern.strip().strip("/")
    if p in ("*", "**", ""):
        return "Whole repository"
    if re.fullmatch(r"(\*\*/)?\*\.[\w.-]+", p):
        return f"{p.rsplit('.', 1)[-1]} files"
    segments = [s for s in p.split("/") if s and "*" not in s]
    kept = [s for s in segments if s.lower() not in _GENERIC] or segments[-1:] or [p]
    return "/".join(kept)


def owner_key(owner: str) -> str:
    """`@cli/codespaces` -> `team:codespaces`; `@octocat` -> `person:octocat`."""
    name = owner.lstrip("@").lower()
    if "/" in name:
        return f"team:{slugify(name.split('/', 1)[1])}"
    return f"person:{name}"


def owner_label(owner: str) -> str:
    name = owner.lstrip("@").lower()
    return f"the {name} team" if "/" in name else name


@dataclass
class CodeOwners:
    docs: list[Doc]
    passages: list
    facts: list
    activity: list[tuple[str, str, str]]  # (handle, doc id, at)
    rules: list[Rule]  # the current file
    history: list[tuple[str, list[Rule]]]  # (day, rules) for every version, oldest first
    names: dict[str, str]  # area slug -> name
    patterns: dict[str, str]  # area slug -> pattern
    teams: dict[str, str]  # team slug -> "org/team"


def codeowners_history(repo: str, versions: list[dict]) -> CodeOwners:
    """Each version is `{"sha", "date", "author_handle", "text"}`, oldest first."""
    out = CodeOwners([], [], [], [], [], [], {}, {}, {})
    previous: dict[str, tuple[str, ...]] = {}
    owner_versions = []
    for v in versions:
        rules = parse_codeowners(v["text"])
        out.history.append((day(v["date"]), rules))
        current: dict[str, tuple[str, ...]] = {}
        for rule in rules:
            slug = area_slug(rule.pattern)
            current[slug] = rule.owners  # a later rule for the same path wins, as on GitHub
            out.patterns[slug] = rule.pattern
            out.names.setdefault(slug, area_name(rule.pattern))
        lines, changed = [], []
        for slug in sorted(set(previous) | set(current), key=lambda s: (s != WHOLE_REPO, s)):
            before, after = previous.get(slug), current.get(slug)
            if before == after:
                continue
            pattern = out.patterns[slug]
            changed.append(out.names[slug])
            show = lambda owners: ", ".join(owners) or "no one"  # noqa: E731
            if before is None:
                lines.append(f"{pattern} added, owned by {show(after)}.")
            elif after is None:
                lines.append(f"{pattern} removed from CODEOWNERS.")
            else:
                lines.append(f"{pattern}: owners changed from {show(before)} to {show(after)}.")
        if not lines:
            continue
        when = day(v["date"])
        title = changed[0] if len(changed) == 1 else f"{changed[0]} and {len(changed) - 1} more"
        doc = Doc(
            id=f"ownership_map:{v['sha'][:10]}",
            kind="ownership_map",
            title=f"CODEOWNERS: {title}",
            url=f"https://github.com/{repo}/commit/{v['sha']}",
            updated_at=when,
            author=v.get("author_handle"),
        )
        passage = passages_of(doc.id, ["\n".join(lines)])[0]
        out.docs.append(doc)
        out.passages.append(passage)
        if v.get("author_handle"):
            out.activity.append((v["author_handle"], doc.id, when))
        owner_versions.append((when, passage.id, current))
        for owners in current.values():
            for o in owners:
                if "/" in o:
                    out.teams[owner_key(o)[5:]] = o.lstrip("@")
        previous = current
    out.rules = out.history[-1][1] if out.history else []

    def text(area: str, owner: str) -> str:
        return f"{out.names[area]} ({out.patterns[area]}) is owned by {owner_label(owner)}."

    out.facts = owned_by_facts(owner_windows(owner_versions), value=owner_key, text=text)
    return out


# ----- the batch -------------------------------------------------------------------------------------------------


def _title(path: str, meta: dict, body: str, repo: str) -> str:
    if meta.get("title"):
        return meta["title"]
    m = re.search(r"^#\s+(.+?)\s*#*\s*$", body, re.M)
    if m:
        return re.sub(r"[*_`]", "", re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", m.group(1))).strip() or Path(path).stem
    stem = Path(path).stem
    if stem.lower() in ("readme", "index"):
        parent = str(PurePosixPath(path).parent)
        return repo if parent == "." else parent
    return stem.replace("-", " ").replace("_", " ").capitalize()


def _snippet(title: str, body: str | None, limit: int = 600) -> str:
    body = re.sub(r"<!--.*?-->", "", body or "", flags=re.S).strip()
    return f"{title}\n{body[:limit]}".strip()


def load_repo(repo: str, fetch: Fetch) -> Batch:
    """Everything one repository says about how its project works, as one batch for the graph writer."""
    meta = fetch("meta") or {}
    branch = meta.get("default_branch") or "main"
    batch = Batch()
    people: dict[str, Person] = {}

    for c in fetch("contributors") or []:
        handle = (c.get("login") or "").lower()
        if handle and not handle.endswith("[bot]"):
            people[handle] = Person(handle, c.get("name") or handle)

    def act(handle: str | None, doc_id: str, rel: str, at: str | None) -> None:
        if handle and at and not handle.endswith("[bot]"):
            handle = handle.lower()
            people.setdefault(handle, Person(handle, handle))
            batch.activity.append(Activity(handle, doc_id, rel, day(at)))  # type: ignore[arg-type]

    owners = codeowners_history(repo, fetch("codeowners") or [])
    batch.docs += owners.docs
    batch.passages += owners.passages
    batch.facts += owners.facts
    for handle, doc_id, at in owners.activity:
        act(handle, doc_id, "AUTHORED", at)
    batch.areas = [Area(slug, name) for slug, name in sorted(owners.names.items())]
    batch.teams = [Team(slug, name) for slug, name in sorted(owners.teams.items())]
    def rules_at(when: str | None) -> list[Rule]:
        """The CODEOWNERS rules in force on a day: a pull request belongs to the areas of its time."""
        found = owners.rules
        if when:
            found = next((r for d, r in reversed(owners.history) if d <= when[:10]), owners.history[0][1] if owners.history else [])
        return found

    def areas_of(paths, when: str | None = None) -> tuple[str, ...]:
        rules = rules_at(when)
        found = {area_for(p, rules) for p in paths}
        return tuple(sorted(a for a in found if a and a != WHOLE_REPO))

    for f in fetch("docs") or []:
        path = f["path"]
        meta_, body = frontmatter(f["text"])
        text = clean_mdx(body)
        commits = f.get("commits") or []  # newest first
        if not text or not commits:
            continue
        decision = bool(_DECISIONS.search(path))
        doc = Doc(
            id=f"{'rfc' if decision else 'doc'}:{path}",
            kind="rfc" if decision else "doc",
            title=_title(path, meta_, body, repo),
            url=f"https://github.com/{repo}/blob/{branch}/{path}",
            updated_at=day(commits[0]["date"]),
            author=(commits[0].get("handle") or None),
            areas=areas_of([path]),
            decided_at=day(commits[-1]["date"]) if decision else None,
        )
        batch.docs.append(doc)
        batch.passages += passages_of(doc.id, split_passages(text))
        seen: set[str] = set()
        for c in commits[:MAX_DOC_AUTHORS]:
            if c.get("handle") and c["handle"] not in seen:
                seen.add(c["handle"])
                act(c["handle"], doc.id, "AUTHORED", c["date"])

    for kind, rows in (("pull", fetch("pulls") or []), ("issue", fetch("issues") or [])):
        for r in rows:
            at = r.get("merged_at") or r.get("created_at")
            doc = Doc(
                id=f"{kind}:{r['number']}",
                kind=kind,  # type: ignore[arg-type]
                title=r["title"],
                url=r["url"],
                updated_at=day(at),
                author=(r.get("author") or "").lower() or None,
                areas=areas_of(r.get("files") or [], at),
            )
            batch.docs.append(doc)
            batch.passages += passages_of(doc.id, [_snippet(r["title"], r.get("body"))])
            act(r.get("author"), doc.id, "AUTHORED", r.get("created_at"))
            for rev in r.get("reviews") or []:
                rel = "REVIEWED" if rev["state"] in ("APPROVED", "CHANGES_REQUESTED") else "COMMENTED"
                act(rev["author"], doc.id, rel, rev["at"])
            for c in r.get("comments") or []:
                act(c["author"], doc.id, "COMMENTED", c["at"])

    # Owners named in CODEOWNERS are people too, even before they show up in any activity.
    for f in batch.facts:
        if f.value.startswith("person:"):
            handle = f.value[7:]
            people.setdefault(handle, Person(handle, handle))
    batch.people = sorted(people.values(), key=lambda p: p.handle)
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
        files(first: 60) { nodes { path } }
        reviews(first: 30) { nodes { author { login __typename } state submittedAt } }
      }
    }
  }
}"""

_ISSUES = """
query($owner: String!, $name: String!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    issues(first: 50, after: $cursor, orderBy: {field: UPDATED_AT, direction: DESC}) {
      pageInfo { hasNextPage endCursor }
      nodes {
        number title bodyText url createdAt updatedAt
        author { login __typename }
        comments(first: 20) { nodes { author { login __typename } createdAt } }
      }
    }
  }
}"""

_REPO = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9._-]{1,100}$")


def parse_repo(text: str) -> str | None:
    """`owner/name` from what a person types: `owner/name`, a github.com URL, with or without `.git`."""
    t = (text or "").strip()
    t = re.sub(r"^(https?://)?(www\.)?github\.com/", "", t, flags=re.I)
    t = re.sub(r"(\.git)?/*$", "", t)
    t = "/".join(t.split("/")[:2])
    return t if _REPO.match(t) and not t.endswith((".", "/..")) and ".." not in t else None


class RepoSource:
    """Reads one repository live. `prepare()` clones or updates the clone; then each piece is fetched by name.

    `since_head` (a commit) limits docs to files changed after it; `since` (an ISO time) limits issues and pull
    requests to those updated after it. Both come from the last sync.
    """

    def __init__(
        self,
        repo: str,
        root: Path,
        *,
        token: str | None = None,
        since_head: str | None = None,
        since: str | None = None,
        max_pulls: int = 150,
        max_issues: int = 150,
        max_contributors: int = 100,
    ):
        self.repo, self.root = repo, Path(root)
        self.since_head, self.since = since_head, since
        self.max_pulls, self.max_issues, self.max_contributors = max_pulls, max_issues, max_contributors
        self.github = gh.GitHub(token=token if token is not None else os.environ.get("GITHUB_TOKEN", ""))
        self.head: str | None = None
        self.removed: list[str] = []
        self._emails: dict[str, str] | None = None

    @property
    def clone_dir(self) -> Path:
        return self.root / "git"

    def prepare(self) -> str:
        """Clone once (blob-less and sparse: only Markdown and CODEOWNERS files are downloaded), else pull."""
        exists = (self.clone_dir / ".git").exists()
        gh.clone(
            f"https://github.com/{self.repo}.git",
            self.clone_dir,
            sparse=["*.md", "*.mdx", *(f"/{p}" for p in CODEOWNERS_PATHS)],
        )
        self.head = gh.pull(self.clone_dir) if exists else gh.head(self.clone_dir)
        return self.head

    def __call__(self, name: str) -> Any:
        return getattr(self, f"_{name}")()

    def _meta(self) -> dict:
        r = self.github.get(f"/repos/{self.repo}").json()
        return {"default_branch": r.get("default_branch"), "description": r.get("description") or ""}

    def _handles(self) -> dict[str, str]:
        """Commit email -> GitHub handle, from the API's view of recent commits. The emails are only used here, to
        turn a commit into a handle; none are kept."""
        if self._emails is None:
            self._emails = {}
            try:
                for c in self.github.paginate(f"/repos/{self.repo}/commits", limit=300):
                    login = ((c.get("author") or {}).get("login") or "").lower()
                    email = ((c.get("commit") or {}).get("author") or {}).get("email") or ""
                    if login and email and not login.endswith("[bot]"):
                        self._emails.setdefault(email.lower(), login)
            except Exception:
                pass
        return self._emails

    def _handle(self, email: str) -> str | None:
        return gh.handle_from_email(email) or self._handles().get(email.lower())

    def _docs(self) -> list[dict]:
        repo = self.clone_dir
        if self.since_head:
            changed = [p for p in gh.changed_paths(repo, self.since_head, self.head or gh.head(repo)) if is_doc(p)]
            paths = [p for p in changed if (repo / p).is_file()]
            self.removed = [p for p in changed if not (repo / p).is_file()]
        else:
            paths = sorted(
                (str(f.relative_to(repo)) for f in repo.rglob("*") if f.is_file() and ".git" not in f.parts),
                key=lambda p: (p.count("/"), p),  # top-level pages first when there are too many
            )
            paths = [p for p in paths if is_doc(p)][:MAX_DOCS]
        if not paths:
            return []
        history = gh.file_commits(repo, *paths) if len(paths) <= 200 else gh.file_commits(repo, "*.md", "*.mdx")
        rows = []
        for path in paths:
            file = repo / path
            if file.stat().st_size > MAX_DOC_BYTES or path not in history:
                continue
            rows.append(
                {
                    "path": path,
                    "text": file.read_text(errors="replace"),
                    "commits": [{"sha": c.sha, "date": c.date, "handle": self._handle(c.email)} for c in history[path]],
                }
            )
        return rows

    def _codeowners(self) -> list[dict]:
        repo = self.clone_dir
        out = gh.git(repo, "log", "--reverse", f"--format=%H{gh._SEP}%aI{gh._SEP}%an{gh._SEP}%ae", "--", *CODEOWNERS_PATHS)
        versions = []
        for line in out.splitlines():
            if not line:
                continue
            c = gh._commit(line)
            text = None
            for path in CODEOWNERS_PATHS:  # the file GitHub reads at that commit
                try:
                    text = gh.show(repo, c.sha, path)
                    break
                except subprocess.CalledProcessError:
                    continue
            versions.append({"sha": c.sha, "date": c.date, "author_handle": self._handle(c.email), "text": text or ""})
        return versions

    def _since_keep(self, limit: int, stamp: str):
        count = 0

        def keep(n: dict) -> bool | None:
            nonlocal count
            if count >= limit or (self.since and (n.get(stamp) or "") < self.since):
                return None
            count += 1
            return True

        return keep

    def _pulls(self) -> list[dict]:
        nodes = self.github.paged(_PULLS, self.repo, "pullRequests", self._since_keep(self.max_pulls, "updatedAt"))
        return [
            {
                "number": n["number"],
                "title": n["title"],
                "body": (n["bodyText"] or "")[:1200],
                "url": n["url"],
                "created_at": n["createdAt"],
                "merged_at": n["mergedAt"],
                "author": gh.login_of(n["author"]),
                "files": [f["path"] for f in (n.get("files") or {}).get("nodes") or []],
                "reviews": [
                    {"author": gh.login_of(r["author"]), "state": r["state"], "at": r["submittedAt"]}
                    for r in n["reviews"]["nodes"]
                    if gh.login_of(r["author"]) and r["submittedAt"]
                ],
            }
            for n in nodes
        ]

    def _issues(self) -> list[dict]:
        nodes = self.github.paged(_ISSUES, self.repo, "issues", self._since_keep(self.max_issues, "updatedAt"))
        return [
            {
                "number": n["number"],
                "title": n["title"],
                "body": (n["bodyText"] or "")[:1200],
                "url": n["url"],
                "created_at": n["createdAt"],
                "author": gh.login_of(n["author"]),
                "comments": [
                    {"author": gh.login_of(c["author"]), "at": c["createdAt"]}
                    for c in n["comments"]["nodes"]
                    if gh.login_of(c["author"])
                ],
            }
            for n in nodes
        ]

    def _contributors(self) -> list[dict]:
        rows = [
            c
            for c in self.github.paginate(f"/repos/{self.repo}/contributors", limit=self.max_contributors)
            if c.get("type") == "User" and c.get("login")
        ]
        names: dict[str, str] = {}
        # Published names in one request: an aliased query per handle.
        for i in range(0, min(len(rows), 60), 30):
            chunk = rows[i : i + 30]
            query = "query {" + " ".join(f'u{j}: user(login: "{c["login"]}") {{ login name }}' for j, c in enumerate(chunk)) + "}"
            try:
                data = self.github.graphql(query, {})
            except Exception:
                break
            for value in data.values():
                if value and value.get("name"):
                    names[value["login"].lower()] = value["name"]
        return [
            {"login": c["login"].lower(), "name": names.get(c["login"].lower()), "contributions": c.get("contributions", 0)}
            for c in rows
        ]
