"""Pull requests are attributed to areas by the directories they change."""

from pathlib import Path

from canon.graph.db import ensure_schema
from canon.graph.writer import write_batch
from canon.people.attribution import Attributor, directory
from canon.sources.posthog import load_posthog
from canon.types import Area, Batch, Doc

AREAS = {
    "feature-flags": "Feature flags",
    "experimentation": "Experiments",
    "dashboards": "Dashboards",
    "settings": "Settings structure (personal & project)",
    "signals": "Inbox",
    "replay": "Replay",
    "hogql": "HogQL",
    "ingestion": "Ingestion",
    "mcp-server": "MCP server",
}


def test_directory_keys():
    assert directory("products/feature_flags/backend/api.py") == "products/feature_flags"
    assert directory("frontend/src/scenes/dashboard/Dashboard.tsx") == "scenes/dashboard"
    assert directory("frontend/src/scenes/App.tsx") is None
    assert directory("posthog/hogql/parser.py") == "posthog/hogql"
    assert directory("nodejs/src/ingestion/process.ts") == "nodejs/ingestion"
    assert directory("plugin-server/src/worker/run.ts") == "nodejs/worker"
    assert directory("services/mcp/src/tools.ts") == "services/mcp"
    assert directory("docs/published/handbook.md") is None
    assert directory("pnpm-lock.yaml") is None


def test_directories_match_areas_by_slug_name_plural_and_alias():
    a = Attributor(AREAS)
    assert a.area("products/feature_flags") == "feature-flags"  # slug
    assert a.area("products/inbox") == "signals"  # the area's name
    assert a.area("scenes/dashboard") == "dashboards"  # singular
    assert a.area("products/experiments") == "experimentation"  # hand-checked alias
    assert a.area("services/mcp") == "mcp-server"
    assert a.area("posthog/hogql") == "hogql"
    assert a.area("nodejs/worker") == "ingestion"  # the rest of the ingestion service


def test_generic_django_modules_are_not_areas():
    a = Attributor(AREAS)
    # `posthog/settings` is Django settings, not the Settings area; `posthog/api` is every area at once.
    assert a.area("posthog/settings") is None
    assert a.area("posthog/api") is None
    assert a.area("frontend/lib") is None
    assert a.area("products/review_hog") is None


def test_aliases_to_unknown_areas_are_ignored():
    a = Attributor({"replay": "Replay"})
    assert a.area("products/experiments") is None


def test_a_pull_request_keeps_the_areas_with_a_fair_share_of_its_files():
    a = Attributor(AREAS)
    paths = [f"products/feature_flags/f{i}.py" for i in range(6)] + [
        "frontend/src/scenes/experiments/x/Exp.tsx",
        "frontend/src/scenes/experiments/x/Exp2.tsx",
        "products/dashboards/d.py",  # one file of nine: in passing
        "pnpm-lock.yaml",
    ]
    assert a.areas_for(paths) == ("feature-flags", "experimentation")
    assert a.areas_for(["README.md", "posthog/api/x/y.py"]) == ()


def test_a_sweeping_change_is_about_no_area_in_particular():
    a = Attributor(AREAS)
    paths = [f"products/{d}/x.py" for d in ("feature_flags", "experiments", "dashboards", "replay", "signals", "hogql")]
    assert a.areas_for(paths) == ()


def _fetch(name: str):
    if name == "pulls":
        return [
            {
                "number": 50001,
                "title": "fix(flags): evaluate faster",
                "body": "",
                "url": "https://github.com/PostHog/posthog/pull/50001",
                "created_at": "2026-10-01T09:00:00Z",
                "merged_at": "2026-10-02T09:00:00Z",
                "author": "someone",
                "labels": [],
                "reviews": [],
            }
        ]
    if name == "pull_files":
        return {"50001": ["products/notebooks/backend/api.py", "products/notebooks/frontend/Notebook.tsx"]}
    if name == "ownership_history":
        text = "export const FEATURE_DATA = { notebooks: { feature: 'Notebooks', owner: ['data-tools'] } }"
        return [{"sha": "a" * 40, "date": "2026-01-01T00:00:00Z", "author_name": "x", "author_handle": None, "text": text}]
    return []


def test_connector_attributes_pull_requests_by_changed_paths():
    batch = load_posthog(Path("/nonexistent"), fetch=_fetch)
    pull = next(d for d in batch.docs if d.id == "pull:50001")
    assert pull.areas == ("notebooks",)


def test_writer_replaces_a_documents_areas(graph):
    ensure_schema(graph)
    doc = Doc("pull:1", "pull", "A change", "https://example.com/1", "2026-10-01", areas=("replay", "hogql"))
    write_batch(graph, Batch(docs=[doc], areas=[Area("replay", "Replay"), Area("hogql", "HogQL")]))
    write_batch(graph, Batch(docs=[Doc(**{**doc.__dict__, "areas": ("hogql",)})]))
    rows = graph.query("MATCH (:Document {id: 'pull:1'})-[:ABOUT]->(a:Area) RETURN a.slug").result_set
    assert rows == [["hogql"]]
