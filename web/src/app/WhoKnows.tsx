// Who knows: pick an area and see the people around it, drawn closer and joined by heavier lines the more
// evidence they have. Clicking a person shows that evidence, line by line, with links to the work itself.

import { ArrowUpRight, CaretDown, MagnifyingGlass, X } from '@phosphor-icons/react'
import { AnimatePresence, motion, useReducedMotion } from 'motion/react'
import { forwardRef, useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react'
import { areaPeople, areas as getAreas, personAreas, type AreaPeople, type AreaPerson, type AreaSummary, type PersonAreas } from './api'
import { ease } from './Answer'
import { actLabel, evidencePhrase, readArea, shortName, useWide, useWidth, WEIGHTS, writeArea } from './people'
import { navigate, ROUTES } from './router'
import { formatDate, kindLabel, plural } from './text'
import type { Workspace } from './workspaces'

type Load<T> = { status: 'loading' } | { status: 'error'; message: string } | { status: 'ready'; data: T }

// ----- the area picker -------------------------------------------------------------------------------------------

function AreaPicker({ list, current, onPick }: { list: AreaSummary[]; current: AreaSummary | null; onPick: (slug: string) => void }) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const root = useRef<HTMLDivElement>(null)
  const field = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (!open) return
    field.current?.focus({ preventScroll: true })
    const away = (e: PointerEvent) => !root.current?.contains(e.target as Node) && setOpen(false)
    const esc = (e: globalThis.KeyboardEvent) => e.key === 'Escape' && setOpen(false)
    window.addEventListener('pointerdown', away)
    window.addEventListener('keydown', esc)
    return () => {
      window.removeEventListener('pointerdown', away)
      window.removeEventListener('keydown', esc)
    }
  }, [open])

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase()
    const known = list.filter((a) => a.people.length)
    return q ? known.filter((a) => a.name.toLowerCase().includes(q) || a.slug.includes(q)) : known
  }, [list, query])

  const pick = (slug: string) => {
    setOpen(false)
    setQuery('')
    onPick(slug)
  }

  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' && shown[0]) pick(shown[0].slug)
  }

  return (
    <div ref={root} className="relative">
      <h1 className="display text-[38px] text-ink sm:text-[56px] lg:text-[64px]">
        <span className="text-faint">Who knows </span>
        <button
          type="button"
          aria-haspopup="listbox"
          aria-expanded={open}
          onClick={() => setOpen((o) => !o)}
          className="group inline-flex items-baseline gap-[0.12em] rounded-[10px] text-left text-ink decoration-line-strong decoration-[0.06em] underline-offset-[0.14em] hover:underline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-cobalt"
        >
          <span>{current?.name ?? 'an area'}</span>
          <CaretDown weight="bold" className="size-[0.42em] shrink-0 translate-y-[-0.06em] text-faint transition-colors group-hover:text-ink" />
        </button>
      </h1>
      <AnimatePresence>
        {open && (
          <motion.div
            className="absolute top-full left-0 z-30 mt-3 w-full max-w-[460px] rounded-[18px] bg-paper p-2 shadow-[0_24px_60px_-20px_rgb(13_14_18/0.35),0_0_0_1px_var(--line)]"
            initial={{ opacity: 0, y: -6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -6 }}
            transition={{ duration: 0.16 }}
          >
            <label className="flex h-11 items-center gap-2.5 rounded-[12px] bg-paper-2 px-3.5 text-muted">
              <MagnifyingGlass size={16} weight="bold" className="shrink-0" />
              <span className="sr-only">Find an area</span>
              <input
                ref={field}
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={onKey}
                placeholder="Find an area"
                className="min-w-0 flex-1 bg-transparent text-[15px] text-ink outline-none placeholder:text-faint"
              />
            </label>
            <ul role="listbox" aria-label="Areas" className="mt-1.5 max-h-[min(52vh,420px)] overflow-y-auto overscroll-contain">
              {shown.map((a) => (
                <li key={a.slug} role="option" aria-selected={a.slug === current?.slug}>
                  <button
                    type="button"
                    onClick={() => pick(a.slug)}
                    className={`flex min-h-11 w-full items-center justify-between gap-4 rounded-[11px] px-3 py-2 text-left hover:bg-paper-2 focus-visible:bg-paper-2 focus-visible:outline-none ${a.slug === current?.slug ? 'bg-paper-2' : ''}`}
                  >
                    <span className="min-w-0">
                      <span className="block truncate text-[15px] font-medium text-ink">{a.name}</span>
                      {a.owners.length > 0 && <span className="block truncate text-[13px] text-faint">{a.owners.map((o) => o.name).join(', ')}</span>}
                    </span>
                    <span className="shrink-0 text-[13px] text-muted tabular-nums">{plural(a.people.length + a.others, 'person', 'people')}</span>
                  </button>
                </li>
              ))}
              {!shown.length && <li className="px-3 py-3 text-[14px] text-faint">No area by that name has any evidence.</li>}
            </ul>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

// ----- the radial graph ------------------------------------------------------------------------------------------

type Placed = { p: AreaPerson; x: number; y: number; r: number; w: number; angle: number; t: number; d: number }
type Box = { x0: number; x1: number; y0: number; y1: number }

function layout(people: AreaPerson[], width: number, height: number, narrow: boolean): Placed[] {
  const top = people[0]?.score || 1
  const cx = width / 2
  const cy = height / 2
  const room = narrow ? 58 : 96 // space for a name beside a node at the left and right edges
  const reach = Math.max(80, Math.min(cx - room, cy - 34))
  const n = people.length
  const hub = narrow ? 18 : 24
  const placed: Placed[] = []
  const box = (n: Placed) => labelBox(n, narrow)
  const overlap = (a: Box, b: Box, pad = 4) => a.x0 < b.x1 + pad && b.x0 < a.x1 + pad && a.y0 < b.y1 + pad && b.y0 < a.y1 + pad
  const nodeBox = (n: Placed, pad = 0): Box => ({ x0: n.x - n.r - pad, x1: n.x + n.r + pad, y0: n.y - n.r - pad, y1: n.y + n.r + pad })
  // Does the line from the hub to `n` run through the box?
  const crosses = (n: Placed, b: Box) => {
    for (let k = 0.15; k < 0.97; k += 0.04) {
      const x = cx + (n.x - cx) * k
      const y = cy + (n.y - cy) * k
      if (x > b.x0 && x < b.x1 && y > b.y0 && y < b.y1) return true
    }
    return false
  }
  const conflicts = (c: Placed) => {
    const cb = box(c)
    let bad = cb.x0 < 2 || cb.x1 > width - 2 || c.y - c.r < 6 || c.y + c.r > height - 6 || cb.y0 < 0 || cb.y1 > height ? 3 : 0
    for (const q of placed) {
      const qb = box(q)
      if (Math.hypot(c.x - q.x, c.y - q.y) < c.r + q.r + 14) bad += 3
      if (overlap(cb, qb)) bad += 2
      if (overlap(cb, nodeBox(q, 3), 0) || overlap(qb, nodeBox(c, 3), 0)) bad += 2
      if (crosses(c, nodeBox(q, 4)) || crosses(c, qb) || crosses(q, nodeBox(c, 4)) || crosses(q, cb)) bad += 1
    }
    return bad
  }
  people.forEach((p, i) => {
    const t = Math.sqrt(Math.max(p.score, 0) / top) // 1 for the strongest, toward 0 for a passing touch
    // The strongest sit closest: half by evidence, half by rank, so a long tail still spreads out.
    // Each next person turns by the golden angle, so neighbours in rank never crowd each other; when that spot is
    // taken (by a node, a name or a line), the nearest free spot around it is used instead.
    const rank = n > 1 ? i / (n - 1) : 0
    const r = 5 + 11 * t
    const base = Math.max(hub + r + 26, reach * (0.34 + 0.66 * (0.45 * (1 - t) + 0.55 * rank)))
    const home = ((-58 + 137.508 * i) * Math.PI) / 180
    let best: Placed | null = null
    let bestBad = Infinity
    for (const grow of [0, 14, 28, -14, 42]) {
      for (const turn of [0, 8, -8, 16, -16, 24, -24, 34, -34, 46, -46, 60, -60]) {
        const angle = home + (turn * Math.PI) / 180
        const d = Math.min(reach * 1.12, Math.max(hub + r + 22, base + grow))
        const c: Placed = { p, t, angle, d, r, x: cx + Math.cos(angle) * d, y: cy + Math.sin(angle) * d, w: 1.3 + 8.2 * (p.score / top) }
        const bad = conflicts(c) * 10 + Math.abs(turn) / 10 + Math.abs(grow) / 10
        if (bad < bestBad) {
          best = c
          bestBad = bad
        }
        if (bad < 10) break
      }
      if (bestBad < 10) break
    }
    placed.push(best!)
  })
  return placed
}

/** The box a person's name takes beside their node, roughly, for keeping names apart. */
function labelBox(n: Placed, narrow: boolean): Box {
  const l = nodeLabel(n)
  const w = shortName(n.p.name, n.p.handle).length * (narrow ? 7 : 7.6) + (n.t === 1 ? 10 : 0)
  const x0 = l.anchor === 'start' ? l.x : l.anchor === 'end' ? l.x - w : l.x - w / 2
  return { x0, x1: x0 + w, y0: l.y - 13, y1: l.y + (n.t === 1 ? 18 : 4) }
}

function nodeLabel(n: Placed) {
  const c = Math.cos(n.angle)
  const s = Math.sin(n.angle)
  const gap = n.r + 8
  if (c > 0.35) return { x: n.x + gap, y: n.y + 4.5, anchor: 'start' as const }
  if (c < -0.35) return { x: n.x - gap, y: n.y + 4.5, anchor: 'end' as const }
  return { x: n.x, y: s < 0 ? n.y - gap - 2 : n.y + gap + 12, anchor: 'middle' as const }
}

function Radial({ data, selected, onSelect }: { data: AreaPeople; selected: string | null; onSelect: (handle: string) => void }) {
  const { ref, width } = useWidth<HTMLDivElement>()
  const reduce = !!useReducedMotion()
  const narrow = width < 560
  const people = data.people.slice(0, narrow ? 9 : 14)
  const height = Math.round(Math.min(560, Math.max(narrow ? 300 : 420, width * (narrow ? 0.84 : 0.62))))
  const placed: Placed[] = width ? layout(people, width, height, narrow) : []
  const cx = width / 2
  const cy = height / 2
  const later = (t: number) => (reduce ? 0 : t)
  const label = `${data.area.name} and the ${plural(people.length, 'person', 'people')} with the most evidence about it`

  return (
    <div ref={ref} className="w-full">
      {width > 0 && (
        <svg key={data.area.slug} viewBox={`0 0 ${width} ${height}`} width={width} height={height} role="img" aria-label={label} className="block overflow-visible">
          {placed.map((n, i) => {
            const on = n.p.handle === selected
            return (
              <motion.line
                key={`e-${n.p.handle}`}
                x1={cx}
                y1={cy}
                x2={n.x}
                y2={n.y}
                stroke={i === 0 ? 'var(--cobalt)' : on ? 'var(--ink)' : n.p.depends ? 'var(--ink)' : 'var(--line-strong)'}
                strokeLinecap="round"
                initial={reduce ? false : { strokeWidth: 0.6, opacity: 0 }}
                animate={{ strokeWidth: n.w, opacity: 1 }}
                transition={{ duration: 0.6, delay: later(0.1 + i * 0.05), ease }}
              />
            )
          })}
          {placed.map((n, i) => {
            const on = n.p.handle === selected
            const l = nodeLabel(n)
            const first = i === 0
            const fill = first ? 'var(--cobalt)' : n.p.depends ? 'var(--ink)' : 'var(--paper)'
            return (
              <motion.g
                key={`n-${n.p.handle}`}
                role="button"
                tabIndex={0}
                aria-label={`${n.p.name}: ${evidencePhrase(n.p.evidence) || 'some evidence'}`}
                aria-pressed={on}
                onClick={() => onSelect(n.p.handle)}
                onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && (e.preventDefault(), onSelect(n.p.handle))}
                className="cursor-pointer outline-none [&:focus-visible>circle.ring]:stroke-cobalt"
                initial={reduce ? false : { opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ duration: 0.4, delay: later(0.25 + i * 0.05) }}
              >
                <circle cx={n.x} cy={n.y} r={n.r + 16} fill="transparent" />
                {on && <circle cx={n.x} cy={n.y} r={n.r + 8} fill="var(--marker)" />}
                {first && <circle className="ring" cx={n.x} cy={n.y} r={n.r + 5.5} fill="none" stroke="var(--cobalt)" strokeWidth="1.5" />}
                {!first && <circle className="ring" cx={n.x} cy={n.y} r={n.r + 4} fill="none" stroke="transparent" strokeWidth="1.5" />}
                <circle
                  cx={n.x}
                  cy={n.y}
                  r={n.r}
                  fill={fill}
                  stroke={first || n.p.depends ? 'none' : 'var(--ink)'}
                  strokeWidth="1.8"
                  strokeDasharray={n.p.score <= WEIGHTS.member + 0.01 && n.p.evidence.member ? '3 2.5' : undefined}
                />
                <text
                  x={l.x}
                  y={l.y}
                  textAnchor={l.anchor}
                  fontSize={narrow ? 12.5 : 13.5}
                  fontWeight={first || on ? 650 : 500}
                  fill={first ? 'var(--cobalt)' : on || n.p.depends ? 'var(--ink)' : 'var(--muted)'}
                  style={{ paintOrder: 'stroke', stroke: 'var(--paper)', strokeWidth: 4, strokeLinejoin: 'round' }}
                >
                  {shortName(n.p.name, n.p.handle)}
                </text>
                {first && (
                  <text
                    x={l.x}
                    y={l.anchor === 'middle' ? l.y - 17 : l.y + 17}
                    textAnchor={l.anchor}
                    fontSize="12"
                    fontWeight="600"
                    fill="var(--cobalt)"
                    opacity="0.8"
                    style={{ paintOrder: 'stroke', stroke: 'var(--paper)', strokeWidth: 4, strokeLinejoin: 'round' }}
                  >
                    Ask first
                  </text>
                )}
              </motion.g>
            )
          })}
          <motion.circle
            cx={cx}
            cy={cy}
            r={narrow ? 18 : 24}
            fill="var(--marker)"
            stroke="var(--paper)"
            strokeWidth="5"
            initial={reduce ? false : { scale: 0.4, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            transition={{ duration: 0.45, ease }}
            style={{ transformOrigin: `${cx}px ${cy}px` }}
          />
        </svg>
      )}
    </div>
  )
}

// ----- the ranked list -------------------------------------------------------------------------------------------

function Ranked({ data, selected, onSelect }: { data: AreaPeople; selected: string | null; onSelect: (handle: string) => void }) {
  const top = data.people[0]?.score || 1
  return (
    <ol className="divide-y divide-line border-y border-line">
      {data.people.map((p, i) => {
        const on = p.handle === selected
        return (
          <li key={p.handle}>
            <button
              type="button"
              onClick={() => onSelect(p.handle)}
              aria-pressed={on}
              className={`grid w-full grid-cols-[22px_minmax(0,1fr)_minmax(64px,28%)] items-center gap-x-4 px-1 py-3 text-left transition-colors hover:bg-paper-2/70 focus-visible:bg-paper-2 focus-visible:outline-none sm:grid-cols-[26px_minmax(0,1fr)_minmax(120px,34%)] ${on ? 'bg-paper-2' : ''}`}
            >
              <span className="text-[13px] text-faint tabular-nums">{i + 1}</span>
              <span className="min-w-0">
                <span className={`block truncate text-[15.5px] ${i === 0 ? 'font-semibold text-cobalt' : 'font-medium text-ink'}`}>{p.name}</span>
                <span className="block text-[13px] leading-snug text-muted">{evidencePhrase(p.evidence) || 'on the owning team'}</span>
              </span>
              <span className="relative h-[6px] rounded-full bg-paper-2" aria-hidden="true">
                <span
                  className={`absolute inset-y-0 left-0 rounded-full ${i === 0 ? 'bg-cobalt' : p.depends ? 'bg-ink' : 'bg-line-strong'}`}
                  style={{ width: `${Math.max(3, (100 * p.score) / top)}%` }}
                />
              </span>
            </button>
          </li>
        )
      })}
    </ol>
  )
}

// ----- one person's evidence -------------------------------------------------------------------------------------

function Composition({ person }: { person: AreaPerson }) {
  const e = person.evidence
  const parts = [
    { key: 'decided', n: e.decided * WEIGHTS.decided, tone: 'bg-cobalt-deep' },
    { key: 'authored', n: e.authored * WEIGHTS.authored, tone: 'bg-ink' },
    { key: 'reviewed', n: e.reviewed * WEIGHTS.reviewed, tone: 'bg-cobalt' },
    { key: 'commented', n: e.commented * WEIGHTS.commented, tone: 'bg-line-strong' },
    { key: 'member', n: e.member ? WEIGHTS.member : 0, tone: 'bg-marker' },
  ].filter((p) => p.n > 0)
  const total = parts.reduce((s, p) => s + p.n, 0) || 1
  return (
    <div className="flex h-[7px] gap-[3px]" aria-hidden="true">
      {parts.map((p) => (
        <span key={p.key} className={`rounded-full ${p.tone}`} style={{ width: `${(100 * p.n) / total}%` }} />
      ))}
    </div>
  )
}

const PersonPanel = forwardRef<HTMLDivElement, { ws: string; data: AreaPeople; person: AreaPerson; onClose: () => void; onArea: (slug: string) => void }>(
  function PersonPanel({ ws, data, person, onClose, onArea }, ref) {
    const [others, setOthers] = useState<{ handle: string; data: PersonAreas | null } | null>(null)
    useEffect(() => {
      const ctrl = new AbortController()
      personAreas(ws, person.handle, ctrl.signal).then(
        (d) => setOthers({ handle: person.handle, data: d }),
        (e: Error) => e.name !== 'AbortError' && setOthers({ handle: person.handle, data: null }),
      )
      return () => ctrl.abort()
    }, [ws, person.handle])

    const e = person.evidence
    const elsewhere = others?.handle === person.handle ? (others.data?.areas.filter((a) => a.slug !== data.area.slug).slice(0, 8) ?? []) : null
    const phrase = evidencePhrase(e)
    const counts = [
      { label: 'Decided', n: e.decided, tone: 'bg-cobalt-deep' },
      { label: 'Wrote', n: e.authored, tone: 'bg-ink' },
      { label: 'Reviewed', n: e.reviewed, tone: 'bg-cobalt' },
      { label: 'Commented', n: e.commented, tone: 'bg-line-strong' },
    ].filter((c) => c.n)

    return (
      <div ref={ref} tabIndex={-1} className="outline-none">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <h2 id="person-title" className="font-display text-[30px] leading-[1.05] font-semibold tracking-[-0.035em] text-ink">
              {person.name}
            </h2>
            <p className="mt-2 text-[14px] text-muted">
              {[person.role, person.teams.length ? person.teams.join(', ') : null].filter(Boolean).join(' · ')}
            </p>
            <a
              href={`https://github.com/${person.handle}`}
              target="_blank"
              rel="noreferrer"
              className="mt-1 inline-flex items-center gap-1 text-[14px] font-semibold text-cobalt hover:text-cobalt-deep"
            >
              @{person.handle} <ArrowUpRight size={12} weight="bold" />
            </a>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="grid size-9 shrink-0 place-items-center rounded-full text-muted transition-colors hover:bg-paper-2 hover:text-ink focus-visible:outline-2 focus-visible:outline-cobalt"
          >
            <X size={16} weight="bold" />
          </button>
        </div>

        <div className="mt-6">
          <p className="text-[16px] leading-relaxed text-ink">
            On {data.area.name}, {person.name.split(' ')[0]} {phrase || 'has no recorded work yet'}
            {phrase && e.member ? ', and is on the team that owns it.' : e.member && phrase ? '.' : '.'}
          </p>
          <div className="mt-4">
            <Composition person={person} />
          </div>
          {counts.length > 0 && (
            <ul className="mt-3 flex flex-wrap gap-x-4 gap-y-1.5 text-[13px] text-muted">
              {counts.map((c) => (
                <li key={c.label} className="flex items-center gap-1.5">
                  <span className={`h-[5px] w-3 rounded-full ${c.tone}`} aria-hidden="true" />
                  {c.label} <span className="text-ink tabular-nums">{c.n}</span>
                </li>
              ))}
              {e.member && (
                <li className="flex items-center gap-1.5">
                  <span className="h-[5px] w-3 rounded-full bg-marker" aria-hidden="true" />
                  Owning team
                </li>
              )}
            </ul>
          )}
          {person.depends && (
            <p className="mt-5 rounded-[12px] bg-proof-soft px-3.5 py-2.5 text-[14px] leading-snug text-[#a3271c]">
              {data.area.bus_factor === 1
                ? `${data.area.name} rests on ${person.name.split(' ')[0]} alone.`
                : `${data.area.name} hinges on ${person.name.split(' ')[0]}: they are on its minimum cut.`}
            </p>
          )}
        </div>

        <h3 className="mt-8 text-[13.5px] font-semibold text-ink">The evidence</h3>
        {person.docs.length ? (
          <ul className="mt-2 divide-y divide-line border-t border-line">
            {person.docs.map((d) => (
              <li key={d.id} className="py-3">
                <p className="text-[13px] text-muted">
                  <span className="font-semibold text-ink">{d.acts.map((a) => actLabel(a.rel, d.kind)).join(', ')}</span>
                  {' · '}
                  {kindLabel(d.kind)}
                  {d.date && <> · {formatDate(d.date)}</>}
                </p>
                {d.url ? (
                  <a href={d.url} target="_blank" rel="noreferrer" className="group mt-0.5 block text-[15px] leading-snug text-ink hover:text-cobalt">
                    {d.title ?? d.id}
                    <ArrowUpRight size={12} weight="bold" className="ml-1 inline align-[-1px] text-faint group-hover:text-cobalt" />
                  </a>
                ) : (
                  <p className="mt-0.5 text-[15px] leading-snug text-ink">{d.title ?? d.id}</p>
                )}
              </li>
            ))}
          </ul>
        ) : (
          <p className="mt-2 text-[14px] leading-relaxed text-muted">No documents yet: {person.name.split(' ')[0]} counts through the team that owns {data.area.name}.</p>
        )}

        {elsewhere && elsewhere.length > 0 && (
          <>
            <h3 className="mt-8 text-[13.5px] font-semibold text-ink">Also knows</h3>
            <p className="mt-2 text-[15px] leading-[1.9] text-muted">
              {elsewhere.map((a, i) => (
                <span key={a.slug}>
                  <button
                    type="button"
                    onClick={() => onArea(a.slug)}
                    className="rounded text-ink underline decoration-line-strong underline-offset-[5px] hover:decoration-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cobalt"
                  >
                    {a.name}
                  </button>
                  {i < elsewhere.length - 1 ? ', ' : ''}
                </span>
              ))}
            </p>
          </>
        )}
      </div>
    )
  },
)

// ----- the screen ------------------------------------------------------------------------------------------------

function Waiting({ label }: { label: string }) {
  const reduce = useReducedMotion()
  return (
    <div className="flex flex-col items-center py-16" role="status">
      <svg viewBox="0 0 120 120" className="size-[120px]" aria-hidden="true">
        {[0, 1, 2, 3, 4].map((i) => {
          const a = ((-58 + i * 72) * Math.PI) / 180
          return (
            <motion.line
              key={i}
              x1="60"
              y1="60"
              x2={60 + Math.cos(a) * 44}
              y2={60 + Math.sin(a) * 44}
              stroke="var(--line-strong)"
              strokeWidth="1.5"
              strokeLinecap="round"
              animate={reduce ? undefined : { opacity: [0.25, 1, 0.25] }}
              transition={{ duration: 1.6, repeat: Infinity, delay: i * 0.18 }}
            />
          )
        })}
        <circle cx="60" cy="60" r="12" fill="var(--marker)" />
      </svg>
      <p className="mt-4 text-[14px] text-muted">{label}</p>
    </div>
  )
}

export function WhoKnows({ ws }: { ws: Workspace }) {
  const [list, setList] = useState<Load<AreaSummary[]>>({ status: 'loading' })
  const [slug, setSlug] = useState<string | null>(readArea)
  const [people, setPeople] = useState<{ slug: string; load: Load<AreaPeople> } | null>(null)
  const [selected, setSelected] = useState<string | null>(null)
  const [dismissed, setDismissed] = useState(false)
  const [attempt, setAttempt] = useState(0)
  const wide = useWide()
  const reduce = useReducedMotion()
  const panel = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const ctrl = new AbortController()
    getAreas(ws.slug, ctrl.signal).then(
      (d) => setList({ status: 'ready', data: d.areas }),
      (e: Error) => e.name !== 'AbortError' && setList({ status: 'error', message: e.message }),
    )
    return () => ctrl.abort()
  }, [ws.slug, attempt])

  // With no area asked for, open on the one with the most evidence.
  const known = list.status === 'ready' ? list.data.filter((a) => a.people.length) : []
  const fallback = known.length ? [...known].sort((a, b) => b.evidence - a.evidence)[0].slug : null
  const active = slug && list.status === 'ready' && list.data.some((a) => a.slug === slug) ? slug : fallback

  useEffect(() => {
    if (!active) return
    writeArea(active)
    const ctrl = new AbortController()
    areaPeople(ws.slug, active, ctrl.signal).then(
      (d) => setPeople({ slug: active, load: { status: 'ready', data: d } }),
      (e: Error) => e.name !== 'AbortError' && setPeople({ slug: active, load: { status: 'error', message: e.message } }),
    )
    return () => ctrl.abort()
  }, [ws.slug, active, attempt])

  useEffect(() => {
    const onPop = () => setSlug(readArea())
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [])

  const load = people?.slug === active ? people.load : ({ status: 'loading' } as const)
  const data = load.status === 'ready' ? load.data : null
  // On a wide screen the strongest person is open from the start; on a phone the graph comes first.
  const current = data ? (data.people.find((p) => p.handle === selected) ?? data.people[0] ?? null) : null
  const asideOpen = wide && !dismissed && !!current
  const sheetOpen = !wide && !dismissed && selected !== null && !!current
  const shown = asideOpen || sheetOpen ? (current?.handle ?? null) : null

  const pickArea = (s: string) => {
    setSelected(null)
    setDismissed(false)
    setSlug(s)
  }
  const select = (handle: string) => {
    setSelected(handle)
    setDismissed(false)
  }
  const close = useCallback(() => setDismissed(true), [])

  useEffect(() => {
    if (sheetOpen) panel.current?.focus({ preventScroll: true })
  }, [sheetOpen, selected])

  useEffect(() => {
    if (!asideOpen && !sheetOpen) return
    const onKey = (e: globalThis.KeyboardEvent) => e.key === 'Escape' && close()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [asideOpen, sheetOpen, close])

  const area = list.status === 'ready' ? (list.data.find((a) => a.slug === active) ?? null) : null

  return (
    <div className="flex min-h-full min-w-0 flex-1 gap-3">
      <main className="slab relative flex min-w-0 flex-1 flex-col bg-paper">
        <div className="mx-auto w-full max-w-[960px] px-5 pt-8 pb-16 sm:px-10 sm:pt-12 lg:px-14">
          {list.status === 'error' ? (
            <Problem message={list.message} onRetry={() => setAttempt((n) => n + 1)} />
          ) : list.status === 'loading' ? (
            <Waiting label="Reading who did what" />
          ) : !known.length ? (
            <Empty ws={ws} />
          ) : (
            <>
              <AreaPicker list={list.data} current={area} onPick={pickArea} />
              {area && (
                <p className="mt-5 max-w-[640px] text-[16.5px] leading-relaxed text-muted sm:text-[18px]">
                  {area.owners.length ? <>Owned by {area.owners.map((o) => o.name).join(' and ')}. </> : null}
                  {area.bus_factor > 0 ? (
                    <>
                      {area.bus_factor === 1 ? 'One person' : `${area.bus_factor} people`} {area.bus_factor === 1 ? 'holds' : 'hold'} it through work of their own.{' '}
                      <a
                        href={ROUTES.busFactor}
                        onClick={(e) => {
                          e.preventDefault()
                          navigate(ROUTES.busFactor)
                        }}
                        className="whitespace-nowrap text-ink underline decoration-line-strong underline-offset-[5px] hover:decoration-ink"
                      >
                        See the bus factor
                      </a>
                    </>
                  ) : (
                    'Nobody has enough recent evidence to answer for it alone.'
                  )}
                </p>
              )}

              <div className="mt-8 sm:mt-10">
                {load.status === 'loading' && <Waiting label="Drawing who knows it" />}
                {load.status === 'error' && <Problem message={load.message} onRetry={() => setAttempt((n) => n + 1)} />}
                {data && (
                  <motion.div key={data.area.slug} initial={reduce ? false : { opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.3 }}>
                    <Radial data={data} selected={shown} onSelect={select} />
                    <p className="mt-2 text-center text-[13.5px] text-faint">
                      Closer and heavier means more evidence. Filled means {data.area.name} hinges on them.
                    </p>
                    <div className="mt-10">
                      <div className="mb-3 flex items-baseline justify-between gap-4">
                        <h2 className="text-[15px] font-semibold text-ink">Everyone with evidence</h2>
                        <span className="text-[13px] text-faint">{plural(data.total, 'person', 'people')}</span>
                      </div>
                      <Ranked data={data} selected={shown} onSelect={select} />
                    </div>
                  </motion.div>
                )}
              </div>
            </>
          )}
        </div>
      </main>

      <AnimatePresence>
        {asideOpen && current && data && (
          <motion.aside
            key="panel"
            aria-labelledby="person-title"
            className="slab sticky top-3 h-[calc(100dvh-24px)] w-[min(430px,38vw)] shrink-0 overflow-y-auto bg-paper px-7 pt-7 pb-10"
            initial={reduce ? false : { opacity: 0, x: 28 }}
            animate={{ opacity: 1, x: 0 }}
            exit={reduce ? { opacity: 0 } : { opacity: 0, x: 28 }}
            transition={{ duration: 0.4, ease }}
          >
            <PersonPanel ref={panel} ws={ws.slug} data={data} person={current} onClose={close} onArea={pickArea} />
          </motion.aside>
        )}
      </AnimatePresence>
      <AnimatePresence>
        {sheetOpen && current && data && (
          <>
            <motion.div
              key="scrim"
              className="fixed inset-0 z-40 bg-night/30"
              onClick={close}
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.25 }}
            />
            <motion.div
              key="sheet"
              role="dialog"
              aria-modal="true"
              aria-labelledby="person-title"
              className="fixed inset-x-0 bottom-0 z-50 flex max-h-[86dvh] flex-col rounded-t-[26px] bg-paper shadow-[0_-20px_60px_-20px_rgb(13_14_18/0.35)]"
              initial={reduce ? false : { y: '100%' }}
              animate={{ y: 0 }}
              exit={reduce ? { opacity: 0 } : { y: '100%' }}
              transition={{ duration: 0.45, ease }}
            >
              <div className="flex justify-center pt-3 pb-2" aria-hidden="true">
                <span className="h-1 w-10 rounded-full bg-line-strong" />
              </div>
              <div className="sheet-scroll overflow-y-auto px-5 pt-2 pb-10">
                <PersonPanel ref={panel} ws={ws.slug} data={data} person={current} onClose={close} onArea={pickArea} />
              </div>
            </motion.div>
          </>
        )}
      </AnimatePresence>
    </div>
  )
}

export function Problem({ message, onRetry }: { message: string; onRetry: () => void }) {
  const missing = message.includes('not in the graph') || message.includes('nothing in it')
  return (
    <div className="py-10" role="alert">
      <svg viewBox="0 0 150 40" className="mb-6 h-10 w-auto" aria-hidden="true">
        <path d="M 14 20 C 50 20, 60 20, 70 20" stroke="var(--line-strong)" strokeWidth="2" strokeLinecap="round" fill="none" />
        <path d="M 88 20 C 100 20, 115 20, 136 20" stroke="var(--line-strong)" strokeWidth="2" strokeLinecap="round" strokeDasharray="3 5" fill="none" />
        <path d="M 74 30 L 84 10" stroke="var(--proof)" strokeWidth="2.5" strokeLinecap="round" />
        <circle cx="14" cy="20" r="9" fill="var(--marker)" />
        <circle cx="136" cy="20" r="6" fill="var(--paper)" stroke="var(--line-strong)" strokeWidth="1.6" />
      </svg>
      <p className="display text-[28px] text-ink sm:text-[34px]">{missing ? 'Nothing here yet.' : 'That did not load.'}</p>
      <p className="mt-3 max-w-[520px] text-[17px] leading-relaxed text-muted">{message}</p>
      {!missing && (
        <button type="button" onClick={onRetry} className="mt-4 text-[15px] font-semibold text-cobalt hover:text-cobalt-deep">
          Try again
        </button>
      )}
    </div>
  )
}

export function Empty({ ws }: { ws: Workspace }) {
  return (
    <div className="py-10">
      <svg viewBox="0 0 160 110" className="h-[110px] w-auto" aria-hidden="true">
        {[
          [30, 26],
          [132, 20],
          [22, 88],
          [138, 92],
          [80, 104],
        ].map(([x, y], i) => (
          <g key={i}>
            <line x1="80" y1="55" x2={x} y2={y} stroke="var(--line)" strokeWidth="1.5" strokeDasharray="3 4" strokeLinecap="round" />
            <circle cx={x} cy={y} r="7" fill="var(--paper)" stroke="var(--line-strong)" strokeWidth="1.5" />
          </g>
        ))}
        <circle cx="80" cy="55" r="15" fill="var(--marker-soft)" stroke="var(--paper)" strokeWidth="4" />
      </svg>
      <p className="display mt-6 text-[28px] text-ink sm:text-[34px]">No one shows up in the record yet.</p>
      <p className="mt-3 max-w-[540px] text-[17px] leading-relaxed text-muted">
        Canon has not worked out who knows what in {ws.name} yet. That comes from pull requests, reviews and RFCs linked to its areas.
      </p>
    </div>
  )
}
