# Canon Phase 2: the product

> **For agentic workers:** this plan runs as four parallel tracks in separate worktrees. Read the Global
> Constraints in `2026-10-15-canon-three-phases.md` first; they all apply.

**Goal:** the features a team uses every day, on the PostHog graph, behind sign-in.

**State at the start (main):**
- `canon_posthog` holds 5,107 documents, 11,935 passages, 2,235 facts, 237 people, 77 teams and 130 areas.
- Activity edges: AUTHORED 1,995, REVIEWED 668, COMMENTED 717 and DECIDED 30. Only 398 documents carry `(:Document)-[:ABOUT]->(:Area)`.
- Ask works end to end (`/app`, SSE).
- Development uses Haiku 5.5 (`CANON_PROFILE` dev); production uses Opus and Sonnet.

## Shared rules for every track

- **Server.**
  - New HTTP routes live in their own module, `server/src/canon/api/<track>_routes.py`, exposing `router = APIRouter()`.
  - Each module is registered with one `app.include_router(...)` line in `api/app.py`.
  - Workspace routes are `/api/w/{ws}/...` and reuse the existing workspace check.
- **Web.**
  - Each screen is its own file in `web/src/app/`.
  - To enable a screen, add its route in `app/router.ts` and flip `soon` off for its entry in `app/App.tsx`'s `NAV`. Keep those edits to a few lines so merges stay trivial.
  - Screens follow the Ask screen and the site: each one draws its idea, in the same palette and type. No card grids of small text, and no monospace except code and ids.
- **Graph rules.**
  - Graph questions are Cypher. Models only draft text.
  - Never aggregate on a key that can be null (FalkorDB 6.0.2 crashes); use `coalesce`.
- **Tests and commits.**
  - TDD with pytest on throwaway graphs, plus headless Playwright screenshots at 1440 and 390.
  - Live model runs use `zsh -ic` (the key lives in the interactive profile) and Haiku.
  - Commits carry no co-author lines.

## Track A: who knows and bus factor

1. **Better area attribution.**
   - Pull requests are mapped to areas by the files they change: `products/<dir>/`, `frontend/src/scenes/<dir>/`, `posthog/<module>/`, and `plugin-server`. Each directory is matched to an ownership-map area by slug or name, with a small hand-checked alias table for the rest.
   - Fetch changed paths for the cached PRs through GraphQL (`files(first: 100)`), cached under `/data/raw`.
   - Target: most of the 1,500 PRs attributed.
2. **Expertise.**
   - `(:Person)-[:KNOWS {score, evidence}]->(:Area)` is computed in Cypher from activity on documents about the area.
   - Weights: DECIDED 4, AUTHORED 3, REVIEWED 2, COMMENTED 1, team membership of the owning team 2.
   - Recency halves the weight every 180 days.
   - `evidence` holds counts per relationship. Store the top documents for display.
3. **Bus factor.**
   - Per area, build a flow network `(:Area)-[:FLOW {cap:1}]->(:Person)-[:FLOW {cap:1}]->(:Sink)` for people above a knowledge threshold.
   - Run `algo.maxFlow`, then recover the min cut: the people whose edges are saturated on a minimum s-t cut.
   - Org view: every area with its owner team, bus factor, and the people it depends on, sorted riskiest first.
4. **API.**
   - `GET /api/w/{ws}/areas` returns areas with owner, bus factor and top people.
   - `GET /api/w/{ws}/areas/{slug}/people` returns ranked people with evidence and documents.
   - `GET /api/w/{ws}/people/{handle}` returns the areas a person knows.
5. **Screens.**
   - **Who knows:** pick an area, see a radial graph of people sized and linked by evidence. Click a person for their evidence lines, which link to PRs, reviews and RFCs.
   - **Bus factor:** areas as a sorted strip of flow diagrams, with the cut drawn in proof red through the people the area depends on.

## Track B: decisions and catch me up

1. **Decisions.**
   - `(:Decision {id, title, status, decided_at})-[:PROPOSED_IN]->(:Document)` from RFCs. Status comes from the RFC text and its PR, its `DECIDED` people from reviewers who approved.
   - `(:Decision)-[:IMPLEMENTED_BY]->(:Document)` for PRs whose body links the RFC.
   - `(:Decision)-[:SUPERSEDED_BY]->(:Decision)` when a later RFC names an earlier one, or a model, given two RFCs on the same area, says it replaces it. Store `reason` and `by`.
   - `(:Decision)-[:ABOUT]->(:Area)` through the RFC's areas.
2. **Catch me up.** `GET /api/w/{ws}/changes?since=YYYY-MM-DD[&area=..&team=..]` returns typed changes:
   - ownership changes (owned_by facts with `valid_from > since`);
   - decisions made or replaced;
   - pages edited whose facts changed (passages removed, facts closed);
   - new out-of-date pages and new disputes;
   - each with its source.

   A `brief` mode drafts a short summary through the same checked-claims pipeline (`ask`-style events), so every sentence carries a verdict.
3. **API:** `GET /api/w/{ws}/decisions` and `GET /api/w/{ws}/decisions/{id}`, plus the changes endpoint above.
4. **Screens.**
   - **Decisions:** a timeline in the hero's language. Each decision is a bar from proposal to replacement. Superseded ones are hatched and struck, with links between them and PR ticks on the accepted one. Click for detail.
   - **Catch me up:** a date picker drawn as a draggable "since you left" range on a timeline. Changes are grouped by kind as markers, and the checked brief sits beside them.

## Track C: the fix queue

1. **Fix nodes.**
   - `(:Fix {id, status: open|approved|dismissed|filed, old, new, created_at, issue_url})`.
   - Edges: `-[:ABOUT]->(:Fact)` (the stale fact), `-[:EVIDENCE]->(:Fact)` (what replaced it), `-[:ON]->(:Document)`, and `-[:ROUTED_TO]->(:Person|:Team)`.
   - Routing: the team owning the page's area; otherwise the team owning the stale fact's subject area, with its lead; otherwise the page's last author.
   - `fixes.build(graph)` is idempotent and runs at the end of ingest. Fixes for facts that are no longer stale close themselves.
2. **Drafting.** The model rewrites only the stale sentence of the passage, using the newer fact. The `old` and `new` sentences are stored. The draft itself is checked with the claim check, and must come back verified against the evidence fact.
3. **The action.**
   - Approving files a GitHub issue through the signed-in user's GitHub token, in a repository the user chooses and has push access to. Never PostHog's repos.
   - The issue carries the page URL, the old sentence, the new one, the evidence link and the routed owner's handle as text, not an @mention.
   - `CANON_ISSUES_DRY_RUN=1`, the default in dev and tests, records the issue body and returns a fake URL. Tests never call GitHub.
4. **API:** `GET /api/w/{ws}/fixes`, plus `POST /api/w/{ws}/fixes/{id}/approve {repo}` and `POST /api/w/{ws}/fixes/{id}/dismiss`. Writes require a signed-in member (Track D's dependency), which is stubbed if Track D isn't merged yet.
5. **Screen: Fix queue.**
   - Each fix is the page drawn as a proof sheet: the stale line struck in red, the correction in cobalt above it, the evidence beneath, and the owner.
   - "Approve and file" picks a repo, then shows the issue link. "Dismiss" asks for a reason.

## Track D: sign-in and workspaces

1. **Accounts.** Adapt Airspace's `server/src/airspace/cloud/` (GitHub OAuth, signed session cookie, accounts graph) to Canon:
   - Users, workspaces and memberships live in `canon_accounts`.
   - Env: `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET`, `CANON_SESSION_SECRET`, `CANON_PUBLIC_URL`.
   - Scope `read:user public_repo` (for filing issues).
   - Tokens are encrypted at rest with a key from `CANON_SESSION_SECRET`.
   - A dev-only `/auth/dev-login` is enabled only when `CANON_DEV_LOGIN=1`.
2. **Workspaces.**
   - `posthog` and `demo` are public and read-only to everyone.
   - A signed-in user creates a workspace from a public GitHub repository (owner/name). A generic connector reads it:
     - Markdown and MDX docs, with git history;
     - CODEOWNERS history as dated `owned_by` facts (authority 3), with areas from CODEOWNERS paths;
     - issues and PRs (bounded);
     - contributors.
   - The connector reuses the PostHog connector's generic pieces.
   - Ingest runs as a background job with progress in the graph (`(:Job {status, step, counts})`).
   - "Sync now" re-reads changed files only and re-runs extraction on changed passages, then link and judge.
3. **API.**
   - `/auth/github`, `/auth/callback`, `/auth/logout`, `/api/me`.
   - `GET /api/workspaces`, `POST /api/workspaces {repo}` and `POST /api/w/{ws}/sync`.
   - `GET /api/w/{ws}/jobs/latest`.
4. **Screens.**
   - The sign-in state sits in the rail.
   - The workspace switcher lists public and own workspaces, with "New workspace from GitHub".
   - Creation is a drawn ingest progress: documents flowing into the graph, as on the site's Sources section.

## Done when

All four tracks are merged, tests pass, and every screen works live on PostHog at 1440 and 390. A dev-login user can create a workspace from a small public repo and ask it a question. Approving a fix in dry-run produces a well-formed issue body.
