// Catch me up: drag the "since you left" edge back along a year of the company, see every change in that range
// as a mark in its lane, and read a brief of it in which each sentence is checked against the graph, the same
// way Ask checks an answer.

import { ArrowUpRight, CaretDown } from '@phosphor-icons/react'
import { AnimatePresence, motion, useReducedMotion } from 'motion/react'
import { useCallback, useEffect, useMemo, useReducer, useRef, useState, type KeyboardEvent, type PointerEvent } from 'react'
import { brief as getBrief, changes as getChanges, isMock, type AskEvent, type Change, type ChangeKind, type Changes } from './api'
import { Answer, ease, Removed, Tally } from './Answer'
import { Sheet, useWide } from './Sheet'
import { SourcePanel } from './SourcePanel'
import { initial, reduce as reduceAsk } from './state'
import { formatDate, kindLabel, MONTH_NAMES, plural } from './text'
import type { Workspace } from './workspaces'

const DAY = 86_400_000
const dayOf = (iso: string) => {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso)
  return m ? Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3])) / DAY : 0
}
const isoOf = (day: number) => new Date(Math.round(day) * DAY).toISOString().slice(0, 10)
const todayIso = () => {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

const LANES: { kind: ChangeKind; label: string; short: string; dot: string; text: string }[] = [
  { kind: 'ownership', label: 'Owners', short: 'Owners', dot: 'bg-cobalt', text: 'text-cobalt' },
  { kind: 'decision', label: 'Decisions', short: 'Decisions', dot: 'bg-ink', text: 'text-ink' },
  { kind: 'stale', label: 'Out of date', short: 'Out of date', dot: 'bg-proof', text: 'text-proof' },
  { kind: 'dispute', label: 'Disputes', short: 'Disputes', dot: 'bg-amber', text: 'text-amber' },
  { kind: 'page', label: 'Pages changed', short: 'Pages', dot: 'bg-muted', text: 'text-muted' },
]

const MONTHS_BACK = 12

/** Where the range starts when the screen opens: `?since=` if given, else the first day of last month. */
function startingSince(today: string): string {
  try {
    const asked = new URLSearchParams(window.location.search).get('since')
    if (asked && /^\d{4}-\d{2}-\d{2}$/.test(asked) && asked < today) return asked
  } catch {
    // no query
  }
  const [y, m] = today.split('-').map(Number)
  return m === 1 ? `${y - 1}-12-01` : `${y}-${String(m - 1).padStart(2, '0')}-01`
}

function rememberSince(since: string) {
  try {
    const url = new URL(window.location.href)
    url.searchParams.set('since', since)
    window.history.replaceState(null, '', url)
  } catch {
    // the address bar is a convenience
  }
}

// ----- the range -----------------------------------------------------------------------------------------------------

function Range({ data, since, onSince, onCommit }: { data: Changes; since: string; onSince: (d: string) => void; onCommit: (d: string) => void }) {
  const track = useRef<HTMLDivElement>(null)
  const reduce = !!useReducedMotion()
  const [dragging, setDragging] = useState(false)
  const wide = useWide()
  const today = data.today
  // A phone shows the last half year; a wide screen the whole year.
  const start = Math.max(dayOf(data.since), wide ? 0 : dayOf(today) - 183)
  const end = dayOf(today) + 12
  const pct = (iso: string) => Math.max(0, ((dayOf(iso) - start) / (end - start)) * 100)
  const last = dayOf(today) - 1
  const latest = useRef(since)
  latest.current = since

  const fromX = (clientX: number) => {
    const rect = track.current!.getBoundingClientRect()
    const day = start + ((clientX - rect.left) / rect.width) * (end - start)
    return isoOf(Math.min(Math.max(Math.round(day), start), last))
  }
  const down = (e: PointerEvent<HTMLDivElement>) => {
    if (e.button !== 0) return
    e.currentTarget.setPointerCapture(e.pointerId)
    setDragging(true)
    onSince(fromX(e.clientX))
  }
  const move = (e: PointerEvent<HTMLDivElement>) => dragging && onSince(fromX(e.clientX))
  const up = () => {
    if (!dragging) return
    setDragging(false)
    onCommit(latest.current)
  }
  const key = (e: KeyboardEvent) => {
    const step = { ArrowLeft: -1, ArrowRight: 1, PageUp: -7, PageDown: 7, ArrowDown: -1, ArrowUp: 1 }[e.key]
    let next: number | null = step ? dayOf(since) + step : null
    if (e.key === 'Home') next = start
    if (e.key === 'End') next = last
    if (next === null) return
    e.preventDefault()
    const iso = isoOf(Math.min(Math.max(next, start), last))
    onSince(iso)
    onCommit(iso)
  }

  // Month ticks along the year.
  const months: { iso: string; label: string }[] = []
  {
    const s = new Date(start * DAY)
    for (let y = s.getUTCFullYear(), m = s.getUTCMonth() + 1; ; m += 1) {
      if (m > 11) {
        y += 1
        m = 0
      }
      const iso = `${y}-${String(m + 1).padStart(2, '0')}-01`
      if (dayOf(iso) >= end) break
      if (dayOf(iso) >= start) months.push({ iso, label: m === 0 && wide ? `${MONTH_NAMES[m]} ${y}` : MONTH_NAMES[m] })
    }
  }

  const inRange = (c: Change) => c.date > since
  const groups = LANES.map((lane) => {
    const byDay = new Map<string, Change[]>()
    for (const c of data.changes) if (c.kind === lane.kind && dayOf(c.date) >= start) byDay.set(c.date, [...(byDay.get(c.date) ?? []), c])
    return { lane, days: [...byDay.entries()], count: data.changes.filter((c) => c.kind === lane.kind && inRange(c)).length }
  })

  return (
    <div className="select-none">
      <div className="grid grid-cols-[88px_minmax(0,1fr)] gap-x-3 sm:grid-cols-[136px_minmax(0,1fr)] sm:gap-x-5">
        <div />
        {/* Months, the handle's date, and today */}
        <div className="relative h-14">
          {months.map((m, i) => (
            <span key={m.iso} className={`absolute bottom-1 pl-1.5 text-[12.5px] font-medium whitespace-nowrap text-faint ${i % 2 && months.length > 7 ? 'max-sm:hidden' : ''}`} style={{ left: `${pct(m.iso)}%` }}>
              {m.label}
            </span>
          ))}
          <motion.span
            className="absolute top-0 z-10 -translate-x-1/2 rounded-full bg-cobalt px-3 py-1 text-[12.5px] font-semibold whitespace-nowrap text-paper shadow-[0_8px_20px_-10px_rgb(44_70_232/0.8)]"
            style={{ left: `${pct(since)}%` }}
            animate={{ scale: dragging ? 1.06 : 1 }}
            transition={{ duration: 0.15 }}
          >
            Since {formatDate(since, { year: false })}
          </motion.span>
          <span className={`absolute top-0 -translate-x-1/2 rounded-full bg-ink px-2.5 py-1 text-[12px] font-semibold text-paper max-sm:hidden ${pct(today) - pct(since) < 9 ? 'hidden' : ''}`} style={{ left: `${pct(today)}%` }}>
            Today
          </span>
        </div>
      </div>

      <div className="relative grid grid-cols-[88px_minmax(0,1fr)] gap-x-3 sm:grid-cols-[136px_minmax(0,1fr)] sm:gap-x-5">
        <ul className="contents">
          {groups.map(({ lane, count }) => (
            <li key={lane.kind} className="col-start-1 flex h-12 items-center justify-between gap-2 border-t border-line">
              <span className={`truncate text-[13.5px] font-semibold sm:text-[14.5px] ${count ? 'text-ink' : 'text-faint'}`}>{wide ? lane.label : lane.short}</span>
              <span className={`text-[13px] tabular-nums ${count ? lane.text : 'text-faint'}`}>{count}</span>
            </li>
          ))}
        </ul>

        {/* The track: drag anywhere to move the edge of the range. */}
        <div
          ref={track}
          className={`relative col-start-2 row-span-5 row-start-1 touch-none ${dragging ? 'cursor-grabbing' : 'cursor-pointer'}`}
          onPointerDown={down}
          onPointerMove={move}
          onPointerUp={up}
          onPointerCancel={up}
        >
          {months.map((m) => (
            <span key={m.iso} className="pointer-events-none absolute inset-y-0 w-px bg-line" style={{ left: `${pct(m.iso)}%` }} />
          ))}
          {/* Since you left: the range is washed in cobalt. */}
          <motion.span
            className="pointer-events-none absolute inset-y-0 rounded-r-[6px] bg-cobalt-soft/70"
            style={{ left: `${pct(since)}%`, right: `${100 - pct(today)}%` }}
            initial={reduce ? false : { opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.4 }}
          />
          {groups.map(({ lane, days }, row) => (
            <div key={lane.kind} className="pointer-events-none absolute inset-x-0 h-12 border-t border-line" style={{ top: row * 48 }}>
              {days.map(([date, items]) => {
                const on = date > since
                const size = Math.min(7 + Math.sqrt(items.length) * 3.2, 18)
                return (
                  <span
                    key={date}
                    title={`${formatDate(date)}: ${items.map((c) => c.title).join('; ')}`}
                    className={`absolute top-1/2 -translate-x-1/2 -translate-y-1/2 rounded-full transition-[background-color,box-shadow] duration-300 ${on ? `${lane.dot} shadow-[0_0_0_2px_var(--paper)]` : 'bg-line-strong'}`}
                    style={{ left: `${pct(date)}%`, width: size, height: size }}
                  />
                )
              })}
            </div>
          ))}
          <span className="pointer-events-none absolute inset-y-0 w-[2px] -translate-x-1/2 bg-ink" style={{ left: `${pct(today)}%` }} />
          {/* The edge: a line with a grip, which also takes the keyboard. */}
          <div
            role="slider"
            tabIndex={0}
            aria-label="Since you left"
            aria-valuemin={start}
            aria-valuemax={last}
            aria-valuenow={dayOf(since)}
            aria-valuetext={formatDate(since)}
            onKeyDown={key}
            className="group absolute -top-3 bottom-0 z-10 w-6 -translate-x-1/2 cursor-grab outline-none active:cursor-grabbing"
            style={{ left: `${pct(since)}%` }}
          >
            <span className="absolute inset-y-0 left-1/2 w-[2px] -translate-x-1/2 bg-cobalt" />
            <span className="absolute top-1/2 left-1/2 grid h-9 w-4 -translate-x-1/2 -translate-y-1/2 place-items-center rounded-full bg-cobalt shadow-[0_6px_16px_-6px_rgb(44_70_232/0.9)] ring-4 ring-transparent transition-shadow group-focus-visible:ring-cobalt/30">
              <span className="h-3.5 w-[5px] border-x-[1.5px] border-paper/80" />
            </span>
          </div>
        </div>
      </div>
    </div>
  )
}

// ----- the changes ---------------------------------------------------------------------------------------------------

function ChangeList({ items }: { items: Change[] }) {
  const [open, setOpen] = useState<Record<string, boolean>>({})
  const groups = LANES.map((lane) => ({ lane, items: items.filter((c) => c.kind === lane.kind) })).filter((g) => g.items.length)
  return (
    <div className="space-y-8">
      {groups.map(({ lane, items }) => {
        const all = open[lane.kind]
        const shown = all ? items : items.slice(0, 4)
        return (
          <section key={lane.kind} aria-labelledby={`lane-${lane.kind}`}>
            <h3 id={`lane-${lane.kind}`} className="flex items-center gap-2.5 text-[14.5px] font-semibold text-ink">
              <span className={`size-2.5 rounded-full ${lane.dot}`} aria-hidden="true" />
              {lane.label}
              <span className="font-normal text-faint tabular-nums">{items.length}</span>
            </h3>
            <ul className="mt-3 space-y-3.5">
              {shown.map((c) => {
                const source = c.sources[0]
                return (
                  <li key={c.id} className="text-[15px] leading-snug">
                    <p className="text-ink">{c.title}</p>
                    {c.detail && c.kind !== 'dispute' && <p className="mt-0.5 text-[13.5px] text-muted">{c.detail}</p>}
                    <p className="mt-1 text-[13px] text-muted">
                      {formatDate(c.date)}
                      {source?.url && (
                        <>
                          {' · '}
                          <a href={source.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-0.5 text-cobalt hover:text-cobalt-deep">
                            {source.kind === 'ownership_map' ? 'Ownership map' : source.kind === 'rfc' ? 'RFC' : kindLabel(source.kind)}
                            <ArrowUpRight size={11} weight="bold" />
                          </a>
                        </>
                      )}
                    </p>
                  </li>
                )
              })}
            </ul>
            {items.length > 4 && (
              <button
                type="button"
                aria-expanded={!!all}
                onClick={() => setOpen((o) => ({ ...o, [lane.kind]: !all }))}
                className="mt-3 inline-flex items-center gap-1 text-[14px] font-semibold text-muted hover:text-ink"
              >
                {all ? 'Show fewer' : `Show all ${items.length}`}
                <CaretDown size={12} weight="bold" className={`transition-transform ${all ? 'rotate-180' : ''}`} />
              </button>
            )}
          </section>
        )
      })}
    </div>
  )
}

// ----- the brief -----------------------------------------------------------------------------------------------------

function BriefProgress({ phase, facts, checked, total }: { phase: string; facts: number | null; checked: number; total: number }) {
  const reduce = useReducedMotion()
  const finished = phase !== 'asking'
  const value = finished ? 1 : facts === null ? 0.1 : !total ? 0.32 : 0.4 + (0.6 * checked) / total
  const label = facts === null ? 'Reading the changes' : finished ? `Written from ${plural(facts, 'fact')}` : total ? `Checking ${checked} of ${total} sentences` : `Drafting from ${plural(facts, 'fact')}`
  return (
    <div>
      <p className="text-[14px] text-muted">{label}</p>
      <div className="relative mt-2.5 h-px overflow-hidden bg-line" aria-hidden="true">
        <motion.div
          className="absolute inset-y-0 left-0 w-full origin-left"
          initial={reduce ? false : { scaleX: 0 }}
          animate={{ scaleX: value, backgroundColor: finished ? 'var(--line-strong)' : 'var(--ink)' }}
          transition={{ duration: reduce ? 0 : 0.6, ease }}
        />
      </div>
    </div>
  )
}

// ----- the screen --------------------------------------------------------------------------------------------------

export function CatchUp({ ws }: { ws: Workspace }) {
  const reduce = useReducedMotion()
  const [today] = useState(todayIso)
  const [since, setSince] = useState(() => startingSince(todayIso()))
  const [briefSince, setBriefSince] = useState(since)
  const [data, setData] = useState<{ value: Changes | null; error: string | null }>({ value: null, error: null })
  const [attempt, setAttempt] = useState(0)
  const [state, dispatch] = useReducer(reduceAsk, initial)
  const [selected, setSelected] = useState<number | null>(null)
  const [announcement, setAnnouncement] = useState('')
  const run = useRef<AbortController | null>(null)

  const yearAgo = useMemo(() => {
    const [y, m, d] = today.split('-').map(Number)
    return `${y - Math.floor(MONTHS_BACK / 12)}-${String(m).padStart(2, '0')}-${String(d).padStart(2, '0')}`
  }, [today])

  useEffect(() => {
    const ctrl = new AbortController()
    getChanges(ws.slug, yearAgo, ctrl.signal).then(
      (value) => setData({ value, error: null }),
      (e: Error) => e.name !== 'AbortError' && setData({ value: null, error: e.message }),
    )
    return () => ctrl.abort()
  }, [ws.slug, yearAgo, attempt])

  const write = useCallback(
    (from: string) => {
      run.current?.abort()
      const ctrl = new AbortController()
      run.current = ctrl
      setSelected(null)
      dispatch({ type: 'start', question: from })
      setAnnouncement(`Writing the brief since ${formatDate(from)}.`)
      const onEvent = (event: AskEvent) => {
        if (ctrl.signal.aborted) return
        dispatch({ type: 'event', event })
        if (event.type === 'done') setAnnouncement('The brief is checked.')
      }
      getBrief(ws.slug, from, onEvent, ctrl.signal).catch((e: Error) => {
        if (e.name === 'AbortError') return
        dispatch({ type: 'fail', message: e.message })
      })
    },
    [ws.slug],
  )

  // The brief follows the range, once it settles.
  useEffect(() => {
    if (!data.value || isMock()) return
    const t = window.setTimeout(() => write(briefSince), 350)
    return () => window.clearTimeout(t)
  }, [briefSince, data.value, write])

  useEffect(() => () => run.current?.abort(), [])

  const commit = (iso: string) => {
    setBriefSince(iso)
    rememberSince(iso)
  }

  const inRange = (data.value?.changes ?? []).filter((c) => c.date > since)
  const current = state.sentences.find((s) => s.index === selected && s.verdict) ?? null
  const close = useCallback(() => setSelected(null), [])
  const presets: { label: string; days: number }[] = [
    { label: 'A week', days: 7 },
    { label: 'A month', days: 30 },
    { label: 'A quarter', days: 91 },
  ]
  const noKey = state.error?.startsWith('Briefs are off') ?? false

  return (
    <div className="flex min-h-full min-w-0 flex-1 gap-3">
      <main className="slab relative flex min-w-0 flex-1 flex-col bg-paper">
        <div role="status" aria-live="polite" className="sr-only">
          {announcement}
        </div>
        <div className="w-full px-5 pt-8 pb-16 sm:px-10 sm:pt-10">
          <motion.header initial={reduce ? false : { opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5, ease }}>
            <h1 className="display text-[40px] text-ink sm:text-[54px]">Catch me up</h1>
            <div className="mt-4 flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
              <p className="max-w-[600px] text-[17px] leading-relaxed text-pretty text-muted">
                Drag the edge back to when you left. Every change since then is a mark below, and the brief beside them is checked sentence by sentence.
              </p>
              <div className="flex items-center gap-1 text-[14px]">
                <span className="mr-1.5 text-faint">Away for</span>
                {presets.map((p) => {
                  const iso = isoOf(dayOf(today) - p.days)
                  return (
                    <button
                      key={p.label}
                      type="button"
                      onClick={() => {
                        setSince(iso)
                        commit(iso)
                      }}
                      className={`h-9 rounded-full px-3.5 transition-colors focus-visible:outline-2 focus-visible:outline-cobalt ${since === iso ? 'bg-ink font-semibold text-paper' : 'text-muted hover:bg-paper-2 hover:text-ink'}`}
                    >
                      {p.label}
                    </button>
                  )
                })}
              </div>
            </div>
          </motion.header>

          <div className="mt-10">
            {!data.value && !data.error && (
              <div aria-hidden="true" className="space-y-2 pt-14">
                {LANES.map((l, i) => (
                  <div key={l.kind} className="h-10 animate-pulse rounded-[10px] bg-paper-2" style={{ opacity: 1 - i * 0.12 }} />
                ))}
              </div>
            )}
            {data.error && (
              <div className="max-w-[560px] py-6">
                <p className="text-[18px] leading-relaxed text-ink">{data.error}</p>
                <button type="button" onClick={() => { setData({ value: null, error: null }); setAttempt((a) => a + 1) }} className="mt-4 text-[15px] font-semibold text-cobalt hover:text-cobalt-deep">
                  Try again
                </button>
              </div>
            )}
            {data.value && <Range data={data.value} since={since} onSince={setSince} onCommit={commit} />}
          </div>

          {data.value && (
            <div className="mt-12 grid grid-cols-1 gap-x-14 gap-y-12 border-t border-line pt-8 min-[1200px]:grid-cols-[minmax(0,1fr)_360px]">
              <section aria-labelledby="brief-title">
                <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1">
                  <h2 id="brief-title" className="text-[15px] font-semibold text-ink">
                    The brief
                  </h2>
                  <span className="text-[14px] text-muted">Since {formatDate(briefSince)}</span>
                </div>
                <div className="mt-4">
                  {state.phase !== 'idle' && state.phase !== 'error' && state.phase !== 'empty' && (
                    <BriefProgress
                      phase={state.phase}
                      facts={state.evidence?.facts ?? null}
                      checked={state.sentences.filter((s) => s.verdict).length}
                      total={state.sentences.length}
                    />
                  )}
                </div>
                <div className="mt-8">
                  {state.phase === 'asking' && !state.sentences.length && (
                    <p className="text-[19px] leading-[1.75] sm:text-[22px]">
                      <span className="pending">Writing what changed since {formatDate(briefSince)}</span>
                    </p>
                  )}
                  {state.sentences.length > 0 && <Answer sentences={state.sentences} selected={selected} onSelect={(i) => setSelected((s) => (s === i ? null : i))} />}
                  {state.phase === 'empty' && (
                    <p className="display text-[26px] text-ink sm:text-[30px]">Nothing in the graph changed since {formatDate(briefSince)}.</p>
                  )}
                  {state.phase === 'error' && (
                    <div>
                      <p className="text-[17px] leading-relaxed text-ink">{state.error}</p>
                      {!noKey && (
                        <button type="button" onClick={() => write(briefSince)} className="mt-3 text-[15px] font-semibold text-cobalt hover:text-cobalt-deep">
                          Try again
                        </button>
                      )}
                    </div>
                  )}
                  {isMock() && state.phase === 'idle' && <p className="text-[16px] text-muted">The recorded demo has no brief. Open the app without ?mock=1.</p>}
                  {(state.phase === 'done' || state.phase === 'asking') && state.sentences.length > 0 && (
                    <div className="mt-10 space-y-4 border-t border-line pt-5">
                      <Removed sentences={state.sentences} selected={selected} onSelect={setSelected} />
                      {state.phase === 'done' && state.counts && <Tally counts={state.counts} />}
                    </div>
                  )}
                </div>
              </section>

              <section aria-label="What changed">
                <AnimatePresence mode="wait" initial={false}>
                  <motion.div key={inRange.length ? 'some' : 'none'} initial={reduce ? false : { opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.2 }}>
                    {inRange.length ? (
                      <ChangeList items={inRange} />
                    ) : (
                      <p className="text-[16px] leading-relaxed text-muted">Nothing changed in this range. Drag the edge further back.</p>
                    )}
                  </motion.div>
                </AnimatePresence>
              </section>
            </div>
          )}
        </div>
      </main>

      <Sheet open={!!current} onClose={close} labelledBy="panel-title">
        {current && <SourcePanel ws={ws.slug} sentence={current} onClose={close} />}
      </Sheet>
    </div>
  )
}
