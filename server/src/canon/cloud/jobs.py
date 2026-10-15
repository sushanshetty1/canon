"""Background jobs that fill a workspace, with their progress kept in the workspace's own graph.

    (:Job {id, kind: 'create' | 'sync', status: 'running' | 'done' | 'failed', step, progress, counts, error,
           started_at, updated_at, finished_at})

`counts` is a JSON object (FalkorDB properties hold no maps). The app polls `latest` and draws the job's progress.
One job runs per workspace at a time. A job whose server stopped before it finished would read as running forever,
so a running job not updated for `STALE_SECONDS` reads as failed and a new one may start.
"""

import json
import logging
import secrets
import threading
import time
from collections.abc import Callable

log = logging.getLogger("canon.jobs")

STALE_SECONDS = 600
_MIN_GAP = 0.4  # seconds between progress writes, so a fast step does not write the graph for every passage


def _iso(t: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))


def _view(props: dict, now: float) -> dict:
    status = props.get("status")
    error = props.get("error")
    if status == "running" and now - float(props.get("updated", 0)) > STALE_SECONDS:
        status, error = "failed", "The server stopped before this finished. Start it again."
    from canon.ingest import STEPS

    step = props.get("step")
    return {
        "id": props.get("id"),
        "kind": props.get("kind"),
        "status": status,
        "step": step,
        "step_label": STEPS.get(step or "", "Starting"),
        "progress": float(props.get("progress") or 0),
        "counts": json.loads(props.get("counts") or "{}"),
        "error": error,
        "started_at": props.get("started_at"),
        "finished_at": props.get("finished_at"),
    }


class Jobs:
    def __init__(self, cloud):
        self.cloud = cloud
        self._lock = threading.Lock()
        self._running: set[str] = set()

    def latest(self, slug: str) -> dict | None:
        from canon.graph.db import workspace_graph_name

        if workspace_graph_name(slug) not in self.cloud.db().list_graphs():
            return None  # reading a graph that does not exist would create it
        graph = self.cloud.graph(slug)
        rows = graph.query("MATCH (j:Job) RETURN j ORDER BY j.started DESC LIMIT 1").result_set
        return _view(dict(rows[0][0].properties), self.cloud.clock()) if rows else None

    def start(self, slug: str, kind: str, work: Callable[[Callable[..., None]], dict]) -> dict | None:
        """Start `work(report)` for the workspace. None when a job is already running there."""
        with self._lock:
            current = self.latest(slug)
            if slug in self._running or (current and current["status"] == "running"):
                return None
            self._running.add(slug)
        graph = self.cloud.graph(slug)
        now = self.cloud.clock()
        job_id = secrets.token_hex(6)
        graph.query(
            """CREATE (:Job {id: $id, kind: $kind, status: 'running', step: 'clone', progress: 0.0, counts: '{}',
                             started: $now, updated: $now, started_at: $at})""",
            {"id": job_id, "kind": kind, "now": now, "at": _iso(now)},
        )
        state = {"step": "clone", "progress": 0.0, "counts": {}, "written": 0.0}

        def report(*, step: str | None = None, counts: dict | None = None, progress: float | None = None) -> None:
            if step:
                state["step"] = step
            if counts is not None:
                state["counts"] = counts
            if progress is not None:
                state["progress"] = max(state["progress"], min(progress, 1.0))
            t = self.cloud.clock()
            if step is None and t - state["written"] < _MIN_GAP:
                return
            state["written"] = t
            graph.query(
                "MATCH (j:Job {id: $id}) SET j.step = $step, j.progress = $progress, j.counts = $counts, j.updated = $t",
                {"id": job_id, "step": state["step"], "progress": state["progress"], "counts": json.dumps(state["counts"]), "t": t},
            )

        def run() -> None:
            status, error = "done", None
            try:
                result = work(report) or {}
                if result.get("counts"):
                    state["counts"] = result["counts"]
                state["progress"] = 1.0
            except Exception as e:
                log.exception("canon: job %s on %s failed", kind, slug)
                status, error = "failed", _calm(e)
            finally:
                t = self.cloud.clock()
                try:
                    graph.query(
                        """MATCH (j:Job {id: $id}) SET j.status = $status, j.error = $error, j.progress = $progress,
                               j.counts = $counts, j.updated = $t, j.finished_at = $at""",
                        {"id": job_id, "status": status, "error": error, "progress": state["progress"],
                         "counts": json.dumps(state["counts"]), "t": t, "at": _iso(t)},
                    )
                finally:
                    with self._lock:
                        self._running.discard(slug)

        self.cloud.runner(run)
        return self.latest(slug)


def _calm(e: Exception) -> str:
    """What went wrong, in words a person can act on. Never the exception text, which can carry a URL or a token."""
    import subprocess

    import httpx

    if isinstance(e, subprocess.CalledProcessError):
        return "The repository could not be read from GitHub."
    if isinstance(e, httpx.HTTPStatusError):
        code = e.response.status_code
        if code in (401, 403):
            return "GitHub refused the request. Sign in again, or try later if the rate limit was reached."
        if code == 404:
            return "GitHub could not find this repository."
        return "GitHub did not answer. Try again in a moment."
    if isinstance(e, httpx.TransportError):
        return "GitHub could not be reached. Try again in a moment."
    return "Something went wrong while reading the repository. Try again."
