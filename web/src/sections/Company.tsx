import { motion } from 'motion/react'
import type { ReactNode } from 'react'
import { Container, Slab } from '../ui'
import { ease, useSeen } from './draw'

// PostHog's public record, counted from its repositories and site on 15 October 2026.
const TEAMS = 58
const DOCS = 44
const ISSUES = 11479
const THREADS = 6830
/** Issues and threads are drawn as one dot for every fifty. */
const PER_DOT = 50

/** A small seeded random, so the constellation is the same on every load. */
function seeded(seed: number) {
  let a = seed
  return () => {
    a |= 0
    a = (a + 0x6d2b79f5) | 0
    let t = Math.imul(a ^ (a >>> 15), 1 | a)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

type P = { x: number; y: number }
type Expanded = P & { name: string; members: number; areas: number; turn: number }

// Three teams opened up to show their people (dots) and the areas they own (squares).
const expanded: Expanded[] = [
  { name: 'Replay', x: 226, y: 218, members: 6, areas: 2, turn: 0.3 },
  { name: 'Feature flags', x: 452, y: 318, members: 5, areas: 3, turn: 1.1 },
  { name: 'Product analytics', x: 262, y: 470, members: 7, areas: 2, turn: 2.2 },
]

/**
 * 58 teams in a loose, round field: a sunflower spiral (even, organic spacing), then relaxed so
 * the three opened teams have room for their people and areas.
 */
const CENTER = { x: 320, y: 340 }
const FIELD_R = 290
const teams: P[] = (() => {
  const rnd = seeded(58)
  const golden = Math.PI * (3 - Math.sqrt(5))
  const pts = Array.from({ length: TEAMS - expanded.length }, (_, i) => {
    const r = 36 * Math.sqrt(i + 0.6)
    const a = i * golden
    return { x: CENTER.x + Math.cos(a) * r + (rnd() - 0.5) * 18, y: CENTER.y + Math.sin(a) * r + (rnd() - 0.5) * 18 }
  })
  for (let step = 0; step < 120; step++) {
    for (const p of pts) {
      for (const e of expanded) {
        const d = Math.hypot(p.x - e.x, p.y - e.y)
        if (d < 84) {
          const push = (84 - d) / 2
          p.x += ((p.x - e.x) / (d || 1)) * push
          p.y += ((p.y - e.y) / (d || 1)) * push
        }
      }
      for (const q of pts) {
        if (q === p) continue
        const d = Math.hypot(p.x - q.x, p.y - q.y)
        if (d < 50) {
          const push = (50 - d) / 4
          p.x += ((p.x - q.x) / (d || 1)) * push
          p.y += ((p.y - q.y) / (d || 1)) * push
        }
      }
      const d = Math.hypot(p.x - CENTER.x, p.y - CENTER.y)
      if (d > FIELD_R) {
        p.x = CENTER.x + ((p.x - CENTER.x) / d) * FIELD_R
        p.y = CENTER.y + ((p.y - CENTER.y) / d) * FIELD_R
      }
    }
  }
  return pts
})()

const satellites = (e: Expanded) => {
  const people = Array.from({ length: e.members }, (_, i) => {
    const a = e.turn + (i / e.members) * Math.PI * 2
    return { x: e.x + Math.cos(a) * 34, y: e.y + Math.sin(a) * 34 }
  })
  const areas = Array.from({ length: e.areas }, (_, i) => {
    const a = e.turn + 0.45 + (i / e.areas) * Math.PI * 2
    return { x: e.x + Math.cos(a) * 54, y: e.y + Math.sin(a) * 54 }
  })
  return { people, areas }
}

const appear = (p: P) => 0.15 + (Math.hypot(p.x - CENTER.x, p.y - CENTER.y) / FIELD_R) * 0.9

function TeamsField({ run, reduce, k = 1, labelSize = 13 }: { run: boolean; reduce: boolean; k?: number; labelSize?: number }) {
  const later = (t: number) => (reduce ? 0 : t)
  return (
    <g>
      {teams.map((t, i) => (
        <motion.circle
          key={i}
          cx={t.x}
          cy={t.y}
          r={6 * k}
          fill="#646a76"
          initial={reduce ? false : { opacity: 0, scale: 0 }}
          animate={run ? { opacity: 1, scale: 1 } : undefined}
          transition={{ duration: 0.4, delay: later(appear(t)), ease }}
        />
      ))}
      {expanded.map((e) => {
        const { people, areas } = satellites(e)
        const t = later(1.25)
        return (
          <g key={e.name}>
            {[...people, ...areas].map((p, i) => (
              <motion.line
                key={i}
                x1={e.x}
                y1={e.y}
                x2={p.x}
                y2={p.y}
                stroke={i >= people.length ? 'rgb(255 226 74 / 0.5)' : '#4a4f5b'}
                strokeWidth="1.25"
                initial={reduce ? false : { pathLength: 0 }}
                animate={run ? { pathLength: 1 } : undefined}
                transition={{ duration: 0.5, delay: t + i * 0.04, ease }}
              />
            ))}
            {people.map((p, i) => (
              <motion.circle
                key={i}
                cx={p.x}
                cy={p.y}
                r={3.8 * k}
                fill="var(--paper)"
                initial={reduce ? false : { opacity: 0 }}
                animate={run ? { opacity: 1 } : undefined}
                transition={{ duration: 0.3, delay: t + 0.35 + i * 0.04 }}
              />
            ))}
            {areas.map((p, i) => (
              <motion.rect
                key={i}
                x={p.x - 5 * k}
                y={p.y - 5 * k}
                width={10 * k}
                height={10 * k}
                rx={2.5 * k}
                fill="var(--marker)"
                initial={reduce ? false : { opacity: 0 }}
                animate={run ? { opacity: 1 } : undefined}
                transition={{ duration: 0.3, delay: t + 0.5 + i * 0.06 }}
              />
            ))}
            <motion.circle
              cx={e.x}
              cy={e.y}
              r={10 * k}
              fill="var(--night)"
              stroke="var(--paper)"
              strokeWidth={2.25 * k}
              initial={reduce ? false : { opacity: 0, scale: 0 }}
              animate={run ? { opacity: 1, scale: 1 } : undefined}
              transition={{ duration: 0.45, delay: later(appear(e)), ease }}
            />
            <motion.text
              x={e.x}
              y={e.y + 66 + labelSize * 0.6}
              textAnchor="middle"
              fontSize={labelSize}
              fontWeight="600"
              fill="var(--paper)"
              stroke="var(--night)"
              strokeWidth={labelSize * 0.6}
              strokeLinejoin="round"
              style={{ paintOrder: 'stroke' }}
              initial={reduce ? false : { opacity: 0 }}
              animate={run ? { opacity: 1 } : undefined}
              transition={{ duration: 0.4, delay: t + 0.6 }}
            >
              {e.name}
            </motion.text>
          </g>
        )
      })}
    </g>
  )
}

const DOC_COLS = 11
/** The 44 design docs, each its own little page. One is the doc the Replay team wrote. */
function DocsField({ run, reduce, lit = 14 }: { run: boolean; reduce: boolean; lit?: number }) {
  return (
    <g>
      {Array.from({ length: DOCS }, (_, i) => {
        const x = (i % DOC_COLS) * 21
        const y = Math.floor(i / DOC_COLS) * 25
        const on = i === lit
        return (
          <motion.path
            key={i}
            d={`M ${x} ${y} h 9 l 4 4 v 13 h -13 z`}
            fill={on ? 'var(--cobalt)' : 'var(--night-2)'}
            stroke={on ? 'var(--cobalt)' : '#7d828e'}
            strokeWidth="1.25"
            strokeLinejoin="round"
            initial={reduce ? false : { opacity: 0 }}
            animate={run ? { opacity: 1 } : undefined}
            transition={{ duration: 0.25, delay: reduce ? 0 : 0.9 + i * 0.025 }}
          />
        )
      })}
    </g>
  )
}

/** A field of dots, one for every fifty. A few are lit where an opened team connects. */
function Dust({ count, cols, color, lit = [], run, reduce, delay, seed, r = 1.9 }: { count: number; cols: number; color: string; lit?: number[]; run: boolean; reduce: boolean; delay: number; seed: number; r?: number }) {
  const rnd = seeded(seed)
  const dots = Array.from({ length: count }, (_, i) => ({ x: (i % cols) * 10 + (rnd() - 0.5) * 4, y: Math.floor(i / cols) * 10 + (rnd() - 0.5) * 4 }))
  return (
    <motion.g initial={reduce ? false : { opacity: 0 }} animate={run ? { opacity: 1 } : undefined} transition={{ duration: 0.8, delay: reduce ? 0 : delay }}>
      {dots.map((d, i) => (
        <circle key={i} cx={d.x} cy={d.y} r={lit.includes(i) ? r * 1.9 : r} fill={lit.includes(i) ? 'var(--paper)' : color} />
      ))}
    </motion.g>
  )
}

const ISSUE_DOTS = Math.round(ISSUES / PER_DOT)
const THREAD_DOTS = Math.round(THREADS / PER_DOT)
const fmt = (n: number) => n.toLocaleString('en-US')

/** A count set large, with what it counts beside it. */
function Count({ x, y, value, label }: { x: number; y: number; value: string; label: string }) {
  return (
    <text x={x} y={y}>
      <tspan className="font-display" fontSize="64" fontWeight="600" letterSpacing="-2.6" fill="var(--paper)">
        {value}
      </tspan>
      <tspan dx="12" fontSize="17" fontWeight="500" fill="#a3a8b3">
        {label}
      </tspan>
    </text>
  )
}

// Where the clusters sit in the wide drawing.
const RIGHT = 712
const DOCS_AT = { x: RIGHT, y: 100 }
const ISSUES_AT = { x: RIGHT, y: 300 }
const THREADS_AT = { x: RIGHT, y: 522 }
const ISSUE_COLS = 26
const ISSUE_LIT = [3 * ISSUE_COLS + 2, 5 * ISSUE_COLS + 6, 2 * ISSUE_COLS + 9]
const THREAD_LIT = [2 * ISSUE_COLS + 1, 4 * ISSUE_COLS + 4]

function Constellation() {
  const { ref, run, reduce } = useSeen<SVGSVGElement>(0.3)
  const [replay, flags, analytics] = expanded
  const docLit = { x: DOCS_AT.x + (14 % DOC_COLS) * 21 + 6, y: DOCS_AT.y + Math.floor(14 / DOC_COLS) * 25 + 8 }
  const dustPoint = (at: P, i: number) => ({ x: at.x + (i % ISSUE_COLS) * 10, y: at.y + Math.floor(i / ISSUE_COLS) * 10 })
  const links: [P, P][] = [
    [replay, docLit],
    [flags, dustPoint(ISSUES_AT, ISSUE_LIT[0])],
    [flags, dustPoint(ISSUES_AT, ISSUE_LIT[1])],
    [analytics, dustPoint(THREADS_AT, THREAD_LIT[0])],
    [analytics, dustPoint(THREADS_AT, THREAD_LIT[1])],
  ]
  return (
    <svg ref={ref} viewBox="0 0 1128 640" className="h-auto w-full" role="img" aria-label={`PostHog as a graph: ${TEAMS} teams, ${DOCS} design docs, ${fmt(ISSUES)} issues and ${fmt(THREADS)} forum threads`}>
      {/* Connections from the opened teams to what they wrote, fixed and answered */}
      {links.map(([a, b], i) => (
        <motion.path
          key={i}
          d={`M ${a.x} ${a.y} C ${a.x + 220} ${a.y}, ${b.x - 200} ${b.y}, ${b.x} ${b.y}`}
          fill="none"
          stroke={i === 0 ? 'var(--cobalt)' : '#3a3f4b'}
          strokeWidth="1.25"
          initial={reduce ? false : { pathLength: 0 }}
          animate={run ? { pathLength: 1 } : undefined}
          transition={{ duration: 0.9, delay: reduce ? 0 : 2 + i * 0.12, ease }}
        />
      ))}
      <TeamsField run={run} reduce={reduce} />
      <Count x={0} y={52} value={String(TEAMS)} label="teams" />
      <Count x={RIGHT} y={DOCS_AT.y - 26} value={String(DOCS)} label="design docs" />
      <g transform={`translate(${DOCS_AT.x} ${DOCS_AT.y})`}>
        <DocsField run={run} reduce={reduce} />
      </g>
      <Count x={RIGHT} y={ISSUES_AT.y - 26} value={fmt(ISSUES)} label="issues" />
      <g transform={`translate(${ISSUES_AT.x} ${ISSUES_AT.y})`}>
        <Dust count={ISSUE_DOTS} cols={ISSUE_COLS} color="#7d828e" lit={ISSUE_LIT} run={run} reduce={reduce} delay={1.3} seed={11} />
      </g>
      <Count x={RIGHT} y={THREADS_AT.y - 26} value={fmt(THREADS)} label="forum threads" />
      <g transform={`translate(${THREADS_AT.x} ${THREADS_AT.y})`}>
        <Dust count={THREAD_DOTS} cols={ISSUE_COLS} color="var(--cobalt)" lit={THREAD_LIT} run={run} reduce={reduce} delay={1.6} seed={68} r={2.1} />
      </g>
    </svg>
  )
}

/** On a phone each cluster gets its own row, with its count above it. */
function PhoneBlock({ value, label, viewBox, children }: { value: string; label: string; viewBox: string; children: (run: boolean, reduce: boolean) => ReactNode }) {
  const { ref, run, reduce } = useSeen<SVGSVGElement>(0.4)
  return (
    <div className="border-t border-night-line pt-6">
      <p className="flex items-baseline gap-3">
        <span className="font-display text-[52px] leading-none font-semibold tracking-[-0.045em]">{value}</span>
        <span className="text-[16px] font-medium text-[#a3a8b3]">{label}</span>
      </p>
      <svg ref={ref} viewBox={viewBox} className="mt-5 h-auto w-full" aria-hidden="true">
        {children(run, reduce)}
      </svg>
    </div>
  )
}

function PhoneConstellation() {
  return (
    <div className="space-y-8">
      <PhoneBlock value={String(TEAMS)} label="teams" viewBox="16 36 608 608">
        {(run, reduce) => <TeamsField run={run} reduce={reduce} k={1.5} labelSize={26} />}
      </PhoneBlock>
      <PhoneBlock value={String(DOCS)} label="design docs" viewBox="-2 -2 226 96">
        {(run, reduce) => <DocsField run={run} reduce={reduce} />}
      </PhoneBlock>
      <PhoneBlock value={fmt(ISSUES)} label="issues" viewBox="-6 -6 262 98">
        {(run, reduce) => <Dust count={ISSUE_DOTS} cols={26} color="#7d828e" lit={ISSUE_LIT} run={run} reduce={reduce} delay={0.2} seed={11} />}
      </PhoneBlock>
      <PhoneBlock value={fmt(THREADS)} label="forum threads" viewBox="-6 -6 262 60">
        {(run, reduce) => <Dust count={THREAD_DOTS} cols={26} color="var(--cobalt)" lit={THREAD_LIT} run={run} reduce={reduce} delay={0.2} seed={68} r={2.1} />}
      </PhoneBlock>
    </div>
  )
}

export function Company() {
  return (
    <Slab id="company" tone="night" className="py-24 sm:py-32">
      <Container>
        <div className="flex flex-col gap-6 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <img src="https://cdn.simpleicons.org/posthog/ffffff" alt="PostHog" className="h-8 w-auto" loading="lazy" />
            <h2 className="display mt-7 max-w-[640px] text-[40px] text-balance sm:text-[56px]">PostHog, as Canon sees it.</h2>
          </div>
          <p className="max-w-[440px] text-[17px] leading-relaxed text-pretty text-[#a3a8b3]">
            The demo company works in public: its handbook, design docs, issues and team pages are all open. Canon reads them into one graph, so every answer
            can be checked against a real source.
          </p>
        </div>

        <div className="mt-16 sm:mt-20">
          <div className="hidden lg:block">
            <Constellation />
          </div>
          <div className="lg:hidden">
            <PhoneConstellation />
          </div>
        </div>

        <div className="mt-12 flex flex-col gap-3 border-t border-night-line pt-6 text-[14px] text-[#7d828e] sm:flex-row sm:justify-between">
          <p>Three teams opened up: their people as dots, the areas they own as squares. One dot for every {PER_DOT} issues or forum threads.</p>
          <p>Public data only. People appear by the GitHub handles and roles PostHog already publishes.</p>
        </div>
      </Container>
    </Slab>
  )
}
