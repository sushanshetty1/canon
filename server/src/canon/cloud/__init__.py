"""Canon's accounts: GitHub sign-in, sessions, workspaces and the jobs that fill them.

A `Cloud` holds what the routes share: the configuration from the environment, one FalkorDB client (opened on first
use), the accounts graph, the HTTP client GitHub is called with, and how background jobs run. `create_app` puts one
on `app.state.cloud`; tests build their own with a throwaway accounts graph, a mocked GitHub and inline jobs.

Environment:

- `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET`: the GitHub OAuth app. Without both, GitHub sign-in is off.
- `CANON_SESSION_SECRET`: signs session cookies and derives the key GitHub tokens are encrypted with. At least 32
  bytes. In development a missing secret is replaced by a random one, so sessions last until the server restarts.
- `CANON_PUBLIC_URL`: where the app is served, e.g. `https://canon.example.com`. The OAuth callback is
  `<CANON_PUBLIC_URL>/auth/callback`.
- `CANON_DEV_LOGIN=1`: a sign-in without GitHub, for local development. Refused when `CANON_PROFILE=prod`.
- `CANON_PUBLIC_WORKSPACES`: workspaces anyone can read, default `posthog,demo`.
- `CANON_ACCOUNTS_GRAPH`: the accounts graph, default `canon_accounts`.
"""

import logging
import os
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger("canon.cloud")

MIN_SECRET = 32
DEFAULT_PUBLIC = ("posthog", "demo")


@dataclass(frozen=True)
class CloudConfig:
    github_client_id: str = ""
    github_client_secret: str = ""
    secret: str = ""
    public_url: str = ""
    profile: str = "dev"
    dev_login: bool = False
    accounts_graph: str = "canon_accounts"
    public_workspaces: tuple[str, ...] = DEFAULT_PUBLIC
    ephemeral_secret: bool = field(default=False, compare=False)

    @classmethod
    def from_env(cls, env: dict | None = None) -> "CloudConfig":
        env = os.environ if env is None else env
        profile = env.get("CANON_PROFILE", "dev").strip() or "dev"
        dev_login = env.get("CANON_DEV_LOGIN", "").strip() == "1"
        if dev_login and profile == "prod":
            log.error("canon: CANON_DEV_LOGIN is ignored because CANON_PROFILE=prod")
            dev_login = False
        secret = env.get("CANON_SESSION_SECRET", "").strip()
        ephemeral = False
        if not secret and profile != "prod":
            secret, ephemeral = secrets.token_hex(32), True
        public = tuple(s.strip() for s in env.get("CANON_PUBLIC_WORKSPACES", ",".join(DEFAULT_PUBLIC)).split(",") if s.strip())
        return cls(
            github_client_id=env.get("GITHUB_CLIENT_ID", "").strip(),
            github_client_secret=env.get("GITHUB_CLIENT_SECRET", "").strip(),
            secret=secret,
            public_url=env.get("CANON_PUBLIC_URL", "").strip().rstrip("/"),
            profile=profile,
            dev_login=dev_login,
            accounts_graph=env.get("CANON_ACCOUNTS_GRAPH", "").strip() or "canon_accounts",
            public_workspaces=public,
            ephemeral_secret=ephemeral,
        )

    @property
    def sessions(self) -> bool:
        """Whether session cookies can be signed and checked: a secret long enough to trust."""
        return len(self.secret.encode()) >= MIN_SECRET

    @property
    def signin(self) -> bool:
        """Whether GitHub sign-in can work: an OAuth app and a signing secret."""
        return bool(self.github_client_id and self.github_client_secret and self.sessions)


def _default_connect():
    from canon.graph.db import connect

    db = connect()
    db.connection.ping()
    return db


def _default_http():
    import httpx

    return httpx.Client(timeout=httpx.Timeout(20.0, connect=5.0))


def _thread_runner(fn: Callable[[], None]) -> None:
    threading.Thread(target=fn, daemon=True, name="canon-job").start()


class Cloud:
    """Shared state for the account routes.

    - `connect()` opens FalkorDB.
    - `http()` makes the client GitHub is called with (a mocked transport in tests).
    - `runner(fn)` runs a job: in a thread by default, inline in tests.
    - `ingest(graph, repo, token, report)` fills a workspace; the real one reads GitHub and calls the model.
    """

    def __init__(
        self,
        config: CloudConfig | None = None,
        *,
        connect: Callable[[], Any] | None = None,
        http: Callable[[], Any] | None = None,
        runner: Callable[[Callable[[], None]], None] | None = None,
        ingest: Callable[..., dict] | None = None,
        clock: Callable[[], float] = time.time,
    ):
        self.config = config or CloudConfig()
        self.connect = connect or _default_connect
        self.http = http or _default_http
        self.runner = runner or _thread_runner
        self.ingest = ingest
        self.clock = clock
        self._lock = threading.Lock()
        self._db: Any = None
        self._accounts: Any = None
        self._jobs: Any = None
        if self.config.secret and not self.config.sessions:
            log.warning("canon: CANON_SESSION_SECRET is shorter than %d bytes, so sign-in is off", MIN_SECRET)
        if self.config.ephemeral_secret:
            log.warning("canon: no CANON_SESSION_SECRET; sessions last until the server restarts")
        if self.config.dev_login:
            log.warning("canon: development sign-in is on (CANON_DEV_LOGIN=1). Never set it on a public server.")

    @classmethod
    def from_env(cls) -> "Cloud":
        return cls(CloudConfig.from_env())

    def db(self) -> Any:
        with self._lock:
            if self._db is None:
                self._db = self.connect()
            return self._db

    def accounts(self):
        from canon.cloud.accounts import Accounts

        db = self.db()
        with self._lock:
            if self._accounts is None:
                accounts = Accounts(db, self.config.accounts_graph, public=self.config.public_workspaces, clock=self.clock)
                accounts.ensure_schema()
                self._accounts = accounts
            return self._accounts

    def graph(self, slug: str):
        """A workspace's own graph."""
        from canon.graph.db import workspace_graph

        return workspace_graph(self.db(), slug)

    def jobs(self):
        from canon.cloud.jobs import Jobs

        with self._lock:
            if self._jobs is None:
                self._jobs = Jobs(self)
            return self._jobs
