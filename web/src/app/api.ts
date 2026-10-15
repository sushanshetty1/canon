// A typed client for the Canon API, and the reader for the Ask event stream.
// With `?mock=1` in the URL, Ask plays a recorded stream from `mock.ts` instead of calling the model.

import type { Job } from './account'
import { mockAsk, mockFact, mockStats } from './mock'

export type VerdictName = 'verified' | 'stale' | 'disputed' | 'unsupported'

/** A fact as the API shows it: the fact, its passage and its document (see `server/src/canon/graph/read.py`). */
export type Source = {
  fact_id: string
  fact: string | null
  subject: string | null
  predicate: string | null
  value: string | null
  value_name?: string | null
  authority: number | null
  valid_from: string | null
  valid_to: string | null
  stale: boolean
  current: boolean
  superseded_by: string | null
  passage_id: string | null
  passage: string | null
  removed: boolean
  doc_id: string | null
  title: string | null
  url: string | null
  kind: string | null
  date: string | null
}

export type Person = { handle: string; name: string; why: string }

export type Counts = Record<VerdictName, number>

export type AskEvent =
  | { type: 'evidence'; facts: number; documents: number }
  | { type: 'claim'; index: number; text: string; fact_ids: string[] }
  | { type: 'verdict'; index: number; verdict: VerdictName; sources: Source[]; newer: Source[]; conflicting: Source[]; error?: string }
  | { type: 'done'; counts: Counts }
  | { type: 'empty'; ask: Person[] }
  | { type: 'error'; message: string }

export type FactDetail = { fact: Source; back: Source[]; forward: Source[]; restated: Source[]; conflicts: Source[] }

export type Stats = {
  labels: Record<string, number>
  current_facts: number
  stale_facts: number
  stale_pages: number
  disputes: number
}

export function isMock(): boolean {
  try {
    return new URLSearchParams(window.location.search).get('mock') === '1'
  } catch {
    return false
  }
}

/** A calm sentence for anything that went wrong on the way to the server. */
async function failure(res: Response): Promise<Error> {
  try {
    const body = await res.json()
    if (res.status === 404 && body?.detail === 'No such workspace.') return new Error('This workspace is not in the graph yet.')
    if (typeof body?.detail === 'string') return new Error(body.detail)
  } catch {
    // not JSON
  }
  if (res.status === 404) return new Error('This workspace has nothing in it yet.')
  return new Error('Canon could not be reached. Try again in a moment.')
}

async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  let res: Response
  try {
    res = await fetch(path, { signal, headers: { accept: 'application/json' } })
  } catch (e) {
    if ((e as Error).name === 'AbortError') throw e
    throw new Error('Canon could not be reached. Try again in a moment.')
  }
  if (!res.ok) throw await failure(res)
  return (await res.json()) as T
}

/** Ask a question; `onEvent` gets every event as it arrives. Resolves when the stream ends. */
export async function ask(ws: string, question: string, onEvent: (e: AskEvent) => void, signal?: AbortSignal): Promise<void> {
  if (isMock()) return mockAsk(ws, question, onEvent, signal)

  let res: Response
  try {
    res = await fetch(`/api/w/${encodeURIComponent(ws)}/ask`, {
      method: 'POST',
      headers: { 'content-type': 'application/json', accept: 'text/event-stream' },
      body: JSON.stringify({ question }),
      signal,
    })
  } catch (e) {
    if ((e as Error).name === 'AbortError') throw e
    throw new Error('Canon could not be reached. Try again in a moment.')
  }
  if (!res.ok || !res.body) throw await failure(res)
  return readEvents(res.body, onEvent)
}

/** Server-sent events: blocks separated by a blank line, each with `data:` lines. Ask and the brief share them. */
async function readEvents(body: ReadableStream<BufferSource>, onEvent: (e: AskEvent) => void): Promise<void> {
  const reader = body.pipeThrough(new TextDecoderStream()).getReader()
  let buffer = ''
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += value
    let end: number
    while ((end = buffer.search(/\r?\n\r?\n/)) !== -1) {
      const block = buffer.slice(0, end)
      buffer = buffer.slice(end).replace(/^\r?\n\r?\n/, '')
      const data = block
        .split(/\r?\n/)
        .filter((line) => line.startsWith('data:'))
        .map((line) => line.slice(5).trimStart())
        .join('\n')
      if (data) onEvent(JSON.parse(data) as AskEvent)
    }
  }
}

export async function fact(ws: string, id: string, signal?: AbortSignal): Promise<FactDetail> {
  try {
    return await getJson<FactDetail>(`/api/w/${encodeURIComponent(ws)}/facts/${encodeURIComponent(id)}`, signal)
  } catch (e) {
    // The recording carries the demo company's facts, so the mock works without a server.
    const recorded = isMock() ? mockFact(id) : null
    if (recorded && (e as Error).name !== 'AbortError') return recorded
    throw e
  }
}

// --- Who knows and bus factor ----------------------------------------------------------------------

export type Evidence = { decided: number; authored: number; reviewed: number; commented: number; member: boolean }

export type Knower = { handle: string; name: string; score: number; evidence: Evidence; depends: boolean }

export type Owner = { slug: string; name: string }

export type AreaSummary = {
  slug: string
  name: string
  owners: Owner[]
  bus_factor: number
  knowers: number
  evidence: number
  depends_on: Knower[]
  people: Knower[]
  others: number
}

export type Act = { rel: 'decided' | 'authored' | 'reviewed' | 'commented'; at: string | null }

export type EvidenceDoc = { id: string; title: string | null; url: string | null; kind: string | null; date: string | null; acts: Act[] }

export type AreaPerson = Knower & { role: string | null; teams: string[]; docs: EvidenceDoc[] }

export type AreaPeople = {
  area: { slug: string; name: string; owners: Owner[]; bus_factor: number; knowers: number }
  people: AreaPerson[]
  total: number
}

export type PersonAreas = {
  person: { handle: string; name: string; role: string | null; teams: string[] }
  areas: { slug: string; name: string; score: number; evidence: Evidence; depends: boolean; bus_factor: number }[]
}

const inWs = (ws: string) => `/api/w/${encodeURIComponent(ws)}`

export const areas = (ws: string, signal?: AbortSignal) => getJson<{ areas: AreaSummary[]; computed: boolean }>(`${inWs(ws)}/areas`, signal)

export const areaPeople = (ws: string, slug: string, signal?: AbortSignal) =>
  getJson<AreaPeople>(`${inWs(ws)}/areas/${encodeURIComponent(slug)}/people`, signal)

export const personAreas = (ws: string, handle: string, signal?: AbortSignal) =>
  getJson<PersonAreas>(`${inWs(ws)}/people/${encodeURIComponent(handle)}`, signal)

export async function stats(ws: string, signal?: AbortSignal): Promise<Stats> {
  try {
    return await getJson<Stats>(`/api/w/${encodeURIComponent(ws)}/stats`, signal)
  } catch (e) {
    const recorded = isMock() ? mockStats(ws) : null
    if (recorded && (e as Error).name !== 'AbortError') return recorded
    throw e
  }
}

// --- The fix queue -----------------------------------------------------------------------------------

export type FixStatus = 'open' | 'approved' | 'filed' | 'dismissed' | 'resolved'
export type FixFilter = 'open' | 'filed' | 'dismissed'

/** Who a fix goes to: the owning team, its lead, or the page's last author. */
export type Routed = { kind: 'team' | 'person'; key: string; name: string; role: 'owner' | 'lead' | 'author'; team?: string }

export type Fix = {
  id: string
  status: FixStatus
  old: string | null
  new: string | null
  checked: string[] | null
  draft_error: string | null
  reason: string | null
  created_at: string | null
  resolved_at: string | null
  page: { id: string | null; title: string | null; url: string | null; kind: string | null; updated_at: string | null; author: string | null }
  passage: { id: string | null; text: string | null }
  stale: Source[]
  evidence: Source[]
  routed: Routed[]
  approved_by: string | null
  issue: { repo: string | null; url: string | null; title: string | null; body: string | null; dry_run: boolean; error: string | null; filed_at: string | null }
  dismissed: { by: string | null; at: string | null; reason: string | null }
}

export type FixList = { fixes: Fix[]; counts: Record<FixStatus, number>; dry_run: boolean }

async function postJson<T>(path: string, body: unknown): Promise<T> {
  let res: Response
  try {
    res = await fetch(path, { method: 'POST', headers: { 'content-type': 'application/json', accept: 'application/json' }, body: JSON.stringify(body) })
  } catch {
    throw new Error('Canon could not be reached. Try again in a moment.')
  }
  if (!res.ok) throw await failure(res)
  return (await res.json()) as T
}

const fixPath = (ws: string, rest = '') => `/api/w/${encodeURIComponent(ws)}/fixes${rest}`

export const fixes = (ws: string, status: FixFilter, signal?: AbortSignal) => getJson<FixList>(fixPath(ws, `?status=${status}`), signal)

export const approveFix = (ws: string, id: string, repo: string) => postJson<Fix>(fixPath(ws, `/${encodeURIComponent(id)}/approve`), { repo })

export const dismissFix = (ws: string, id: string, reason: string) => postJson<Fix>(fixPath(ws, `/${encodeURIComponent(id)}/dismiss`), { reason })

// --- Decisions and catch me up ---------------------------------------------------------------------

export type DecisionStatus = 'proposed' | 'accepted' | 'withdrawn' | 'rejected' | 'retired' | 'superseded'

export type DecisionLink = {
  id: string
  reason: string | null
  by: 'reference' | 'model' | null
  title?: string | null
  status?: DecisionStatus | null
  decided_at?: string | null
}

/** A decision as `GET /api/w/{ws}/decisions` lists it (see `server/src/canon/decisions/read.py`). */
export type Decision = {
  id: string
  title: string
  status: DecisionStatus
  proposed_at: string | null
  decided_at: string | null
  replaced_at: string | null
  closed_at?: string | null
  summary: string
  url: string | null
  doc_id: string | null
  author: string | null
  people: { handle: string; name: string; role: string | null; how: 'approved' | 'merged'; at: string | null }[]
  areas: { slug: string; name: string }[]
  pulls: { id: string; title: string; url: string; merged_at: string | null; author: string | null; how: 'link' | 'title' }[]
  superseded_by: DecisionLink[]
  supersedes: DecisionLink[]
}

export type DecisionDetail = Decision & { facts: Source[]; passages: number }

export type Decisions = { today: string; counts: Partial<Record<DecisionStatus, number>>; decisions: Decision[] }

export type ChangeKind = 'ownership' | 'decision' | 'page' | 'stale' | 'dispute'

export type Change = {
  id: string
  kind: ChangeKind
  date: string
  title: string
  detail: string
  fact_ids: string[]
  sources: { doc_id: string; title: string | null; url: string | null; kind: string | null; date: string | null }[]
  area?: string
  areas?: string[]
  decision_id?: string
}

export type Changes = { since: string; today: string; counts: Record<ChangeKind, number>; changes: Change[] }

export const decisions = (ws: string, signal?: AbortSignal) => getJson<Decisions>(`/api/w/${encodeURIComponent(ws)}/decisions`, signal)

export const decision = (ws: string, id: string, signal?: AbortSignal) =>
  getJson<DecisionDetail>(`/api/w/${encodeURIComponent(ws)}/decisions/${encodeURIComponent(id)}`, signal)

export const changes = (ws: string, since: string, signal?: AbortSignal) =>
  getJson<Changes>(`/api/w/${encodeURIComponent(ws)}/changes?since=${encodeURIComponent(since)}`, signal)

/** The catch-up brief: the same events as Ask, so the answer reads the same way. */
export async function brief(ws: string, since: string, onEvent: (e: AskEvent) => void, signal?: AbortSignal): Promise<void> {
  let res: Response
  try {
    res = await fetch(`/api/w/${encodeURIComponent(ws)}/changes/brief?since=${encodeURIComponent(since)}`, {
      headers: { accept: 'text/event-stream' },
      signal,
    })
  } catch (e) {
    if ((e as Error).name === 'AbortError') throw e
    throw new Error('Canon could not be reached. Try again in a moment.')
  }
  if (!res.ok || !res.body) throw await failure(res)
  return readEvents(res.body, onEvent)
}

// --- Sources ---------------------------------------------------------------------------------------

export type SourceKey = 'docs' | 'tickets' | 'chats' | 'decisions' | 'code_owners' | 'people'

export type SourceKind = {
  kind: string
  documents: number
  passages: number
  facts: number
  current_facts: number
  speakers: number
  last_read: string | null
  newest: string | null
}

/** One kind of source as `GET /api/w/{ws}/sources` counts it (see `server/src/canon/sources/summary.py`). */
export type SourceFamily = {
  key: SourceKey
  documents: number
  passages: number
  facts: number
  current_facts: number
  last_read: string | null
  newest: string | null
  kinds: SourceKind[]
  decisions?: number
  statuses?: Record<string, number>
  areas?: number
  people?: number
  teams?: number
  speakers?: number
}

/** A place the workspace reads from: its GitHub repository, an uploaded export, a connected tool. */
export type Connection = {
  id: string
  kind: string
  label: string
  status: string | null
  last_synced_at: string | null
  error: string | null
  config: Record<string, string | number | boolean>
}

export type SourcesView = {
  families: SourceFamily[]
  connections: Connection[]
  repo: { repo: string; synced_at: string | null } | null
  totals: { documents: number; facts: number }
  can_upload: boolean
}

export const sources = (ws: string, signal?: AbortSignal) => getJson<SourcesView>(`${inWs(ws)}/sources`, signal)

export type UploadKind = 'slack' | 'pages'

/** Send an export (a zip) to be read into the workspace. Resolves with the job that reads it. */
export async function uploadExport(ws: string, kind: UploadKind, file: File): Promise<{ job: Job }> {
  const body = new FormData()
  body.set('kind', kind)
  body.set('file', file)
  let res: Response
  try {
    res = await fetch(`${inWs(ws)}/uploads`, { method: 'POST', body, headers: { accept: 'application/json' } })
  } catch {
    throw new Error('Canon could not be reached. Try again in a moment.')
  }
  if (!res.ok) throw await failure(res)
  return (await res.json()) as { job: Job }
}
