import { motion } from 'motion/react'
import type { ReactNode } from 'react'
import { Container, Slab } from '../ui'
import { Traveller, useSeen } from './draw'

const STROKE = '#7d828e'
const FILL = 'var(--night-2)'
const LINE = '#2f333d'

/* Each source has its own document shape, drawn in a 40 x 48 box. */
const glyphs: Record<string, ReactNode> = {
  Handbook: (
    <>
      <rect x="4" y="2" width="32" height="44" rx="4" fill={FILL} stroke={STROKE} strokeWidth="1.5" />
      <line x1="11" y1="2" x2="11" y2="46" stroke={STROKE} strokeWidth="1.5" />
      <path d="M25 2 V15 L28.5 12 L32 15 V2 Z" fill="var(--proof)" />
      <rect x="15" y="21" width="15" height="2.5" rx="1.25" fill={STROKE} />
      <rect x="15" y="27" width="11" height="2.5" rx="1.25" fill={STROKE} />
    </>
  ),
  'Design docs': (
    <>
      <path d="M4 2 H26 L36 12 V46 H4 Z" fill={FILL} stroke={STROKE} strokeWidth="1.5" strokeLinejoin="round" />
      <path d="M26 2 V12 H36" fill="none" stroke={STROKE} strokeWidth="1.5" strokeLinejoin="round" />
      <rect x="9" y="17" width="17" height="4" rx="2" fill="var(--paper)" />
      <rect x="9" y="26" width="22" height="2.5" rx="1.25" fill={STROKE} />
      <rect x="9" y="32" width="22" height="2.5" rx="1.25" fill={STROKE} />
      <rect x="9" y="38" width="14" height="2.5" rx="1.25" fill={STROKE} />
    </>
  ),
  Issues: (
    <>
      <rect x="4" y="2" width="32" height="44" rx="4" fill={FILL} stroke={STROKE} strokeWidth="1.5" />
      <circle cx="14" cy="14" r="5" fill="none" stroke="var(--paper)" strokeWidth="1.5" />
      <circle cx="14" cy="14" r="1.6" fill="var(--paper)" />
      <rect x="9" y="26" width="22" height="2.5" rx="1.25" fill={STROKE} />
      <rect x="9" y="32" width="16" height="2.5" rx="1.25" fill={STROKE} />
    </>
  ),
  'Pull requests': (
    <>
      <rect x="4" y="2" width="32" height="44" rx="4" fill={FILL} stroke={STROKE} strokeWidth="1.5" />
      <g fill="none" stroke="var(--paper)" strokeWidth="1.5" strokeLinecap="round">
        <circle cx="13" cy="12" r="3" />
        <circle cx="13" cy="36" r="3" />
        <circle cx="27" cy="36" r="3" />
        <path d="M13 15 V33" />
        <path d="M27 33 V22 Q27 17 22 17 H18" />
      </g>
    </>
  ),
  Reviews: (
    <>
      <rect x="4" y="2" width="32" height="44" rx="4" fill={FILL} stroke={STROKE} strokeWidth="1.5" />
      <rect x="9" y="10" width="22" height="2.5" rx="1.25" fill={STROKE} />
      <rect x="9" y="16" width="18" height="2.5" rx="1.25" fill={STROKE} />
      <rect x="9" y="22" width="20" height="2.5" rx="1.25" fill={STROKE} />
      <circle cx="27" cy="36" r="6.5" fill="var(--cobalt)" />
      <path d="M24 36 L26.2 38.2 L30 34.2" fill="none" stroke="var(--paper)" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
    </>
  ),
  'Forum threads': (
    <>
      <path d="M3 6 a4 4 0 0 1 4 -4 H25 a4 4 0 0 1 4 4 V18 a4 4 0 0 1 -4 4 H11 L6 27 V22 a4 4 0 0 1 -3 -4 Z" fill={FILL} stroke={STROKE} strokeWidth="1.5" strokeLinejoin="round" />
      <path d="M11 24 a4 4 0 0 1 4 -4 H33 a4 4 0 0 1 4 4 V36 a4 4 0 0 1 -3 4 V45 L29 40 H15 a4 4 0 0 1 -4 -4 Z" fill={FILL} stroke="var(--paper)" strokeWidth="1.5" strokeLinejoin="round" />
      <rect x="16" y="27" width="15" height="2.5" rx="1.25" fill={STROKE} />
      <rect x="16" y="33" width="10" height="2.5" rx="1.25" fill={STROKE} />
    </>
  ),
  'Ownership map': (
    <>
      <g fill="none" stroke={STROKE} strokeWidth="1.5">
        <path d="M20 13 V22 M8 22 H32 M8 22 V31 M20 22 V31 M32 22 V31" />
      </g>
      <rect x="13" y="3" width="14" height="10" rx="3" fill="var(--marker)" />
      <rect x="3" y="31" width="10" height="10" rx="3" fill={FILL} stroke={STROKE} strokeWidth="1.5" />
      <rect x="15" y="31" width="10" height="10" rx="3" fill={FILL} stroke={STROKE} strokeWidth="1.5" />
      <rect x="27" y="31" width="10" height="10" rx="3" fill={FILL} stroke={STROKE} strokeWidth="1.5" />
    </>
  ),
  'Team pages': (
    <>
      <rect x="4" y="2" width="32" height="44" rx="4" fill={FILL} stroke={STROKE} strokeWidth="1.5" />
      <rect x="9" y="9" width="16" height="3.5" rx="1.75" fill="var(--paper)" />
      {[0, 1, 2].map((r) =>
        [0, 1].map((c) => <circle key={`${r}${c}`} cx={14 + c * 12} cy={22 + r * 8} r="2.6" fill={STROKE} />),
      )}
    </>
  ),
}

// What Canon reads, and the one thing it takes from each.
const sources = [
  ['Handbook', 'what the company says'],
  ['Design docs', 'what was decided'],
  ['Issues', 'what is broken'],
  ['Pull requests', 'what actually changed'],
  ['Reviews', 'who knows the code'],
  ['Forum threads', 'what people ask'],
  ['Ownership map', 'who owns what'],
  ['Team pages', 'who works where'],
] as const

type Kind = 'person' | 'team' | 'area' | 'page' | 'fact' | 'old' | 'issue' | 'pr' | 'thread'
type GNode = { id: string; kind: Kind; x: number; y: number; label?: string; place?: 'left' | 'above'; tone?: string }

// The graph Canon builds, in its own 480 x 440 space. An example, not PostHog's real graph.
const gnodes: GNode[] = [
  { id: 'hb', kind: 'page', x: 410, y: 52, label: 'Handbook page', place: 'above' },
  { id: 'old', kind: 'old', x: 462, y: 150, label: 'Replaced', place: 'left', tone: 'var(--proof)' },
  { id: 'dd', kind: 'page', x: 240, y: 300, label: 'Design doc' },
  { id: 'new', kind: 'fact', x: 350, y: 220 },
  { id: 'i1', kind: 'issue', x: 130, y: 360 },
  { id: 'i2', kind: 'issue', x: 40, y: 300 },
  { id: 'pr1', kind: 'pr', x: 345, y: 340 },
  { id: 'pr2', kind: 'pr', x: 430, y: 395 },
  { id: 'p1', kind: 'person', x: 280, y: 418 },
  { id: 'q1', kind: 'thread', x: 470, y: 280 },
  { id: 'q2', kind: 'thread', x: 18, y: 165 },
  { id: 'area', kind: 'area', x: 290, y: 105, label: 'Session replay' },
  { id: 'team', kind: 'team', x: 160, y: 185, label: 'Replay team' },
  { id: 'p2', kind: 'person', x: 90, y: 245 },
  { id: 'p3', kind: 'person', x: 175, y: 60 },
]
const byId = Object.fromEntries(gnodes.map((n) => [n.id, n]))

/** Which nodes each source brings into the graph, in source order. */
const brings: string[][] = [['hb', 'old'], ['dd', 'new'], ['i1', 'i2'], ['pr1', 'pr2'], ['p1'], ['q1', 'q2'], ['area'], ['team', 'p2', 'p3']]

const gedges: [string, string, ('replaced' | undefined)?][] = [
  ['hb', 'old'],
  ['old', 'new', 'replaced'],
  ['dd', 'new'],
  ['dd', 'pr1'],
  ['pr1', 'pr2'],
  ['i1', 'pr1'],
  ['i2', 'i1'],
  ['p1', 'pr1'],
  ['p1', 'pr2'],
  ['q1', 'new'],
  ['q2', 'p2'],
  ['area', 'team'],
  ['area', 'hb'],
  ['area', 'new'],
  ['team', 'p2'],
  ['team', 'p3'],
  ['i2', 'team'],
  ['dd', 'team'],
  ['p3', 'area'],
]

// Timing: one dot per source sets off in turn; the nodes it brings appear as it lands.
const LEAVE = 0.25
const GAP = 0.34
const TRAVEL = 1.35
const arrival = (s: number) => LEAVE + s * GAP + TRAVEL
const appearAt: Record<string, number> = {}
brings.forEach((ids, s) => ids.forEach((id, j) => (appearAt[id] = arrival(s) + j * 0.16)))

type Layout = {
  viewBox: [number, number]
  /** Where each source row sits. */
  row: (i: number) => { x: number; y: number }
  glyphScale: number
  nameSize: number
  showWhat: boolean
  /** Where each source's line leaves from, and the route to a point in the graph. */
  route: (i: number, to: { x: number; y: number }) => string
  graph: { x: number; y: number; k: number }
  labelSize: number
  /** How large nodes are drawn. */
  nodeK: number
}

const desktop: Layout = {
  viewBox: [1128, 500],
  row: (i) => ({ x: 0, y: 12 + i * 60 }),
  glyphScale: 1,
  nameSize: 16,
  showWhat: true,
  route: (i, to) => {
    const y = 12 + i * 60 + 24
    return `M 236 ${y} C 420 ${y}, ${to.x - 200} ${to.y}, ${to.x} ${to.y}`
  },
  graph: { x: 618, y: 26, k: 1 },
  labelSize: 13,
  nodeK: 1.4,
}

// On a phone the sources stack on the left and their lines drop down on rails into the graph below.
const RAIL = (i: number) => 330 - i * 19
const phone: Layout = {
  viewBox: [360, 790],
  row: (i) => ({ x: 0, y: 6 + i * 50 }),
  glyphScale: 0.78,
  nameSize: 15,
  showWhat: false,
  route: (i, to) => {
    const y = 6 + i * 50 + 19
    const x = RAIL(i)
    return `M 150 ${y} H ${x - 12} Q ${x} ${y} ${x} ${y + 12} V 430 C ${x} 470, ${to.x} 450, ${to.x} ${to.y}`
  },
  graph: { x: 22, y: 478, k: 0.65 },
  labelSize: 12,
  nodeK: 0.8,
}

function NodeShape({ n, k }: { n: GNode; k: number }) {
  const s = (v: number) => v * k
  switch (n.kind) {
    case 'person':
      return <circle r={s(8)} fill="var(--paper)" />
    case 'team':
      return <circle r={s(13)} fill="var(--night)" stroke="var(--paper)" strokeWidth="2" />
    case 'area':
      return <circle r={s(11)} fill="var(--marker)" />
    case 'page':
      return <rect x={-s(10)} y={-s(12)} width={s(20)} height={s(24)} rx="3.5" fill="var(--night-2)" stroke="#a3a8b3" strokeWidth="1.5" />
    case 'fact':
      return <circle r={s(7.5)} fill="var(--cobalt)" />
    case 'old':
      return (
        <g>
          <circle r={s(7.5)} fill="#3a3f4b" />
          <line x1={-s(10)} y1={s(5)} x2={s(10)} y2={-s(5)} stroke="var(--proof)" strokeWidth="2" strokeLinecap="round" />
        </g>
      )
    case 'issue':
      return <circle r={s(5.5)} fill="var(--night)" stroke="#a3a8b3" strokeWidth="1.5" />
    case 'pr':
      return <circle r={s(5.5)} fill="#a3a8b3" />
    case 'thread':
      return <rect x={-s(6)} y={-s(5)} width={s(12)} height={s(10)} rx="3" fill="var(--night)" stroke="#a3a8b3" strokeWidth="1.5" />
  }
}

function IntakeDiagram({ layout, className = '' }: { layout: Layout; className?: string }) {
  const { ref, run, reduce } = useSeen<SVGSVGElement>(0.3)
  const { x: gx, y: gy, k } = layout.graph
  const at = (id: string) => ({ x: gx + byId[id].x * k, y: gy + byId[id].y * k })
  const [w, h] = layout.viewBox
  const later = (t: number) => (reduce ? 0 : t)

  return (
    <svg ref={ref} viewBox={`0 0 ${w} ${h}`} className={`h-auto w-full ${className}`} role="img" aria-label="Eight kinds of source flowing into one graph">
      {/* Lines from each source into the node it brings first */}
      {sources.map(([name], i) => (
        <path key={name} d={layout.route(i, at(brings[i][0]))} fill="none" stroke={LINE} strokeWidth="1.5" />
      ))}

      {/* Edges, drawn once both ends exist */}
      {gedges.map(([a, b, kind]) => {
        const p = at(a)
        const q = at(b)
        const t = Math.max(appearAt[a], appearAt[b]) + 0.1
        return (
          <motion.line
            key={`${a}-${b}`}
            x1={p.x}
            y1={p.y}
            x2={q.x}
            y2={q.y}
            stroke={kind === 'replaced' ? 'var(--proof)' : '#5f6470'}
            strokeWidth={kind === 'replaced' ? 1.75 : 1.25}
            strokeDasharray={kind === 'replaced' ? '4 4' : undefined}
            initial={reduce ? false : { opacity: 0 }}
            animate={run ? { opacity: 1 } : undefined}
            transition={{ duration: 0.5, delay: later(t) }}
          />
        )
      })}

      {/* Nodes */}
      {gnodes.map((n) => {
        const p = at(n.id)
        return (
          <g key={n.id} transform={`translate(${p.x} ${p.y})`}>
            <motion.g
              initial={reduce ? false : { scale: 0, opacity: 0 }}
              animate={run ? { scale: 1, opacity: 1 } : undefined}
              transition={{ duration: 0.45, delay: later(appearAt[n.id]), ease: [0.34, 1.5, 0.64, 1] }}
            >
              <NodeShape n={n} k={layout.nodeK} />
            </motion.g>
            {n.label && (
              <motion.text
                x={n.place === 'above' ? 0 : (n.place === 'left' ? -1 : 1) * (n.kind === 'team' ? 20 : 16) * layout.nodeK}
                y={n.place === 'above' ? -21 * layout.nodeK : 4.5}
                textAnchor={n.place === 'above' ? 'middle' : n.place === 'left' ? 'end' : 'start'}
                fontSize={layout.labelSize}
                fontWeight={500}
                fill={n.tone ?? '#a3a8b3'}
                initial={reduce ? false : { opacity: 0 }}
                animate={run ? { opacity: 1 } : undefined}
                transition={{ duration: 0.4, delay: later(appearAt[n.id] + 0.2) }}
              >
                {n.label}
              </motion.text>
            )}
          </g>
        )
      })}

      {/* Fact dots on their way in: two per source */}
      {!reduce &&
        sources.map(([name], i) =>
          [0, 1].map((j) => (
            <Traveller
              key={`${name}-${j}`}
              d={layout.route(i, at(brings[i][0]))}
              run={run}
              delay={LEAVE + i * GAP + j * 0.42}
              duration={TRAVEL}
              r={j === 0 ? 4 : 3}
              fill={j === 0 ? 'var(--paper)' : '#a3a8b3'}
            />
          )),
        )}

      {/* The sources themselves */}
      {sources.map(([name, what], i) => {
        const { x, y } = layout.row(i)
        const g = layout.glyphScale
        return (
          <g key={name} transform={`translate(${x} ${y})`}>
            <g transform={`scale(${g})`}>{glyphs[name]}</g>
            <text x={52 * g + 6} y={layout.showWhat ? 20 : 24 * g + 5} fontSize={layout.nameSize} fontWeight={600} fill="var(--paper)">
              {name}
            </text>
            {layout.showWhat && (
              <text x={58} y={39} fontSize={13.5} fill="#7d828e">
                {what}
              </text>
            )}
          </g>
        )
      })}
    </svg>
  )
}

function Legend() {
  const items: [Kind, string][] = [
    ['person', 'Person'],
    ['team', 'Team'],
    ['area', 'Area'],
    ['page', 'Page'],
    ['fact', 'Fact'],
    ['old', 'Replaced fact'],
  ]
  return (
    <ul className="flex flex-wrap gap-x-6 gap-y-2.5 text-[13.5px] text-[#a3a8b3]">
      {items.map(([kind, label]) => (
        <li key={kind} className="flex items-center gap-2">
          <svg viewBox="-16 -16 32 32" className="size-5" aria-hidden="true">
            <NodeShape n={{ id: kind, kind, x: 0, y: 0 }} k={1} />
          </svg>
          {label}
        </li>
      ))}
    </ul>
  )
}

export function Sources() {
  return (
    <Slab tone="night" className="py-20 sm:py-28">
      <Container>
        <div className="flex flex-col gap-6 lg:flex-row lg:items-end lg:justify-between">
          <h2 className="display max-w-[640px] text-[40px] text-balance sm:text-[56px]">What Canon reads.</h2>
          <p className="max-w-[440px] text-[17px] leading-relaxed text-pretty text-[#a3a8b3]">
            Eight kinds of source, read into one graph. Every fact keeps where it came from, who it involves and when it held.
          </p>
        </div>
        <div className="mt-14 sm:mt-16">
          <IntakeDiagram layout={desktop} className="hidden lg:block" />
          <IntakeDiagram layout={phone} className="mx-auto max-w-[460px] lg:hidden" />
        </div>
        <div className="mt-10 border-t border-night-line pt-6">
          <Legend />
        </div>
      </Container>
    </Slab>
  )
}
