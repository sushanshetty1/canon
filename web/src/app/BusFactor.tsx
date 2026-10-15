// Bus factor: every area as a small flow from the area to the people who could answer for it, riskiest first.
// The proof-red line is the minimum cut from `algo.maxFlow`: the people the area depends on. Lose them and nobody
// left knows it.

import { ArrowRight } from '@phosphor-icons/react'
import { motion, useInView, useReducedMotion } from 'motion/react'
import { useEffect, useMemo, useState } from 'react'
import { Traveller } from '../sections/draw'
import { areas as getAreas, type AreaSummary } from './api'
import { ease } from './Answer'
import { shortName, useWide, useWidth } from './people'
import { navigate, ROUTES } from './router'
import { plural } from './text'
import { Empty, Problem } from './WhoKnows'
import type { Workspace } from './workspaces'

type Load = { status: 'loading' } | { status: 'error'; message: string } | { status: 'ready'; areas: AreaSummary[] }

const SHOWN = 5 // people drawn per area; the rest are counted
const ROW_GAP = 30

type Pt = { x: number; y: number }
const curve = (a: Pt, b: Pt) => `M ${a.x} ${a.y} C ${(a.x + b.x) / 2} ${a.y}, ${(a.x + b.x) / 2} ${b.y}, ${b.x} ${b.y}`

/** Where the curve from a to b crosses the vertical line at x. The curves are symmetric cubics: solve numerically. */
function crossing(a: Pt, b: Pt, x: number) {
  const mx = (a.x + b.x) / 2
  const bez = (t: number, p0: number, p1: number, p2: number, p3: number) => (1 - t) ** 3 * p0 + 3 * (1 - t) ** 2 * t * p1 + 3 * (1 - t) * t ** 2 * p2 + t ** 3 * p3
  let lo = 0
  let hi = 1
  for (let i = 0; i < 28; i++) {
    const t = (lo + hi) / 2
    if (bez(t, a.x, mx, mx, b.x) < x) lo = t
    else hi = t
  }
  return bez(lo, a.y, a.y, b.y, b.y)
}

/** How many people touched an area without knowing it well enough to answer for it. */
const below = (a: AreaSummary) => a.people.length + a.others - a.depends_on.length

function Flow({ area, index, compact }: { area: AreaSummary; index: number; compact: boolean }) {
  const { ref, width } = useWidth<HTMLDivElement>()
  const seen = useInView(ref, { once: true, amount: 0.6 })
  const reduce = !!useReducedMotion()
  const run = seen || reduce
  const people = area.depends_on.slice(0, compact ? 4 : SHOWN)
  const extra = area.depends_on.length - people.length
  const gap = compact ? 16 : ROW_GAP
  const height = Math.max(compact ? 52 : 64, people.length * gap + 16)
  const src = { x: 12, y: height / 2 }
  const px = compact ? width - 9 : Math.max(150, Math.min(300, width * 0.5))
  const cutX = src.x + (px - src.x) * 0.62
  const nodes = people.map((p, i) => ({ p, x: px, y: height / 2 + (i - (people.length - 1) / 2) * gap }))
  // Everyone else with some evidence: short strands that stop before the cut. They touched it; they could not answer.
  const strands = Math.min(below(area), compact ? 5 : 8)
  const spread = height - 14
  const stubs = Array.from({ length: strands }, (_, i) => {
    const f = strands === 1 ? 0.5 : i / (strands - 1)
    return { x: src.x + (cutX - src.x) * (0.62 + 0.14 * Math.sin(i * 2.4) ** 2), y: 7 + f * spread }
  })
  const later = (t: number) => (reduce ? 0 : t)
  const one = area.bus_factor === 1
  const names = people.map((p) => p.name).join(', ')

  return (
    <div ref={ref} className="w-full">
      {width > 0 && (
        <svg
          viewBox={`0 0 ${width} ${height}`}
          width={width}
          height={height}
          role="img"
          aria-label={`${area.name} depends on ${names}${extra ? ` and ${extra} more` : ''}`}
          className="block overflow-visible"
        >
          {stubs.map((t, i) => (
            <g key={`s${i}`}>
              <motion.path
                d={curve(src, t)}
                fill="none"
                stroke="var(--line-strong)"
                strokeWidth="1.2"
                strokeLinecap="round"
                initial={reduce ? false : { pathLength: 0 }}
                animate={run ? { pathLength: 1 } : undefined}
                transition={{ duration: 0.5, delay: later(0.2 + 0.03 * i), ease }}
              />
              <circle cx={t.x} cy={t.y} r="2.6" fill="var(--paper)" stroke="var(--line-strong)" strokeWidth="1.2" />
            </g>
          ))}
          {nodes.map((n, i) => (
            <motion.path
              key={`e${i}`}
              d={curve(src, n)}
              fill="none"
              stroke="var(--ink)"
              strokeWidth="2"
              strokeLinecap="round"
              initial={reduce ? false : { pathLength: 0 }}
              animate={run ? { pathLength: 1 } : undefined}
              transition={{ duration: 0.55, delay: later(0.05 * i), ease }}
            />
          ))}
          {!reduce && index < 8 && nodes.map((n, i) => <Traveller key={`t${i}`} d={curve(src, n)} run={run} delay={0.5 + i * 0.12} duration={0.9} r={3} fill="var(--marker)" />)}
          {/* The minimum cut: every path from the area to someone who knows it crosses it. */}
          <motion.line
            x1={cutX}
            y1={4}
            x2={cutX}
            y2={height - 4}
            stroke="var(--proof)"
            strokeWidth="2"
            strokeDasharray="5 4.5"
            strokeLinecap="round"
            initial={reduce ? false : { pathLength: 0 }}
            animate={run ? { pathLength: 1 } : undefined}
            transition={{ duration: 0.45, delay: later(1.1), ease }}
          />
          {nodes.map((n, i) => {
            const y = crossing(src, n, cutX)
            return (
              <motion.g
                key={`x${i}`}
                initial={reduce ? false : { opacity: 0, scale: 0.4 }}
                animate={run ? { opacity: 1, scale: 1 } : undefined}
                transition={{ duration: 0.3, delay: later(1.35 + i * 0.05), ease }}
                style={{ transformOrigin: `${cutX}px ${y}px` }}
              >
                <circle cx={cutX} cy={y} r="6.5" fill="var(--proof)" stroke="var(--paper)" strokeWidth="2" />
                <path d={`M ${cutX - 2.6} ${y - 2.6} l 5.2 5.2 m 0 -5.2 l -5.2 5.2`} stroke="var(--paper)" strokeWidth="1.6" strokeLinecap="round" />
              </motion.g>
            )
          })}
          {nodes.map((n, i) => (
            <g key={`n${i}`}>
              <circle cx={n.x} cy={n.y} r={compact ? 6 : 7.5} fill={one ? 'var(--proof)' : 'var(--ink)'} />
              {!compact && (
                <text x={n.x + 15} y={n.y + 4.5} fontSize="14" fontWeight="550" fill="var(--ink)">
                  {width < 420 ? shortName(n.p.name, n.p.handle) : n.p.name}
                </text>
              )}
            </g>
          ))}
          {extra > 0 && !compact && (
            <text x={px + 15} y={height - 2} fontSize="12.5" fill="var(--faint)">
              and {extra} more
            </text>
          )}
          <circle cx={src.x} cy={src.y} r="10" fill="var(--marker)" stroke="var(--paper)" strokeWidth="3" />
        </svg>
      )}
    </div>
  )
}

function Row({ area, index, compact }: { area: AreaSummary; index: number; compact: boolean }) {
  const href = `${ROUTES.whoKnows}?area=${encodeURIComponent(area.slug)}`
  const one = area.bus_factor === 1
  const others = below(area)
  const names = area.depends_on.map((p) => (area.depends_on.length > 1 ? shortName(p.name, p.handle) : p.name))
  return (
    <li>
      <a
        href={href}
        onClick={(e) => {
          e.preventDefault()
          navigate(href)
        }}
        className="group grid grid-cols-[30px_minmax(0,1fr)_96px] items-center gap-x-3 rounded-[16px] px-1 py-4 transition-colors hover:bg-paper-2/70 focus-visible:bg-paper-2 focus-visible:outline-none sm:grid-cols-[64px_minmax(180px,250px)_minmax(0,1fr)] sm:gap-x-6 sm:rounded-[18px] sm:px-4 sm:py-5"
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
          {compact ? (
            <span className={`mt-0.5 block truncate text-[13.5px] ${one ? 'text-proof' : 'text-ink'}`}>
              {names.length > 3 ? `${names.slice(0, 3).join(', ')} and ${names.length - 3} more` : names.join(names.length === 2 ? ' and ' : ', ')}
            </span>
          ) : (
            others > 0 && <span className="mt-0.5 block text-[13px] text-faint">{plural(others, 'other', 'others')} with less evidence</span>
          )}
        </span>
        <span className="min-w-0">
          <Flow area={area} index={index} compact={compact} />
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
              <motion.path
                key={i}
                d={curve({ x: 12, y: 32 }, { x: 150, y })}
                fill="none"
                stroke="var(--line-strong)"
                strokeWidth="2"
                animate={reduce ? undefined : { opacity: [0.3, 1, 0.3] }}
                transition={{ duration: 1.6, repeat: Infinity, delay: r * 0.2 + i * 0.1 }}
              />
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
            <p className="mt-5 max-w-[640px] text-[16.5px] leading-relaxed text-muted sm:text-[18px]">
              For each area, the people who could still answer for it if everyone else left, from who wrote, reviewed and decided its work. The red line is
              the cut: lose those people and nobody left knows it.
            </p>
            <div className="mt-8 max-w-[640px]">
              <Spread areas={risky} />
            </div>

            <ol className="mt-10 divide-y divide-line border-y border-line sm:mt-12">
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
