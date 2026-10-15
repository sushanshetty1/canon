"""A small company with five RFCs, for the decisions and catch-up tests."""

from canon.graph.db import ensure_schema
from canon.graph.writer import write_batch
from canon.sources.posthog import passages_of
from canon.types import Area, Batch, Doc, Person

DIR = "requests-for-comments"


def _pr(number, created, merged=None, merged_by=None, reviews=()):
    return {
        "number": number,
        "author": "carol",
        "created_at": f"{created}T09:00:00Z",
        "merged_at": f"{merged}T09:00:00Z" if merged else None,
        "merged_by": merged_by,
        "reviews": [{"author": a, "state": s, "at": f"{created}T10:00:00Z"} for a, s in reviews],
        "comments": [],
    }


RFCS = [
    {
        "path": f"{DIR}/2025-01-10-flag-environments.md",
        "title": "RFC: Flag environments",
        "text": "# Request for comments: Flag environments\n\nUsers want feature flags per environment. We will copy flags "
        "between projects so a flag can be used in each environment.\n",
        "created_at": "2025-01-10T09:00:00Z",
        "updated_at": "2025-01-20T09:00:00Z",
        "pr": _pr(10, "2025-01-10", "2025-01-20", "alice", [("bob", "APPROVED"), ("outsider", "APPROVED"), ("alice", "COMMENTED")]),
    },
    {
        "path": f"{DIR}/2025-02-01-resilient-flags.md",
        "title": "RFC: Resilient feature flags",
        "text": "# Request for comments: Resilient feature flags\n\nFeature flags should keep working when the "
        "servers are down, so flags are evaluated with the last known values.\n",
        "created_at": "2025-02-01T09:00:00Z",
        "updated_at": "2025-02-01T09:00:00Z",
        "proposal": {"state": "OPEN", "closed_at": None, "url": "https://github.com/acme/rfcs/pull/14", "title": "Add RFC"},
        "pr": _pr(14, "2025-02-01"),
    },
    {
        "path": f"{DIR}/2025-05-01-flag-folders.md",
        "title": "RFC: Flag folders",
        "text": "# Request for comments: Flag folders\n\nPut each feature flag in a folder per environment, so flags for "
        "staging and production stay apart.\n",
        "created_at": "2025-05-01T09:00:00Z",
        "updated_at": "2025-05-20T09:00:00Z",
        "proposal": {"state": "CLOSED", "closed_at": "2025-05-20T09:00:00Z", "url": "https://github.com/acme/rfcs/pull/13",
                     "title": "RFC: Flag folders"},
        "pr": _pr(13, "2025-05-01"),
    },
    {
        "path": f"{DIR}/2025-03-01-local-evaluation.md",
        "title": "RFC: Local evaluation of feature flags",
        "text": "# Request for comments: Local evaluation of feature flags\n\n> **Decision:** we evaluate feature flags "
        "locally in every server SDK.\n\nFlags are slow when every check is a request.\n",
        "created_at": "2025-03-01T09:00:00Z",
        "updated_at": "2025-03-05T09:00:00Z",
        "pr": _pr(12, "2025-03-01", "2025-03-05", "alice"),
    },
    {
        "path": f"{DIR}/2025-06-01-project-environments.md",
        "title": "RFC: Project environments, by Carol Smith",
        "text": "# RFC: Project environments, by Carol Smith\n\nThis replaces the [flag environments RFC]"
        "(./2025-01-10-flag-environments.md): environments live inside one project, and feature flags follow them.\n\n"
        "Flags keep one key across environments. Flags can differ per environment. Flags are copied never again. "
        "Flags in staging stay in staging. Flags show their environment.\n\n"
        "I'm also folding [the flag folders proposal](https://github.com/PostHog/requests-for-comments-public/pull/13) "
        "into this.\n",
        "created_at": "2025-06-01T09:00:00Z",
        "updated_at": "2025-06-15T09:00:00Z",
        "pr": _pr(11, "2025-06-01", "2026-09-15", "carol"),
    },
    {
        "path": f"{DIR}/2024-03-01-full-saml.md",
        "title": "RFC: Full SAML support",
        "text": "# RFC: Full SAML support\n\n## THIS RFC IS OUT OF DATE AND ITS CONTENTS DO NOT REFLECT HOW SAML WORKS.\n\n"
        "SAML single sign-on for every organization, with SAML enforced per domain.\n",
        "created_at": "2024-03-01T09:00:00Z",
        "updated_at": "2024-04-01T09:00:00Z",
        "pr": _pr(9, "2024-03-01", "2024-03-10", "alice", [("bob", "APPROVED")]),
    },
]

PULLS = [
    {
        "number": 501,
        "title": "feat(flags): environments inside a project",
        "body": "Builds https://github.com/PostHog/requests-for-comments-public/blob/main/requests-for-comments/"
        "2025-06-01-project-environments.md",
        "url": "https://github.com/PostHog/posthog/pull/501",
        "created_at": "2026-09-20T09:00:00Z",
        "merged_at": "2026-09-25T09:00:00Z",
        "author": "carol",
    },
    {
        "repo": "PostHog/posthog.com",
        "number": 77,
        "title": "docs: project environments",
        "body": "Docs for https://github.com/PostHog/requests-for-comments-public/pull/11",
        "url": "https://github.com/PostHog/posthog.com/pull/77",
        "created_at": "2026-09-26T09:00:00Z",
        "merged_at": "2026-09-27T09:00:00Z",
        "author": "bob",
    },
    {
        "number": 502,
        "title": "wip: flag environments",
        "body": "Draft for requests-for-comments/2025-01-10-flag-environments.md",
        "url": "https://github.com/PostHog/posthog/pull/502",
        "created_at": "2025-02-01T09:00:00Z",
        "merged_at": None,
        "author": "carol",
    },
]


def rfc_batch() -> Batch:
    batch = Batch()
    batch.people = [Person("alice", "Alice Ames"), Person("bob", "Bob Boyd"), Person("carol", "Carol Smith")]
    batch.areas = [Area("feature-flags", "Feature flags"), Area("sso", "SSO")]
    for r in RFCS:
        if r.get("proposal"):
            continue  # proposals are not on the main branch: the decisions build adds them
        doc_id = f"rfc:{r['path']}"
        batch.docs.append(Doc(doc_id, "rfc", r["title"], f"https://example.com/{r['path']}", r["updated_at"][:10]))
        batch.passages += passages_of(doc_id, [p for p in r["text"].split("\n\n") if p.strip()])
    batch.docs.append(Doc("pull:501", "pull", PULLS[0]["title"], PULLS[0]["url"], "2026-09-25", "carol"))
    batch.passages += passages_of("pull:501", [PULLS[0]["title"]])
    return batch


def seed_rfcs(graph) -> None:
    ensure_schema(graph)
    write_batch(graph, rfc_batch())


class Judge:
    """A stand-in model: says the later RFC replaces the earlier one only for the pairs it is given."""

    def __init__(self, replaces: set[tuple[str, str]] = frozenset()):
        self.replaces = replaces
        self.calls: list[str] = []

    async def json(self, system, prompt, schema):
        self.calls.append(prompt)
        first = prompt.split("First RFC: ", 1)[1].split('"')[1]
        second = prompt.split("Second RFC: ", 1)[1].split('"')[1]
        yes = (first, second) in self.replaces
        return {"why": f"{second} {'replaces' if yes else 'does not replace'} {first}.", "replaces": yes}
