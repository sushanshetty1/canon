// A recorded Ask, for building and demoing the screen without a model key: `/app?mock=1`.
//
// The facts are the seeded demo company, Kestrel (`server/src/canon/demo_seed.py`), exactly as
// `GET /api/w/demo/facts/{id}` returns them. The streams are what `ask()` yields for each question:
// evidence, every claim at once when the draft returns, then verdicts in the order their checks finish.

import type { AskEvent, Counts, FactDetail, Source, Stats, VerdictName } from './api'

type Links = { back: string[]; forward: string[]; restated: string[]; conflicts: string[] }

const FACTS: Record<string, Source> = {
  "001ecdf81aadc943": {"fact_id":"001ecdf81aadc943","fact":"Product analytics owns session replay.","subject":"area:session-replay","predicate":"owned_by","value":"team:product-analytics","authority":3,"valid_from":"2026-02-10","valid_to":"2026-06-18","stale":false,"current":false,"superseded_by":"a9065c5424adc158","passage_id":"ownership_map:3f9c2a71d0#0","passage":"session-replay: Product analytics. notebooks: Product analytics. feature-flags: Platform. billing: Billing.","removed":false,"doc_id":"ownership_map:3f9c2a71d0","title":"Ownership map: first owners","url":"https://kestrel.example.com/ownership/commit/3f9c2a71d0","kind":"ownership_map","date":"2026-02-10"},
  "8863b08c13c7bf1d": {"fact_id":"8863b08c13c7bf1d","fact":"Product analytics owns notebooks.","subject":"area:notebooks","predicate":"owned_by","value":"team:product-analytics","authority":3,"valid_from":"2026-02-10","valid_to":"2026-09-02","stale":false,"current":false,"superseded_by":"c435f8f1fe35ff15","passage_id":"ownership_map:3f9c2a71d0#0","passage":"session-replay: Product analytics. notebooks: Product analytics. feature-flags: Platform. billing: Billing.","removed":false,"doc_id":"ownership_map:3f9c2a71d0","title":"Ownership map: first owners","url":"https://kestrel.example.com/ownership/commit/3f9c2a71d0","kind":"ownership_map","date":"2026-02-10"},
  "0055535e8c6b44ab": {"fact_id":"0055535e8c6b44ab","fact":"Platform owns feature flags.","subject":"area:feature-flags","predicate":"owned_by","value":"team:platform","authority":3,"valid_from":"2026-02-10","valid_to":null,"stale":false,"current":true,"superseded_by":null,"passage_id":"ownership_map:3f9c2a71d0#0","passage":"session-replay: Product analytics. notebooks: Product analytics. feature-flags: Platform. billing: Billing.","removed":false,"doc_id":"ownership_map:3f9c2a71d0","title":"Ownership map: first owners","url":"https://kestrel.example.com/ownership/commit/3f9c2a71d0","kind":"ownership_map","date":"2026-02-10"},
  "759c3056888e224e": {"fact_id":"759c3056888e224e","fact":"Billing owns billing.","subject":"area:billing","predicate":"owned_by","value":"team:billing","authority":3,"valid_from":"2026-02-10","valid_to":null,"stale":false,"current":true,"superseded_by":null,"passage_id":"ownership_map:3f9c2a71d0#0","passage":"session-replay: Product analytics. notebooks: Product analytics. feature-flags: Platform. billing: Billing.","removed":false,"doc_id":"ownership_map:3f9c2a71d0","title":"Ownership map: first owners","url":"https://kestrel.example.com/ownership/commit/3f9c2a71d0","kind":"ownership_map","date":"2026-02-10"},
  "a9065c5424adc158": {"fact_id":"a9065c5424adc158","fact":"Replay owns session replay.","subject":"area:session-replay","predicate":"owned_by","value":"team:replay","authority":3,"valid_from":"2026-06-18","valid_to":null,"stale":false,"current":true,"superseded_by":null,"passage_id":"ownership_map:8b41e6c5f2#0","passage":"session-replay: Product analytics changed to session-replay: Replay.","removed":false,"doc_id":"ownership_map:8b41e6c5f2","title":"Ownership map: session replay moves to Replay","url":"https://kestrel.example.com/ownership/commit/8b41e6c5f2","kind":"ownership_map","date":"2026-06-18"},
  "c435f8f1fe35ff15": {"fact_id":"c435f8f1fe35ff15","fact":"Data tools owns notebooks.","subject":"area:notebooks","predicate":"owned_by","value":"team:data-tools","authority":3,"valid_from":"2026-09-02","valid_to":null,"stale":false,"current":true,"superseded_by":null,"passage_id":"ownership_map:c07d93ab14#0","passage":"notebooks: Product analytics changed to notebooks: Data tools.","removed":false,"doc_id":"ownership_map:c07d93ab14","title":"Ownership map: notebooks move to Data tools","url":"https://kestrel.example.com/ownership/commit/c07d93ab14","kind":"ownership_map","date":"2026-09-02"},
  "19234936365f266d": {"fact_id":"19234936365f266d","fact":"The Replay team owns session replay.","subject":"area:session-replay","predicate":"owned_by","value":"team:replay","authority":2,"valid_from":"2026-07-02","valid_to":null,"stale":false,"current":true,"superseded_by":null,"passage_id":"team_page:teams/replay#0","passage":"The Replay team owns session replay, from the recorder in the browser to the player. Mara Okafor leads the team.","removed":false,"doc_id":"team_page:teams/replay","title":"Replay team","url":"https://kestrel.example.com/teams/replay","kind":"team_page","date":"2026-07-02"},
  "eea254f55c41e53f": {"fact_id":"eea254f55c41e53f","fact":"Mara Okafor leads the Replay team.","subject":"person:name:mara-okafor","predicate":"leads","value":"team:replay","authority":2,"valid_from":"2026-07-02","valid_to":null,"stale":false,"current":true,"superseded_by":null,"passage_id":"team_page:teams/replay#0","passage":"The Replay team owns session replay, from the recorder in the browser to the player. Mara Okafor leads the team.","removed":false,"doc_id":"team_page:teams/replay","title":"Replay team","url":"https://kestrel.example.com/teams/replay","kind":"team_page","date":"2026-07-02"},
  "823e44404f2db233": {"fact_id":"823e44404f2db233","fact":"Data tools owns notebooks.","subject":"area:notebooks","predicate":"owned_by","value":"team:data-tools","authority":2,"valid_from":"2026-09-05","valid_to":null,"stale":false,"current":true,"superseded_by":null,"passage_id":"team_page:teams/data-tools#0","passage":"Data tools builds notebooks and the SQL editor. Jonas Weber leads the team.","removed":false,"doc_id":"team_page:teams/data-tools","title":"Data tools team","url":"https://kestrel.example.com/teams/data-tools","kind":"team_page","date":"2026-09-05"},
  "a25d40a8c566158c": {"fact_id":"a25d40a8c566158c","fact":"Jonas Weber leads the Data tools team.","subject":"person:name:jonas-weber","predicate":"leads","value":"team:data-tools","authority":2,"valid_from":"2026-09-05","valid_to":null,"stale":false,"current":true,"superseded_by":null,"passage_id":"team_page:teams/data-tools#0","passage":"Data tools builds notebooks and the SQL editor. Jonas Weber leads the team.","removed":false,"doc_id":"team_page:teams/data-tools","title":"Data tools team","url":"https://kestrel.example.com/teams/data-tools","kind":"team_page","date":"2026-09-05"},
  "e0d4ffe3be23d4ed": {"fact_id":"e0d4ffe3be23d4ed","fact":"The Product analytics team owns session replay.","subject":"area:session-replay","predicate":"owned_by","value":"team:product-analytics","authority":1,"valid_from":"2026-08-20","valid_to":null,"stale":true,"current":false,"superseded_by":"a9065c5424adc158","passage_id":"handbook:handbook/session-replay.md#0","passage":"Session replay is owned by the Product analytics team. Questions about recordings go to #team-product-analytics.","removed":false,"doc_id":"handbook:handbook/session-replay.md","title":"Session replay","url":"https://kestrel.example.com/handbook/session-replay","kind":"handbook","date":"2026-08-20"},
  "af92f2388532d3c5": {"fact_id":"af92f2388532d3c5","fact":"Session recordings are kept for 30 days on the free plan and 90 days on paid plans.","subject":"topic:replay-retention","predicate":"policy","value":"30 days on free, 90 days on paid","authority":1,"valid_from":"2026-08-20","valid_to":null,"stale":false,"current":true,"superseded_by":null,"passage_id":"handbook:handbook/session-replay.md#1","passage":"Recordings are kept for 30 days on the free plan and 90 days on paid plans.","removed":false,"doc_id":"handbook:handbook/session-replay.md","title":"Session replay","url":"https://kestrel.example.com/handbook/session-replay","kind":"handbook","date":"2026-08-20"},
  "f1cb3e456f4285ce": {"fact_id":"f1cb3e456f4285ce","fact":"Product analytics owns notebooks.","subject":"area:notebooks","predicate":"owned_by","value":"team:product-analytics","authority":1,"valid_from":"2026-03-04","valid_to":"2026-09-02","stale":false,"current":false,"superseded_by":"c435f8f1fe35ff15","passage_id":"handbook:handbook/notebooks.md#0","passage":"Notebooks are built and owned by Product analytics.","removed":false,"doc_id":"handbook:handbook/notebooks.md","title":"Notebooks","url":"https://kestrel.example.com/handbook/notebooks","kind":"handbook","date":"2026-03-04"},
  "4ad11e33a3a14805": {"fact_id":"4ad11e33a3a14805","fact":"Nobody deploys to production after 2pm on Fridays.","subject":"topic:friday-deploys","predicate":"policy","value":"no deploys after 2pm on fridays","authority":1,"valid_from":"2026-09-10","valid_to":null,"stale":false,"current":true,"superseded_by":null,"passage_id":"handbook:handbook/engineering/deployments.md#0","passage":"We do not deploy to production after 2pm on Fridays.","removed":false,"doc_id":"handbook:handbook/engineering/deployments.md","title":"Deployments","url":"https://kestrel.example.com/handbook/engineering/deployments","kind":"handbook","date":"2026-09-10"},
  "1bd0880bc5f08e95": {"fact_id":"1bd0880bc5f08e95","fact":"Deploys are allowed on any day, including Fridays, with the on-call engineer's approval.","subject":"topic:friday-deploys","predicate":"policy","value":"deploys any day with on-call approval","authority":1,"valid_from":"2026-09-24","valid_to":null,"stale":false,"current":true,"superseded_by":null,"passage_id":"handbook:handbook/engineering/on-call.md#0","passage":"Deploys are fine on any day, Fridays included, as long as the on-call engineer approves.","removed":false,"doc_id":"handbook:handbook/engineering/on-call.md","title":"On-call","url":"https://kestrel.example.com/handbook/engineering/on-call","kind":"handbook","date":"2026-09-24"},
}

// For each fact, the ids `GET /facts/{id}` returns around it.
const LINKS: Record<string, Links> = {
  "001ecdf81aadc943": {"back":[],"forward":["a9065c5424adc158"],"restated":["e0d4ffe3be23d4ed"],"conflicts":[]},
  "8863b08c13c7bf1d": {"back":[],"forward":["c435f8f1fe35ff15"],"restated":["f1cb3e456f4285ce"],"conflicts":[]},
  "0055535e8c6b44ab": {"back":[],"forward":[],"restated":[],"conflicts":[]},
  "759c3056888e224e": {"back":[],"forward":[],"restated":[],"conflicts":[]},
  "a9065c5424adc158": {"back":["001ecdf81aadc943","e0d4ffe3be23d4ed"],"forward":[],"restated":["19234936365f266d"],"conflicts":[]},
  "c435f8f1fe35ff15": {"back":["8863b08c13c7bf1d","f1cb3e456f4285ce"],"forward":[],"restated":["823e44404f2db233"],"conflicts":[]},
  "19234936365f266d": {"back":[],"forward":[],"restated":["a9065c5424adc158"],"conflicts":[]},
  "eea254f55c41e53f": {"back":[],"forward":[],"restated":[],"conflicts":[]},
  "823e44404f2db233": {"back":[],"forward":[],"restated":["c435f8f1fe35ff15"],"conflicts":[]},
  "a25d40a8c566158c": {"back":[],"forward":[],"restated":[],"conflicts":[]},
  "e0d4ffe3be23d4ed": {"back":[],"forward":["a9065c5424adc158"],"restated":["001ecdf81aadc943"],"conflicts":[]},
  "af92f2388532d3c5": {"back":[],"forward":[],"restated":[],"conflicts":[]},
  "f1cb3e456f4285ce": {"back":[],"forward":["c435f8f1fe35ff15"],"restated":["8863b08c13c7bf1d"],"conflicts":[]},
  "4ad11e33a3a14805": {"back":[],"forward":[],"restated":[],"conflicts":["1bd0880bc5f08e95"]},
  "1bd0880bc5f08e95": {"back":[],"forward":[],"restated":[],"conflicts":["4ad11e33a3a14805"]},
}

const facts = (...ids: string[]) => ids.map((id) => FACTS[id])

type Step = { at: number; event: AskEvent }

type Fixture = {
  match: RegExp
  evidence: { facts: number; documents: number }
  claims: { text: string; fact_ids: string[] }[]
  /** Verdicts in the order their checks finish, with when (ms after the claims) each one lands. */
  verdicts: { index: number; after: number; verdict: VerdictName; sources: string[]; newer?: string[]; conflicting?: string[] }[]
}

const FIXTURES: Fixture[] = [
  {
    // Verified, with a sentence about the stale handbook page, and one sentence the check removes.
    match: /session replay|replay/i,
    evidence: { facts: 9, documents: 5 },
    claims: [
      { text: 'The Replay team owns session replay.', fact_ids: ['a9065c5424adc158', '19234936365f266d'] },
      { text: 'It moved from Product analytics to Replay on June 18, when the ownership map changed.', fact_ids: ['001ecdf81aadc943', 'a9065c5424adc158'] },
      { text: 'Mara Okafor leads the team.', fact_ids: ['eea254f55c41e53f'] },
      { text: 'The handbook page on session replay, last edited on August 20, still names Product analytics, so it is out of date.', fact_ids: ['e0d4ffe3be23d4ed', 'a9065c5424adc158'] },
      { text: 'She has led Replay since the team was formed.', fact_ids: ['eea254f55c41e53f'] },
    ],
    verdicts: [
      { index: 2, after: 900, verdict: 'verified', sources: ['eea254f55c41e53f'] },
      { index: 0, after: 1400, verdict: 'verified', sources: ['a9065c5424adc158', '19234936365f266d'] },
      { index: 4, after: 2000, verdict: 'unsupported', sources: ['eea254f55c41e53f'] },
      { index: 3, after: 2600, verdict: 'verified', sources: ['e0d4ffe3be23d4ed', 'a9065c5424adc158'] },
      { index: 1, after: 3200, verdict: 'verified', sources: ['001ecdf81aadc943', 'a9065c5424adc158'] },
    ],
  },
  {
    // Two current handbook pages disagree.
    match: /friday|deploy/i,
    evidence: { facts: 2, documents: 2 },
    claims: [
      { text: 'The Deployments page says nobody deploys to production after 2pm on Fridays.', fact_ids: ['4ad11e33a3a14805'] },
      { text: "The On-call page allows deploys on any day, Fridays included, with the on-call engineer's approval.", fact_ids: ['1bd0880bc5f08e95'] },
    ],
    verdicts: [
      { index: 1, after: 1100, verdict: 'disputed', sources: ['1bd0880bc5f08e95'], conflicting: ['4ad11e33a3a14805'] },
      { index: 0, after: 1700, verdict: 'disputed', sources: ['4ad11e33a3a14805'], conflicting: ['1bd0880bc5f08e95'] },
    ],
  },
  {
    // The drafter cited the old handbook page; the check finds the fact that replaced it.
    match: /notebook/i,
    evidence: { facts: 9, documents: 5 },
    claims: [
      { text: 'Notebooks are built and owned by Product analytics.', fact_ids: ['f1cb3e456f4285ce'] },
      { text: 'Jonas Weber leads the Data tools team.', fact_ids: ['a25d40a8c566158c'] },
      { text: 'The Data tools team page lists notebooks as its own.', fact_ids: ['823e44404f2db233'] },
    ],
    verdicts: [
      { index: 1, after: 900, verdict: 'verified', sources: ['a25d40a8c566158c'] },
      { index: 0, after: 1600, verdict: 'stale', sources: ['f1cb3e456f4285ce'], newer: ['c435f8f1fe35ff15'] },
      { index: 2, after: 2300, verdict: 'verified', sources: ['823e44404f2db233'] },
    ],
  },
]

const sleep = (ms: number, signal?: AbortSignal) =>
  new Promise<void>((resolve, reject) => {
    if (signal?.aborted) return reject(new DOMException('Aborted', 'AbortError'))
    const t = setTimeout(resolve, ms)
    signal?.addEventListener('abort', () => (clearTimeout(t), reject(new DOMException('Aborted', 'AbortError'))), { once: true })
  })

function script(question: string): Step[] {
  const fixture = FIXTURES.find((f) => f.match.test(question))
  if (!fixture) {
    // Billing has an owner and a lead but nothing written down: the drafter has nothing to say.
    if (/billing|refund|invoice/i.test(question)) {
      return [
        { at: 700, event: { type: 'evidence', facts: 1, documents: 1 } },
        { at: 1900, event: { type: 'empty', ask: [{ handle: 'name:ines-carvalho', name: 'Ines Carvalho', why: 'Leads Billing, which owns billing.' }] } },
      ]
    }
    return [
      { at: 700, event: { type: 'evidence', facts: 0, documents: 0 } },
      { at: 900, event: { type: 'empty', ask: [] } },
    ]
  }
  const drafted = 2100
  const steps: Step[] = [
    { at: 650, event: { type: 'evidence', ...fixture.evidence } },
    ...fixture.claims.map((c, index): Step => ({ at: drafted, event: { type: 'claim', index, ...c } })),
  ]
  const counts: Counts = { verified: 0, stale: 0, disputed: 0, unsupported: 0 }
  for (const v of fixture.verdicts) {
    counts[v.verdict] += 1
    steps.push({
      at: drafted + v.after,
      event: {
        type: 'verdict',
        index: v.index,
        verdict: v.verdict,
        sources: facts(...v.sources),
        newer: facts(...(v.newer ?? [])),
        conflicting: facts(...(v.conflicting ?? [])),
      },
    })
  }
  const last = Math.max(...fixture.verdicts.map((v) => v.after))
  steps.push({ at: drafted + last + 150, event: { type: 'done', counts } })
  return steps
}

export async function mockAsk(ws: string, question: string, onEvent: (e: AskEvent) => void, signal?: AbortSignal): Promise<void> {
  // Only the demo company is recorded; any other workspace answers as an empty one would.
  if (ws !== 'demo') {
    await sleep(400, signal)
    throw new Error('This workspace is not in the graph yet.')
  }
  let now = 0
  for (const step of script(question)) {
    await sleep(step.at - now, signal)
    now = step.at
    onEvent(step.event)
  }
}

const byDate = (xs: Source[]) => [...xs].sort((a, b) => (a.valid_from ?? '').localeCompare(b.valid_from ?? ''))

export function mockFact(id: string): FactDetail | null {
  const fact = FACTS[id]
  const links = LINKS[id]
  if (!fact || !links) return null
  return {
    fact,
    back: byDate(facts(...links.back)),
    forward: facts(...links.forward),
    restated: byDate(facts(...links.restated)),
    conflicts: byDate(facts(...links.conflicts)),
  }
}

export function mockStats(ws: string): Stats | null {
  if (ws !== 'demo') return null
  return {
    labels: { Team: 5, Area: 4, Person: 7, Document: 9, Passage: 10, Fact: 15, Topic: 2 },
    current_facts: 11,
    stale_facts: 1,
    stale_pages: 1,
    disputes: 1,
  }
}
