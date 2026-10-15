from decision_kit import PULLS, RFCS, Judge, seed_rfcs

from canon.decisions import rfc as R
from canon.decisions import read
from canon.decisions.build import build, short_title

FLAGS = "2025-01-10-flag-environments"
RESILIENT = "2025-02-01-resilient-flags"
LOCAL = "2025-03-01-local-evaluation"
PROJECTS = "2025-06-01-project-environments"
SAML = "2024-03-01-full-saml"
FOLDERS = "2025-05-01-flag-folders"


def row(decision_id: str) -> dict:
    return next(r for r in RFCS if R.decision_id(r["path"]) == decision_id)


def _rfc(decision_id: str) -> R.Rfc:
    return R.from_row(row(decision_id))


# ----- reading one RFC -------------------------------------------------------------------------------------------


def test_status_from_text_and_pull_request():
    assert R.status_of(_rfc(FLAGS)) == "accepted"
    assert R.status_of(_rfc(RESILIENT)) == "proposed"  # its pull request is open
    assert R.status_of(_rfc(FOLDERS)) == "withdrawn"  # its pull request closed without merging
    assert R.status_of(_rfc(SAML)) == "retired"  # it says it is out of date
    rejected = R.from_row({**row(LOCAL), "text": "# RFC: Thing\n\n> **Decision:** No, we will keep the old way.\n"})
    assert R.status_of(rejected) == "rejected"
    # Committed to the main branch without a pull request: accepted when it landed.
    direct = R.from_row({**row(LOCAL), "pr": None})
    assert R.status_of(direct) == "accepted" and direct.decided_at == "2025-03-01"


def test_summary_prefers_the_decision_line():
    assert R.summary_of(row(LOCAL)["text"]) == "we evaluate feature flags locally in every server SDK."
    assert R.summary_of(row(FLAGS)["text"]).startswith("Users want feature flags per environment.")
    # "Decision date:" is not a decision.
    assert R.summary_of("# RFC\n\nDecision date: April 25\n\nWe want to run events for builders in London.") == (
        "We want to run events for builders in London."
    )


def test_decided_by_approvers_and_ids():
    r = _rfc(FLAGS)
    assert r.id == FLAGS and r.decided_at == "2025-01-20" and r.proposed_at == "2025-01-10"
    assert r.approvers == [("bob", "2025-01-10"), ("outsider", "2025-01-10")]
    assert R.decision_id("requests-for-comments/2026-07-24-wizard-v2.5.md") == "2026-07-24-wizard-v2-5"


def test_references_need_replacement_words_beside_the_link():
    known = {r.id: r for r in map(R.from_row, RFCS)}
    refs = R.references(known[PROJECTS], known)
    assert sorted((x.target, x.replaces) for x in refs) == [(FLAGS, True), (FOLDERS, True)]
    near_only = R.from_row({**row(LOCAL), "text": "See [the flags RFC](./2025-01-10-flag-environments.md) for the history. "
                            + "x" * 120 + " The old limits no longer hold."})
    assert [(x.target, x.replaces) for x in R.references(near_only, known)] == [(FLAGS, False)]


def test_areas_from_title_and_body():
    areas = {"feature-flags": "Feature flags", "sso": "SSO", "support": "Support", "search": "Search"}
    assert R.areas_of("Full SAML support", row(SAML)["text"], areas) == ["sso"]  # "support" here is not the team
    assert R.areas_of("Project environments", "feature flags " * 7, areas) == ["feature-flags"]
    assert R.areas_of("Hire a YouTuber", "We search for a YouTuber.", areas) == []


def test_pull_requests_that_link_or_name_an_rfc():
    r = _rfc(PROJECTS)
    found = R.implemented_by(r, "Project environments", PULLS)
    assert [(R.pull_id(p), how) for p, how in found] == [("pull:501", "link"), ("pull:PostHog/posthog.com#77", "link")]
    named = {"number": 9, "title": "feat: envs", "body": "Per the RFC Project environments, this adds...", "merged_at": "x"}
    assert R.implemented_by(r, "Project environments", [named])[0][1] == "title"
    # An unmerged pull request builds nothing yet.
    assert R.implemented_by(_rfc(FLAGS), "Flag environments", PULLS) == []


def test_short_titles():
    assert short_title("RFC: Project environments, by Michael Matloka") == "Project environments"
    assert short_title("RFC: Renaming our plans by @raquelmsmith") == "Renaming our plans"
    assert short_title("RFC: Nail Exports - Ben White") == "Nail Exports"
    assert short_title("RFC: HogTok videos #project-dopamine-brainrot") == "HogTok videos"
    assert short_title("RFC: Wizard v2.5") == "Wizard v2.5"
    assert short_title("RFC: Notifications & @pauldambra") == "Notifications"
    assert short_title("RFC: Onboarding 2.0 (continued) - Emanuele Capparelli / Raquel Smith") == "Onboarding 2.0 (continued)"
    assert short_title("RFC: [OST] The PostHog social network") == "The PostHog social network"
    assert short_title("RFC: Comms - Data Warehouse launch") == "Comms - Data Warehouse launch"


# ----- the graph -------------------------------------------------------------------------------------------------


def _one(graph, q, params=None):
    return graph.query(q, params or {}).result_set


def test_build_writes_decisions(graph):
    seed_rfcs(graph)
    counts = build(graph, RFCS, PULLS)
    assert counts["decisions"] == 6 and counts["superseded_by"] == 2 and counts["judged"] == 0

    by_id = {d["id"]: d for d in read.decisions(graph)}
    assert by_id[FLAGS]["status"] == "superseded" and by_id[FLAGS]["replaced_at"] == "2026-09-15"
    assert by_id[FLAGS]["superseded_by"] == [{"id": PROJECTS, "reason": by_id[FLAGS]["superseded_by"][0]["reason"], "by": "reference"}]
    assert "replaces the flag environments RFC" in by_id[FLAGS]["superseded_by"][0]["reason"]
    assert by_id[PROJECTS]["status"] == "accepted" and by_id[PROJECTS]["supersedes"][0]["id"] == FLAGS
    assert by_id[PROJECTS]["title"] == "Project environments"
    assert by_id[RESILIENT]["status"] == "proposed" and by_id[RESILIENT]["decided_at"] is None
    # A closed proposal folded into a later RFC is replaced, and its document is its pull request.
    assert by_id[FOLDERS]["status"] == "superseded" and by_id[FOLDERS]["superseded_by"][0]["id"] == PROJECTS
    assert by_id[FOLDERS]["url"] == "https://github.com/acme/rfcs/pull/13" and by_id[FOLDERS]["title"] == "Flag folders"
    assert by_id[SAML]["status"] == "retired" and [a["slug"] for a in by_id[SAML]["areas"]] == ["sso"]
    assert [a["slug"] for a in by_id[PROJECTS]["areas"]] == ["feature-flags"]

    # Approvers who are staff decided it; without approvals, the person who merged it did.
    assert [(p["handle"], p["how"]) for p in by_id[FLAGS]["people"]] == [("bob", "approved")]
    assert [(p["handle"], p["how"]) for p in by_id[LOCAL]["people"]] == [("alice", "merged")]

    # Linking pull requests; one from another repo is added as a document.
    assert [p["id"] for p in by_id[PROJECTS]["pulls"]] == ["pull:501", "pull:PostHog/posthog.com#77"]
    assert _one(graph, "MATCH (d:Document {id: 'pull:PostHog/posthog.com#77'})-[:HAS]->(p:Passage) RETURN d.kind, d.author")[0] == ["pull", "bob"]
    assert _one(graph, "MATCH (:Decision {id: $id})-[:PROPOSED_IN]->(d:Document) RETURN d.id", {"id": FLAGS})[0][0] == f"rfc:{row(FLAGS)['path']}"
    assert _one(graph, "MATCH (:Decision {id: $id})-[:PROPOSED_IN]->(d:Document)-[:HAS]->(p) RETURN d.kind, count(p)", {"id": FOLDERS})[0] == ["rfc", 1]


def test_decision_facts_carry_the_history(graph):
    seed_rfcs(graph)
    build(graph, RFCS, PULLS)
    rows = {r[0]: r[1:] for r in _one(graph, "MATCH (f:Fact) WHERE f.subject STARTS WITH 'decision:' RETURN f.id, f.value, f.valid_from, f.valid_to, f.text")}
    accepted, replaced = rows[f"decision:{FLAGS}:accepted"], rows[f"decision:{FLAGS}:replaced"]
    assert accepted[:3] == ["accepted", "2025-01-20", "2026-09-15"]
    assert replaced[0] == f"replaced by decision:{PROJECTS}" and replaced[1] == "2026-09-15"
    assert replaced[3] == 'The "Flag environments" RFC was replaced by the "Project environments" RFC on 2026-09-15.'
    assert rows[f"decision:{RESILIENT}:proposed"][0] == "proposed"
    assert rows[f"decision:{SAML}:retired"][0] == "retired"
    assert rows[f"decision:{FOLDERS}:proposed"][:3] == ["proposed", "2025-05-01", "2026-09-15"]
    assert rows[f"decision:{FOLDERS}:replaced"][1] == "2026-09-15"
    chain = _one(graph, "MATCH (a:Fact {id: $a})-[e:SUPERSEDED_BY]->(b:Fact) RETURN b.id, e.reason", {"a": f"decision:{FLAGS}:accepted"})
    assert chain == [[f"decision:{FLAGS}:replaced", "newer"]]
    # Each fact is stated in its RFC's opening passage.
    stated = _one(graph, "MATCH (f:Fact {id: $id})-[:STATED_IN]->(p:Passage) RETURN p.text", {"id": f"decision:{LOCAL}:accepted"})
    assert stated[0][0].startswith("# Request for comments: Local evaluation")


def _snapshot(graph):
    nodes = _one(graph, "MATCH (n) RETURN count(n)")[0][0]
    edges = sorted(tuple(r) for r in _one(graph, "MATCH (a)-[e]->(b) RETURN type(e), labels(a)[0], labels(b)[0], count(e)"))
    props = sorted(tuple(r) for r in _one(graph, "MATCH (d:Decision) RETURN d.id, d.status, d.replaced_at, d.summary"))
    return nodes, edges, props


def test_build_is_idempotent(graph):
    seed_rfcs(graph)
    build(graph, RFCS, PULLS)
    first = _snapshot(graph)
    build(graph, RFCS, PULLS)
    assert _snapshot(graph) == first


def test_model_judges_pairs_on_one_area_once(graph):
    seed_rfcs(graph)
    judge = Judge({("Resilient feature flags", "Local evaluation of feature flags")})
    counts = build(graph, RFCS, PULLS, model=judge)
    # Five RFCs share feature flags. Only a later accepted RFC can replace: local and projects. Projects already
    # says it replaces flags and folders, which leaves flags, resilient and local for it, and flags and resilient
    # for local.
    pairs = sorted((c.split('First RFC: "')[1].split('"')[0], c.split('Second RFC: "')[1].split('"')[0]) for c in judge.calls)
    assert pairs == [
        ("Flag environments", "Local evaluation of feature flags"),
        ("Local evaluation of feature flags", "Project environments"),
        ("Resilient feature flags", "Local evaluation of feature flags"),
        ("Resilient feature flags", "Project environments"),
    ]
    assert counts["judged"] == 4
    d = {x["id"]: x for x in read.decisions(graph)}
    assert d[RESILIENT]["status"] == "superseded"
    assert d[RESILIENT]["superseded_by"] == [{"id": LOCAL, "by": "model", "reason": "Local evaluation of feature flags replaces Resilient feature flags."}]
    assert d[FLAGS]["superseded_by"][0]["by"] == "reference"

    # A second run asks nothing and keeps what the model said.
    again = Judge()
    counts = build(graph, RFCS, PULLS, model=again)
    assert again.calls == [] and counts["judged"] == 0
    assert {x["id"]: x["status"] for x in read.decisions(graph)}[RESILIENT] == "superseded"
    # Without a model the earlier verdicts stay too.
    build(graph, RFCS, PULLS)
    assert {x["id"]: x["status"] for x in read.decisions(graph)}[RESILIENT] == "superseded"


def test_a_removed_rfc_takes_its_decision_with_it(graph):
    seed_rfcs(graph)
    build(graph, RFCS, PULLS)
    build(graph, [r for r in RFCS if "full-saml" not in r["path"]], PULLS)
    assert SAML not in {d["id"] for d in read.decisions(graph)}
    assert not _one(graph, "MATCH (f:Fact) WHERE f.subject = $s RETURN f.id", {"s": f"decision:{SAML}"})


def test_decision_detail(graph):
    seed_rfcs(graph)
    build(graph, RFCS, PULLS)
    d = read.decision(graph, FLAGS)
    assert d["superseded_by"][0]["title"] == "Project environments" and d["superseded_by"][0]["status"] == "accepted"
    assert [f["value"] for f in d["facts"]] == ["accepted", f"replaced by decision:{PROJECTS}"]
    assert d["facts"][0]["current"] is False and d["facts"][1]["current"] is True
    assert read.decision(graph, "nope") is None
