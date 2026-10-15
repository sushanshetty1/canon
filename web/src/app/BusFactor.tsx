// Bus factor: every area as its flow network, riskiest first. Knowledge flows from the area through the documents
// that hold it (each one can back a single person) to the people who know it. The maximum flow is how many people
// hold the area through work of their own; the proof-red line is the minimum cut, through the people or the
// documents the area hinges on.

import { ArrowRight } from '@phosphor-icons/react'
import { motion, useInView, useReducedMotion } from 'motion/react'
import { useEffect, useMemo, useState } from 'react'
import { Traveller } from '../sections/draw'
import { areas as getAreas, type AreaSummary, type DocRef, type FlowPerson } from './api'
import { ease } from './Answer'
import { shortName, useWide, useWidth } from './people'
import { navigate, ROUTES } from './router'
import { kindLabel, plural } from './text'
import { Empty, Problem } from './WhoKnows'
import type { Workspace } from './workspaces'

type Load = { status: 'loading' } | { status: 'error'; message: string } | { status: 'ready'; areas: AreaSummary[] }

type Pt = { x: number; y: number }
const curve = (a: Pt, b: Pt) => `M ${a.x} ${a.y} C ${(a.x + b.x) / 2} ${a.y}, ${(a.x + b.x) / 2} ${b.y}, ${b.x} ${b.y}`

/** A document's short name: "#12345" for a pull request or issue, else its title. */
function docLabel(d: DocRef): string {
  const n = /^(?:pull|issue):(\d+)$/.exec(d.id)
  return n ? `#${n[1]}` : (d.title ?? d.id)
}

type Drawn = { person: FlowPerson; y: number; shown: number }
type Page = { key: string; doc: DocRef | null; y: number; flows: boolean; cut: boolean; people: Drawn[] }

/** Who and what to draw for one area. People: those in its flow, strongest first, with everyone on or behind the cut
 *  always included. Documents: the one the flow routed to each person, drawn solid, and a few more of each person's
 *  own, drawn faint, so a person holding hundreds shows as a fan of pages into one node. Everything else is counted. */
function plan(area: AreaSummary, maxPeople: number, maxPages: number, gap: number, pageGap: number) {
  const net = area.network
  const hinge = new Set(area.hinges_on.flatMap((h) => h.people))
  const must = net.filter((p) => p.cut || hinge.has(p.handle))
  const rest = net.filter((p) => !must.includes(p))
  const people = [...must, ...rest].slice(0, Math.max(maxPeople, must.length)).sort((a, b) => b.docs - a.docs || a.handle.localeCompare(b.handle))
  const cutDocs = new Set(area.hinges_on.map((h) => h.id))

  // Pages per person: their routed document, then faint ones for the rest of what they hold, sharing what room is left.
  const vias = new Set(people.filter((p) => p.via).map((p) => p.via!.id))
  let room = Math.max(0, maxPages - vias.size)
  const spare = people.map((p) => Math.max(0, p.docs - (p.via ? 1 : 0)))
  const total = spare.reduce((s, n) => s + n, 0) || 1
  const extra = spare.map((n) => Math.min(n, Math.round((n / total) * room)))
  room -= extra.reduce((s, n) => s + n, 0)
  for (let i = 0; room > 0 && i < people.length; i++)
    if (spare[i] > extra[i]) {
      extra[i] += 1
      room -= 1
    }

  const pages: Page[] = []
  const owner: Map<string, Page> = new Map()
  const groups = people.map((person, i) => {
    const mine: Page[] = []
    for (let k = 0; k < extra[i]; k++) mine.push({ key: `${person.handle}-${k}`, doc: null, y: 0, flows: false, cut: false, people: [] })
    if (person.via) {
      // The routed document sits in the middle of the person's pages, level with them.
      const page = owner.get(person.via.id) ?? { key: person.via.id, doc: person.via, y: 0, flows: true, cut: cutDocs.has(person.via.id), people: [] }
      owner.set(person.via.id, page)
      mine.splice(Math.floor(mine.length / 2), 0, page)
    }
    for (const page of mine) if (!pages.includes(page)) pages.push(page)
    return mine
  })

  const height = Math.max(64, people.length * gap + 18, pages.length * pageGap + 18)
  const drawn: Drawn[] = people.map((person, i) => ({
    person,
    y: height / 2 + (i - (people.length - 1) / 2) * gap,
    shown: groups[i].length,
  }))
  pages.forEach((p, i) => (p.y = height / 2 + (i - (pages.length - 1) / 2) * pageGap))
  groups.forEach((mine, i) => mine.forEach((p) => p.people.includes(drawn[i]) || p.people.push(drawn[i])))
  // People the flow could not use reach the shared document they know the area through.
  for (const h of area.hinges_on) {
    const page = owner.get(h.id)
    for (const handle of h.people) {
      const d = drawn.find((x) => x.person.handle === handle)
      if (page && d && !page.people.includes(d)) page.people.push(d)
    }
  }
  return { drawn, pages, height, hidden: net.length - people.length }
}

function Flow({ area, index, compact }: { area: AreaSummary; index: number; compact: boolean }) {
  const { ref, width } = useWidth<HTMLDivElement>()
  const seen = useInView(ref, { once: true, amount: 0.5 })
  const reduce = !!useReducedMotion()
  const run = seen || reduce
  const later = (t: number) => (reduce ? 0 : t)
  const { drawn, pages, height, hidden } = plan(area, compact ? 3 : 5, compact ? 5 : 7, compact ? 22 : 30, compact ? 13 : 15.5)

  const src = { x: 11, y: height / 2 }
  const x1 = compact ? width * 0.42 : Math.max(110, Math.min(190, width * 0.3)) // documents
  const x2 = compact ? width - 10 : x1 + Math.max(80, Math.min(130, width * 0.22)) // people
  const one = area.bus_factor === 1

  // The cut runs just before each document and person on it, and curves between them, top to bottom.
  const marks = [
    ...pages.filter((p) => p.cut).map((p) => ({ x: x1 - 14, y: p.y })),
    ...drawn.filter((d) => d.person.cut).map((d) => ({ x: x2 - 15, y: d.y })),
  ].sort((a, b) => a.y - b.y)
  let cutPath = ''
  if (marks.length) {
    const pts = [{ x: marks[0].x, y: 3 }, ...marks, { x: marks[marks.length - 1].x, y: height - 3 }]
    cutPath = `M ${pts[0].x} ${pts[0].y}`
    for (let i = 1; i < pts.length; i++) {
      const a = pts[i - 1]
      const b = pts[i]
      const my = (a.y + b.y) / 2
      cutPath += ` C ${a.x} ${my}, ${b.x} ${my}, ${b.x} ${b.y}`
    }
  }

  const label = `${area.name}: ${plural(area.bus_factor, 'person', 'people')} hold it through work of their own, out of ${plural(area.network.length, 'person', 'people')} with evidence in ${plural(area.evidence_docs, 'document')}`

  return (
    <div ref={ref} className="w-full">
      {width > 0 && (
        <svg viewBox={`0 0 ${width} ${height}`} width={width} height={height} role="img" aria-label={label} className="block overflow-visible">
          {/* Area to documents: one unit each */}
          {pages.map((p, i) => (
            <motion.path
              key={`ad-${p.key}`}
              d={curve(src, { x: x1 - 5, y: p.y })}
              fill="none"
              stroke={p.flows ? 'var(--ink)' : 'var(--line-strong)'}
              strokeWidth={p.flows ? 1.8 : 1.1}
              strokeLinecap="round"
              initial={reduce ? false : { pathLength: 0 }}
              animate={run ? { pathLength: 1 } : undefined}
              transition={{ duration: 0.5, delay: later(0.03 * i), ease }}
            />
          ))}
          {/* Documents to people: solid where the flow runs */}
          {pages.flatMap((p) =>
            p.people.map((d) => {
              const used = p.flows && d.person.via?.id === p.key
              const shared = p.flows && !used
              return (
                <motion.path
                  key={`dp-${p.key}-${d.person.handle}`}
                  d={curve({ x: x1 + 5, y: p.y }, { x: x2 - 7, y: d.y })}
                  fill="none"
                  stroke={used ? 'var(--ink)' : 'var(--line-strong)'}
                  strokeWidth={used ? 1.8 : 1.1}
                  strokeDasharray={shared ? '3 3.5' : undefined}
                  strokeLinecap="round"
                  initial={reduce ? false : { pathLength: 0 }}
                  animate={run ? { pathLength: 1 } : undefined}
                  transition={{ duration: 0.45, delay: later(0.35), ease }}
                />
              )
            }),
          )}
          {!reduce &&
            index < 6 &&
            pages
              .filter((p) => p.flows)
              .map((p, i) => {
                const to = drawn.find((d) => d.person.via?.id === p.key)
                const path = `${curve(src, { x: x1, y: p.y })} ${to ? curve({ x: x1, y: p.y }, { x: x2, y: to.y }).replace('M', 'L') : ''}`
                return <Traveller key={`t-${p.key}`} d={path} run={run} delay={0.6 + i * 0.12} duration={1.1} r={3} fill="var(--marker)" />
              })}

          {/* Documents: a page each */}
          {pages.map((p) => (
            <g key={`pg-${p.key}`}>
              <rect
                x={x1 - 5}
                y={p.y - 6}
                width="10"
                height="12.5"
                rx="2"
                fill="var(--paper)"
                stroke={p.flows ? 'var(--ink)' : 'var(--line-strong)'}
                strokeWidth={p.flows ? 1.6 : 1.2}
              />
              {p.flows && <path d={`M ${x1 - 2.4} ${p.y - 1.6} h 5 M ${x1 - 2.4} ${p.y + 1.5} h 3.5`} stroke="var(--ink)" strokeWidth="1.1" strokeLinecap="round" />}
            </g>
          ))}

          {/* The minimum cut */}
          {cutPath && (
            <motion.path
              d={cutPath}
              fill="none"
              stroke="var(--proof)"
              strokeWidth="2"
              strokeDasharray="5 4.5"
              strokeLinecap="round"
              initial={reduce ? false : { pathLength: 0 }}
              animate={run ? { pathLength: 1 } : undefined}
              transition={{ duration: 0.6, delay: later(1.1), ease }}
            />
          )}
          {marks.map((m, i) => (
            <motion.g
              key={`x${i}`}
              initial={reduce ? false : { opacity: 0, scale: 0.4 }}
              animate={run ? { opacity: 1, scale: 1 } : undefined}
              transition={{ duration: 0.3, delay: later(1.5 + i * 0.05), ease }}
              style={{ transformOrigin: `${m.x}px ${m.y}px` }}
            >
              <circle cx={m.x} cy={m.y} r="6.5" fill="var(--proof)" stroke="var(--paper)" strokeWidth="2" />
              <path d={`M ${m.x - 2.6} ${m.y - 2.6} l 5.2 5.2 m 0 -5.2 l -5.2 5.2`} stroke="var(--paper)" strokeWidth="1.6" strokeLinecap="round" />
            </motion.g>
          ))}

          {/* People, with how much of the area's record they hold */}
          {drawn.map((d) => {
            const counted = !!d.person.via
            const name = width < 420 ? shortName(d.person.name, d.person.handle) : d.person.name
            return (
              <g key={`p-${d.person.handle}`}>
                <circle
                  cx={x2}
                  cy={d.y}
                  r={compact ? 6 : 7}
                  fill={counted ? (one && d.person.cut ? 'var(--proof)' : 'var(--ink)') : 'var(--paper)'}
                  stroke={counted ? 'none' : 'var(--line-strong)'}
                  strokeWidth="1.6"
                />
                {!compact && (
                  <text x={x2 + 15} y={d.y + 4.5} fontSize="14" fontWeight={counted ? 550 : 450} fill={counted ? 'var(--ink)' : 'var(--faint)'}>
                    {name}
                    <tspan fill="var(--faint)" fontWeight="450" fontSize="12.5">
                      {'  '}
                      {width < 420 ? d.person.docs : plural(d.person.docs, 'document')}
                    </tspan>
                  </text>
                )}
              </g>
            )
          })}
          {!compact && hidden > 0 && (
            <text x={x2 + 15} y={height - 1} fontSize="12" fill="var(--faint)">
              and {hidden} more
            </text>
          )}
          <circle cx={src.x} cy={src.y} r="10" fill="var(--marker)" stroke="var(--paper)" strokeWidth="3" />
        </svg>
      )}
    </div>
  )
}

/** What the cut runs through, in words. */
function cutWords(area: AreaSummary, compact: boolean): string {
  const people = area.depends_on.map((p) => (compact || area.depends_on.length > 2 ? shortName(p.name, p.handle) : p.name))
  const docs = area.hinges_on.map((d) => `${kindLabel(d.kind).toLowerCase()} ${docLabel(d)}`)
  const parts = [...people, ...docs]
  if (parts.length > 3) return `${parts.slice(0, 3).join(', ')} and ${parts.length - 3} more`
  return parts.length === 2 ? parts.join(' and ') : parts.join(', ')
}

function Row({ area, index, compact }: { area: AreaSummary; index: number; compact: boolean }) {
  const href = `${ROUTES.whoKnows}?area=${encodeURIComponent(area.slug)}`
  const one = area.bus_factor === 1
  const held = area.network.length
  return (
    <li>
      <a
        href={href}
        onClick={(e) => {
          e.preventDefault()
          navigate(href)
        }}
        className="group grid grid-cols-[30px_minmax(0,1fr)] items-center gap-x-3 gap-y-3 rounded-[16px] px-1 py-4 transition-colors hover:bg-paper-2/70 focus-visible:bg-paper-2 focus-visible:outline-none sm:grid-cols-[64px_minmax(180px,240px)_minmax(0,1fr)] sm:gap-x-6 sm:rounded-[18px] sm:px-4 sm:py-5"
      >
        <span className={`font-display text-[34px] leading-none font-semibold tracking-[-0.05em] tabular-nums sm:text-[52px] ${one ? 'text-proof' : 'text-ink'}`}>
          {area.bus_factor}
        </span>
        <span className="min-w-0">
          <span className="flex items-center gap-1.5 text-[17px] leading-snug font-semibold tracking-[-0.01em] text-ink">
            <span className="truncate">{area.name}</span>
            <ArrowRight size={14} weight="bold" className="shrink-0 text-faint opacity-0 transition-opacity group-hover:opacity-100" />
          </span>
          <span className="mt-0.5 block truncate text-[14px] text-muted">{area.owners.map((o) => o.name).join(', ') || 'No owner in the map'}</span>
          <span className={`mt-0.5 block text-[13.5px] leading-snug ${compact ? (one ? 'text-proof' : 'text-ink') : 'text-faint'}`}>
            {compact ? (
              <span className="line-clamp-2">Hinges on {cutWords(area, true)}</span>
            ) : held > area.bus_factor ? (
              `${held} people know it, through ${plural(area.evidence_docs, 'document')}; ${held - area.bus_factor} only through work another holds`
            ) : (
              `${plural(held, 'person', 'people')}, ${plural(area.evidence_docs, 'document')}`
            )}
          </span>
        </span>
        <span className="col-span-2 min-w-0 sm:col-span-1">
          <Flow area={area} index={index} compact={false} />
          {!compact && area.hinges_on.length > 0 && (
            <span className="mt-2 block text-[13px] leading-snug text-muted">
              Hinges on{' '}
              {area.hinges_on.slice(0, 2).map((d, i) => (
                <span key={d.id}>
                  {i > 0 && ' and '}
                  <span className="text-ink">{kindLabel(d.kind)} {docLabel(d)}</span>
                  {d.title && docLabel(d).startsWith('#') && <span className="text-faint"> {d.title.length > 48 ? `${d.title.slice(0, 46)}…` : d.title}</span>}
                </span>
              ))}
            </span>
          )}
        </span>
      </a>
    </li>
  )
}

/** How the areas spread over bus factors, as one bar split by count. */
function Spread({ areas }: { areas: AreaSummary[] }) {
  const reduce = useReducedMotion()
  const groups = [
    { label: 'rest on one person', n: areas.filter((a) => a.bus_factor === 1).length, tone: 'bg-proof', text: 'text-proof' },
    { label: 'on two', n: areas.filter((a) => a.bus_factor === 2).length, tone: 'bg-ink', text: 'text-ink' },
    { label: 'on three or more', n: areas.filter((a) => a.bus_factor >= 3).length, tone: 'bg-line-strong', text: 'text-muted' },
  ].filter((g) => g.n)
  const total = groups.reduce((s, g) => s + g.n, 0) || 1
  return (
    <div>
      <div className="flex h-3 gap-1" aria-hidden="true">
        {groups.map((g, i) => (
          <motion.span
            key={g.label}
            className={`origin-left rounded-full ${g.tone}`}
            style={{ width: `${(100 * g.n) / total}%` }}
            initial={reduce ? false : { scaleX: 0 }}
            animate={{ scaleX: 1 }}
            transition={{ duration: 0.6, delay: reduce ? 0 : 0.15 + i * 0.12, ease }}
          />
        ))}
      </div>
      <ul className="mt-3 flex flex-wrap gap-x-6 gap-y-1 text-[14.5px] text-muted">
        {groups.map((g) => (
          <li key={g.label}>
            <span className={`font-semibold tabular-nums ${g.text}`}>{g.n}</span> {g.label}
          </li>
        ))}
      </ul>
    </div>
  )
}

/** How to read a row, drawn small: the area, documents, people, and the cut. */
function Key({ shared }: { shared: boolean }) {
  return (
    <ul className="flex flex-wrap items-center gap-x-6 gap-y-2 text-[13.5px] text-muted">
      <li className="flex items-center gap-2">
        <svg viewBox="0 0 14 14" className="size-3.5" aria-hidden="true">
          <circle cx="7" cy="7" r="6" fill="var(--marker)" />
        </svg>
        The area
      </li>
      <li className="flex items-center gap-2">
        <svg viewBox="0 0 12 15" className="h-3.5 w-3" aria-hidden="true">
          <rect x="1" y="1" width="10" height="13" rx="2" fill="var(--paper)" stroke="var(--ink)" strokeWidth="1.6" />
        </svg>
        A document: backs one person
      </li>
      <li className="flex items-center gap-2">
        <svg viewBox="0 0 14 14" className="size-3.5" aria-hidden="true">
          <circle cx="7" cy="7" r="6" fill="var(--ink)" />
        </svg>
        Counted
      </li>
      {shared && (
        <li className="flex items-center gap-2">
          <svg viewBox="0 0 14 14" className="size-3.5" aria-hidden="true">
            <circle cx="7" cy="7" r="5.5" fill="var(--paper)" stroke="var(--line-strong)" strokeWidth="1.6" />
          </svg>
          Knows it only through work another holds
        </li>
      )}
      <li className="flex items-center gap-2">
        <svg viewBox="0 0 22 10" className="h-2.5 w-[22px]" aria-hidden="true">
          <path d="M1 5 H21" stroke="var(--proof)" strokeWidth="2" strokeDasharray="4 3" strokeLinecap="round" />
        </svg>
        The cut
      </li>
    </ul>
  )
}

function Waiting() {
  const reduce = useReducedMotion()
  const rows = [1, 2, 1]
  return (
    <div className="space-y-6 py-10" role="status" aria-label="Reading the graph">
      {rows.map((n, r) => (
        <svg key={r} viewBox="0 0 260 64" className="h-16 w-[260px]" aria-hidden="true">
          {Array.from({ length: n }, (_, i) => {
            const y = 32 + (i - (n - 1) / 2) * 30
            return (
              <g key={i}>
                <motion.path
                  d={`${curve({ x: 12, y: 32 }, { x: 110, y })} L 190 ${y}`}
                  fill="none"
                  stroke="var(--line-strong)"
                  strokeWidth="2"
                  animate={reduce ? undefined : { opacity: [0.3, 1, 0.3] }}
                  transition={{ duration: 1.6, repeat: Infinity, delay: r * 0.2 + i * 0.1 }}
                />
                <rect x="105" y={y - 6} width="10" height="13" rx="2" fill="var(--paper)" stroke="var(--line-strong)" strokeWidth="1.4" />
              </g>
            )
          })}
          <circle cx="12" cy="32" r="9" fill="var(--marker-soft)" />
        </svg>
      ))}
      <p className="text-[14px] text-muted">Running the flow for every area</p>
    </div>
  )
}

export function BusFactor({ ws }: { ws: Workspace }) {
  const [load, setLoad] = useState<Load>({ status: 'loading' })
  const [attempt, setAttempt] = useState(0)
  const [all, setAll] = useState(false)
  const roomy = useWide('(min-width: 640px)')

  useEffect(() => {
    const ctrl = new AbortController()
    getAreas(ws.slug, ctrl.signal).then(
      (d) => setLoad({ status: 'ready', areas: d.areas }),
      (e: Error) => e.name !== 'AbortError' && setLoad({ status: 'error', message: e.message }),
    )
    return () => ctrl.abort()
  }, [ws.slug, attempt])

  const { risky, silent } = useMemo(() => {
    const list = load.status === 'ready' ? load.areas : []
    return { risky: list.filter((a) => a.bus_factor > 0), silent: list.filter((a) => a.bus_factor === 0) }
  }, [load])
  const ones = risky.filter((a) => a.bus_factor === 1).length
  const shown = all ? risky : risky.slice(0, roomy ? 24 : 12)

  return (
    <main className="slab relative flex min-w-0 flex-1 flex-col bg-paper">
      <div className="mx-auto w-full max-w-[1000px] px-5 pt-8 pb-16 sm:px-10 sm:pt-12 lg:px-14">
        {load.status === 'error' ? (
          <Problem message={load.message} onRetry={() => setAttempt((n) => n + 1)} />
        ) : load.status === 'loading' ? (
          <Waiting />
        ) : !risky.length ? (
          <Empty ws={ws} />
        ) : (
          <>
            <h1 className="display max-w-[820px] text-[38px] text-balance text-ink sm:text-[56px] lg:text-[64px]">
              {ones ? (
                <>
                  <span className="text-proof">{ones === 1 ? 'One area rests' : `${ones} areas rest`}</span> on one person.
                </>
              ) : (
                'No area rests on one person.'
              )}
            </h1>
            <p className="mt-5 max-w-[660px] text-[16.5px] leading-relaxed text-muted sm:text-[18px]">
              The number is how many people hold an area through work of their own. A pull request, review or RFC backs one person, however many touched it.
              The red line is the minimum cut: the people, or the documents, the area hinges on.
            </p>
            <div className="mt-8 max-w-[660px]">
              <Spread areas={risky} />
            </div>
            <div className="mt-8">
              <Key shared={risky.some((a) => a.network.some((p) => !p.via))} />
            </div>

            <ol className="mt-8 divide-y divide-line border-y border-line">
              {shown.map((a, i) => (
                <Row key={a.slug} area={a} index={i} compact={!roomy} />
              ))}
            </ol>
            {risky.length > shown.length && (
              <button
                type="button"
                onClick={() => setAll(true)}
                className="mt-6 inline-flex h-11 items-center rounded-full px-5 text-[14.5px] font-semibold text-ink shadow-[inset_0_0_0_1.5px_var(--line-strong)] transition-shadow hover:shadow-[inset_0_0_0_1.5px_var(--ink)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cobalt"
              >
                Show all {risky.length} areas
              </button>
            )}

            {silent.length > 0 && (
              <section className="mt-14 max-w-[760px]">
                <h2 className="text-[15px] font-semibold text-ink">No one shows up for {plural(silent.length, 'area')}</h2>
                <p className="mt-2 text-[15px] leading-[1.75] text-muted">
                  Nothing written, reviewed or decided about these in the record Canon reads, so it cannot say who would answer:{' '}
                  {silent.map((a) => a.name).join(', ')}.
                </p>
              </section>
            )}
          </>
        )}
      </div>
    </main>
  )
}
