"""Settings read from the environment, with local-development defaults."""

import os
from dataclasses import dataclass, field

# Which models Canon uses. Development and tests run everything on Haiku, which is cheap; the deployed app sets
# CANON_PROFILE=prod for Opus answers and Sonnet extraction. Each model can still be set on its own.
PROFILES = {
    "dev": {"answer": "claude-haiku-5-5", "extract": "claude-haiku-5-5", "check": "claude-haiku-5-5"},
    "prod": {"answer": "claude-opus-5-5", "extract": "claude-sonnet-5-5", "check": "claude-sonnet-5-5"},
}


def _model(role: str) -> str:
    profile = PROFILES.get(os.environ.get("CANON_PROFILE", "dev"), PROFILES["dev"])
    return os.environ.get(f"CANON_{role.upper()}_MODEL", profile[role])


@dataclass(frozen=True)
class Settings:
    falkordb_host: str = os.environ.get("FALKORDB_HOST", "localhost")
    # Canon's own FalkorDB, apart from anything else on the machine (docker compose publishes it on 6380).
    falkordb_port: int = int(os.environ.get("FALKORDB_PORT", "6380"))
    anthropic_api_key: str = os.environ.get("ANTHROPIC_API_KEY", "")
    profile: str = os.environ.get("CANON_PROFILE", "dev")
    answer_model: str = field(default_factory=lambda: _model("answer"))
    extract_model: str = field(default_factory=lambda: _model("extract"))
    check_model: str = field(default_factory=lambda: _model("check"))


def settings() -> Settings:
    return Settings()
