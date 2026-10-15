// Decisions: every RFC on one timeline, in the hero's language. A decision is a bar from the day it was
// accepted to the day another replaced it, with a thin line before it for the weeks it was a proposal.
// Replaced decisions are hatched and struck, with a line down to what replaced them; ticks are the pull
// requests that built them. Proposals that closed are a dashed line that stops. Click one for the detail.

import { ArrowUpRight, X } from '@phosphor-icons/react'
import { motion, useReducedMotion } from 'motion/react'
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { decision as getDecision, decisions as getDecisions, type Decision, type DecisionDetail, type Decisions as DecisionList } from './api'
import { ease } from './Answer'
import { FactHistory } from './FactHistory'
import { Sheet, useWide } from './Sheet'
import { formatDate, plural } from './text'
import type { Workspace } from './workspaces'

const DAY = 86_400_000

function dayOf(iso: string): number {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso)
  return m ? Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3])) / DAY : 0
}

const ENDED_STYLE = {
  backgroundImage: 'repeating-linear-gradient(135deg, var(--paper-2) 0 6px, #e4e6eb 6px 7px)',
  boxShadow: 'inset 0 0 0 1px var(--line)',
}

type Filter = 'all' | 'force' | 'replaced' | 'open' | 'closed'

const FILTERS: { key: Filter; label: string; has: (d: Decision) => boolean }[] = [
  { key: 'all', label: 'All', has: () => true },
  { key: 'force', label: 'In force', has: (d) => d.status === 'accepted' },
  { key: 'replaced', label: 'Replaced', has: (d) => d.status === 'superseded' || d.status === 'retired' },
  { key: 'open', label: 'Open', has: (d) => d.status === 'proposed' },
  { key: 'closed', label: 'Closed', has: (d) => d.status === 'withdrawn' || d.status === 'rejected' },
]

/** The end of a decision's time in force: the day it was replaced, or today. */
function endOf(d: Decision, today: string): string {
  return d.replaced_at ?? (d.status === 'withdrawn' || d.status === 'rejected' ? (d.closed_at ?? today) : today)
}

function statusLine(d: Decision): { text: string; tone: string } {
  switch (d.status) {
    case 'accepted':
      return { text: d.decided_at ? `In force since ${formatDate(d.decided_at)}` : 'In force', tone: 'text-cobalt' }
    case 'superseded':
      return { text: d.replaced_at ? `Replaced on ${formatDate(d.replaced_at)}` : 'Replaced', tone: 'text-muted' }
    case 'retired':
      return { text: 'Out of date, by its own words', tone: 'text-proof' }
    case 'proposed':
      return { text: d.proposed_at ? `Open since ${formatDate(d.proposed_at)}` : 'Open', tone: 'text-cobalt' }
    case 'withdrawn':
      return { text: d.closed_at ? `Closed without a decision on ${formatDate(d.closed_at)}` : 'Closed without a decision', tone: 'text-muted' }
    case 'rejected':
      return { text: 'Rejected', tone: 'text-muted' }
  }
}

// ----- the timeline ------------------------------------------------------------------------------------------------

type Span = 'all' | '2y' | '1y'
const SPANS: { key: Span; label: string; days: number | null }[] = [
  { key: 'all', label: 'Every year', days: null },
  { key: '2y', label: 'Two years', days: 730 },
  { key: '1y', label: 'One year', days: 365 },
]

type Tick = { iso: string; label: string }
type Axis = { start: number; end: number; pct: (iso: string) => number; ticks: Tick[]; startIso: string }

const MONTHS_SHORT = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

function axisFor(items: Decision[], today: string, span: Span): Axis {
  const days = items.map((d) => d.proposed_at ?? d.decided_at).filter((x): x is string => !!x).map(dayOf)
  const back = SPANS.find((s) => s.key === span)!.days
  const earliest = new Date((back ? dayOf(today) - back : days.length ? Math.min(...days) : dayOf(today) - 365) * DAY)
  const y0 = earliest.getUTCFullYear()
  const m0 = back ? earliest.getUTCMonth() : earliest.getUTCMonth() < 6 ? 0 : 6
  const start = Date.UTC(y0, m0, 1) / DAY
  const end = dayOf(today) + (back ? Math.round(back / 24) : 45)
  // Clamped, so a bar that began before the axis starts at its left edge.
  const pct = (iso: string) => Math.max(0, ((dayOf(iso) - start) / (end - start)) * 100)
  const ticks: Tick[] = []
  const step = back ? 3 : 12 // quarters when zoomed in, years otherwise
  for (let y = y0, m = back ? Math.ceil(m0 / 3) * 3 : m0 ? 12 : 0; ; m += step) {
    const yy = y + Math.floor(m / 12)
    const mm = m % 12
    const day = Date.UTC(yy, mm, 1) / DAY
    if (day >= dayOf(today) - 40) break
    if (day >= start) ticks.push({ iso: new Date(day * DAY).toISOString().slice(0, 10), label: back ? (mm === 0 ? String(yy) : MONTHS_SHORT[mm]) : String(yy) })
  }
  return { start, end, pct, ticks, startIso: new Date(start * DAY).toISOString().slice(0, 10) }
}

const ROW = { wide: 48, narrow: 64 }

function Bar({ d, axis, today, index, below, reduce }: { d: Decision; axis: Axis; today: string; index: number; below: number | null; reduce: boolean }) {
  const { pct } = axis
  const born = d.proposed_at ?? d.decided_at ?? today
  const decided = d.decided_at && d.status !== 'proposed' && d.status !== 'withdrawn' ? d.decided_at : null
  const end = endOf(d, today)
  const ended = d.status === 'superseded' || d.status === 'retired'
  const closed = d.status === 'withdrawn' || d.status === 'rejected'
  const open = d.status === 'proposed'
  const fuseEnd = decided ?? end
  const from = pct(born)
  const delay = reduce ? 0 : Math.min(index * 0.025, 0.9)
  const grow = { duration: reduce ? 0 : 0.7, delay, ease }

  return (
    <span className="relative block h-full" aria-hidden="true">
      {/* The proposal: a thin line from the day it was proposed, dashed while it is open or after it closed. */}
      <motion.span
        className={`absolute top-1/2 h-0 -translate-y-1/2 ${open ? 'border-t-2 border-dashed border-cobalt/60' : closed ? 'border-t-2 border-dashed border-line-strong' : 'border-t-2 border-cobalt/30'}`}
        style={{ left: `${from}%`, width: `${Math.max(pct(fuseEnd) - from, 0.15)}%`, transformOrigin: 'left' }}
        initial={reduce ? false : { scaleX: 0 }}
        animate={{ scaleX: 1 }}
        transition={grow}
      />
      {from > 0 && (
        <span
          className={`absolute top-1/2 size-[9px] -translate-x-1/2 -translate-y-1/2 rounded-full border-2 bg-paper ${open ? 'border-cobalt' : closed ? 'border-line-strong' : ended ? 'border-faint' : 'border-cobalt'}`}
          style={{ left: `${from}%` }}
        />
      )}
      {closed && (
        <span className="absolute top-1/2 -translate-x-1/2 -translate-y-1/2 text-[13px] leading-none font-semibold text-faint" style={{ left: `${pct(end)}%` }}>
          ×
        </span>
      )}
      {open && <span className="absolute top-1/2 size-[7px] -translate-x-1/2 -translate-y-1/2 rounded-full bg-cobalt/60" style={{ left: `${pct(end)}%` }} />}

      {/* In force: from the day it was accepted to the day something replaced it. */}
      {decided && (
        <motion.span
          className={`absolute top-1/2 h-[14px] -translate-y-1/2 overflow-hidden rounded-full ${ended ? '' : 'bg-cobalt'}`}
          style={{ left: `${pct(decided)}%`, width: `max(${pct(end) - pct(decided)}%, 6px)`, ...(ended ? ENDED_STYLE : {}) }}
          initial={reduce ? false : { clipPath: 'inset(0 100% 0 0 round 999px)' }}
          animate={{ clipPath: 'inset(0 0% 0 0 round 999px)' }}
          transition={{ ...grow, delay: delay + 0.15 }}
        >
          {ended && <span className="absolute inset-x-1.5 top-1/2 h-[1.5px] -translate-y-1/2 bg-faint/70" />}
        </motion.span>
      )}

      {/* The pull requests that built it. */}
      {d.pulls
        .filter((p) => p.merged_at && p.merged_at >= axis.startIso)
        .map((p) => (
          <span key={p.id} title={p.title} className="absolute top-1/2 h-[24px] w-[2px] -translate-x-1/2 -translate-y-1/2 rounded-full bg-ink" style={{ left: `${pct(p.merged_at!)}%` }} />
        ))}

      {/* A line down to the decision that replaced it. */}
      {below !== null && d.replaced_at && (
        <motion.span
          className="pointer-events-none absolute z-10 w-0 -translate-x-1/2 border-l-[1.5px] border-dashed border-ink/45"
          style={{ left: `${pct(d.replaced_at)}%`, top: '50%', height: below, transformOrigin: 'top' }}
          initial={reduce ? false : { scaleY: 0 }}
          animate={{ scaleY: 1 }}
          transition={{ duration: reduce ? 0 : 0.6, delay: delay + 0.6, ease }}
        >
          <span className="absolute -bottom-[4px] -left-[4.5px] size-[8px] rounded-full bg-ink" />
        </motion.span>
      )}
    </span>
  )
}

function Timeline({ items: listed, all, today, span, selected, onSelect }: {
  items: Decision[]
  all: Decision[]
  today: string
  span: Span
  selected: string | null
  onSelect: (id: string) => void
}) {
  const reduce = !!useReducedMotion()
  const wide = useWide()
  const axis = useMemo(() => axisFor(all, today, span), [all, today, span])
  // Zoomed in, a decision that ended before the axis begins has nothing to draw.
  const items = listed.filter((d) => endOf(d, today) >= axis.startIso)
  const row = wide ? ROW.wide : ROW.narrow
  const at = new Map(items.map((d, i) => [d.id, i]))

  const rules = (
    <>
      {axis.ticks.map((t) => (
        <span key={t.iso} className="absolute inset-y-0 w-px bg-line" style={{ left: axis.pct(t.iso) + '%' }} />
      ))}
    </>
  )

  return (
    <div className="relative">
      {/* Years, and today */}
      <div className="relative mb-1 h-9 min-[900px]:ml-[300px]">
        {axis.ticks.map((t, i) => (
          <span
            key={t.iso}
            className={`absolute bottom-2 pl-2 text-[13px] font-medium whitespace-nowrap text-faint ${!wide && axis.ticks.length > 4 && (span === 'all' ? i % 2 : !/^\d|Jul/.test(t.label)) ? 'hidden' : ''}`}
            style={{ left: axis.pct(t.iso) + '%' }}
          >
            {t.label}
          </span>
        ))}
        <span
          className={`absolute top-0 rounded-full bg-ink px-2.5 py-1 text-[12px] font-semibold whitespace-nowrap text-paper ${axis.pct(today) > 94 ? '-translate-x-[85%]' : '-translate-x-1/2'}`}
          style={{ left: axis.pct(today) + '%' }}
        >
          Today
        </span>
      </div>

      <div className="relative">
        <div className="pointer-events-none absolute inset-y-0 right-0 left-0 min-[900px]:left-[300px]" aria-hidden="true">
          {rules}
        </div>
        <ul className="relative" aria-label="Decisions, oldest proposal first">
          {items.map((d, i) => {
            const next = d.superseded_by.map((s) => at.get(s.id)).find((j) => j !== undefined && j > i)
            const meta = d.areas.length ? d.areas.map((a) => a.name).join(', ') : statusLine(d).text
            const on = selected === d.id
            return (
              <li key={d.id} style={{ height: row }} className="border-t border-line">
                <button
                  type="button"
                  onClick={() => onSelect(d.id)}
                  aria-pressed={on}
                  className={`grid h-full w-full grid-cols-1 grid-rows-[auto_minmax(0,1fr)] text-left transition-colors focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-cobalt min-[900px]:grid-cols-[300px_minmax(0,1fr)] min-[900px]:grid-rows-1 min-[900px]:items-center ${on ? 'bg-ink/[0.045]' : 'hover:bg-ink/[0.025]'}`}
                >
                  <span className="flex min-w-0 items-baseline gap-2 pt-2 pr-4 pl-1 min-[900px]:block min-[900px]:pt-0 min-[900px]:pl-3">
                    <span className={`block max-w-[78%] shrink-0 truncate text-[14.5px] font-semibold min-[900px]:max-w-none tracking-[-0.01em] ${d.status === 'superseded' || d.status === 'retired' ? 'text-muted line-through decoration-faint/70' : d.status === 'withdrawn' ? 'text-muted' : 'text-ink'}`}>
                      {d.title}
                    </span>
                    <span className="block min-w-0 truncate text-[12.5px] text-faint min-[900px]:mt-0.5">{meta}</span>
                  </span>
                  <span className="relative block h-full min-h-[34px]">
                    <Bar d={d} axis={axis} today={today} index={i} below={next === undefined ? null : (next - i) * row} reduce={reduce} />
                  </span>
                </button>
                <span className="sr-only">{statusLine(d).text}.</span>
              </li>
            )
          })}
        </ul>
        {/* Today, drawn over the rows so a selected row does not hide it. */}
        <div className="pointer-events-none absolute inset-y-0 right-0 left-0 z-10 min-[900px]:left-[300px]" aria-hidden="true">
          <span className="absolute inset-y-0 w-[2px] -translate-x-1/2 bg-ink" style={{ left: axis.pct(today) + '%' }} />
        </div>
      </div>
    </div>
  )
}

/** How to read the timeline, drawn in its own marks. */
function Key() {
  const item = 'flex items-center gap-2.5'
  return (
    <ul className="flex flex-wrap gap-x-6 gap-y-2.5 text-[13.5px] text-muted" aria-label="How to read it">
      <li className={item}>
        <span className="relative h-3 w-9" aria-hidden="true">
          <span className="absolute top-1/2 left-0 size-[9px] -translate-y-1/2 rounded-full border-2 border-cobalt bg-paper" />
          <span className="absolute top-1/2 left-[9px] w-[27px] border-t-2 border-cobalt/30" />
        </span>
        Proposed
      </li>
      <li className={item}>
        <span className="h-[12px] w-9 rounded-full bg-cobalt" aria-hidden="true" />
        In force
      </li>
      <li className={item}>
        <span className="relative h-[12px] w-9 overflow-hidden rounded-full" style={ENDED_STYLE} aria-hidden="true">
          <span className="absolute inset-x-1 top-1/2 h-[1.5px] -translate-y-1/2 bg-faint/70" />
        </span>
        <span className="line-through decoration-faint">Replaced</span>
      </li>
      <li className={item}>
        <span className="relative h-3 w-9" aria-hidden="true">
          <span className="absolute top-1/2 left-0 w-[28px] border-t-2 border-dashed border-line-strong" />
          <span className="absolute top-1/2 right-0 -translate-y-1/2 text-[13px] leading-none font-semibold text-faint">×</span>
        </span>
        Closed without a decision
      </li>
      <li className={item}>
        <span className="h-4 w-[2px] rounded-full bg-ink" aria-hidden="true" />
        Pull request that built it
      </li>
    </ul>
  )
}

// ----- the detail ----------------------------------------------------------------------------------------------------

function Lifeline({ d, today }: { d: Decision; today: string }) {
  const reduce = !!useReducedMotion()
  const steps: { label: string; date: string | null; tone: string }[] = [{ label: 'Proposed', date: d.proposed_at, tone: 'border-cobalt' }]
  if (d.decided_at && d.status !== 'proposed' && d.status !== 'withdrawn') steps.push({ label: 'Accepted', date: d.decided_at, tone: 'bg-cobalt border-cobalt' })
  if (d.status === 'withdrawn' || d.status === 'rejected') steps.push({ label: 'Closed', date: d.closed_at ?? null, tone: 'border-line-strong bg-line-strong' })
  if (d.replaced_at) steps.push({ label: 'Replaced', date: d.replaced_at, tone: 'border-ink bg-ink' })
  else if (d.status === 'accepted' || d.status === 'proposed') steps.push({ label: 'Today', date: today, tone: 'border-ink bg-paper' })
  return (
    <ol className="relative grid" style={{ gridTemplateColumns: `repeat(${steps.length}, minmax(0, 1fr))` }}>
      <motion.span
        aria-hidden="true"
        className="absolute top-[5px] left-[6px] h-[2px] origin-left bg-line-strong"
        style={{ right: `calc(${100 / steps.length}% - 6px)` }}
        initial={reduce ? false : { scaleX: 0 }}
        animate={{ scaleX: 1 }}
        transition={{ duration: reduce ? 0 : 0.6, ease }}
      />
      {steps.map((s) => (
        <li key={s.label} className="relative pr-2">
          <span className={`block size-3 rounded-full border-2 ${s.tone}`} aria-hidden="true" />
          <span className="mt-2 block text-[13px] font-semibold text-ink">{s.label}</span>
          <span className="block text-[13px] text-muted">{formatDate(s.date)}</span>
        </li>
      ))}
    </ol>
  )
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section>
      <h3 className="text-[14px] font-semibold text-ink">{title}</h3>
      <div className="mt-2.5">{children}</div>
    </section>
  )
}

function Linked({ links, all, onSelect, verb }: { links: Decision['superseded_by']; all: Map<string, Decision>; onSelect: (id: string) => void; verb: string }) {
  return (
    <ul className="space-y-4">
      {links.map((l) => {
        const other = all.get(l.id)
        return (
          <li key={l.id}>
            <button
              type="button"
              onClick={() => onSelect(l.id)}
              className="text-left text-[16px] font-semibold text-cobalt underline decoration-cobalt/30 underline-offset-4 hover:decoration-cobalt focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cobalt"
            >
              {other?.title ?? l.title ?? l.id}
            </button>
            {l.reason && <p className="mt-1.5 border-l-2 border-line-strong pl-3 text-[14.5px] leading-relaxed text-muted">{l.reason}</p>}
            <p className="mt-1.5 text-[12.5px] text-faint">
              {l.by === 'model' ? `The model read both RFCs and judged that one ${verb} the other.` : `The RFC says so where it links the other.`}
            </p>
          </li>
        )
      })}
    </ul>
  )
}

function DecisionPanel({ ws, d, all, today, onSelect, onClose }: {
  ws: string
  d: Decision
  all: Map<string, Decision>
  today: string
  onSelect: (id: string) => void
  onClose: () => void
}) {
  const [detail, setDetail] = useState<{ id: string; data: DecisionDetail | null } | null>(null)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const ctrl = new AbortController()
    getDecision(ws, d.id, ctrl.signal).then(
      (data) => setDetail({ id: d.id, data }),
      (e: Error) => e.name !== 'AbortError' && setDetail({ id: d.id, data: null }),
    )
    return () => ctrl.abort()
  }, [ws, d.id])

  useEffect(() => ref.current?.focus({ preventScroll: true }), [d.id])

  const status = statusLine(d)
  const facts = detail?.id === d.id ? (detail.data?.facts ?? []) : []
  const focus = facts.find((f) => f.current) ?? facts[facts.length - 1]

  return (
    <div ref={ref} tabIndex={-1} className="outline-none">
      <header className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <p className={`text-[14px] font-semibold ${status.tone}`}>{status.text}</p>
          <h2 id="decision-title" className={`mt-2 text-[24px] leading-tight font-semibold tracking-[-0.02em] text-pretty ${d.status === 'superseded' ? 'text-muted line-through decoration-faint/60 decoration-[1.5px]' : 'text-ink'}`}>
            {d.title}
          </h2>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close the decision"
          className="-mt-1 -mr-1 grid size-9 shrink-0 place-items-center rounded-full text-muted transition-colors hover:bg-paper-2 hover:text-ink focus-visible:outline-2 focus-visible:outline-cobalt"
        >
          <X size={17} weight="bold" />
        </button>
      </header>

      {d.summary && <p className="mt-4 text-[16px] leading-relaxed text-pretty text-ink">{d.summary}</p>}

      <div className="mt-7">
        <Lifeline d={d} today={today} />
      </div>

      <div className="mt-9 space-y-8">
        {d.superseded_by.length > 0 && (
          <Section title="Replaced by">
            <Linked links={d.superseded_by} all={all} onSelect={onSelect} verb="replaces" />
          </Section>
        )}
        {d.supersedes.length > 0 && (
          <Section title="Replaces">
            <Linked links={d.supersedes} all={all} onSelect={onSelect} verb="replaces" />
          </Section>
        )}
        <Section title="Decided by">
          {d.people.length ? (
            <ul className="space-y-1.5">
              {d.people.map((p) => (
                <li key={p.handle} className="text-[15px] text-ink">
                  <span className="font-semibold">{p.name}</span>
                  <span className="text-muted"> {p.how === 'approved' ? 'approved it' : 'merged it'}</span>
                  <a href={`https://github.com/${p.handle}`} target="_blank" rel="noreferrer" className="ml-2 text-[13.5px] text-cobalt hover:text-cobalt-deep">
                    @{p.handle}
                  </a>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-[15px] text-muted">{!d.decided_at ? 'Nobody: it was never merged.' : 'Nobody on the published team list approved or merged it.'}</p>
          )}
        </Section>
        {d.areas.length > 0 && (
          <Section title="About">
            <p className="text-[15px] text-ink">{d.areas.map((a) => a.name).join(', ')}</p>
          </Section>
        )}
        <Section title="Built by">
          {d.pulls.length ? (
            <ul className="space-y-2.5">
              {d.pulls.map((p) => (
                <li key={p.id}>
                  <a href={p.url} target="_blank" rel="noreferrer" className="group inline-flex items-baseline gap-1 text-[15px] leading-snug text-ink hover:text-cobalt">
                    {p.title}
                    <ArrowUpRight size={12} weight="bold" className="shrink-0 text-faint group-hover:text-cobalt" />
                  </a>
                  <p className="text-[13px] text-muted">
                    Merged {formatDate(p.merged_at)}
                    {p.how === 'title' ? ', names the RFC' : ', links the RFC'}
                  </p>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-[15px] text-muted">No pull request in the graph links this RFC.</p>
          )}
        </Section>
        {focus && (
          <Section title="As facts">
            <p className="-mt-1 mb-4 text-[13.5px] text-muted">What the graph states about this decision, over time. Answers are checked against these.</p>
            <FactHistory ws={ws} factId={focus.fact_id} />
          </Section>
        )}
        {d.url && (
          <a
            href={d.url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 text-[14px] font-semibold text-cobalt hover:text-cobalt-deep focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cobalt"
          >
            {!d.decided_at ? 'Open the pull request' : 'Open the RFC'} <ArrowUpRight size={13} weight="bold" />
          </a>
        )}
      </div>
    </div>
  )
}

// ----- the screen --------------------------------------------------------------------------------------------------

function Skeleton() {
  return (
    <div aria-hidden="true" className="space-y-0">
      {Array.from({ length: 9 }, (_, i) => (
        <div key={i} className="grid h-[46px] grid-cols-1 items-center border-t border-line min-[900px]:grid-cols-[300px_minmax(0,1fr)]">
          <div className="hidden h-3.5 w-40 animate-pulse rounded bg-paper-2 min-[900px]:ml-3 min-[900px]:block" />
          <div className="relative h-6">
            <div className="absolute inset-y-0 animate-pulse rounded-[8px] bg-paper-2" style={{ left: `${8 + i * 9}%`, right: 0 }} />
          </div>
        </div>
      ))}
    </div>
  )
}

export function Decisions({ ws }: { ws: Workspace }) {
  const [state, setState] = useState<{ data: DecisionList | null; error: string | null; loading: boolean }>({ data: null, error: null, loading: true })
  const [filter, setFilter] = useState<Filter>('all')
  const [span, setSpan] = useState<Span>(() => (window.matchMedia('(min-width: 900px)').matches ? 'all' : '2y'))
  const [selected, setSelected] = useState<string | null>(null)
  const [attempt, setAttempt] = useState(0)
  const reduce = useReducedMotion()

  useEffect(() => {
    const ctrl = new AbortController()
    getDecisions(ws.slug, ctrl.signal).then(
      (data) => setState({ data, error: null, loading: false }),
      (e: Error) => e.name !== 'AbortError' && setState({ data: null, error: e.message, loading: false }),
    )
    return () => ctrl.abort()
  }, [ws.slug, attempt])

  const close = useCallback(() => setSelected(null), [])
  const data = state.data
  const all = useMemo(() => data?.decisions ?? [], [data])
  const byId = useMemo(() => new Map(all.map((d) => [d.id, d])), [all])
  const shown = all.filter(FILTERS.find((f) => f.key === filter)!.has)
  const current = selected ? (byId.get(selected) ?? null) : null
  const today = data?.today ?? new Date().toISOString().slice(0, 10)
  const live = all.filter((d) => d.status === 'accepted').length

  return (
    <div className="flex min-h-full min-w-0 flex-1 gap-3">
      <main className="slab relative flex min-w-0 flex-1 flex-col bg-paper">
        <div className="w-full px-5 pt-8 pb-16 sm:px-10 sm:pt-10">
          <motion.header initial={reduce ? false : { opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5, ease }}>
            <h1 className="display text-[40px] text-ink sm:text-[54px]">Decisions</h1>
            <p className="mt-4 max-w-[640px] text-[17px] leading-relaxed text-pretty text-muted">
              Every RFC {ws.name} wrote, from the day it was proposed to the day another one replaced it.
              {data && all.length > 0 && (
                <>
                  {' '}
                  {plural(all.length, 'decision')}, {live} still in force.
                </>
              )}
            </p>
          </motion.header>

          {data && all.length > 0 && (
            <div className="mt-8 flex flex-col gap-5 border-b border-line pb-6">
              <div role="radiogroup" aria-label="Show" className="-mx-1 flex flex-wrap gap-1">
                {FILTERS.filter((f) => f.key === 'all' || all.some(f.has)).map((f) => {
                  const n = all.filter(f.has).length
                  const on = filter === f.key
                  return (
                    <button
                      key={f.key}
                      type="button"
                      role="radio"
                      aria-checked={on}
                      disabled={!n}
                      onClick={() => setFilter(f.key)}
                      className={`inline-flex h-9 items-center gap-1.5 rounded-full px-3.5 text-[14px] transition-colors disabled:opacity-40 focus-visible:outline-2 focus-visible:outline-cobalt ${on ? 'bg-ink font-semibold text-paper' : 'text-muted hover:bg-paper-2 hover:text-ink'}`}
                    >
                      {f.label}
                      <span className={`tabular-nums ${on ? 'text-paper/70' : 'text-faint'}`}>{n}</span>
                    </button>
                  )
                })}
              </div>
              <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
                <Key />
                <div role="radiogroup" aria-label="Time shown" className="flex shrink-0 gap-1 text-[13.5px]">
                  {SPANS.map((s) => (
                    <button
                      key={s.key}
                      type="button"
                      role="radio"
                      aria-checked={span === s.key}
                      onClick={() => setSpan(s.key)}
                      className={`h-8 rounded-full px-3 transition-colors focus-visible:outline-2 focus-visible:outline-cobalt ${span === s.key ? 'bg-paper-2 font-semibold text-ink shadow-[inset_0_0_0_1px_var(--line-strong)]' : 'text-muted hover:text-ink'}`}
                    >
                      {s.label}
                    </button>
                  ))}
                </div>
              </div>
            </div>
          )}

          <div className="mt-6">
            {state.loading && <Skeleton />}
            {state.error && (
              <div className="max-w-[560px] py-10">
                <p className="text-[18px] leading-relaxed text-ink">{state.error}</p>
                <button type="button" onClick={() => { setState({ data: null, error: null, loading: true }); setAttempt((a) => a + 1) }} className="mt-4 text-[15px] font-semibold text-cobalt hover:text-cobalt-deep">
                  Try again
                </button>
              </div>
            )}
            {data && all.length === 0 && (
              <div className="max-w-[560px] py-10">
                <p className="display text-[28px] text-ink">No decisions in the graph yet.</p>
                <p className="mt-3 text-[17px] leading-relaxed text-muted">Decisions come from RFCs. Once {ws.name}'s RFCs are read, each one shows here from proposal to replacement.</p>
              </div>
            )}
            {data && shown.length > 0 && (
              <Timeline items={shown} all={all} today={today} span={span} selected={selected} onSelect={(id) => setSelected((s) => (s === id ? null : id))} />
            )}
          </div>
        </div>
      </main>

      <Sheet open={!!current} onClose={close} labelledBy="decision-title">
        {current && <DecisionPanel ws={ws.slug} d={current} all={byId} today={today} onSelect={setSelected} onClose={close} />}
      </Sheet>
    </div>
  )
}
