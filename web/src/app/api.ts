// A typed client for the Canon API, and the reader for the Ask event stream.
// With `?mock=1` in the URL, Ask plays a recorded stream from `mock.ts` instead of calling the model.

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

  // Server-sent events: blocks separated by a blank line, each with `data:` lines.
  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader()
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

export async function stats(ws: string, signal?: AbortSignal): Promise<Stats> {
  try {
    return await getJson<Stats>(`/api/w/${encodeURIComponent(ws)}/stats`, signal)
  } catch (e) {
    const recorded = isMock() ? mockStats(ws) : null
    if (recorded && (e as Error).name !== 'AbortError') return recorded
    throw e
  }
}
