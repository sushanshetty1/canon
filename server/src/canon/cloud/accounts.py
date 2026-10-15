"""The accounts graph, `canon_accounts`: users, workspaces and who belongs to which.

    (:User {id, github_id, login, name, token, dev, created_at, signed_in_at})
    (:Workspace {slug, name, repo, public, created_at})
    (:User)-[:MEMBER {role: 'owner' | 'member', at}]->(:Workspace)

A GitHub user's id is `gh<github id>`, so a renamed account is still the same user; a development user's is
`dev-<login>`. `token` is the user's GitHub token sealed with `canon.cloud.crypto`, never the token itself.

Public workspaces (`posthog`, `demo`) are `Workspace {public: true}` with no members: anyone reads them, nobody
writes to them. A workspace made from a repository belongs to the user who made it and is private to its members.
Its slug comes from the repository's name, and each one is its own graph, `canon_<slug>`.
"""

import re
import secrets
import time
from collections.abc import Callable

from canon.graph.db import workspace_graph_name
from canon.sources.text import slugify

MAX_WORKSPACES = 5
PUBLIC_NAMES = {"posthog": ("PostHog", "PostHog/posthog.com"), "demo": ("Kestrel", None)}
RESERVED = {"accounts", "new", "app", "api", "auth"}
_INDEXES = [("User", "id"), ("User", "github_id"), ("Workspace", "slug")]


class LimitReached(Exception):
    pass


def slug_for(repo: str) -> str:
    """`cli/cli` -> `cli-cli`, cut to fit a graph name."""
    return slugify(repo.replace("/", "-"))[:36].strip("-") or "repo"


class Accounts:
    def __init__(self, db, graph_name: str = "canon_accounts", *, public: tuple[str, ...] = (), clock: Callable[[], float] = time.time):
        self.db = db
        self.graph = db.select_graph(graph_name)
        self.public = tuple(public)
        self.clock = clock

    def _q(self, cypher: str, params: dict | None = None) -> list[list]:
        return self.graph.query(cypher, params or {}).result_set

    def _now(self) -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.clock()))

    def ensure_schema(self) -> None:
        for label, prop in _INDEXES:
            try:
                self._q(f"CREATE INDEX FOR (n:{label}) ON (n.{prop})")
            except Exception as e:
                if "already indexed" not in str(e).lower():
                    raise
        for slug in self.public:
            name, repo = PUBLIC_NAMES.get(slug, (slug.replace("-", " ").title(), None))
            self._q(
                """MERGE (w:Workspace {slug: $slug}) ON CREATE SET w.created_at = $now
                   SET w.public = true, w.name = $name, w.repo = $repo""",
                {"slug": slug, "name": name, "repo": repo, "now": self._now()},
            )

    # ----- users

    def upsert_github_user(self, profile: dict, sealed_token: str | None) -> str:
        """The user for a GitHub profile ({id, login, name}), created on first sign-in. Returns its id."""
        rows = self._q(
            """MERGE (u:User {id: $id}) ON CREATE SET u.created_at = $now
               SET u.github_id = $gid, u.login = $login, u.name = $name, u.token = $token, u.dev = false,
                   u.signed_in_at = $now
               RETURN u.id""",
            {
                "id": f"gh{int(profile['id'])}",
                "gid": int(profile["id"]),
                "login": str(profile["login"]).lower(),
                "name": str(profile.get("name") or profile["login"]),
                "token": sealed_token,
                "now": self._now(),
            },
        )
        return rows[0][0]

    def upsert_dev_user(self, login: str) -> str:
        login = re.sub(r"[^a-z0-9-]", "", login.lower())[:39] or "dev"
        rows = self._q(
            """MERGE (u:User {id: $id}) ON CREATE SET u.created_at = $now
               SET u.login = $login, u.name = $login, u.dev = true, u.signed_in_at = $now RETURN u.id""",
            {"id": f"dev-{login}", "login": login, "now": self._now()},
        )
        return rows[0][0]

    def user(self, user_id: str) -> dict | None:
        rows = self._q("MATCH (u:User {id: $id}) RETURN u.login, u.name, u.token, coalesce(u.dev, false)", {"id": user_id})
        if not rows:
            return None
        login, name, token, dev = rows[0]
        return {"login": login, "name": name, "token": token, "dev": dev}

    # ----- workspaces

    def _view(self, row: list) -> dict:
        slug, name, repo, public, created_at, role = row
        return {"slug": slug, "name": name, "repo": repo, "public": bool(public), "created_at": created_at, "role": role}

    def workspace(self, slug: str) -> dict | None:
        rows = self._q(
            """MATCH (w:Workspace {slug: $slug})
               RETURN w.slug, w.name, w.repo, coalesce(w.public, false), w.created_at, null""",
            {"slug": slug},
        )
        return self._view(rows[0]) if rows else None

    def role(self, user_id: str | None, slug: str) -> str | None:
        """'owner' or 'member' when the user belongs to the workspace, else None."""
        if not user_id:
            return None
        rows = self._q("MATCH (:User {id: $user})-[m:MEMBER]->(:Workspace {slug: $slug}) RETURN m.role", {"user": user_id, "slug": slug})
        return rows[0][0] if rows else None

    def public_workspaces(self) -> list[dict]:
        rows = self._q(
            """MATCH (w:Workspace) WHERE w.public = true AND w.slug IN $public
               RETURN w.slug, w.name, w.repo, true, w.created_at, null""",
            {"public": list(self.public)},
        )
        order = {s: i for i, s in enumerate(self.public)}
        return sorted((self._view(r) for r in rows), key=lambda w: order.get(w["slug"], 99))

    def workspaces_of(self, user_id: str) -> list[dict]:
        rows = self._q(
            """MATCH (:User {id: $user})-[m:MEMBER]->(w:Workspace)
               RETURN w.slug, w.name, w.repo, coalesce(w.public, false), w.created_at, m.role
               ORDER BY w.created_at, w.slug""",
            {"user": user_id},
        )
        return [self._view(r) for r in rows]

    def create_workspace(self, user_id: str, repo: str) -> tuple[dict, bool]:
        """The user's workspace for `repo`: an existing one (and False), or a new one (and True).

        Raises LimitReached at MAX_WORKSPACES. The slug is the repository's, with a number added when another
        user's workspace already has it.
        """
        for w in self.workspaces_of(user_id):
            if (w["repo"] or "").lower() == repo.lower():
                return w, False
        count = self._q("MATCH (:User {id: $user})-[m:MEMBER {role: 'owner'}]->(:Workspace) RETURN count(m)", {"user": user_id})
        if count and count[0][0] >= MAX_WORKSPACES:
            raise LimitReached(f"You have {MAX_WORKSPACES} workspaces, the most allowed.")
        base = slug_for(repo)
        graphs = set(self.db.list_graphs())
        for n in range(1, 50):
            slug = base if n == 1 else f"{base}-{n}"
            if slug in RESERVED or slug in self.public or slug.startswith("test"):
                continue
            if workspace_graph_name(slug) in graphs and not self.workspace(slug):
                continue  # a graph no workspace owns (loaded by hand): never write into it
            claim = secrets.token_hex(8)
            # MERGE on the slug claims it in one statement, so two requests cannot both take it.
            rows = self._q(
                """MATCH (u:User {id: $user})
                   MERGE (w:Workspace {slug: $slug})
                   ON CREATE SET w.name = $repo, w.repo = $repo, w.public = false, w.created_at = $now, w.claim = $claim
                   WITH u, w WHERE w.claim = $claim
                   MERGE (u)-[m:MEMBER]->(w) SET m.role = 'owner', m.at = $now
                   RETURN w.slug""",
                {"user": user_id, "slug": slug, "repo": repo, "now": self._now(), "claim": claim},
            )
            if rows:
                return self.workspaces_of_one(user_id, slug), True
        raise LimitReached("No free name for this workspace.")

    def workspaces_of_one(self, user_id: str, slug: str) -> dict:
        return next(w for w in self.workspaces_of(user_id) if w["slug"] == slug)
