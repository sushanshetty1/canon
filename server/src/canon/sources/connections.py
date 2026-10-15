"""A workspace's connections: the tools it reads, their sealed credentials, and the syncs that keep them current.

    (:Connection {id, kind, label, config, secret, info, status, created_at, created_by, last_synced_at,
                  last_tried_at, cursor, counts, notes, error})

- `config` is JSON the connector needs that is not secret (an Atlassian site, channel names, volume caps).
- `secret` is the credential sealed with `canon.cloud.crypto` (for Jira and Confluence, the account email and the
  API token together). It is opened only to build a connector, and never logged or returned.
- `info` is what the credential check learned (the Slack team's name), `counts` and `notes` what the last sync read.
- `status` is `new`, `syncing`, `ok` or `failed`; `error` says what went wrong, in words a person can act on.

`start_sync` runs one connection's sync as a workspace job (`canon.cloud.jobs`). `Scheduler` re-syncs every
connection every `CANON_SYNC_MINUTES` (default 60; 0 turns it off), so knowledge stays current without anyone
pressing a button. Uploaded files are one connection per workspace (`files`); they are read when uploaded.
"""

import calendar
import json
import logging
import os
import secrets
import sys
import threading
import time
from datetime import date

from canon.cloud import crypto
from canon.sources.client import SourceError

log = logging.getLogger("canon.connections")

KINDS = {"slack": "Slack", "notion": "Notion", "linear": "Linear", "jira": "Jira", "confluence": "Confluence", "upload": "Files"}
API_KINDS = ("slack", "notion", "linear", "jira", "confluence")
UPLOAD_ID = "files"
MAX_CONNECTIONS = 12
# Config keys each kind may keep, beside its volume caps. Anything else sent is dropped.
CONFIG_KEYS = {
    "slack": ("channels", "max_channels", "max_messages", "max_threads", "max_replies", "lookback_days", "rethread_days"),
    "notion": ("max_pages", "max_blocks", "max_depth"),
    "linear": ("max_issues", "max_projects", "max_teams"),
    "jira": ("site", "projects", "max_issues", "max_projects", "max_comments", "lookback_days"),
    "confluence": ("site", "spaces", "max_pages", "max_spaces", "max_page_chars"),
    "upload": (),
}
_PROPS = ("id", "kind", "label", "config", "info", "status", "created_at", "created_by", "last_synced_at",
          "last_tried_at", "counts", "notes", "error")


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def clean_config(kind: str, config: dict | None) -> dict:
    """Only the keys a kind uses: short strings, short lists of short strings, small numbers."""
    out: dict = {}
    for key in CONFIG_KEYS.get(kind, ()):
        value = (config or {}).get(key)
        if value is None or value == "" or value == []:
            continue
        if key in ("channels", "projects", "spaces"):
            items = value.split(",") if isinstance(value, str) else value if isinstance(value, list) else []
            items = [str(v).strip()[:80] for v in items if str(v).strip()][:50]
            if items:
                out[key] = items
        elif key == "site":
            out[key] = str(value).strip()[:200]
        elif isinstance(value, int | str) and str(value).isdigit():
            out[key] = int(value)
    return out


def secret_of(kind: str, config: dict | None, secret: str | None) -> str:
    """The credential as it is sealed: the token, or for Atlassian `{"email", "token"}` as JSON."""
    token = (secret or "").strip()
    if kind in ("jira", "confluence"):
        email = str((config or {}).get("email") or "").strip()
        if token.startswith("{"):
            try:
                parsed = json.loads(token)
                email, token = parsed.get("email") or email, parsed.get("token") or ""
            except ValueError:
                pass
        from canon.sources.atlassian import credentials

        email, token = credentials(email, token)
        return json.dumps({"email": email, "token": token})
    if not token:
        raise SourceError(f"Paste the {KINDS.get(kind, kind)} token.")
    if kind == "slack" and not token.startswith("xoxb-"):
        if token.startswith(("xoxp-", "xoxe")):
            raise SourceError("That is a user token. Canon needs the Bot User OAuth Token, which starts with xoxb-.")
        raise SourceError("A Slack bot token starts with xoxb-. Copy the Bot User OAuth Token from OAuth & Permissions.")
    if kind == "notion" and not token.startswith(("secret_", "ntn_")):
        raise SourceError("A Notion integration token starts with ntn_ (or secret_ for older ones).")
    if kind == "linear" and not token.startswith("lin_api_"):
        raise SourceError("A Linear personal API key starts with lin_api_.")
    return token


def build(kind: str, config: dict, secret: str, *, http=None, sleep=time.sleep):
    """The connector for a connection, with its credential opened."""
    if kind == "slack":
        from canon.sources.slack import SlackConnector

        return SlackConnector(secret, config, http=http, sleep=sleep)
    if kind == "notion":
        from canon.sources.notion import NotionConnector

        return NotionConnector(secret, config, http=http, sleep=sleep)
    if kind == "linear":
        from canon.sources.linear import LinearConnector

        return LinearConnector(secret, config, http=http, sleep=sleep)
    if kind == "jira":
        from canon.sources.jira import JiraConnector

        return JiraConnector(json.loads(secret), config, http=http, sleep=sleep)
    if kind == "confluence":
        from canon.sources.confluence import ConfluenceConnector

        return ConfluenceConnector(json.loads(secret), config, http=http, sleep=sleep)
    raise SourceError("Canon cannot connect to that kind of source.")


def check(kind: str, config: dict, secret: str, *, http=None, sleep=time.sleep) -> dict:
    """One cheap call that proves the credential works. Raises `SourceError` saying what is wrong."""
    connector = build(kind, config, secret, http=http, sleep=sleep)
    try:
        return connector.check()
    finally:
        connector.client.close()


# ----- the store -------------------------------------------------------------------------------------------------


class Connections:
    def __init__(self, graph):
        self.graph = graph

    def _q(self, cypher: str, params: dict | None = None) -> list[list]:
        return self.graph.query(cypher, params or {}).result_set

    @staticmethod
    def view(props: dict) -> dict:
        """What the API shows: never the secret, never the cursor."""
        out = {k: props.get(k) for k in _PROPS}
        for key in ("config", "info", "counts"):
            out[key] = json.loads(props.get(key) or "{}")
        out["notes"] = json.loads(props.get("notes") or "[]")
        out["config"] = {k: v for k, v in out["config"].items() if k != "email"}
        return out

    def raw(self, conn_id: str) -> dict | None:
        rows = self._q("MATCH (c:Connection {id: $id}) RETURN c", {"id": conn_id})
        return dict(rows[0][0].properties) if rows else None

    def get(self, conn_id: str) -> dict | None:
        props = self.raw(conn_id)
        return self.view(props) if props else None

    def all_raw(self) -> list[dict]:
        rows = self._q("MATCH (c:Connection) RETURN c ORDER BY c.created_at, c.id")
        return [dict(r[0].properties) for r in rows]

    def list(self) -> list[dict]:
        return [self.view(p) for p in self.all_raw()]

    def count(self) -> int:
        return self._q("MATCH (c:Connection) RETURN count(c)")[0][0]

    def create(self, kind: str, label: str, config: dict, sealed: str | None, info: dict, by: str, conn_id: str | None = None) -> dict:
        conn_id = conn_id or secrets.token_hex(6)
        self._q(
            """MERGE (c:Connection {id: $id})
               ON CREATE SET c.created_at = $now, c.created_by = $by, c.status = 'new', c.counts = '{}', c.notes = '[]'
               SET c.kind = $kind, c.label = $label, c.config = $config, c.secret = $secret, c.info = $info""",
            {"id": conn_id, "kind": kind, "label": label, "config": json.dumps(config), "secret": sealed,
             "info": json.dumps(info), "now": _now(), "by": by},
        )
        return self.get(conn_id)  # type: ignore[return-value]

    def update(self, conn_id: str, **fields) -> None:
        for key in ("counts", "notes", "info", "config"):
            if key in fields and not isinstance(fields[key], str):
                fields[key] = json.dumps(fields[key])
        sets = ", ".join(f"c.{k} = ${k}" for k in fields)
        self._q(f"MATCH (c:Connection {{id: $id}}) SET {sets}", {"id": conn_id, **fields})

    def delete(self, conn_id: str) -> None:
        self._q("MATCH (c:Connection {id: $id}) DELETE c", {"id": conn_id})


def remove_documents(graph, conn_id: str, *, delete: bool) -> int:
    """A removed connection's documents: kept for history and marked `removed_at` (their passages detached, so the
    facts they stated are closed by `link`), or deleted with their passages and facts."""
    ids = [r[0] for r in graph.query("MATCH (d:Document {connection: $id}) RETURN d.id", {"id": conn_id}).result_set]
    if not ids:
        return 0
    if delete:
        graph.query(
            """UNWIND $ids AS id MATCH (d:Document {id: id})-[:HAS|HAD]->(p:Passage)<-[:STATED_IN]-(f:Fact)
               DETACH DELETE f""",
            {"ids": ids},
        )
        graph.query("UNWIND $ids AS id MATCH (d:Document {id: id})-[:HAS|HAD]->(p:Passage) DETACH DELETE p", {"ids": ids})
        graph.query("UNWIND $ids AS id MATCH (d:Document {id: id}) DETACH DELETE d", {"ids": ids})
    else:
        today = date.today().isoformat()
        graph.query(
            """UNWIND $ids AS id MATCH (d:Document {id: id})-[h:HAS]->(p:Passage)
               MERGE (d)-[:HAD]->(p) SET p.removed_at = $today DELETE h""",
            {"ids": ids, "today": today},
        )
        graph.query("UNWIND $ids AS id MATCH (d:Document {id: id}) SET d.removed = true, d.removed_at = $today",
                    {"ids": ids, "today": today})
    from canon.verify.supersede import link

    link(graph)
    return len(ids)


# ----- syncs -----------------------------------------------------------------------------------------------------


def _models(cloud) -> dict:
    """The extraction and judging models for a sync: off without a model key. Tests replace it on the cloud."""
    custom = getattr(cloud, "connector_models", None)
    if custom is not None:
        return custom()
    from canon.config import settings
    from canon.sources.cache import data_dir

    s = settings()
    if not s.anthropic_api_key:
        return {}
    from canon.llm import check_model

    return {"extract_model": s.extract_model, "extract_cache": data_dir() / "extract", "check": check_model()}


def start_sync(cloud, slug: str, conn_id: str, *, connector=None) -> dict | None:
    """Start a sync of one connection as the workspace's job. None when a job is already running there.
    `connector` is given for uploads (the files to read); otherwise it is built from the stored credential."""
    from canon.sources.sync import run_connector

    graph = cloud.graph(slug)
    store = Connections(graph)
    props = store.raw(conn_id)
    if props is None:
        raise SourceError("No such connection.")
    kind = props["kind"]
    if connector is None and kind not in API_KINDS:
        raise SourceError("Upload the files again to read them.")

    def work(report) -> dict:
        report(step="connect", progress=0.01)
        store.update(conn_id, status="syncing", error=None, last_tried_at=_now())
        made = connector
        try:
            if made is None:
                secret = crypto.unseal(props.get("secret"), cloud.config.secret)
                if not secret:
                    raise SourceError("The saved credential can no longer be opened. Remove this connection and add it again.")
                made = build(kind, json.loads(props.get("config") or "{}"), secret, http=cloud.http,
                             sleep=getattr(cloud, "sleep", time.sleep))
            out = run_connector(graph, made, cursor=props.get("cursor"), connection_id=conn_id, report=report, **_models(cloud))
        except Exception as e:
            public = e if isinstance(e, SourceError) else None
            if public is None:
                log.exception("canon: a %s sync in %s failed", kind, slug)
                public = SourceError(f"Something went wrong while reading {KINDS.get(kind, kind)}. Try again.")
            store.update(conn_id, status="failed", error=public.public_message)
            raise public from None
        finally:
            client = getattr(made, "client", None)
            if client is not None:
                client.close()
        store.update(conn_id, status="ok", error=None, cursor=out["cursor"], last_synced_at=_now(),
                     counts=out.get("connection") or {}, notes=out.get("notes") or [])
        return out

    return cloud.jobs().start(slug, "sync", work, connection=conn_id, step="connect")


def sync_minutes(env: dict | None = None) -> int:
    env = os.environ if env is None else env
    try:
        return max(0, int(env.get("CANON_SYNC_MINUTES", "60")))
    except ValueError:
        return 60


class Scheduler:
    """Re-syncs each connection every `minutes`, in one daemon thread that looks once a minute. A workspace runs one
    job at a time, so a due connection whose workspace is busy waits for the next look."""

    def __init__(self, cloud, minutes: int, *, clock=time.time):
        self.cloud = cloud
        self.minutes = minutes
        self.clock = clock
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def due(self, props: dict, now: float) -> bool:
        if props.get("kind") not in API_KINDS:
            return False
        last = props.get("last_tried_at") or props.get("last_synced_at") or props.get("created_at")
        if not last:
            return True
        try:
            then = calendar.timegm(time.strptime(last, "%Y-%m-%dT%H:%M:%SZ"))
        except ValueError:
            return True
        return now - then >= self.minutes * 60

    def tick(self) -> list[tuple[str, str]]:
        """Start the syncs that are due. Returns (workspace, connection) for each one started."""
        from canon.graph.db import workspace_graph_name

        started = []
        db = self.cloud.db()
        graphs = set(db.list_graphs())
        accounts = self.cloud.accounts()
        rows = accounts.graph.query("MATCH (w:Workspace) WHERE coalesce(w.public, false) = false RETURN w.slug").result_set
        now = self.clock()
        for (slug,) in rows:
            if slug in self.cloud.config.public_workspaces:
                continue
            try:
                if workspace_graph_name(slug) not in graphs:
                    continue
            except ValueError:
                continue
            for props in Connections(self.cloud.graph(slug)).all_raw():
                if not self.due(props, now):
                    continue
                try:
                    job = start_sync(self.cloud, slug, props["id"])
                except Exception:
                    log.exception("canon: scheduled sync of a connection in %s could not start", slug)
                    continue
                if job is not None:
                    started.append((slug, props["id"]))
                break  # one job per workspace at a time
        return started

    def _loop(self) -> None:
        while not self._stop.wait(60):
            try:
                self.tick()
            except Exception:
                log.exception("canon: the sync scheduler's look failed")

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._loop, daemon=True, name="canon-sync-scheduler")
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()


def start_scheduler(cloud) -> Scheduler | None:
    """The scheduler, started, unless `CANON_SYNC_MINUTES=0` or under tests."""
    minutes = sync_minutes()
    if minutes == 0 or "pytest" in sys.modules:
        return None
    scheduler = Scheduler(cloud, minutes)
    scheduler.start()
    log.info("canon: connections re-sync every %d minutes", minutes)
    return scheduler
