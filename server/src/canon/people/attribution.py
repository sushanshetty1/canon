"""Which areas a pull request is about, from the files it changed.

PostHog's monorepo is laid out by product: `products/<dir>/`, `frontend/src/scenes/<dir>/`, `posthog/<module>/`,
`ee/<module>/`, the Node ingestion service (`nodejs/`, once `plugin-server/`), Rust services under `rust/<crate>/`
and other services under `services/<name>/`. Each changed path gives one directory key such as
`products/feature_flags`. A key names an area when its last segment matches an ownership-map area by slug or by
name (`feature_flags` is `feature-flags`, `inbox` is the area named Inbox), or through `ALIASES`, a small table
checked by hand against the repository for the directories whose names differ from their area's.

A pull request that touches many products in passing (a rename across the codebase) is about none of them in
particular, so a pull request keeps only the areas that hold a fair share of its changed files, at most three.
"""

import re
from collections import Counter
from collections.abc import Iterable, Mapping

# Directory key -> area slug, for directories whose name is not their area's slug or name. Checked by hand.
ALIASES: dict[str, str] = {
    # products/
    "products/warehouse_sources": "pipeline-sources",
    "products/warehouse_sources_queue": "pipeline-sources",
    "products/managed_warehouse": "data-warehouse",
    "products/warehouse_suggestions": "data-warehouse",
    "products/experiments": "experimentation",
    "products/desktop": "posthog-code",
    "products/product_analytics": "insights",
    "products/replay_vision": "session-summaries",
    "products/cdp": "data-pipelines",
    "products/conversations": "support",
    "products/skills": "skills-store",
    "products/access_control": "permissions",
    "products/authz": "permissions",
    "products/alerts_platform": "alerts",
    "products/billing_alerts": "billing",
    "products/data_catalog": "semantic-layer",
    "products/github_commands": "github-integration",
    "products/notifications": "internal-messaging",
    "products/event_definitions": "data-management",
    "products/groups": "group-analytics",
    "products/cross_project_dashboards": "dashboards",
    # frontend/src/scenes/
    "scenes/experiments": "experimentation",
    "scenes/dashboard": "dashboards",
    "scenes/saved-insights": "insights",
    "scenes/max": "posthog-ai",
    "scenes/hog-functions": "pipeline-destinations",
    "scenes/session-recordings": "replay",
    "scenes/activity": "activity-view",
    "scenes/team-activity": "activity-log",
    "scenes/toolbar-launch": "toolbar",
    "scenes/persons": "persons-view",
    # posthog/ and ee/
    "posthog/hogql_queries": "hogql",
    "posthog/cdp": "data-pipelines",
    "posthog/session_recordings": "replay",
    "posthog/github": "github-integration",
    "posthog/slack": "slack-app",
    "posthog/personhog_client": "persons",
    "ee/hogai": "posthog-ai",
    "ee/session_recordings": "replay",
    # services
    "nodejs/ingestion": "ingestion",
    "nodejs/cdp": "data-pipelines",
    "nodejs/session-recording": "replay",
    "nodejs/session-replay": "replay",
    "nodejs/messaging": "workflows",
    "rust/capture": "ingestion",
    "rust/ingestion-consumer": "ingestion",
    "rust/cymbal": "error-tracking",
    "rust/cymbal-proto": "error-tracking",
    "rust/property-defs-rs": "data-management",
    "rust/cohort-seeder": "cohorts",
    "rust/personhog-identity": "persons",
    "rust/personhog-common": "persons",
    "rust/personhog-replica": "persons",
    "rust/personhog-router": "persons",
    "rust/personhog-leader": "persons",
    "services/mcp": "mcp-server",
    "services/integration-service": "integrations",
    "common/replay-headless": "replay",
    "common/replay-shared": "replay",
    "common/ingestion": "ingestion",
    "frontend/toolbar": "toolbar",
    "frontend/public/surveys": "surveys",
}

# Roots whose module names are generic (Django apps, shared libraries) and match an area only through ALIASES,
# except for the names below: `posthog/settings` is Django settings, not the Settings area.
_STRICT_ROOTS = {"posthog", "ee", "nodejs", "frontend", "common"}
_LOOSE_OK = {"posthog/hogql", "ee/billing", "posthog/security"}

MAX_AREAS = 3
MIN_SHARE = 0.2  # of the pull request's files that name an area


def directory(path: str) -> str | None:
    """The directory key of one changed path, or None for files outside product code (docs, lockfiles, CI)."""
    parts = path.split("/")
    if len(parts) < 3:
        return None
    root = parts[0]
    if root == "products":
        return f"products/{parts[1]}"
    if parts[:3] == ["frontend", "src", "scenes"]:
        return f"scenes/{parts[3]}" if len(parts) > 4 else None
    if parts[:2] == ["frontend", "src"]:
        return f"frontend/{parts[2]}"
    if parts[:2] == ["frontend", "public"]:
        return f"frontend/public/{parts[2]}"
    if root in ("nodejs", "plugin-server"):
        # `nodejs/src/cdp/...` and `nodejs/tests/cdp/...` name a part of the service.
        return f"nodejs/{parts[2]}" if parts[1] in ("src", "tests") and len(parts) > 3 else "nodejs/"
    if root in ("posthog", "ee", "rust", "services", "common"):
        return f"{root}/{parts[1]}"
    return None


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


class Attributor:
    """Maps directory keys to areas. `areas` is slug -> name, from the ownership map."""

    def __init__(self, areas: Mapping[str, str], aliases: Mapping[str, str] = ALIASES):
        self.by_key: dict[str, str] = {}
        for slug, name in areas.items():
            for key in (_norm(slug), _norm(name)):
                self.by_key.setdefault(key, slug)
                # Singular and plural forms: `dashboard` and `dashboards`.
                self.by_key.setdefault(key[:-1] if key.endswith("s") else key + "s", slug)
        self.aliases = {k: v for k, v in aliases.items() if v in areas}
        self.slugs = set(areas)

    def area(self, key: str) -> str | None:
        if key in self.aliases:
            return self.aliases[key]
        if key.startswith("nodejs/"):
            return "ingestion" if "ingestion" in self.slugs else None  # the rest of the ingestion service
        root, _, name = key.rpartition("/")
        if root.split("/")[0] in _STRICT_ROOTS and key not in _LOOSE_OK:
            return None
        return self.by_key.get(_norm(name))

    def areas_for(self, paths: Iterable[str]) -> tuple[str, ...]:
        """The areas a set of changed paths is mostly about, most files first."""
        counts: Counter[str] = Counter()
        for path in paths:
            key = directory(path)
            slug = self.area(key) if key else None
            if slug:
                counts[slug] += 1
        total = sum(counts.values())
        if not total:
            return ()
        ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
        return tuple(slug for slug, n in ranked[:MAX_AREAS] if n / total >= MIN_SHARE)
