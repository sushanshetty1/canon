<p align="center">
  <img alt="Canon. Every answer, checked against what's true today." src="assets/readme/banner.png" width="100%">
</p>

<p align="center">
  <img alt="Status: building at the FalkorDB Hackathon" src="https://img.shields.io/badge/status-building-2c46e8?style=flat-square&labelColor=0d0e12">
  <img alt="Built on FalkorDB" src="https://img.shields.io/badge/built%20on-FalkorDB-0d0e12?style=flat-square">
  <img alt="Answers by Claude" src="https://img.shields.io/badge/answers-Claude-d97757?style=flat-square&labelColor=0d0e12">
  <a href="LICENSE"><img alt="Apache-2.0 licence" src="https://img.shields.io/badge/license-Apache--2.0-0d0e12?style=flat-square"></a>
</p>

**Canon is a company brain that checks its own answers.** Ask how your company works: who owns this, why did we decide that, who should I ask, what changed while I was away. Canon answers from one graph of your docs, tickets and chats, and before you see the answer it checks every sentence against that graph. Each sentence comes back verified, out of date, disputed, or not said at all.

Every company-brain tool today can find text and cite it. None of them checks whether what it cites is still true. A handbook page that says Team A owns billing, written before billing moved, gets quoted with a confident citation. Canon is built so that does not happen, and when it finds a page like that, it sends the fix to whoever owns it.

## How it works

1. **Connect.** Canon reads a company's handbook, design docs, issues, pull requests, reviews, forum threads and team pages into one FalkorDB graph. Every fact it extracts keeps the passage it came from and the dates it held.
2. **Ask.** Canon finds the evidence for a question in the graph, then a model writes the answer one claim at a time, each claim tied to the facts behind it.
3. **Check.** Every claim is checked against the graph before it is shown. Whether a fact is current is a graph question, not the model's opinion:

   | Verdict | Means |
   | --- | --- |
   | **Verified** | A source says it, and nothing newer replaced it. |
   | **Out of date** | A newer source replaced it. Canon shows which one, and when. |
   | **Disputed** | Two current sources disagree. Canon shows both. |
   | **Unsupported** | Nothing in the graph backs it, so Canon does not say it. |

4. **Fix.** Out-of-date and disputed knowledge goes to a fix queue: the exact change, the evidence, and the person who owns that page, chosen from the graph. A person approves it, and Canon files it as a GitHub issue.

## What a team uses it for

| | |
| --- | --- |
| **Ask** | Plain questions about the company, answered claim by claim with the source of each one. |
| **Who actually knows** | People ranked by what they did (reviewed, wrote, decided, answered), with that evidence shown. Not by job title. |
| **Bus factor** | For each area, how many people could still answer if the rest left. Computed with `algo.maxFlow`. |
| **Decisions** | Every design doc from proposal to acceptance to replacement, with the pull requests that shipped it. |
| **Catch me up** | What changed since a date: owners, decisions, and pages that now say something different. |
| **Fix queue** | Pages Canon found out of date, each with its change drafted and routed to its owner. |

## Why a graph

| | |
| --- | --- |
| **"Still true" is a path** | A fact is current when no `SUPERSEDED_BY` edge leads away from it. Search finds similar words; it cannot tell you that one fact replaced another, or when. |
| **Every claim has a lineage** | Claim, passage, document, author: one traversal answers "where did this come from" for every sentence of an answer. |
| **Expertise is evidence** | "Who knows session replay" is weighted paths from people through what they reviewed, wrote and decided to the area. |
| **Bus factor is a flow** | How many people can independently answer for an area is the maximum flow from the area to the people who know it. `algo.maxFlow` returns it, and the minimum cut names who to worry about. |

## The graph

Each company is its own FalkorDB graph, so workspaces never share nodes.

```text
(:Person {handle, role})-[:MEMBER_OF {since, until}]->(:Team {slug, name})
(:Person)-[:LEADS]->(:Team)
(:Team)-[:OWNS {valid_from, valid_to}]->(:Area {slug, name})

(:Document {id, kind, url, title, updated_at})-[:HAS]->(:Passage {id, text})
(:Fact {id, text, valid_from, valid_to})-[:STATED_IN]->(:Passage)
(:Fact)-[:ABOUT]->(:Area | :Team | :Person | :Decision)
(:Fact)-[:SUPERSEDED_BY]->(:Fact)
(:Fact)-[:CONTRADICTS]->(:Fact)

(:Decision {id, title, status, decided_at})-[:PROPOSED_IN]->(:Document)
(:Decision)-[:SUPERSEDED_BY]->(:Decision)
(:Decision)-[:IMPLEMENTED_BY]->(:Document)

(:Person)-[:AUTHORED | :REVIEWED | :COMMENTED | :DECIDED]->(:Document)
(:Fix {id, status})-[:ABOUT]->(:Fact)
(:Fix)-[:ROUTED_TO]->(:Person)
```

Canon is being built during the hackathon. This model and the queries below are the design; this section changes as the code lands.

```cypher
// Is this claim still true? Follow its fact forward in time to whatever replaced it.
MATCH (p:Passage)<-[:STATED_IN]-(f:Fact {id: $fact})
OPTIONAL MATCH chain = (f)-[:SUPERSEDED_BY*1..5]->(now:Fact)
WHERE now.valid_to IS NULL
RETURN p.text, f.valid_to IS NULL AS current, [n IN nodes(chain) | n.text] AS since
```

```cypher
// Bus factor: how many people can independently answer for an area.
MATCH (a:Area {slug: $area}), (sink:Sink {id: $sink})
CALL algo.maxFlow({sourceNodes: [a], targetNodes: [sink], capacityProperty: 'cap', relationshipTypes: ['KNOWS_FLOW']})
YIELD maxFlow
RETURN maxFlow
```

## The demo company

Rule 6 of the hackathon allows public data only, so the demo runs on a company that works in public: **PostHog**.

| Source | What it gives Canon | Licence |
| --- | --- | --- |
| [Handbook and team pages](https://github.com/PostHog/posthog.com/tree/master/contents) | What the company says, team by team, with full edit history | MIT |
| [Feature ownership map](https://github.com/PostHog/posthog.com/blob/master/src/hooks/useFeatureOwnership.tsx) | Who owns which product area, and every change to that | MIT |
| [Design docs (RFCs)](https://github.com/PostHog/requests-for-comments-public) | 44 dated decisions with their review threads | MIT |
| [Issues and pull requests](https://github.com/PostHog/posthog) | Who worked on what, who reviewed it, what shipped | MIT |
| [Community forum](https://posthog.com/questions) | What people actually ask | Public pages |

People appear only by the GitHub handles and roles PostHog already publishes.

## How we will measure it

A set of real questions about PostHog, many of which depend on time ("who owns X now", "is this decision still in force"), answered two ways with the same model: Canon, and a standard pipeline that searches the same documents and summarises the top passages. We score correctness, how many out-of-date claims each one states as fact, and whether each citation actually supports its sentence. The results, every question and every answer, will be published in this repo.

## What we learned from

We studied these projects closely and wrote our own code.

| Project | What we took | What Canon adds |
| --- | --- | --- |
| [Graphiti](https://github.com/getzep/graphiti) | Facts with validity windows: a new fact closes an old one without deleting it | Checking each claim of an answer against those windows before it is shown |
| [Onyx](https://github.com/onyx-dot-app/onyx) | Connectors, and answers that respect who can see what | A graph of people, ownership and decisions, not only documents |
| [FalkorDB GraphRAG-SDK](https://github.com/FalkorDB/GraphRAG-SDK) | Provenance from document to chunk to entity | Provenance that also runs forward in time |
| [kotaemon](https://github.com/Cinnamon/kotaemon) | Showing the exact passage behind a sentence | A verdict on whether that passage is still true |
| [Microsoft GraphRAG](https://github.com/microsoft/graphrag), [LightRAG](https://github.com/HKUDS/LightRAG) | Graph and vector retrieval side by side | Incremental updates that change verdicts, not a rebuilt index |
| [Unblocked](https://getunblocked.com), [Guru](https://www.getguru.com) | Expertise from code review; knowledge that people verify on a schedule | Expertise from every source with its evidence, and verification that runs on every answer |

## Repo layout

| Path | What it is |
| --- | --- |
| [`server/src/canon/graph`](server/src/canon/graph) | FalkorDB connection, one graph per workspace, indexes |
| [`server/src/canon/sources`](server/src/canon/sources) | Connectors: handbooks, design docs, issues, pull requests, forums |
| [`server/src/canon/extract`](server/src/canon/extract) | Documents to facts, each with its passage and validity window |
| [`server/src/canon/answer`](server/src/canon/answer) | Evidence from the graph, drafted into an answer claim by claim |
| [`server/src/canon/verify`](server/src/canon/verify) | The check: every claim against the graph |
| [`server/src/canon/people`](server/src/canon/people) | Ownership, expertise from evidence, bus factor |
| [`server/src/canon/fixes`](server/src/canon/fixes) | The fix queue and the GitHub action |
| [`server/src/canon/cloud`](server/src/canon/cloud) | Sign-in and company workspaces |
| [`server/src/canon/bench`](server/src/canon/bench) | Canon against the search-and-summarise baseline |
| [`web`](web) | The site and the app (Vite, React, Tailwind) |

## Quick start

```sh
docker compose up -d falkordb      # Canon's FalkorDB on :6380, its Browser on :3001
cd server && uv sync
uv run canon serve                 # the API on :8790
uv run pytest -q                   # tests (FalkorDB must be running)

cd ../web && npm install && npm run dev
```

Answers need `ANTHROPIC_API_KEY` in the environment.

## Roadmap

- [x] Scaffold: server, FalkorDB with per-workspace graphs, site
- [x] PostHog connectors: handbook, ownership map, RFCs, issues and pull requests, forum
- [x] Extraction: facts with passages and validity windows, superseded and contradicting facts
- [x] Ask, with every claim checked
- [ ] People: ownership, expertise from evidence, bus factor
- [ ] Decisions and catch me up
- [ ] Fix queue and the GitHub action
- [ ] Sign-in and company workspaces
- [ ] Benchmark against search-and-summarise
- [ ] Live deployment and demo video

## FalkorDB Hackathon

Built for the [FalkorDB Hackathon](https://www.wemakedevs.org/hackathons/falkordb) (October 15 to 18, 2026), entering **Track 03 · Company Brain**. Work on Canon began on October 15, during the event.

We use AI coding assistants (Claude Code) for research, scaffolding and pair programming, and say so here as the rules require. We can explain every part of the graph model, the queries and the design.

## Creators

<table>
  <tr>
    <td align="center" width="160">
      <a href="https://github.com/sushanshetty1"><img src="https://github.com/sushanshetty1.png?size=160" width="80" alt="Sushan Shetty"><br><b>Sushan Shetty</b></a><br><sub>@sushanshetty1</sub>
    </td>
  </tr>
</table>

## License

[Apache-2.0](LICENSE).
