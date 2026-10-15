"""Decisions: what a company decided, when, who decided it, what built it, and what replaced it.

A decision comes from an RFC. `rfc` reads one RFC's raw text and pull request (status, summary, the RFCs it names,
its areas, the pull requests that link it). `build` writes them into the graph:

- `(:Decision {id, title, status, proposed_at, decided_at, replaced_at, summary})-[:PROPOSED_IN]->(:Document)`
- `(:Person)-[:DECIDED {how, at}]->(:Decision)`: the reviewers who approved its pull request, else who merged it
- `(:Decision)-[:IMPLEMENTED_BY {how}]->(:Document)`: merged pull requests whose body links the RFC
- `(:Decision)-[:SUPERSEDED_BY {reason, by}]->(:Decision)`: a later RFC that replaces it
- `(:Decision)-[:ABOUT]->(:Area)`

Each decision also states dated facts (accepted, replaced) in its RFC's passages, so a catch-up brief about
decisions is checked the same way as any answer. `read` serves the API.
"""
