from canon.cli import render

SRC = {"fact": "Replay owns session replay.", "title": "Ownership map", "date": "2026-06-18", "url": "https://example.com/m"}


def test_render_prints_claims_in_order_with_verdicts():
    events = [
        {"type": "evidence", "facts": 3, "documents": 2},
        {"type": "claim", "index": 0, "text": "Replay owns session replay.", "fact_ids": ["m"]},
        {"type": "claim", "index": 1, "text": "Product analytics owns session replay.", "fact_ids": ["h"]},
        {"type": "verdict", "index": 1, "verdict": "stale", "sources": [], "newer": [SRC], "conflicting": []},
        {"type": "verdict", "index": 0, "verdict": "verified", "sources": [SRC], "newer": [], "conflicting": []},
        {"type": "done", "counts": {"verified": 1, "stale": 1, "disputed": 0, "unsupported": 0}},
    ]
    out = render("Who owns session replay?", events)
    assert out.index("Verified") < out.index("Out of date")
    assert "Now: Replay owns session replay. (Ownership map, 2026-06-18" in out
    assert out.endswith("1 verified, 1 out of date")
    assert "—" not in out and "–" not in out


def test_render_empty_names_who_to_ask():
    events = [{"type": "evidence", "facts": 0, "documents": 0},
              {"type": "empty", "ask": [{"handle": "name:ines", "name": "Ines", "why": "Leads Billing, which owns Billing."}]}]
    assert "Ask Ines (name:ines): Leads Billing" in render("Q?", events)
