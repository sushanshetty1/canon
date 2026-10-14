# Canon Implementation Plan (three phases)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build Canon end to end: a company brain on FalkorDB that answers questions about a company and checks every sentence of the answer against a graph that knows when each fact held. Out-of-date knowledge goes to its owner as a fix.

**Architecture:** One Python server package (`server/src/canon`) and one web app (`web/`). The server owns:

- the graph (FalkorDB, one graph per workspace);
- the connectors (PostHog first: handbook, team pages, ownership map history, RFCs, issues and pull requests, forum);
- extraction (passages to facts with a subject, a predicate, a value and a validity window);
- the supersession linker (deterministic Cypher, no model);
- retrieval, the answer drafter and the verifier.

Phase 2 adds people and expertise, bus factor, decisions, catch me up, the fix queue with a GitHub action, sign-in and workspaces. Phase 3 adds the benchmark, deployment, the video and the write-up.

**Tech stack:**

- Server: Python 3.12, uv, `falkordb`, FalkorDB 6.0.2 in Docker (port 6380), FastAPI, `anthropic`, `httpx`, pytest.
- Web: Vite 8, React 19, TypeScript, Tailwind v4, `motion/react`, `@phosphor-icons/react`.

**Spec:** `README.md` (graph model, verdicts, Cypher, sources, measurement), and the memory notes on the Canon concept and site design.

## Global Constraints

- FalkorDB is the primary and only store for company knowledge, accounts and fixes (hackathon rule). Raw downloads may be cached as files under `/data/` (gitignored); nothing reads them at answer time.
- **The graph decides; the model drafts.** These are graph queries, never a model's opinion:
  - whether a fact is current;
  - whether it is disputed;
  - who owns something;
  - who knows something;
  - the bus factor.

  Models are used only to (a) extract facts from passages, (b) draft answer sentences from facts the graph returned, and (c) check that a sentence says what its facts say.
- Models: answers use `claude-opus-5-5` (setting `CANON_ANSWER_MODEL`). Extraction and the entailment check use `claude-sonnet-5-5` (`CANON_EXTRACT_MODEL`). Use structured outputs (`output_config={"format": {...}}`). Opus 5.5 always thinks: never send a `thinking` budget; set depth with `output_config.effort` ("high" for answers). Never print or log `ANTHROPIC_API_KEY`.
- Public data only. People appear only by the GitHub handles, names and roles PostHog already publishes. No emails, no avatars stored, no private data.
- One graph per workspace, `canon_<slug>`; accounts in `canon_accounts`. Tests use `test_canon_<hex>` graphs and delete them.
- Never stop, restart or modify other FalkorDB containers on the machine. Canon's container is `canon-falkordb-1` on 6380.
- No em dashes or en dashes in user-facing strings. Copy is short and factual.
- Commits are authored by the repo owner only. No `Co-Authored-By` or AI attribution lines.
- Tests never open windows or play sound. Tests that call a model are marked `@pytest.mark.live`, are skipped without `ANTHROPIC_API_KEY`, and are not part of the default run (`-m "not live"`).
- Web: light theme, the palette and type in `web/src/index.css`, no monospace except code, no fake UI decoration.

## Review Focus

1. **A fact restated later by a stale page.** The ownership map moved an area to team B in September, but a handbook page last edited in October still says team A. That page is out of date, not disputed, because the ownership map is the authority for ownership. *Owner: Task 4; test `test_lower_authority_restatement_is_stale_not_disputed`.*
2. **Two current sources of equal authority disagree.** Both are current; the verdict is Disputed and both are shown. Neither one is silently picked. *Owner: Task 4 (`test_equal_authority_disagreement_contradicts`) and Task 5 (`test_verdict_disputed`).*
3. **A claim citing a fact id the model invented, or citing no fact.** The verdict is Unsupported and the sentence is dropped from the shown answer. *Owner: Task 5; tests `test_unknown_fact_is_unsupported` and `test_claim_without_facts_is_unsupported`.*
4. **A question about something the company never wrote down.** Canon says it found nothing, and suggests who to ask from ownership. It must not draft an answer from nothing. *Owner: Task 6; test `test_no_evidence_returns_no_answer`.*
5. **Re-running ingestion.** It is idempotent: no duplicate documents, passages or facts. A changed page replaces its passages, and its old facts are closed (`valid_to`) rather than deleted. *Owner: Task 3 (`test_reingest_is_idempotent`) and Task 4 (`test_changed_page_closes_old_facts`).*

---

## The three phases

| Phase | Outcome | Done when |
|---|---|---|
| **1. Checked answers** (Oct 15 to 16) | PostHog in the graph with dated facts; Ask returns answers claim by claim with verdicts; a first app screen shows it | `canon ingest posthog` loads the demo graph. The question "Who owns notebooks?" returns the current owner, Verified, with the ownership map commit as its source. At least one real handbook page is found to state an ownership the map has since changed. The Ask screen streams claims and verdicts from the live API. |
| **2. The product** (Oct 16 to 17) | The features a team would use daily, behind sign-in | Who knows, bus factor (`algo.maxFlow` with the min cut), decisions, catch me up and the fix queue all work on PostHog. Approving a fix files a GitHub issue in a repo the user chooses (never PostHog's). GitHub sign-in works. A public read-only PostHog workspace exists, and a signed-in user can create a workspace from a GitHub repo of Markdown docs. |
| **3. Proof and ship** (Oct 17 to 18) | Measured results, live demo, submission | The benchmark runs Canon against search-and-summarise on 40+ PostHog questions, and the results are in the README. The app is live at the confirmed domain. The video is recorded, the repo is public, and the submission is made before Oct 18 23:59 IST. |

### Open-source work we learn from, and what we do better

We study these and write our own code.

| Project | Idea we take | Canon's own step |
|---|---|---|
| Graphiti (Apache-2.0) | Edges with `valid_at` and `invalid_at`; a new fact invalidates an old one, which stays on record | Supersession is deterministic Cypher over a closed predicate vocabulary, with source authority. Every answer sentence is checked against it before it is shown. |
| GraphRAG-SDK (MIT) | Document to chunk to entity provenance | Provenance also runs forward in time (`SUPERSEDED_BY`) |
| Onyx (MIT core) | Connector shape: pull, normalise, cursor | Connectors also emit dated structured facts from history (git log of the ownership map) |
| kotaemon (Apache-2.0) | Passage highlighting beside each sentence | A verdict per sentence, and the newer passage when it is out of date |
| Microsoft GraphRAG, LightRAG (MIT) | Full-text or vector first, then graph expansion | Expansion follows `SUPERSEDED_BY` to the current fact before drafting |

---

## Phase 1 file structure

```
server/src/canon/
  types.py                     # Task 1: shared dataclasses (the contract between modules)
  graph/db.py                  # exists: connect, workspace_graph, ensure_schema
  graph/writer.py              # Task 1: upsert documents, passages, people, teams, areas, facts
  sources/github.py            # Task 2: small GitHub client (contents, commits, file at sha, issues, pulls)
  sources/posthog.py           # Task 2: PostHog connector -> Batch
  sources/cache.py             # Task 2: on-disk cache under /data/raw
  extract/facts.py             # Task 3: passage -> ExtractedFact via the extract model
  extract/predicates.py        # Task 3: the closed predicate vocabulary and authority ranks
  verify/supersede.py          # Task 4: link SUPERSEDED_BY / CONTRADICTS, close validity windows
  verify/check.py              # Task 5: claim -> Verdict
  answer/retrieve.py           # Task 6: question -> Evidence
  answer/draft.py              # Task 6: Evidence -> Draft (claims citing fact ids)
  answer/ask.py                # Task 6: ask(): retrieve, draft, check, as a stream of events
  api/app.py                   # Task 7: /api/w/{ws}/ask (SSE), /api/w/{ws}/facts/{id}, /api/w/{ws}/documents/{id}
  cli.py                       # Task 7: canon ingest posthog, canon ask
server/tests/
  test_writer.py  test_posthog.py  test_extract.py  test_supersede.py  test_check.py  test_ask.py  test_api.py
web/src/
  app/                         # Task 8: the app shell (routes /app/...)
  app/Ask.tsx                  # Task 8: ask, then claims stream in with verdicts and sources
  app/api.ts                   # Task 8: typed client and the SSE reader
```

**Parallel execution.** Task 1 lands first, because it is the contract. Then three tracks run at once in separate worktrees:

- Tasks 2 and 3 (data);
- Tasks 4 and 5 (verification);
- Task 8 (web, against the event contract in Task 6).

Task 6 joins them, and Task 7 exposes them.

---

### Task 1: The contract and the graph writer

**Files:**
- Create: `server/src/canon/types.py`, `server/src/canon/graph/writer.py`
- Test: `server/tests/test_writer.py`

**Interfaces (produced, used by every later task):**

```python
# server/src/canon/types.py
from dataclasses import dataclass, field
from typing import Literal

Kind = Literal["handbook", "team_page", "ownership_map", "rfc", "issue", "pull", "forum"]
Verdict = Literal["verified", "stale", "disputed", "unsupported"]

@dataclass(frozen=True)
class Doc:
    id: str            # stable: f"{kind}:{path or number}", e.g. "handbook:contents/handbook/engineering/deployments.md"
    kind: Kind
    title: str
    url: str           # public URL a reader can open
    updated_at: str    # ISO date of the version read
    author: str | None = None   # GitHub handle when known

@dataclass(frozen=True)
class Passage:
    id: str            # f"{doc_id}#{index}"
    doc_id: str
    text: str          # 1 to 6 sentences; a heading's section, split on paragraphs

@dataclass(frozen=True)
class Fact:
    id: str            # sha1(subject|predicate|value|source_passage)[:16]
    subject: str       # an entity key: "area:notebooks", "team:replay", "person:timgl", "topic:friday-deploys"
    predicate: str     # one of extract.predicates.PREDICATES
    value: str         # normalised: an entity key or a short phrase
    text: str          # the fact as one plain sentence
    valid_from: str    # ISO date
    passage_id: str
    authority: int     # from extract.predicates.AUTHORITY[doc kind]
    valid_to: str | None = None

@dataclass(frozen=True)
class Person:
    handle: str; name: str; role: str | None = None

@dataclass(frozen=True)
class Team:
    slug: str; name: str; members: tuple[str, ...] = (); leads: tuple[str, ...] = ()

@dataclass(frozen=True)
class Area:
    slug: str; name: str

@dataclass(frozen=True)
class Activity:      # who did what to which document
    handle: str; doc_id: str; rel: Literal["AUTHORED", "REVIEWED", "COMMENTED", "DECIDED"]; at: str

@dataclass
class Batch:         # what a connector returns
    docs: list[Doc] = field(default_factory=list)
    passages: list[Passage] = field(default_factory=list)
    facts: list[Fact] = field(default_factory=list)      # structured facts (no model), e.g. ownership history
    people: list[Person] = field(default_factory=list)
    teams: list[Team] = field(default_factory=list)
    areas: list[Area] = field(default_factory=list)
    activity: list[Activity] = field(default_factory=list)
```

```python
# server/src/canon/graph/writer.py
def write_batch(graph, batch: Batch) -> dict[str, int]: ...   # counts per label written
def write_facts(graph, facts: list[Fact]) -> int: ...
```

Writer rules:

- Every write is an `UNWIND $rows AS r MERGE (...) SET ...` on the indexed key, so re-ingest is idempotent.
- `(Document)-[:HAS]->(Passage)` and `(Fact)-[:STATED_IN]->(Passage)` are written as part of the same batch.
- A Fact's `subject` and `value` link to entity nodes with `(Fact)-[:ABOUT]->(e)`, and with `(Fact)-[:VALUE]->(e)` when the value is an entity key.
  - The key prefix picks the label: `area`, `team` or `person`.
  - A `topic` key becomes a `(:Topic {key})` node.
- When a Doc is re-ingested with a newer `updated_at`, its passages that no longer exist are detached from it (kept for history, `removed_at` set).

- [ ] **Step 1:** Write `test_writer.py`:
  - `test_write_batch_creates_lineage`: Doc, Passage and Fact are written; one query returns `fact.text`, `passage.text` and `doc.url`.
  - `test_reingest_is_idempotent`: write the same batch twice; node counts are unchanged.
  - `test_fact_links_entities`: an `area:notebooks` subject and a `team:data-tools` value create the ABOUT and VALUE edges to `Area` and `Team`.
- [ ] **Step 2:** Run `uv run pytest tests/test_writer.py -q`. Expected: fails (module missing).
- [ ] **Step 3:** Implement `types.py` and `writer.py`. Add `Topic.key` to `INDEXES` in `graph/db.py`.
- [ ] **Step 4:** Run the tests. Expected: pass.
- [ ] **Step 5:** Commit `Types and graph writer`.

### Task 2: PostHog connector

**Files:**
- Create: `server/src/canon/sources/{github.py,cache.py,posthog.py}`
- Test: `server/tests/test_posthog.py` (fixtures in `server/tests/fixtures/posthog/`)

**Interfaces:**
- Consumes: `Batch` and the dataclasses from Task 1.
- Produces: `def load_posthog(cache_dir: Path, *, issues_since: str = "2025-10-01", max_pulls: int = 1500) -> Batch`.

**What it reads:**

- **`PostHog/posthog.com` handbook** (`contents/handbook/**/*.md(x)`) and **team pages** (`contents/teams/*/index.mdx` plus `objectives.mdx`), via a shallow `git clone --filter=blob:none` into the cache. Read the current files, plus each file's last-commit date and author handle (`git log -1 --format=%aI%x09%an -- path`).
  - Strip the MDX frontmatter and components.
  - Split into passages by heading, then by paragraph, at most about 900 characters each.
- **Ownership map history** (`src/hooks/useFeatureOwnership.tsx`). For every commit touching it (`git log --format=%H%x09%aI -- path`), read the file at that sha and parse `FEATURE_DATA` with a regex, giving each `slug` its `feature` and `owner` list.
  - Walk the commits oldest first. Each time an area's owner list changes, emit a structured `Fact(subject="area:<slug>", predicate="owned_by", value="team:<owner>", valid_from=<commit date>, authority=3)`.
  - Close the previous owner's fact (`valid_to`).
  - Each commit becomes a `Doc(kind="ownership_map", id=f"ownership_map:{sha[:10]}", url=commit URL)` with one passage: the changed lines.
  - This is the authoritative, provable timeline.
- **Teams and people.** Team slugs and names come from `contents/teams/*`. Members, leads and roles come from the public Strapi endpoint `https://better-animal-d658c56969.strapiapp.com/api/teams?populate[profiles][fields][0]=firstName&populate[profiles][fields][1]=lastName&populate[profiles][fields][2]=companyRole&populate[profiles][fields][3]=githubUsername&populate[leadProfiles][fields][0]=githubUsername&pagination[pageSize]=100`.
  - Keep only names, roles and GitHub handles.
  - People without a GitHub handle are kept by name with handle `name:<slug>`.
- **RFCs.** `PostHog/requests-for-comments-public` gives one Doc per RFC file, with a date from the first commit, an author, and status if stated. Its PR review comments become `Activity(REVIEWED/COMMENTED)`.
- **Issues and pulls.** `PostHog/posthog` issues and PRs since `issues_since`, up to `max_pulls` merged PRs. Keep labels (`feature/*` maps to an area through the ownership map `label`), author, reviewers and merged date.
  - These become Docs with one passage each (title plus the first 600 characters of the body), and `Activity` rows.
  - Use `GITHUB_TOKEN` when set. Respect rate limits with a sleep on 403/429.
- **Forum.** `https://posthog.com/api/questions` (paged): title, first post, resolved flag, date. Keep only threads from the last 12 months.

Everything is cached under `/data/raw/posthog/` so a second run makes no network calls.

- [ ] **Step 1:** Write the tests with small recorded fixtures (three ownership map versions, one handbook file, one team JSON):
  - `test_ownership_history_emits_windows`: an area that moved from `product-analytics` to `data-tools` gives two facts, with the first one's `valid_to` set to the second one's `valid_from`.
  - `test_handbook_passages_split_by_heading`.
  - `test_people_keep_public_fields_only`: the Person dataclass has only handle, name and role.
- [ ] **Step 2:** Implement with the fixtures injected (`load_posthog` takes an optional `fetch` callable for tests).
- [ ] **Step 3:** Run it for real once: `uv run canon ingest posthog --dry-run` prints counts. Record them in the commit message.
- [ ] **Step 4:** Commit `PostHog connector`.

### Task 3: Fact extraction

**Files:**
- Create: `server/src/canon/extract/{predicates.py,facts.py}`
- Test: `server/tests/test_extract.py`

**Interfaces:**
- Consumes: `Passage`, `Doc` and the entity lists (teams, areas, people) for normalisation.
- Produces:
  - `PREDICATES: dict[str, str]` (name to description);
  - `AUTHORITY: dict[Kind, int]`;
  - `async def extract(passages, docs, entities, *, model, concurrency=8) -> list[Fact]`.

**Predicates (closed vocabulary; supersession matches on `(subject, predicate)`):**

| Predicate | Meaning |
|---|---|
| `owned_by` | area to team |
| `member_of` | person to team |
| `leads` | person to team |
| `decided` | topic to a short decision phrase |
| `process` | topic to how something is done |
| `policy` | topic to a rule |
| `uses` | team or topic to a tool |
| `contact_for` | topic to a person or team |

**Authority ranks:** `ownership_map` 3, `team_page` 2, `rfc` 2 (when accepted), `handbook` 1, `pull` 1, `issue` 0, `forum` 0.

- The model gets the passage, its document title, and the lists of team slugs and area slugs. It returns JSON through structured outputs: `facts: [{subject, predicate, value, text}]`. Subjects and values must be entity keys from the given lists, or `topic:<kebab-slug>` of at most four words.
- Topic slugs are normalised so the same topic from different pages lands on one key:
  1. lowercase;
  2. remove stopwords;
  3. merge two topics when their slugs share all content words (a cheap union-find).
- `valid_from` is the document's `updated_at`; for an RFC it is its decided date.
- Ownership facts from the handbook are extracted too. They are what Task 4 compares against the ownership map.

- [ ] **Step 1:** Write the tests:
  - `test_normalise_topic_slug`;
  - `test_rejects_unknown_entity_keys` (the model output is validated, and unknown keys are dropped);
  - a `@live` test `test_extract_handbook_ownership_sentence` on a real sentence.
- [ ] **Step 2:** Implement with `anthropic.AsyncAnthropic`, `output_config={"format": {"type": "json_schema", ...}}`, a semaphore, and retries on 429/529.
- [ ] **Step 3:** Commit `Fact extraction`.

### Task 4: Supersession and disputes (deterministic)

**Files:**
- Create: `server/src/canon/verify/supersede.py`
- Test: `server/tests/test_supersede.py`

**Interfaces:**
- Produces: `def link(graph) -> dict[str, int]`, returning `{"superseded": n, "contradicts": n, "stale_pages": n}`.

**Rules,** for each `(subject, predicate)` group of facts, ordered by `valid_from`:

1. **Same value:** a later fact with the same value restates the earlier one. Link the two with `(:Fact)-[:RESTATES]->(:Fact)`; they are not superseded.
2. **A newer value replaces an older one:** fact B with a different value and `valid_from` after A, where B's authority is at least A's. Then `(A)-[:SUPERSEDED_BY]->(B)` and `A.valid_to = B.valid_from`.
3. **A stale restatement:** a lower-authority fact L that asserts an older value after a higher-authority fact H already replaced it (`L.valid_from > H.valid_from`, `L.authority < H.authority`). Then `(L)-[:SUPERSEDED_BY]->(H)` and `L.stale = true`. L's page goes on the fix list.
4. **A dispute:** two current facts with equal authority and different values, neither replaced. Link them with `(A)-[:CONTRADICTS]->(B)`.

Facts are current when `valid_to IS NULL AND NOT (f)-[:SUPERSEDED_BY]->()`.

```cypher
// Groups to examine: every (subject, predicate) with more than one distinct value.
MATCH (f:Fact)
WITH f.subject AS s, f.predicate AS p, collect(f) AS fs
WHERE size(fs) > 1
RETURN s, p, [x IN fs | {id: x.id, value: x.value, from: x.valid_from, auth: x.authority}] AS facts
```

The grouping runs in Cypher. The ordering and the four rules run in Python over each group's rows, which are small. The results are written back with `UNWIND` batches.

- [ ] **Step 1:** Write the tests (each builds its facts with `write_facts`):
  - `test_newer_value_supersedes`;
  - `test_same_value_restates_not_supersedes`;
  - `test_lower_authority_restatement_is_stale_not_disputed`: ownership map Sep `area:notebooks owned_by team:data-tools` (authority 3), and handbook Oct saying `team:product-analytics` (authority 1). Expect the handbook fact to be stale and superseded by the map fact.
  - `test_equal_authority_disagreement_contradicts`;
  - `test_changed_page_closes_old_facts`: re-extracting a page whose passage changed sets `valid_to` on facts from the removed passage.
  - `test_link_is_idempotent`.
- [ ] **Step 2:** Implement.
- [ ] **Step 3:** Commit `Supersession and disputes`.

### Task 5: The check

**Files:**
- Create: `server/src/canon/verify/check.py`
- Test: `server/tests/test_check.py`

**Interfaces:**
- Produces:
  - `@dataclass Claim(text: str, fact_ids: list[str])`;
  - `@dataclass Checked(claim: Claim, verdict: Verdict, sources: list[dict], newer: list[dict], conflicting: list[dict])`;
  - `def check_graph(graph, claim) -> Checked`, which is deterministic;
  - `async def check(graph, claim, *, entail) -> Checked`, which adds the entailment check.

**Verdict rules,** in order:

1. No `fact_ids`, or no cited fact exists in the graph: `unsupported`.
2. The entailment check says the claim says more than the facts (`entail(claim.text, [f.text]) == False`): `unsupported`.
3. Any cited fact is superseded or stale: `stale`. `newer` holds the end of the `SUPERSEDED_BY` chain, with its passage and document.
4. Any cited fact has a current `CONTRADICTS` partner: `disputed`. `conflicting` holds the partner with its source.
5. Otherwise: `verified`. `sources` holds each fact's passage text, document title, url and date.

```cypher
MATCH (f:Fact) WHERE f.id IN $ids
MATCH (f)-[:STATED_IN]->(p:Passage)<-[:HAS]-(d:Document)
OPTIONAL MATCH chain = (f)-[:SUPERSEDED_BY*1..6]->(n:Fact)
WHERE NOT (n)-[:SUPERSEDED_BY]->()
OPTIONAL MATCH (n)-[:STATED_IN]->(np:Passage)<-[:HAS]-(nd:Document)
OPTIONAL MATCH (f)-[:CONTRADICTS]-(c:Fact) WHERE c.valid_to IS NULL AND NOT (c)-[:SUPERSEDED_BY]->()
OPTIONAL MATCH (c)-[:STATED_IN]->(cp:Passage)<-[:HAS]-(cd:Document)
RETURN f, p, d, n, np, nd, collect(DISTINCT {fact: c, passage: cp, doc: cd}) AS conflicts
```

`entail` is the extract model with a structured output, `{supported: bool}`. It is injected so tests pass a stub.

- [ ] **Step 1:** Write the tests: `test_unknown_fact_is_unsupported`, `test_claim_without_facts_is_unsupported`, `test_verdict_verified_has_sources`, `test_verdict_stale_names_newer_fact`, `test_verdict_disputed`, `test_entailment_failure_is_unsupported`.
- [ ] **Step 2:** Implement.
- [ ] **Step 3:** Commit `Claim check`.

### Task 6: Ask

**Files:**
- Create: `server/src/canon/answer/{retrieve.py,draft.py,ask.py}`
- Test: `server/tests/test_ask.py`

**Interfaces:**
- `def retrieve(graph, question, *, limit=24) -> Evidence`. `Evidence` holds:
  - `facts`: dicts with `id`, `text`, `subject`, `predicate`, `value`, `current`, `source`;
  - `entities`: the matched area, team and person keys.
- `async def draft(question, evidence, *, model) -> list[Claim]`.
- `async def ask(graph, question) -> AsyncIterator[dict]`, which yields these events in order:
  - `{"type":"evidence","facts":n,"documents":n}`
  - `{"type":"claim","index":i,"text":...}`, one per claim as it is drafted
  - `{"type":"verdict","index":i,"verdict":...,"sources":[...],"newer":[...],"conflicting":[...]}`
  - `{"type":"done","counts":{"verified":n,"stale":n,"disputed":n,"unsupported":n}}`
  - or `{"type":"empty","ask":[{"handle":..., "why":...}]}` when there is no evidence

**Retrieval:**

1. Full-text over passages: `CALL db.idx.fulltext.queryNodes('Passage', $q) YIELD node, score`, top 30. Facts are then gathered through `STATED_IN`.
2. Entity match: question words against area, team and person names (case-insensitive contains) give the facts `ABOUT` those entities.
3. Every fact found is followed forward along `SUPERSEDED_BY` to the current fact, which is added. The drafter gets both, each labelled current or replaced, so it answers from current facts and can say what changed.

**Drafting:**

- Opus with `output_config.effort="high"` and a structured output of `claims: [{text, fact_ids}]`.
- The system prompt says: one claim per sentence; cite only the given fact ids; use current facts; mention a replaced fact only to say what changed.

- [ ] **Step 1:** Write the tests, with a stub drafter and stub entail:
  - `test_retrieve_follows_supersession_to_current`;
  - `test_ask_event_order`;
  - `test_no_evidence_returns_no_answer`: the result is an `empty` event that names the owner team's lead when the question names an area.
- [ ] **Step 2:** Implement. Add a `@live` end-to-end test on the PostHog graph: "Who owns notebooks?"
- [ ] **Step 3:** Commit `Ask: retrieve, draft, check`.

### Task 7: API and CLI

**Files:**
- Modify: `server/src/canon/api/app.py`, `server/src/canon/cli.py`
- Test: `server/tests/test_api.py`

**Endpoints:**

- `POST /api/w/{ws}/ask {question}` returns `text/event-stream` with the Task 6 events as `data:` lines.
- `GET /api/w/{ws}/facts/{id}` returns the fact, its passage and document, its chain forward and back, and its conflicts.
- `GET /api/w/{ws}/stats` returns counts per label, plus the stale-page count.

**CLI:**

- `canon ingest posthog [--workspace posthog] [--skip-extract] [--dry-run]` runs connector, writer, extract, writer, then link, and prints counts.
- `canon ask "<question>" [--workspace posthog]` prints claims with verdicts.

Steps:

- [ ] Write the tests with FastAPI `TestClient` and a stubbed `ask`: `test_ask_streams_events`, `test_unknown_workspace_404`.
- [ ] Implement.
- [ ] Run the real ingest once and record the counts in the commit message.
- [ ] Commit `API and CLI`.

### Task 8: The Ask screen

**Files:**
- Create: `web/src/app/{App.tsx,Ask.tsx,api.ts}`
- Modify: `web/src/main.tsx` (route `/app` to the app, `/` to the site)

**Behaviour:**

- One question box, at the top on desktop and pinned to the bottom on mobile, with three suggested PostHog questions.
- On submit:
  - the claims appear one by one as sentences of a paragraph, each in a neutral "checking" style;
  - as its verdict arrives, each sentence takes its mark: cobalt underline (verified), red strike plus the newer fact inserted after it (stale), amber marker (disputed);
  - unsupported sentences fold away under "1 sentence removed: nothing backs it".
- Clicking a sentence opens its source on the right (a sheet on mobile):
  - the passage with the cited words in highlighter yellow;
  - the document title and date, with a link to the public URL;
  - for stale sentences, the newer source above it.
- The counts line at the end reads, for example: "4 verified, 1 out of date".
- The same visual language as the site: Funnel type, slabs, no monospace except fact ids in the inspector.

Steps:

- [ ] Build against a local mock of the event stream (`api.ts` exports `ask(question, onEvent)`, `mock` when `?mock=1`).
- [ ] Verify at 1440 and 390 widths with headless Playwright.
- [ ] Commit `Ask screen`.

---

## Phase 2: The product (outline; detailed plan written when Phase 1 lands)

1. **Who knows.**
   - Expertise score for (person, area) = Σ over activity edges to documents ABOUT the area of weight(rel) × recency decay. The weights are DECIDED 4, AUTHORED 3, REVIEWED 2, COMMENTED 1, answered forum 1.
   - Computed in Cypher and stored as `(:Person)-[:KNOWS {score, evidence}]->(:Area)`.
   - The screen shows people with their evidence, as lines they can open.
2. **Bus factor.**
   - Per area: build `(:Area)-[:KNOWS_FLOW {cap:1}]->(:Person)-[:KNOWS_FLOW {cap:1}]->(:Sink)` for people above a threshold. Run `algo.maxFlow`.
   - The min cut names the people the area depends on.
   - Org view: areas sorted by bus factor, with the owner team. This is the "who to worry about" list.
3. **Decisions.** RFC Decision nodes with `PROPOSED_IN`, `SUPERSEDED_BY` and `IMPLEMENTED_BY` (PRs that link the RFC). The timeline uses the hero's language.
4. **Catch me up.** Since date D, within areas or teams I follow:
   - ownership changes (facts with `valid_from > D`, predicate `owned_by`);
   - new and replaced decisions;
   - pages edited whose facts changed.

   It is grouped and drafted into short checked claims through the same `ask` pipeline.
5. **Fix queue.**
   - A `(:Fix)` node for each stale page fact:
     - the drafted correction (old sentence, new sentence);
     - the evidence (the newer fact and its source);
     - `ROUTED_TO` the page's owner. The owner comes from the team owning the page's area, otherwise the page's last author.
   - Approve or dismiss in the app.
   - Approving files a GitHub issue through the signed-in user's token, in a repo the user picks (never PostHog's own). The issue URL is stored on the Fix.
6. **Sign-in and workspaces.**
   - GitHub OAuth (the Airspace pattern), with users and workspaces in `canon_accounts`.
   - A public read-only `posthog` workspace.
   - "New workspace from a GitHub repo" ingests that repo's Markdown docs, CODEOWNERS (as `owned_by` facts with git history), issues and PRs, using the generic parts of the PostHog connector.
7. **Incremental update.** A webhook or "Sync now" re-reads changed files, re-extracts only their passages and re-runs `link`. The demo shows a verdict flip after a commit.

## Phase 3: Proof and ship (outline)

1. **Benchmark.**
   - 40 to 60 PostHog questions with gold answers taken from the graph's structured facts and RFCs, about half of them time-sensitive.
   - Baseline: full-text search over the same passages plus the same model summarising the top 8 passages with citations.
   - Metrics:
     - answer correctness (judged against gold by a separate model, with a sample checked by hand);
     - stale claims stated as fact;
     - citation support rate.
   - Every question, answer and score is committed under `bench/results/`.
2. **Deploy.** Docker images for the server and web, with FalkorDB on the VPS, behind the existing Traefik through labels only (never touching Traefik's own config or other projects' containers). The domain must be confirmed by the owner first. The PostHog snapshot is bundled so the demo needs no ingest at boot.
3. **Video** (under 3 minutes):
   - ask a time-sensitive question;
   - see a stale sentence caught;
   - open the newer source;
   - the fix goes to its owner and is filed;
   - the bus factor min cut.
4. **README** with real numbers, graph model, Cypher and AI disclosure. Make the repo public, then submit.
