"""The Canon API. Routes are thin: every answer comes from the graph or the verifier behind it.

- `POST /api/w/{ws}/ask {question}` streams the Ask events (see `canon.answer.ask`) as server-sent events.
- `GET /api/w/{ws}/facts/{id}` gives a fact with its source, what it replaced, what replaced it, and its disputes.
- `GET /api/w/{ws}/stats` counts nodes per label, and the stale facts, stale pages and disputes.

A workspace is a graph with documents in it; anything else is a 404.
"""

import json
import logging
from collections.abc import Callable
from functools import cache

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from canon.api.people_routes import router as people_router
from canon.config import settings
from canon.graph import read
from canon.graph.db import connect, workspace_graph_name

log = logging.getLogger("canon.api")


class AskBody(BaseModel):
    question: str = Field(min_length=1, max_length=500)


@cache
def _db():
    return connect()


def _default_graph(ws: str):
    db = _db()
    name = workspace_graph_name(ws)
    # Querying a graph that does not exist would create it, so look before touching.
    return db.select_graph(name) if name in db.list_graphs() else None


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


def fact_detail(graph, fact_id: str) -> dict | None:
    found = read.facts(graph, [fact_id])
    if fact_id not in found:
        return None
    path = graph.query(
        """MATCH p = (f:Fact {id: $id})-[:SUPERSEDED_BY*1..6]->(n:Fact) WHERE NOT (n)-[:SUPERSEDED_BY]->()
           RETURN [x IN nodes(p) | x.id]""",
        {"id": fact_id},
    ).result_set
    forward = path[0][0][1:] if path else []
    back = [r[0] for r in graph.query(
        "MATCH (b:Fact)-[:SUPERSEDED_BY*1..6]->(:Fact {id: $id}) RETURN DISTINCT b.id", {"id": fact_id}
    ).result_set]
    restated = [r[0] for r in graph.query(
        "MATCH (:Fact {id: $id})-[:RESTATES]-(o:Fact) RETURN DISTINCT o.id", {"id": fact_id}
    ).result_set]
    conflicts = read.conflicts(graph, [fact_id]).get(fact_id, [])
    rows = read.facts(graph, [*forward, *back, *restated, *conflicts])
    by_date = lambda ids: sorted((rows[i] for i in ids if i in rows), key=lambda f: f["valid_from"] or "")  # noqa: E731
    return {
        "fact": found[fact_id],
        "back": by_date(back),
        "forward": [rows[i] for i in forward if i in rows],
        "restated": by_date(restated),
        "conflicts": by_date(conflicts),
    }


def stats(graph) -> dict:
    one = lambda q: graph.query(q).result_set[0][0]  # noqa: E731
    labels = graph.query("MATCH (n) RETURN coalesce(labels(n)[0], 'none'), count(n)").result_set
    return {
        "labels": dict(labels),
        "current_facts": one("MATCH (f:Fact) WHERE f.valid_to IS NULL AND NOT (f)-[:SUPERSEDED_BY]->() RETURN count(f)"),
        "stale_facts": one("MATCH (f:Fact {stale: true}) RETURN count(f)"),
        "stale_pages": one(
            "MATCH (f:Fact {stale: true})-[:STATED_IN]->(:Passage)<-[:HAS]-(d:Document) RETURN count(DISTINCT d)"
        ),
        "disputes": one("MATCH (:Fact)-[r:CONTRADICTS]->(:Fact) RETURN count(r)"),
    }


def create_app(*, graph_for: Callable | None = None, ask_fn: Callable | None = None) -> FastAPI:
    """`graph_for(slug)` returns a workspace graph or None; `ask_fn(graph, question)` yields Ask events. Both
    default to the real ones and are injected in tests."""
    app = FastAPI(title="Canon", docs_url=None, redoc_url=None)
    graph_for = graph_for or _default_graph

    def workspace(ws: str):
        try:
            workspace_graph_name(ws)
        except ValueError:
            raise HTTPException(404, "No such workspace.") from None
        graph = graph_for(ws)
        if graph is None or not graph.query("MATCH (d:Document) RETURN d.id LIMIT 1").result_set:
            raise HTTPException(404, "No such workspace.")
        return graph

    # Route modules reach the workspace check through the app.
    app.state.workspace = workspace
    app.include_router(people_router)

    @app.get("/api/health")
    def health() -> dict:
        s = settings()
        try:
            connect().connection.ping()
            graph = "up"
        except Exception:
            graph = "down"
        return {"service": "canon", "graph": graph, "answers": "on" if s.anthropic_api_key else "off"}

    @app.post("/api/w/{ws}/ask")
    def ask_route(ws: str, body: AskBody) -> StreamingResponse:
        graph = workspace(ws)
        run = ask_fn
        if run is None:
            if not settings().anthropic_api_key:
                raise HTTPException(503, "Answers are off: no model key is set on the server.")
            from canon.answer.ask import ask as run

        async def events():
            try:
                async for event in run(graph, body.question.strip()):
                    yield _sse(event)
            except Exception:
                log.exception("ask failed")
                yield _sse({"type": "error", "message": "Canon could not finish this answer. Try again."})

        headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
        return StreamingResponse(events(), media_type="text/event-stream", headers=headers)

    @app.get("/api/w/{ws}/facts/{fact_id}")
    def fact_route(ws: str, fact_id: str) -> dict:
        detail = fact_detail(workspace(ws), fact_id)
        if detail is None:
            raise HTTPException(404, "No such fact.")
        return detail

    @app.get("/api/w/{ws}/stats")
    def stats_route(ws: str) -> dict:
        return stats(workspace(ws))

    return app
