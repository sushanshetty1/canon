"""The accounts graph, `canon_accounts`: users, workspaces and who belongs to which.

    (:User {id, github_id, login, name, token, scopes, dev, created_at, signed_in_at})
    (:Workspace {slug, name, repo, public, private_repo, created_at})
    (:User)-[:MEMBER {role: 'owner' | 'member', at}]->(:Workspace)
    (:Invite {slug, login, github_id, by, at})-[:TO]->(:Workspace)

A GitHub user's id is `gh<github id>`, so a renamed account is still the same user; a development user's is
`dev-<login>`. `token` is the user's GitHub token sealed with `canon.cloud.crypto`, never the token itself, and
`scopes` is what GitHub said that token was granted (space separated), so the app knows whether it can read private
and organisation repositories.

Public workspaces (`posthog`, `demo`) are `Workspace {public: true}` with no members: anyone reads them, nobody
writes to them. A workspace made from a repository belongs to the user who made it and is private to its members.
Its slug comes from the repository's owner and name, and each one is its own graph, `canon_<slug>`. A workspace made
from a private repository is also marked `private_repo`.

An owner invites a teammate by GitHub handle. The invite keeps the handle and, when GitHub knew it, the account id,
so a handle that someone renames away from cannot be taken over to claim the invite. An invite becomes a membership
the next time that person signs in or opens their list of workspaces.
"""

import re
import secrets
import time
from collections.abc import Callable

from canon.graph.db import workspace_graph_name
from canon.sources.text import slugify

MAX_WORKSPACES = 5
MAX_MEMBERS = 50  # members and open invites, per workspace
PUBLIC_NAMES = {"posthog": ("PostHog", "PostHog/posthog.com"), "demo": ("Kestrel", None)}
RESERVED = {"accounts", "new", "app", "api", "auth"}
_INDEXES = [("User", "id"), ("User", "github_id"), ("User", "login"), ("Workspace", "slug"), ("Invite", "login")]


class LimitReached(Exception):
    pass


def normal_scopes(scope: str | None) -> str:
    """GitHub's `scope` ("repo,read:org") as a sorted, space separated set."""
    return " ".join(sorted({s for s in re.split(r"[\s,]+", scope or "") if s}))


def reads_private(scopes: str | None) -> bool:
    """Whether a token with these scopes can read private repositories and organisation membership."""
    have = set((scopes or "").split())
    return "repo" in have and bool({"read:org", "write:org", "admin:org"} & have)


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
            # A workspace someone made never turns public because its slug was later listed as a public one.
            self._q(
                """MERGE (w:Workspace {slug: $slug}) ON CREATE SET w.created_at = $now
                   WITH w WHERE NOT ()-[:MEMBER]->(w)
                   SET w.public = true, w.name = $name, w.repo = $repo""",
                {"slug": slug, "name": name, "repo": repo, "now": self._now()},
            )

    # ----- users

    def upsert_github_user(self, profile: dict, sealed_token: str | None, scopes: str | None = None) -> str:
        """The user for a GitHub profile ({id, login, name}), created on first sign-in, with the sealed token and the
        scopes GitHub granted it. Open invites for the account become memberships. Returns the user's id."""
        rows = self._q(
            """MERGE (u:User {id: $id}) ON CREATE SET u.created_at = $now
               SET u.github_id = $gid, u.login = $login, u.name = $name, u.token = $token, u.scopes = $scopes,
                   u.dev = false, u.signed_in_at = $now
               RETURN u.id""",
            {
                "id": f"gh{int(profile['id'])}",
                "gid": int(profile["id"]),
                "login": str(profile["login"]).lower(),
                "name": str(profile.get("name") or profile["login"]),
                "token": sealed_token,
                "scopes": normal_scopes(scopes),
                "now": self._now(),
            },
        )
        self.claim_invites(rows[0][0])
        return rows[0][0]

    def upsert_dev_user(self, login: str) -> str:
        login = re.sub(r"[^a-z0-9-]", "", login.lower())[:39] or "dev"
        rows = self._q(
            """MERGE (u:User {id: $id}) ON CREATE SET u.created_at = $now
               SET u.login = $login, u.name = $login, u.dev = true, u.signed_in_at = $now RETURN u.id""",
            {"id": f"dev-{login}", "login": login, "now": self._now()},
        )
        self.claim_invites(rows[0][0])
        return rows[0][0]

    def user(self, user_id: str) -> dict | None:
        rows = self._q(
            "MATCH (u:User {id: $id}) RETURN u.login, u.name, u.token, coalesce(u.dev, false), coalesce(u.scopes, '')",
            {"id": user_id},
        )
        if not rows:
            return None
        login, name, token, dev, scopes = rows[0]
        return {"login": login, "name": name, "token": token, "dev": dev, "scopes": scopes}

    def claim_invites(self, user_id: str) -> list[str]:
        """Turn the user's open invites into memberships. Returns the slugs joined.

        A GitHub user claims an invite made for their account id, or for their handle when GitHub gave no id at the
        time. A development user claims by handle (development sign-in is never on in production)."""
        rows = self._q(
            """MATCH (u:User {id: $id})
               MATCH (i:Invite)-[:TO]->(w:Workspace)
               WHERE (coalesce(u.dev, false) = false AND i.github_id IS NOT NULL AND i.github_id = u.github_id)
                  OR ((coalesce(u.dev, false) = true OR i.github_id IS NULL) AND i.login = u.login)
               MERGE (u)-[m:MEMBER]->(w) ON CREATE SET m.role = 'member', m.at = $now
               WITH i, w.slug AS slug
               DETACH DELETE i
               RETURN slug""",
            {"id": user_id, "now": self._now()},
        )
        return [r[0] for r in rows]

    # ----- members

    def members(self, slug: str) -> list[dict]:
        """The workspace's members, the owner first, then in the order they joined."""
        rows = self._q(
            """MATCH (u:User)-[m:MEMBER]->(:Workspace {slug: $slug})
               RETURN u.id, u.login, coalesce(u.name, u.login), m.role, m.at""",
            {"slug": slug},
        )
        people = [{"id": i, "login": login, "name": name, "role": role, "at": at} for i, login, name, role, at in rows]
        return sorted(people, key=lambda p: (p["role"] != "owner", p["at"] or "", p["login"]))

    def invites(self, slug: str) -> list[dict]:
        rows = self._q(
            "MATCH (i:Invite)-[:TO]->(:Workspace {slug: $slug}) RETURN i.login, i.by, i.at ORDER BY i.at, i.login",
            {"slug": slug},
        )
        return [{"login": login, "by": by, "at": at} for login, by, at in rows]

    def invite(self, slug: str, login: str, github_id: int | None, by: str) -> str:
        """Invite `login` to the workspace: 'member' when they already belong, else 'invited'.

        Raises LimitReached when the workspace already has MAX_MEMBERS members and invites."""
        login = login.lower()
        members, invites = self.members(slug), self.invites(slug)
        if any(m["login"] == login for m in members):
            return "member"
        if any(i["login"] == login for i in invites):
            return "invited"
        if len(members) + len(invites) >= MAX_MEMBERS:
            raise LimitReached(f"A workspace holds at most {MAX_MEMBERS} members and invites.")
        self._q(
            """MATCH (w:Workspace {slug: $slug})
               MERGE (i:Invite {slug: $slug, login: $login})
               MERGE (i)-[:TO]->(w)
               SET i.github_id = $gid, i.by = $by, i.at = $now""",
            {"slug": slug, "login": login, "gid": github_id, "by": by, "now": self._now()},
        )
        return "invited"

    def remove(self, slug: str, login: str) -> bool:
        """Remove a member (never the owner) or cancel an invite, by handle. True when there was one to remove."""
        login = login.lower()
        gone = self._q(
            """MATCH (u:User {login: $login})-[m:MEMBER]->(:Workspace {slug: $slug}) WHERE m.role <> 'owner'
               DELETE m RETURN count(m)""",
            {"slug": slug, "login": login},
        )
        cancelled = self._q(
            "MATCH (i:Invite {slug: $slug, login: $login}) DETACH DELETE i RETURN count(i)", {"slug": slug, "login": login}
        )
        return bool((gone and gone[0][0]) or (cancelled and cancelled[0][0]))

    def member_tokens(self, slug: str) -> list[tuple[str, str]]:
        """(user id, sealed token) for every member who has a GitHub token, the owner first."""
        rows = self._q(
            """MATCH (u:User)-[m:MEMBER]->(:Workspace {slug: $slug}) WHERE u.token IS NOT NULL
               RETURN u.id, u.token, m.role, m.at""",
            {"slug": slug},
        )
        return [(i, t) for i, t, _, _ in sorted(rows, key=lambda r: (r[2] != "owner", r[3] or ""))]

    # ----- workspaces

    def _view(self, row: list) -> dict:
        slug, name, repo, public, created_at, role, private = row
        return {
            "slug": slug, "name": name, "repo": repo, "public": bool(public), "created_at": created_at, "role": role,
            "private": bool(private),
        }

    def workspace(self, slug: str) -> dict | None:
        rows = self._q(
            """MATCH (w:Workspace {slug: $slug})
               RETURN w.slug, w.name, w.repo, coalesce(w.public, false), w.created_at, null,
                      coalesce(w.private_repo, false)""",
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
               RETURN w.slug, w.name, w.repo, true, w.created_at, null, false""",
            {"public": list(self.public)},
        )
        order = {s: i for i, s in enumerate(self.public)}
        return sorted((self._view(r) for r in rows), key=lambda w: order.get(w["slug"], 99))

    def workspaces_of(self, user_id: str) -> list[dict]:
        rows = self._q(
            """MATCH (:User {id: $user})-[m:MEMBER]->(w:Workspace)
               RETURN w.slug, w.name, w.repo, coalesce(w.public, false), w.created_at, m.role,
                      coalesce(w.private_repo, false)
               ORDER BY w.created_at, w.slug""",
            {"user": user_id},
        )
        return [self._view(r) for r in rows]

    def find_own(self, user_id: str, text: str) -> dict | None:
        """The user's workspace (made or joined) for the repository `owner/name`, or whose slug is `text`."""
        text = (text or "").strip().lower()
        for w in self.workspaces_of(user_id):
            if (w["repo"] or "").lower() == text or w["slug"] == text:
                return w
        return None

    def create_workspace(self, user_id: str, repo: str, *, private: bool = False) -> tuple[dict, bool]:
        """The user's workspace for `repo`: an existing one (and False), or a new one (and True).

        Raises LimitReached at MAX_WORKSPACES. The slug is the repository's owner and name, with a number added when
        another user's workspace already has it.
        """
        existing = self.find_own(user_id, repo)
        if existing:
            return existing, False
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
                   ON CREATE SET w.name = $repo, w.repo = $repo, w.public = false, w.private_repo = $private,
                                 w.created_at = $now, w.claim = $claim
                   WITH u, w WHERE w.claim = $claim
                   MERGE (u)-[m:MEMBER]->(w) SET m.role = 'owner', m.at = $now
                   RETURN w.slug""",
                {"user": user_id, "slug": slug, "repo": repo, "now": self._now(), "claim": claim, "private": private},
            )
            if rows:
                return self.workspaces_of_one(user_id, slug), True
            # The same person asking twice at once (a double click, a retry): the first request made it.
            mine = self.find_own(user_id, repo)
            if mine:
                return mine, False
        raise LimitReached("No free name for this workspace.")

    def workspaces_of_one(self, user_id: str, slug: str) -> dict:
        return next(w for w in self.workspaces_of(user_id) if w["slug"] == slug)
