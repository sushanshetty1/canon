from canon.graph.db import ensure_schema
from canon.graph.writer import write_batch
from canon.sources.rosters import write_rosters
from canon.types import Batch, Person, Team


def test_rosters_become_sourced_facts_by_handle_only(graph):
    ensure_schema(graph)
    write_batch(
        graph,
        Batch(
            teams=[Team("replay", "Replay", members=("pauldambra", "name:jane-doe"), leads=("tuehaulund",))],
            people=[Person("tuehaulund", "Tue"), Person("pauldambra", "Paul"), Person("name:jane-doe", "Jane Doe")],
        ),
    )
    assert write_rosters(graph, team_url="https://posthog.com/teams/{slug}", as_of="2026-10-15") == 2
    write_rosters(graph, team_url="https://posthog.com/teams/{slug}", as_of="2026-10-15")
    rows = graph.query(
        """MATCH (f:Fact)-[:STATED_IN]->(p:Passage)<-[:HAS]-(d:Document {id: 'roster:replay'})
           RETURN f.predicate, f.text, p.text, d.url ORDER BY f.predicate"""
    ).result_set
    assert [r[:2] for r in rows] == [
        ["leads", "tuehaulund leads the Replay team."],
        ["member_of", "pauldambra is a member of the Replay team."],
    ]
    assert "Jane" not in rows[0][2] and rows[0][3] == "https://posthog.com/teams/replay"
