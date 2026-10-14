"""The Canon API. Routes are thin: every answer comes from the graph or the verifier behind it."""

from fastapi import FastAPI


from canon.config import settings


def create_app() -> FastAPI:
    app = FastAPI(title="Canon", docs_url=None, redoc_url=None)

    @app.get("/api/health")
    def health() -> dict:
        from canon.graph.db import connect

        s = settings()
        try:
            connect().connection.ping()
            graph = "up"
        except Exception:
            graph = "down"
        return {"service": "canon", "graph": graph, "answers": "on" if s.anthropic_api_key else "off"}

    return app
