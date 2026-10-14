"""Settings read from the environment, with local-development defaults."""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    falkordb_host: str = os.environ.get("FALKORDB_HOST", "localhost")
    # Canon's own FalkorDB, apart from anything else on the machine (docker compose publishes it on 6380).
    falkordb_port: int = int(os.environ.get("FALKORDB_PORT", "6380"))
    anthropic_api_key: str = os.environ.get("ANTHROPIC_API_KEY", "")
    # Answers are written by this model; extraction runs offline in batches and may use a cheaper one.
    answer_model: str = os.environ.get("CANON_ANSWER_MODEL", "claude-opus-5-5")
    extract_model: str = os.environ.get("CANON_EXTRACT_MODEL", "claude-sonnet-5-5")


def settings() -> Settings:
    return Settings()
