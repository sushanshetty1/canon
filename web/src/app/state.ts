// What the Ask screen knows about one question, built up from the event stream.

import type { AskEvent, Closest, Counts, Person, Source, VerdictName } from './api'

export type Sentence = {
  index: number
  text: string
  factIds: string[]
  verdict: VerdictName | null
  sources: Source[]
  newer: Source[]
  conflicting: Source[]
  error?: string
}

export type Phase = 'idle' | 'asking' | 'done' | 'empty' | 'error'

export type AskState = {
  phase: Phase
  question: string
  evidence: { facts: number; documents: number } | null
  sentences: Sentence[]
  people: Person[]
  closest: Closest[]
  counts: Counts | null
  error: string | null
}

export type Action = { type: 'start'; question: string } | { type: 'event'; event: AskEvent } | { type: 'fail'; message: string } | { type: 'reset' }

export const initial: AskState = { phase: 'idle', question: '', evidence: null, sentences: [], people: [], closest: [], counts: null, error: null }

function tally(sentences: Sentence[]): Counts {
  const counts: Counts = { verified: 0, stale: 0, disputed: 0, unsupported: 0 }
  for (const s of sentences) if (s.verdict) counts[s.verdict] += 1
  return counts
}

export function reduce(state: AskState, action: Action): AskState {
  switch (action.type) {
    case 'reset':
      return initial
    case 'start':
      return { ...initial, phase: 'asking', question: action.question }
    case 'fail':
      return { ...state, phase: 'error', error: action.message }
    case 'event': {
      const e = action.event
      switch (e.type) {
        case 'evidence':
          return { ...state, evidence: { facts: e.facts, documents: e.documents } }
        case 'claim': {
          const sentence: Sentence = { index: e.index, text: e.text, factIds: e.fact_ids ?? [], verdict: null, sources: [], newer: [], conflicting: [] }
          const rest = state.sentences.filter((s) => s.index !== e.index)
          return { ...state, sentences: [...rest, sentence].sort((a, b) => a.index - b.index) }
        }
        case 'verdict': {
          const sentences = state.sentences.map((s) =>
            s.index === e.index
              ? { ...s, verdict: e.verdict, sources: e.sources ?? [], newer: e.newer ?? [], conflicting: e.conflicting ?? [], error: e.error }
              : s,
          )
          return { ...state, sentences }
        }
        case 'done':
          return { ...state, phase: 'done', counts: e.counts ?? tally(state.sentences) }
        case 'empty':
          return { ...state, phase: 'empty', people: e.ask ?? [], closest: e.passages ?? [] }
        case 'error':
          return { ...state, phase: 'error', error: e.message }
      }
      return state
    }
  }
}

/** The fact a sentence's history is drawn around: the out-of-date one for a stale sentence, else the first current one. */
export function focusFact(s: Sentence): Source | null {
  if (s.verdict === 'stale') return s.sources.find((f) => !f.current) ?? s.sources[0] ?? null
  return s.sources.find((f) => f.current) ?? s.sources[0] ?? null
}
