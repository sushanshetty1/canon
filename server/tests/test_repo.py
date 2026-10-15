"""The generic repository connector: CODEOWNERS history, docs with git history, issues, pull requests, people."""

import json
import re
import subprocess
from dataclasses import asdict
from types import SimpleNamespace

import pytest

from canon.ingest import ingest_repo, source_state
from canon.sources import github as gh
from canon.sources.repo import (
    RepoSource,
    area_for,
    area_name,
    is_doc,
    codeowners_history,
    load_repo,
    matches,
    parse_codeowners,
    parse_repo,
)

V1 = """# Owners
* @acme/core
docs/ @alice
pkg/cmd/billing/ @acme/billing  # the billing commands
"""
V2 = """* @acme/core
docs/ @acme/docs owner@example.com
pkg/cmd/billing/ @acme/billing
"""
V3 = """* @acme/core
docs/ @acme/docs @acme/core
"""


def versions():
    return [
        {"sha": "a" * 40, "date": "2026-01-10T09:00:00Z", "author_handle": "alice", "text": V1},
        {"sha": "b" * 40, "date": "2026-03-02T09:00:00Z", "author_handle": "bob", "text": V2},
        {"sha": "c" * 40, "date": "2026-03-02T12:00:00Z", "author_handle": None, "text": V2},  # no change
        {"sha": "d" * 40, "date": "2026-06-20T09:00:00Z", "author_handle": "bob", "text": V3},
    ]


@pytest.mark.parametrize(
    "path, doc",
    [
        ("docs/releasing.md", True),
        ("README.mdx", True),
        ("CHANGELOG.md", False),
        ("main.go", False),
        (".github/ISSUE_TEMPLATE/bug.md", False),
        ("pkg/cmd/pr/fixtures/repo/.github/PULL_REQUEST_TEMPLATE/fix.md", False),
        ("docs/pull_request_template.md", False),
        ("internal/attachments/testdata/input.md", False),
        ("web/node_modules/x/README.md", False),
    ],
)
def test_which_files_are_docs(path, doc):
    assert is_doc(path) is doc


def test_parse_codeowners_drops_comments_and_emails():
    rules = parse_codeowners(V2)
    assert [(r.pattern, r.owners) for r in rules] == [
        ("*", ("@acme/core",)),
        ("docs/", ("@acme/docs",)),
        ("pkg/cmd/billing/", ("@acme/billing",)),
    ]
    assert parse_codeowners(V1)[2].owners == ("@acme/billing",)


@pytest.mark.parametrize(
    "pattern, path, hit",
    [
        ("*", "anything/at/all.md", True),
        ("docs/", "docs/guide/setup.md", True),
        ("docs/", "src/docs/x.md", True),  # an unanchored directory matches at any depth
        ("/docs/", "src/docs/x.md", False),
        ("pkg/cmd/billing/", "pkg/cmd/billing/run.go", True),
        ("pkg/cmd/billing/", "pkg/cmd/billingx/run.go", False),
        ("*.go", "pkg/main.go", True),
        ("*.go", "README.md", False),
        ("docs/*.md", "docs/a.md", True),
        ("test/integration/attestation-cmd", "test/integration/attestation-cmd/run.sh", True),
    ],
)
def test_matches(pattern, path, hit):
    assert matches(pattern, path) is hit


def test_last_matching_rule_wins_and_names_read_well():
    rules = parse_codeowners(V1)
    assert area_for("docs/guide.md", rules) == "docs"
    assert area_for("pkg/cmd/billing/x.go", rules) == "pkg-cmd-billing"
    assert area_for("README.md", rules) == "all"
    assert area_name("pkg/cmd/codespace/") == "codespace"
    assert area_name("*") == "Whole repository"
    assert area_name("*.go") == "go files"
    assert area_name("/internal/skills/") == "skills"


def test_codeowners_history_gives_dated_windows_with_co_owners():
    own = codeowners_history("acme/app", versions())
    assert [d.id for d in own.docs] == ["ownership_map:aaaaaaaaaa", "ownership_map:bbbbbbbbbb", "ownership_map:dddddddddd"]
    assert own.docs[1].title == "CODEOWNERS: docs" and own.docs[1].kind == "ownership_map"
    assert own.docs[1].url == "https://github.com/acme/app/commit/" + "b" * 40
    windows = {(f.subject, f.value, f.valid_from, f.valid_to) for f in own.facts}
    assert windows == {
        ("area:all", "team:core", "2026-01-10", None),
        ("area:docs", "person:alice", "2026-01-10", "2026-03-02"),
        ("area:docs", "team:docs", "2026-03-02", "2026-06-20"),
        # The docs team stays on as a co-owner: restated from the commit that added core, not replaced by it.
        ("area:docs", "team:docs", "2026-06-20", None),
        ("area:docs", "team:core", "2026-06-20", None),
        ("area:pkg-cmd-billing", "team:billing", "2026-01-10", "2026-06-20"),
    }
    assert all(f.authority == 3 and f.predicate == "owned_by" for f in own.facts)
    assert {f.text for f in own.facts if f.value == "person:alice"} == {"docs (docs/) is owned by alice."}
    # Co-owners name each other, so a reader sees one shared area, not two sources disagreeing.
    assert {f.text for f in own.facts if f.subject == "area:docs" and f.valid_to is None} == {
        "docs (docs/) is owned by the acme/docs team, together with the acme/core team.",
        "docs (docs/) is owned by the acme/core team, together with the acme/docs team.",
    }
    assert "pkg/cmd/billing/ removed from CODEOWNERS." in own.passages[2].text
    assert own.teams == {"core": "acme/core", "billing": "acme/billing", "docs": "acme/docs"}


def fixture_fetch(name):
    return {
        "meta": {"default_branch": "trunk"},
        "contributors": [{"login": "alice", "name": "Alice Ng", "contributions": 40}, {"login": "dependabot[bot]"}],
        "codeowners": versions(),
        "docs": [
            {
                "path": "docs/releasing.md",
                "text": "---\ntitle: Releasing\n---\n# Releasing\n\nThe docs team owns releases. Releases go out on Tuesdays.\n",
                "commits": [
                    {"sha": "e" * 40, "date": "2026-07-01T10:00:00Z", "handle": "bob"},
                    {"sha": "f" * 40, "date": "2026-02-01T10:00:00Z", "handle": "alice"},
                ],
            },
            {
                "path": "docs/rfcs/0001-plugins.md",
                "text": "# Plugins\n\nWe will support plugins.\n",
                "commits": [{"sha": "1" * 40, "date": "2026-04-01T10:00:00Z", "handle": None}],
            },
        ],
        "pulls": [
            {
                "number": 7,
                "title": "Fix billing rounding",
                "body": "Rounds cents.",
                "url": "https://github.com/acme/app/pull/7",
                "created_at": "2026-05-01T00:00:00Z",
                "merged_at": "2026-05-03T00:00:00Z",
                "author": "carol",
                "files": ["pkg/cmd/billing/round.go", "README.md"],
                "reviews": [{"author": "alice", "state": "APPROVED", "at": "2026-05-02T00:00:00Z"}],
            }
        ],
        "issues": [
            {
                "number": 8,
                "title": "Docs typo",
                "body": "",
                "url": "https://github.com/acme/app/issues/8",
                "created_at": "2026-05-05T00:00:00Z",
                "author": "dave",
                "comments": [{"author": "alice", "at": "2026-05-06T00:00:00Z"}],
            }
        ],
    }.get(name)


def test_load_repo_builds_one_batch():
    batch = load_repo("acme/app", fixture_fetch)
    docs = {d.id: d for d in batch.docs}
    page = docs["doc:docs/releasing.md"]
    assert page.kind == "doc" and page.title == "Releasing" and page.updated_at == "2026-07-01"
    assert page.url == "https://github.com/acme/app/blob/trunk/docs/releasing.md" and page.areas == ("docs",)
    rfc = docs["rfc:docs/rfcs/0001-plugins.md"]
    assert rfc.kind == "rfc" and rfc.title == "Plugins" and rfc.decided_at == "2026-04-01"
    # A pull request is about the areas its files fall under; the catch-all rule names no area.
    assert docs["pull:7"].areas == ("pkg-cmd-billing",)
    acts = {(a.handle, a.doc_id, a.rel) for a in batch.activity}
    assert {("bob", "doc:docs/releasing.md", "AUTHORED"), ("alice", "doc:docs/releasing.md", "AUTHORED")} <= acts
    assert {("alice", "pull:7", "REVIEWED"), ("carol", "pull:7", "AUTHORED"), ("alice", "issue:8", "COMMENTED")} <= acts
    people = {p.handle: p.name for p in batch.people}
    assert people["alice"] == "Alice Ng" and "dependabot[bot]" not in people and people["carol"] == "carol"
    assert {a.slug for a in batch.areas} == {"all", "docs", "pkg-cmd-billing"}
    assert {t.slug for t in batch.teams} == {"core", "docs", "billing"}
    # Public data only: no email reaches the batch.
    assert "@example.com" not in json.dumps([asdict(x) for x in [*batch.docs, *batch.passages, *batch.facts, *batch.people]])


@pytest.mark.parametrize(
    "text, repo",
    [
        ("cli/cli", "cli/cli"),
        ("https://github.com/cli/cli", "cli/cli"),
        ("github.com/pallets/flask.git", "pallets/flask"),
        ("https://github.com/cli/cli/tree/trunk/docs", "cli/cli"),
        ("  owner/name.js  ", "owner/name.js"),
        ("git@github.com:PostHog/posthog.git", "PostHog/posthog"),
        ("ssh://git@github.com/cli/cli.git", "cli/cli"),
        ("not a repo", None),
        ("../etc", None),
        ("a/..", None),
        ("", None),
    ],
)
def test_parse_repo(text, repo):
    assert parse_repo(text) == repo


# ----- a real git repository on disk ------------------------------------------------------------------------------


def _git(repo, *args, env=None):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, env=env)


def _commit(repo, message, when, handle):
    env = {
        "GIT_AUTHOR_NAME": handle, "GIT_AUTHOR_EMAIL": f"1+{handle}@users.noreply.github.com",
        "GIT_COMMITTER_NAME": handle, "GIT_COMMITTER_EMAIL": f"1+{handle}@users.noreply.github.com",
        "GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when, "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
        "HOME": str(repo),
    }
    _git(repo, "add", "-A", env=env)
    _git(repo, "commit", "-q", "-m", message, env=env)


@pytest.fixture
def local_source(tmp_path):
    root = tmp_path / "acme"
    repo = root / "git"
    repo.mkdir(parents=True)
    _git(repo, "init", "-q", "-b", "main")
    (repo / "CODEOWNERS").write_text(V1)
    (repo / "docs").mkdir()
    (repo / "docs" / "guide.md").write_text("# Guide\n\nThe core team reviews every change.\n")
    (repo / "docs" / "old.md").write_text("# Old\n\nThe billing team owns invoices.\n")
    (repo / "CHANGELOG.md").write_text("# Changes\n")
    (repo / "main.go").write_text("package main\n")
    _commit(repo, "first", "2026-01-10T09:00:00+00:00", "alice")
    _git(repo, "mv", "CODEOWNERS", ".github-CODEOWNERS")  # moved aside, then into .github/
    (repo / ".github").mkdir()
    _git(repo, "mv", ".github-CODEOWNERS", ".github/CODEOWNERS")
    (repo / ".github" / "CODEOWNERS").write_text(V2)
    _commit(repo, "docs team", "2026-03-02T09:00:00+00:00", "bob")
    src = RepoSource("acme/app", root, token="")
    src._emails = {}  # no API: handles come from noreply emails only
    return src, repo


def test_live_source_reads_docs_and_codeowners_from_git(local_source):
    src, repo = local_source
    src.head = gh.head(repo)
    docs = src("docs")
    assert [d["path"] for d in docs] == ["docs/guide.md", "docs/old.md"]  # no changelog, no code
    assert [c["handle"] for c in docs[0]["commits"]] == ["alice"]
    owners = src("codeowners")
    assert [v["author_handle"] for v in owners] == ["alice", "bob"]
    assert owners[0]["text"] == V1 and owners[1]["text"] == V2  # GitHub's precedence finds the moved file
    batch = load_repo("acme/app", lambda n: {"docs": docs, "codeowners": owners}.get(n))
    assert {(f.subject, f.value, f.valid_to) for f in batch.facts if f.subject == "area:docs"} == {
        ("area:docs", "person:alice", "2026-03-02"),
        ("area:docs", "team:docs", None),
    }


def test_since_reads_only_changed_docs_and_notices_deleted_ones(local_source):
    src, repo = local_source
    first = gh.head(repo)
    (repo / "docs" / "guide.md").write_text("# Guide\n\nThe docs team reviews every change.\n")
    (repo / "docs" / "old.md").unlink()
    _commit(repo, "edit", "2026-07-01T09:00:00+00:00", "carol")
    src.since_head, src.head = first, gh.head(repo)
    docs = src("docs")
    assert [d["path"] for d in docs] == ["docs/guide.md"]
    assert [c["handle"] for c in docs[0]["commits"]] == ["carol", "alice"]
    assert src.removed == ["docs/old.md"]


def test_git_sends_the_token_as_a_header_and_never_stores_it(local_source, tmp_path, monkeypatch):
    import base64

    _, origin = local_source
    token = "gho_privateTOKEN123"
    encoded = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    runs = []
    real = subprocess.run

    def recording(args, **kwargs):
        runs.append((list(args), dict(kwargs.get("env") or {})))
        return real(args, **kwargs)

    monkeypatch.setattr(gh.subprocess, "run", recording)
    dest = tmp_path / "clone" / "git"
    with gh.git_token(token):
        gh.clone(f"file://{origin}", dest, sparse=["*.md", "/.github/CODEOWNERS"])
        head = gh.pull(dest)
        assert "core team" in gh.show(dest, head, "docs/guide.md")
    assert runs and all(token not in " ".join(args) and encoded not in " ".join(args) for args, _ in runs)
    for _, env in runs:
        assert env["GIT_TERMINAL_PROMPT"] == "0"  # never waits for a password
        assert env["GIT_CONFIG_KEY_0"] == "http.https://github.com/.extraheader"  # sent to github.com only
        assert env["GIT_CONFIG_VALUE_0"] == f"Authorization: Basic {encoded}"
    # Nothing under .git holds the token: not the remote URL, not the config, not a log.
    for f in (dest / ".git").rglob("*"):
        if f.is_file():
            data = f.read_bytes()
            assert token.encode() not in data and encoded.encode() not in data, f
    assert "github.com" not in gh.git(dest, "config", "--local", "--list")
    # Outside the block git runs with no token.
    assert "GIT_CONFIG_COUNT" not in gh.git_env()

    # The live source reads under its own token: a blob-less clone fetches old versions as it reads them.
    src = RepoSource("acme/app", tmp_path / "clone", token=token)
    src._emails, src.head = {}, head
    runs.clear()
    assert [d["path"] for d in src("docs")] == ["docs/guide.md", "docs/old.md"]
    assert runs and all(env.get("GIT_CONFIG_VALUE_0") == f"Authorization: Basic {encoded}" for _, env in runs)


# ----- ingest, first run and sync ----------------------------------------------------------------------------------


class FakeSource:
    """A source over fixtures, with a head per run."""

    def __init__(self, head, pieces, removed=()):
        self.head, self.pieces, self.removed = head, pieces, list(removed)

    def prepare(self):
        return self.head

    def __call__(self, name):
        return self.pieces.get(name)


class FakeClaude:
    """Answers extraction calls: an ownership statement in any passage that names a team owning releases."""

    def __init__(self):
        self.prompts = []
        self.messages = SimpleNamespace(create=self.create)

    async def create(self, **kw):
        text = kw["messages"][0]["content"]
        self.prompts.append(text)
        facts = []
        if "owns releases" in text:
            team = re.search(r"The (\w+) team owns releases", text).group(1)
            facts = [{"subject": "topic:releases", "predicate": "contact_for", "value": f"team:{team}", "text": f"The {team} team owns releases."}]
        if "owns the docs" in text:
            facts.append({"subject": "area:docs", "predicate": "owned_by", "value": "team:billing", "text": "The billing team owns the docs."})
        usage = SimpleNamespace(input_tokens=10, output_tokens=5, cache_read_input_tokens=0, cache_creation_input_tokens=0)
        return SimpleNamespace(stop_reason="end_turn", usage=usage,
                               content=[SimpleNamespace(type="text", text=json.dumps({"facts": facts}))])


def pieces(docs):
    base = {k: fixture_fetch(k) for k in ("meta", "contributors", "codeowners", "pulls", "issues")}
    return {**base, "docs": docs}


def doc(path, text, when, handle="bob"):
    return {"path": path, "text": text, "commits": [{"sha": "e" * 40, "date": when, "handle": handle}]}


def test_ingest_then_sync_reextracts_only_changed_passages(graph, tmp_path):
    claude = FakeClaude()
    steps = []
    first = [
        doc("docs/releasing.md", "# Releasing\n\nThe core team owns releases.", "2026-07-01T00:00:00Z"),
        doc("docs/handbook.md", "# Handbook\n\nThe billing team owns the docs. Ask in the forum.", "2026-07-02T00:00:00Z"),
        doc("docs/gone.md", "# Gone\n\nThe billing team owns releases for invoices.", "2026-07-02T00:00:00Z"),
    ]
    out = ingest_repo(graph, "acme/app", cache_root=tmp_path, source=FakeSource("h1", pieces(first)),
                      report=lambda **kw: steps.append(kw.get("step")), extract_model="claude-haiku-5-5",
                      extract_client=claude)
    assert [s for s in steps if s] == ["clone", "docs", "codeowners", "activity", "activity", "people", "write", "extract", "link"]
    assert out["counts"]["docs"] == 3 and out["counts"]["pulls"] == 1 and out["counts"]["documents"] > 3
    assert len(claude.prompts) == 3
    assert source_state(graph)["head"] == "h1"
    # The handbook page says billing owns the docs, but CODEOWNERS gave docs to other teams: out of date.
    stale = graph.query("MATCH (f:Fact {predicate: 'owned_by', stale: true})-[:ABOUT]->(:Area {slug: 'docs'}) RETURN f.text").result_set
    assert stale == [["The billing team owns the docs."]]

    # Sync: one page edited, one deleted, one untouched.
    claude.prompts.clear()
    edited = [doc("docs/releasing.md", "# Releasing\n\nThe docs team owns releases.", "2026-08-01T00:00:00Z")]
    ingest_repo(graph, "acme/app", cache_root=tmp_path, source=FakeSource("h2", pieces(edited), removed=["docs/gone.md"]),
                extract_model="claude-haiku-5-5", extract_client=claude)
    assert len(claude.prompts) == 1 and "docs team owns releases" in claude.prompts[0]
    assert source_state(graph)["head"] == "h2"
    rows = graph.query(
        "MATCH (f:Fact {subject: 'topic:releases'}) RETURN f.value, f.valid_to IS NULL ORDER BY f.value"
    ).result_set
    # The billing statement's page is gone, so its fact is closed; core's passage was replaced, so its fact closed.
    assert rows == [["team:billing", False], ["team:core", False], ["team:docs", True]]
    assert graph.query("MATCH (d:Document {id: 'doc:docs/gone.md'})-[:HAS]->() RETURN count(*)").result_set[0][0] == 0

    # A third run with nothing new extracts nothing.
    claude.prompts.clear()
    ingest_repo(graph, "acme/app", cache_root=tmp_path, source=FakeSource("h2", pieces([])),
                extract_model="claude-haiku-5-5", extract_client=claude)
    assert claude.prompts == []


def test_ingest_without_a_model_still_loads_ownership(graph, tmp_path):
    ingest_repo(graph, "acme/app", cache_root=tmp_path, source=FakeSource("h1", pieces([])))
    owners = graph.query(
        """MATCH (f:Fact {predicate: 'owned_by'})-[:ABOUT]->(:Area {slug: 'docs'})
           WHERE f.valid_to IS NULL AND NOT (f)-[:SUPERSEDED_BY]->() RETURN f.value ORDER BY f.value"""
    ).result_set
    assert owners == [["team:core"], ["team:docs"]]
