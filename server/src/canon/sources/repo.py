"""A connector for any public GitHub repository: its docs, wiki, decision records, CODEOWNERS history, issues and
pull requests with their comment threads, discussions, releases and contributors, as one `Batch`.

Like the PostHog connector it works in two steps. A source fetches raw pieces by name (`"meta"`, `"docs"`,
`"wiki"`, `"codeowners"`, `"pulls"`, `"issues"`, `"discussions"`, `"releases"`, `"contributors"`); tests pass a
callable over small fixtures instead. Then `load_repo` turns them into a batch.

- **Docs.** Every Markdown and MDX file (not changelogs, licences or templates) is a document with its git history:
  dated by its last commit, authored by everyone who committed to it.
- **Decision records.** Pages under `docs/adr/`, `doc/adr/`, `docs/decisions/` (kind `adr`) or `rfcs/`, `rfc/`,
  `proposals/`, `design/` (kind `rfc`), or with ADR or RFC frontmatter, are decided on the day they were added.
  `canon.decisions` makes each one a Decision with its status and what replaced it.
- **Wiki.** The `<repo>.wiki.git` repository, when there is one: each page with its git history.
- **CODEOWNERS.** The file's git history is the authority on who owns what (authority 3), exactly as PostHog's
  ownership map is: each commit that changes an owner list is a document, and each area's owners hold from that
  commit until the list changes again. An area is a CODEOWNERS path. `@org/team` owners are teams, `@handle`
  owners are people. Email owners are skipped: no emails are kept.
- **Issues and pull requests** (tickets), bounded and newest first. A pull request is about the areas whose
  CODEOWNERS paths its changed files fall under. Their comments are a separate document, a comment thread, with one
  passage per comment that says who wrote it and when.
- **Discussions** (chats), bounded and newest first: the opening post, the accepted answer and the first comments,
  each a passage with its author and date.
- **Releases**: what shipped when, each a document dated by its publication.
- **Contributors**, by GitHub handle and published name.

`RepoSource` reads a repository live from a blob-less sparse clone (only Markdown and CODEOWNERS files are ever
downloaded) and the GitHub API, with the signed-in user's token or the server's. With `since` it reads only what
changed: docs touched between two commits, and issues, pull requests and discussions updated after a time. API
answers are cached on disk for the day, so a run that is retried asks GitHub nothing twice.
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
from canon.sources.cache import Cache
from canon.sources.ownership import owned_by_facts, owner_windows
from canon.sources.text import Turn, clean_mdx, day, frontmatter, passages_of, slugify, split_passages, turn_passages
from canon.types import Activity, Area, Batch, Doc, Person, Team

Fetch = Callable[[str], Any]

CODEOWNERS_PATHS = (".github/CODEOWNERS", "CODEOWNERS", "docs/CODEOWNERS")  # GitHub's order of precedence
DOC_SUFFIXES = (".md", ".mdx")
_SKIP_DOC = re.compile(
    r"(^|/)(node_modules|vendor|third_party|\.git|fixtures?|testdata|__snapshots__)/"
    r"|(^|/)(CHANGELOG|CHANGES|HISTORY|LICENSE|LICENCE|NOTICE|COPYING)[^/]*$"
    r"|(^|/)(ISSUE_TEMPLATE|PULL_REQUEST_TEMPLATE)(/|\.md$)",
    re.I,
)
_ADR_DIR = re.compile(r"(^|/)(adrs?|decisions?|decision[-_]records?|architecture[-_]decisions?)/", re.I)
_RFC_DIR = re.compile(r"(^|/)(rfcs?|proposals?|design)/", re.I)
_INDEX = re.compile(r"(^|/)(readme|index|template)[^/]*$", re.I)
# Path segments that say nothing about what an area is, left out of its name.
_GENERIC = {"src", "lib", "pkg", "cmd", "internal", "app", "apps", "packages", "source", "sources", "main"}
WHOLE_REPO = "all"
MAX_DOCS = 400
MAX_DOC_BYTES = 200_000
MAX_DOC_AUTHORS = 20
MAX_RELEASE_PASSAGES = 6
MAX_WIKI_PAGES = 200
MAX_COMMENT = 1500


def is_doc(path: str) -> bool:
    return path.lower().endswith(DOC_SUFFIXES) and not _SKIP_DOC.search(path)


def decision_kind(path: str, meta: dict[str, str]) -> str | None:
    """`"adr"` or `"rfc"` for a decision record, by its folder or its frontmatter; None for any other page. The
    index or template of a decision folder is not a decision."""
    if _ADR_DIR.search(path):
        return None if _INDEX.search(path) else "adr"
    if _RFC_DIR.search(path):
        return None if _INDEX.search(path) else "rfc"
    keys = {k.lower() for k in meta}
    said = " ".join(f"{k} {v}" for k, v in meta.items() if k.lower() in ("type", "kind", "title", "category", "layout", "tags"))
    if "adr" in keys or re.search(r"\badr\b", said, re.I):
        return "adr"
    if "rfc" in keys or re.search(r"\brfc\b", said, re.I):
        return "rfc"
    return None


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

    # Owners listed together on one rule are co-owners: each fact names the others, so two owners read as a shared
    # area, not as two sources that disagree.
    listed = {(pid, area): owners for _, pid, current in owner_versions for area, owners in current.items()}

    def text(w) -> str:
        others = [o for o in listed.get((w.passage_id, w.area), ()) if o != w.owner]
        also = f", together with {' and '.join(owner_label(o) for o in others)}" if others else ""
        return f"{out.names[w.area]} ({out.patterns[w.area]}) is owned by {owner_label(w.owner)}{also}."

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

    def page(f: dict, *, wiki: bool) -> None:
        path = f["path"]
        meta_, body = frontmatter(f["text"])
        text = clean_mdx(body)
        commits = f.get("commits") or []  # newest first
        if not text or not commits:
            return
        kind = "wiki" if wiki else (decision_kind(path, meta_) or "doc")
        if wiki:
            name = PurePosixPath(path).with_suffix("").as_posix()
            url = f"https://github.com/{repo}/wiki" + ("" if name.lower() == "home" else f"/{name.replace(' ', '-')}")
            title = meta_.get("title") or name.replace("-", " ")
        else:
            url = f"https://github.com/{repo}/blob/{branch}/{path}"
            title = _title(path, meta_, body, repo)
        doc = Doc(
            id=f"{kind}:{path}",
            kind=kind,  # type: ignore[arg-type]
            title=title,
            url=url,
            updated_at=day(commits[0]["date"]),
            author=(commits[0].get("handle") or None),
            areas=() if wiki else areas_of([path]),
            decided_at=day(commits[-1]["date"]) if kind in ("rfc", "adr") else None,
        )
        batch.docs.append(doc)
        batch.passages += passages_of(doc.id, split_passages(text))
        seen: set[str] = set()
        for c in commits[:MAX_DOC_AUTHORS]:
            if c.get("handle") and c["handle"] not in seen:
                seen.add(c["handle"])
                act(c["handle"], doc.id, "AUTHORED", c["date"])

    for f in fetch("docs") or []:
        page(f, wiki=False)
    for f in fetch("wiki") or []:
        page(f, wiki=True)

    def turn(c: dict, label: str | None = None) -> Turn:
        handle = (c.get("author") or "").lower() or None
        return Turn(handle or "Someone", c.get("at") or "", c.get("body") or "", handle, label)

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
            # The conversation under it: who said what, and when, one passage per comment.
            said = [c for c in r.get("comments") or [] if (c.get("body") or "").strip() and c.get("at")]
            if said:
                thread = Doc(f"thread:{kind}:{r['number']}", "thread", r["title"], r["url"], day(said[-1]["at"]),
                             doc.author, doc.areas)
                batch.docs.append(thread)
                batch.passages += turn_passages(thread.id, [turn(c) for c in said])
                for c in said:
                    act(c["author"], thread.id, "COMMENTED", c["at"])

    for d in fetch("discussions") or []:
        doc = Doc(f"discussion:{d['number']}", "discussion", d["title"], d["url"], day(d.get("updated_at") or d["created_at"]),
                  (d.get("author") or "").lower() or None)
        opening = {"author": d.get("author"), "at": d["created_at"], "body": f"{d['title']}\n{d.get('body') or ''}"}
        turns = [turn(opening)]
        answer = d.get("answer")
        if answer and (answer.get("body") or "").strip():
            turns.append(turn(answer, "Answer"))
        turns += [turn(c) for c in d.get("comments") or [] if not answer or c.get("body") != answer.get("body")]
        batch.docs.append(doc)
        batch.passages += turn_passages(doc.id, turns)
        act(d.get("author"), doc.id, "AUTHORED", d["created_at"])
        for c in [answer or {}, *(d.get("comments") or [])]:
            act(c.get("author"), doc.id, "COMMENTED", c.get("at"))

    for r in fetch("releases") or []:
        when = r.get("published_at") or r.get("created_at")
        if not when:
            continue
        title = r.get("name") or r["tag"]
        doc = Doc(f"release:{r['tag']}", "release", title if r["tag"] in title else f"{title} ({r['tag']})", r["url"],
                  day(when), (r.get("author") or "").lower() or None)
        notes = split_passages(clean_mdx(r.get("body") or ""))[:MAX_RELEASE_PASSAGES]
        batch.docs.append(doc)
        batch.passages += passages_of(doc.id, [f"{doc.title}, released {day(when)}\n{p}" for p in notes] or [f"{doc.title}, released {day(when)}"])
        act(r.get("author"), doc.id, "AUTHORED", when)

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
        comments(first: 20) { nodes { author { login __typename } bodyText createdAt } }
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
        comments(first: 20) { nodes { author { login __typename } bodyText createdAt } }
      }
    }
  }
}"""

_DISCUSSIONS = """
query($owner: String!, $name: String!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    discussions(first: 25, after: $cursor, orderBy: {field: UPDATED_AT, direction: DESC}) {
      pageInfo { hasNextPage endCursor }
      nodes {
        number title bodyText url createdAt updatedAt
        author { login __typename }
        category { name }
        answer { author { login __typename } bodyText createdAt }
        comments(first: 8) { nodes { author { login __typename } bodyText createdAt } }
      }
    }
  }
}"""

_REPO =re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9._-]{1,100}$")


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
        max_discussions: int = 100,
        max_releases: int = 40,
    ):
        self.repo, self.root = repo, Path(root)
        self.since_head, self.since = since_head, since
        self.max_pulls, self.max_issues, self.max_contributors = max_pulls, max_issues, max_contributors
        self.max_discussions, self.max_releases = max_discussions, max_releases
        self.github = gh.GitHub(token=token if token is not None else os.environ.get("GITHUB_TOKEN", ""))
        self.head: str | None = None
        self.removed: list[str] = []
        self._emails: dict[str, str] | None = None
        self._meta_row: dict | None = None
        self.cache = Cache(self.root / "api")

    @property
    def clone_dir(self) -> Path:
        return self.root / "git"

    @property
    def wiki_dir(self) -> Path:
        return self.root / "wiki"

    def _cached(self, name: str, fetch: Callable[[], Any]) -> Any:
        """An API answer, kept on disk for the day under the window it was asked for, so a retried run reuses it."""
        from datetime import date

        window = re.sub(r"[^0-9A-Za-z]+", "", self.since or "all")
        return self.cache.json(f"{name}-{window}-{date.today().isoformat()}", fetch)

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
        if self._meta_row is None:
            r = self.github.get(f"/repos/{self.repo}").json()
            self._meta_row = {
                "default_branch": r.get("default_branch"),
                "description": r.get("description") or "",
                "has_wiki": bool(r.get("has_wiki")),
                "has_discussions": bool(r.get("has_discussions")),
            }
        return self._meta_row

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

    @staticmethod
    def _all_docs(repo: Path) -> list[str]:
        """Every doc path in a clone: decision folders first, then top-level pages first, for when there are too many."""
        paths = [str(f.relative_to(repo)) for f in repo.rglob("*") if f.is_file() and ".git" not in f.parts]
        return sorted((p for p in paths if is_doc(p)), key=lambda p: (not (_ADR_DIR.search(p) or _RFC_DIR.search(p)), p.count("/"), p))

    def _rows(self, repo: Path, paths: list[str]) -> list[dict]:
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

    def _docs(self) -> list[dict]:
        repo = self.clone_dir
        if self.since_head:
            changed = [p for p in gh.changed_paths(repo, self.since_head, self.head or gh.head(repo)) if is_doc(p)]
            paths = [p for p in changed if (repo / p).is_file()]
            self.removed = [p for p in changed if not (repo / p).is_file()]
        else:
            paths = self._all_docs(repo)[:MAX_DOCS]
        return self._rows(repo, paths)

    def _decision_records(self) -> list[dict]:
        """Every decision record on the default branch, read whole on every run: which decision replaced which is
        decided across all of them, not only the ones that changed. Rows in the shape `canon.decisions.rfc` reads."""
        repo = self.clone_dir
        rows = []
        for path in self._all_docs(repo)[:MAX_DOCS]:
            file = repo / path
            if file.stat().st_size > MAX_DOC_BYTES:
                continue
            text = file.read_text(errors="replace")
            kind = decision_kind(path, frontmatter(text)[0])
            if kind:
                rows.append({"path": path, "doc_id": f"{kind}:{path}", "text": text})
        if not rows:
            return []
        history = gh.file_commits(repo, *[r["path"] for r in rows])
        out = []
        for r in rows:
            commits = history.get(r["path"]) or []
            if commits:  # newest first
                out.append({**r, "created_at": commits[-1].date, "updated_at": commits[0].date})
        return out

    def _wiki(self) -> list[dict]:
        """The wiki's pages, from a clone of `<repo>.wiki.git`. A repository without a wiki gives nothing."""
        if not self._meta().get("has_wiki"):
            return []
        try:
            if (self.wiki_dir / ".git").exists():
                gh.pull(self.wiki_dir)
            else:
                gh.clone(f"https://github.com/{self.repo}.wiki.git", self.wiki_dir, quiet_fail=True)
        except subprocess.CalledProcessError:
            return []
        if not (self.wiki_dir / ".git").exists():
            return []
        paths = [p for p in self._all_docs(self.wiki_dir) if not p.startswith("_")][:MAX_WIKI_PAGES]
        return self._rows(self.wiki_dir, paths)

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

    @staticmethod
    def _comments(n: dict) -> list[dict]:
        return [
            {"author": gh.login_of(c["author"]), "at": c["createdAt"], "body": (c.get("bodyText") or "")[:MAX_COMMENT]}
            for c in (n.get("comments") or {}).get("nodes") or []
            if gh.login_of(c["author"])
        ]

    def _pulls(self) -> list[dict]:
        def read() -> list[dict]:
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
                    "comments": self._comments(n),
                }
                for n in nodes
            ]

        return self._cached("pulls", read)

    def _issues(self) -> list[dict]:
        def read() -> list[dict]:
            nodes = self.github.paged(_ISSUES, self.repo, "issues", self._since_keep(self.max_issues, "updatedAt"))
            return [
                {
                    "number": n["number"],
                    "title": n["title"],
                    "body": (n["bodyText"] or "")[:1200],
                    "url": n["url"],
                    "created_at": n["createdAt"],
                    "author": gh.login_of(n["author"]),
                    "comments": self._comments(n),
                }
                for n in nodes
            ]

        return self._cached("issues", read)

    def _discussions(self) -> list[dict]:
        """Discussions, newest first: each with its accepted answer and first comments. Nothing when the repository
        has discussions turned off."""
        if not self._meta().get("has_discussions"):
            return []

        def read() -> list[dict]:
            try:
                nodes = self.github.paged(
                    _DISCUSSIONS, self.repo, "discussions", self._since_keep(self.max_discussions, "updatedAt")
                )
            except RuntimeError:  # GraphQL said no: discussions are off or hidden
                return []
            out = []
            for n in nodes:
                answer = n.get("answer")
                out.append(
                    {
                        "number": n["number"],
                        "title": n["title"],
                        "body": (n.get("bodyText") or "")[:MAX_COMMENT],
                        "url": n["url"],
                        "created_at": n["createdAt"],
                        "updated_at": n["updatedAt"],
                        "author": gh.login_of(n["author"]),
                        "category": (n.get("category") or {}).get("name"),
                        "answer": {
                            "author": gh.login_of(answer.get("author")),
                            "at": answer["createdAt"],
                            "body": (answer.get("bodyText") or "")[:MAX_COMMENT],
                        }
                        if answer
                        else None,
                        "comments": self._comments(n),
                    }
                )
            return out

        return self._cached("discussions", read)

    def _releases(self) -> list[dict]:
        """Published releases, newest first. Drafts are not releases."""

        def read() -> list[dict]:
            rows = self.github.paginate(f"/repos/{self.repo}/releases", limit=self.max_releases)
            return [
                {
                    "tag": r["tag_name"],
                    "name": (r.get("name") or "").strip() or None,
                    "url": r["html_url"],
                    "published_at": r.get("published_at"),
                    "created_at": r.get("created_at"),
                    "author": gh.login_of({"login": (r.get("author") or {}).get("login"), "__typename": (r.get("author") or {}).get("type")}),
                    "body": (r.get("body") or "")[:8000],
                    "prerelease": bool(r.get("prerelease")),
                }
                for r in rows
                if not r.get("draft") and r.get("tag_name") and (not self.since or (r.get("published_at") or "") >= self.since)
            ]

        return self._cached("releases", read)

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
