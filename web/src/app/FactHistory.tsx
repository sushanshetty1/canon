// A small knowledge timeline for one fact, in the hero's language: every fact on the same subject is a bar over
// the months it held. Replaced facts are grey and struck, out-of-date pages are proof red, disputes are amber.

import { motion, useReducedMotion } from 'motion/react'
import { useEffect, useState } from 'react'
import { fact as getFact, type FactDetail, type Source } from './api'
import { kindLabel, MONTH_NAMES, monthsOf, valueLabel } from './text'

type Tone = 'current' | 'ended' | 'stale' | 'disputed'

function toneOf(f: Source, detail: FactDetail): Tone {
  if (f.stale) return 'stale'
  if (!f.current) return 'ended'
  if (detail.conflicts.length && (f.fact_id === detail.fact.fact_id || detail.conflicts.some((c) => c.fact_id === f.fact_id))) return 'disputed'
  return 'current'
}

const barTone: Record<Tone, string> = {
  current: 'bg-cobalt text-paper',
  ended: 'text-faint',
  stale: 'bg-proof-soft text-proof shadow-[inset_0_0_0_1px_#f6b9b2]',
  disputed: 'bg-amber-soft text-amber shadow-[inset_0_0_0_1px_#ecc98a]',
}

const labelTone: Record<Tone, string> = { current: 'text-cobalt', ended: 'text-faint', stale: 'text-proof', disputed: 'text-amber' }

const ENDED_STYLE = {
  backgroundImage: 'repeating-linear-gradient(135deg, var(--paper-2) 0 6px, #e7e9ee 6px 7px)',
  boxShadow: 'inset 0 0 0 1px var(--line)',
}

function todayIso() {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

export function FactHistory({ ws, factId }: { ws: string; factId: string }) {
  const [state, setState] = useState<{ id: string; detail: FactDetail | null; failed: boolean } | null>(null)
  const reduce = !!useReducedMotion()

  useEffect(() => {
    const ctrl = new AbortController()
    getFact(ws, factId, ctrl.signal).then(
      (detail) => setState({ id: factId, detail, failed: false }),
      (e: Error) => e.name !== 'AbortError' && setState({ id: factId, detail: null, failed: true }),
    )
    return () => ctrl.abort()
  }, [ws, factId])

  const loading = !state || state.id !== factId
  if (!loading && state.failed) return <p className="text-[14px] text-faint">The history for this fact could not be loaded.</p>
  if (loading || !state.detail) {
    return (
      <div aria-hidden="true" className="space-y-2">
        {[0, 1, 2].map((i) => (
          <div key={i} className="h-7 animate-pulse rounded-[9px] bg-paper-2" style={{ width: `${80 - i * 18}%`, marginLeft: `${i * 12}%` }} />
        ))}
      </div>
    )
  }

  const detail = state.detail
  const seen = new Set<string>()
  const rows = [...detail.back, detail.fact, ...detail.restated, ...detail.forward, ...detail.conflicts]
    .filter((f) => f.valid_from && !seen.has(f.fact_id) && seen.add(f.fact_id))
    .sort((a, b) => (a.valid_from ?? '').localeCompare(b.valid_from ?? '') || (b.authority ?? 0) - (a.authority ?? 0))

  const today = todayIso()
  // At least six months on the axis, so a fact from last month reads as recent rather than filling the row.
  const start = Math.floor(Math.min(monthsOf(today) - 6, ...rows.map((f) => monthsOf(f.valid_from!))))
  const end = Math.max(monthsOf(today), ...rows.map((f) => monthsOf(f.valid_to ?? today))) + 0.35
  const span = Math.max(end - start, 1)
  const pct = (m: number) => `${((m - start) / span) * 100}%`
  const ticks = Array.from({ length: Math.floor(end - start) + 1 }, (_, i) => start + i).filter((m) => m < end - 0.3)

  return (
    <figure>
      <div className="grid grid-cols-[100px_minmax(0,1fr)] gap-x-3 sm:grid-cols-[112px_minmax(0,1fr)]">
        <div />
        <div className="relative h-5" aria-hidden="true">
          {ticks.map((m, i) => (
            <span key={m} className={`absolute top-0 text-[11.5px] font-medium text-faint ${i % 2 ? 'max-sm:hidden' : ''}`} style={{ left: pct(m) }}>
              {MONTH_NAMES[m % 12]}
            </span>
          ))}
        </div>
      </div>
      <div className="relative">
        <div className="pointer-events-none absolute inset-y-0 right-0 left-[112px] sm:left-[124px]" aria-hidden="true">
          {ticks.map((m) => (
            <span key={m} className="absolute inset-y-0 w-px bg-line" style={{ left: pct(m) }} />
          ))}
          <span className="absolute inset-y-0 w-[2px] -translate-x-1/2 bg-ink" style={{ left: pct(monthsOf(today)) }} />
        </div>
        <ul className="relative space-y-1.5">
          {rows.map((f, i) => {
            const tone = toneOf(f, detail)
            const from = monthsOf(f.valid_from!)
            const to = monthsOf(f.valid_to ?? today)
            const isThis = f.fact_id === detail.fact.fact_id
            const label = f.value_name || valueLabel(f.value) || f.fact || ''
            const struck = tone === 'ended' || tone === 'stale' ? 'line-through decoration-current/50' : ''
            // A short bar carries its label beside it, on the empty months before it.
            const outside = (to - from) / span < 0.3 && (from - start) / span > 0.3
            const source = f.title && f.title.length <= 16 ? f.title : kindLabel(f.kind)
            return (
              <li key={f.fact_id} className="grid grid-cols-[100px_minmax(0,1fr)] items-center gap-x-3 sm:grid-cols-[112px_minmax(0,1fr)]">
                <span className={`flex min-w-0 items-center gap-1.5 text-[12px] ${isThis ? 'font-semibold text-ink' : 'text-muted'}`} title={f.title ?? undefined}>
                  <span className={`size-1.5 shrink-0 rounded-full ${isThis ? 'bg-ink' : 'bg-transparent'}`} aria-hidden="true" />
                  <span className="truncate">{source}</span>
                </span>
                <span className="relative block h-7">
                  {outside && (
                    <span
                      className={`absolute inset-y-0 flex items-center justify-end pr-2 text-[12.5px] font-semibold ${labelTone[tone]}`}
                      style={{ left: 0, width: pct(from) }}
                    >
                      <span className={`truncate ${struck}`}>{label}</span>
                    </span>
                  )}
                  <motion.span
                    className={`absolute inset-y-0 flex items-center overflow-hidden rounded-[9px] px-2.5 ${barTone[tone]}`}
                    style={{ left: `calc(${pct(from)} + 2px)`, width: `max(calc(${pct(to)} - ${pct(from)} - 4px), 10px)`, ...(tone === 'ended' ? ENDED_STYLE : {}) }}
                    initial={reduce ? false : { clipPath: 'inset(0 100% 0 0 round 9px)' }}
                    animate={{ clipPath: 'inset(0 0% 0 0 round 9px)' }}
                    transition={{ duration: reduce ? 0 : 0.7, delay: reduce ? 0 : 0.1 + i * 0.12, ease: [0.22, 1, 0.36, 1] }}
                  >
                    {!outside && <span className={`truncate text-[12.5px] font-semibold ${struck}`}>{label}</span>}
                  </motion.span>
                  <span className="sr-only">
                    {f.fact} {kindLabel(f.kind)}, {f.title}, from {f.valid_from}
                    {f.valid_to ? ` to ${f.valid_to}` : ''}. {tone === 'stale' ? 'Out of date.' : tone === 'ended' ? 'Replaced.' : tone === 'disputed' ? 'Disputed.' : 'Current.'}
                  </span>
                </span>
              </li>
            )
          })}
        </ul>
      </div>
    </figure>
  )
}
