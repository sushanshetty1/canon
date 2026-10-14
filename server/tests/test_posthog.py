"""The PostHog connector over small recorded fixtures: real excerpts of PostHog's MIT-licensed site and its API."""

import dataclasses
import json
from pathlib import Path

import pytest

from canon.sources.posthog import clean_mdx, load_posthog, parse_ownership, split_passages
from canon.types import Person

FIXTURES = Path(__file__).parent / "fixtures" / "posthog"

# Three real versions of the ownership map, cut down to three areas.
VERSIONS = [
    ("5bf066499a55c0d18c91f8fef3b5d2913b8be799", "2026-01-07T13:54:47Z", "Abigail", "abigailbramble", "v1.tsx"),
    ("5cfd49f11c925e3e2ca0c0d4a4fb4ea47a23809c", "2026-06-18T16:55:54+03:00", "Eleftheria Trivyzaki", None, "v2.tsx"),
    ("3c094a18fdd7666724acaae6c8a6f2bcd9e9a28a", "2026-10-05T12:32:43+02:00", "Anna Szell", None, "v3.tsx"),
]


def fixture_fetch(name: str):
    if name == "ownership_history":
        return [
            {"sha": sha, "date": at, "author_name": who, "author_handle": handle, "text": (FIXTURES / "ownership" / f).read_text()}
            for sha, at, who, handle, f in VERSIONS
        ]
    if name == "strapi_teams":
        return json.loads((FIXTURES / "strapi_teams.json").read_text())
    if name == "handbook":
        return [
            {
                "path": "contents/handbook/product/metrics.md",
                "text": (FIXTURES / "handbook-product-metrics.md").read_text(),
                "created_at": "2024-03-01T10:00:00Z",
                "updated_at": "2026-09-02T10:00:00Z",
                "author_name": "Anna Szell",
                "author_handle": None,
            }
        ]
    if name == "pulls":
        return [
            {
                "number": 40001,
                "title": "feat(notebooks): faster loading",
                "body": "Loads notebooks in one query.",
                "url": "https://github.com/PostHog/posthog/pull/40001",
                "created_at": "2026-10-01T09:00:00Z",
                "merged_at": "2026-10-02T09:00:00Z",
                "author": "mariusandra",
                "labels": ["feature/notebooks"],
                "reviews": [{"author": "annaszell", "state": "APPROVED", "at": "2026-10-02T08:00:00Z"}],
            }
        ]
    return []


@pytest.fixture(scope="module")
def batch():
    return load_posthog(Path("/nonexistent"), fetch=fixture_fetch)


def test_ownership_history_emits_windows(batch):
    notebooks = sorted((f for f in batch.facts if f.subject == "area:notebooks"), key=lambda f: f.valid_from)
    assert [f.value for f in notebooks] == ["team:platform-features", "team:data-tools"]
    first, second = notebooks
    assert first.valid_to == second.valid_from == "2026-06-18"
    assert second.valid_to is None
    assert all(f.authority == 3 and f.predicate == "owned_by" for f in notebooks)
    # The second fact is stated in the commit that moved it, and that commit is a public document.
    doc = next(d for d in batch.docs if second.passage_id.startswith(d.id))
    assert doc.kind == "ownership_map"
    assert doc.url == "https://github.com/PostHog/posthog.com/commit/5cfd49f11c925e3e2ca0c0d4a4fb4ea47a23809c"
    passage = next(p for p in batch.passages if p.id == second.passage_id)
    assert "platform-features to data-tools" in passage.text


def test_ownership_change_in_a_later_version(batch):
    actions = sorted((f for f in batch.facts if f.subject == "area:actions"), key=lambda f: f.valid_from)
    assert [(f.value, f.valid_from, f.valid_to) for f in actions] == [
        ("team:analytics-platform", "2026-01-07", "2026-10-05"),
        ("team:product-analytics", "2026-10-05", None),
    ]


def test_parse_ownership_survives_notes_with_jsx():
    features = parse_ownership((FIXTURES / "ownership" / "v1.tsx").read_text())
    assert features["notebooks"].owners == ("platform-features",)
    assert features["notebooks"].labels == ("feature/notebooks",)
    assert features["actions"].labels == ("feature/actions",)  # the site's default label


def test_areas_and_teams(batch):
    assert {a.slug for a in batch.areas} == {"actions", "alerts", "notebooks"}
    teams = {t.slug: t for t in batch.teams}
    assert teams["data-tools"].name == "Data Tools"
    assert teams["data-tools"].leads == ("mariusandra",)
    assert "annaszell" in teams["data-tools"].members
    assert teams["analytics-platform"].name == "Analytics platform"  # only in the map's history


def test_people_keep_public_fields_only(batch):
    assert [f.name for f in dataclasses.fields(Person)] == ["handle", "name", "role"]
    people = {p.handle: p for p in batch.people}
    assert people["annaszell"] == Person("annaszell", "Anna Szell", "Product Manager")
    assert people["name:roy-cohen"].name == "Roy Cohen"  # no GitHub handle published


def test_handbook_passages_split_by_heading(batch):
    doc = next(d for d in batch.docs if d.kind == "handbook")
    assert doc.url == "https://posthog.com/handbook/product/metrics"
    assert doc.title == "Product metrics"
    assert doc.updated_at == "2026-09-02"
    assert doc.author == "annaszell"  # matched by published name
    passages = [p for p in batch.passages if p.doc_id == doc.id]
    assert passages[0].text.startswith("We track a short list of metrics")
    revenue = next(p for p in passages if p.text.startswith("Revenue\n"))
    # The SmallTeam component becomes the team's name, so the passage reads as the page does.
    assert "written and owned by the Billing team." in revenue.text
    assert "<" not in revenue.text


def test_split_passages_caps_length():
    body = "## Heading\n\n" + "\n\n".join(f"Paragraph {i} " + "word " * 60 for i in range(10))
    passages = split_passages(body, max_chars=900)
    assert len(passages) > 1
    assert all(p.startswith("Heading\n") for p in passages)
    assert all(len(p) <= 900 + len("Heading\n") for p in passages)


def test_clean_mdx_names_people_and_teams():
    text = 'Owned by <TeamMember name="Eli Kinsey" photo /> and the <SmallTeam slug="billing" />.'
    assert clean_mdx(text, {"billing": "Billing"}) == "Owned by Eli Kinsey and the Billing team."


def test_pull_label_maps_to_area_and_activity(batch):
    doc = next(d for d in batch.docs if d.kind == "pull")
    assert doc.areas == ("notebooks",)
    rels = {(a.handle, a.rel) for a in batch.activity if a.doc_id == doc.id}
    assert rels == {("mariusandra", "AUTHORED"), ("annaszell", "REVIEWED")}


@pytest.mark.live
def test_live_dry_run_counts(tmp_path):
    """Reads the real cache (or fetches it). Run with `-m live`."""
    from canon.sources.cache import data_dir

    batch = load_posthog(data_dir() / "raw" / "posthog")
    kinds = {d.kind for d in batch.docs}
    assert {"handbook", "team_page", "ownership_map", "rfc"} <= kinds
    assert sum(f.valid_to is None for f in batch.facts) > 50
