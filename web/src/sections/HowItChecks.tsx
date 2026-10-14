import { motion } from 'motion/react'
import type { CSSProperties, ReactNode } from 'react'
import { Container, SectionTitle, Slab } from '../ui'
import { Traveller, ease, useSeen } from './draw'

type NodeId = 'claim' | 'passage' | 'old' | 'new' | 'person' | 'fix'

// One sentence of an answer, and everything the check visits to judge it.
const info: Record<NodeId, { kind: string; title: string; detail: string }> = {
  claim: { kind: 'Claim', title: '"Session replay belongs to Product Analytics."', detail: 'One sentence of an answer' },
  passage: { kind: 'Passage', title: '"We own insights and session replay."', detail: 'Handbook, Product Analytics page' },
  old: { kind: 'Fact', title: 'Product Analytics owns replay', detail: 'Held until the ownership changed' },
  new: { kind: 'Fact', title: 'Replay owns session replay', detail: 'Current, no end date' },
  person: { kind: 'Person', title: 'Replay team lead', detail: 'Owns session replay now' },
  fix: { kind: 'Fix', title: 'Change the handbook line', detail: 'Drafted with the evidence attached' },
}

type EdgeId = 'stated' | 'asserts' | 'superseded' | 'owned' | 'routed'
const rel: Record<EdgeId, string> = {
  stated: 'STATED_IN',
  asserts: 'ASSERTS',
  superseded: 'SUPERSEDED_BY',
  owned: 'OWNED_BY',
  routed: 'ROUTED_TO',
}
const walk: { id: EdgeId; from: NodeId; to: NodeId; step?: number }[] = [
  { id: 'stated', from: 'claim', to: 'passage', step: 1 },
  { id: 'asserts', from: 'passage', to: 'old' },
  { id: 'superseded', from: 'old', to: 'new', step: 2 },
  { id: 'owned', from: 'new', to: 'person' },
  { id: 'routed', from: 'fix', to: 'person', step: 3 },
]

// The walk's clock, in seconds after it scrolls into view.
const START = 0.7
const HOP = 1.3
const TRAVEL = 0.95
const leaves = (i: number) => START + i * HOP
const lands = (i: number) => leaves(i) + TRAVEL
const litAt: Record<NodeId, number> = {
  claim: 0.25,
  passage: lands(0),
  old: lands(1),
  new: lands(2),
  person: lands(3),
  fix: leaves(4) - 0.4,
}
/** The old fact is struck the moment the walk finds the fact that replaced it. */
const STRUCK = lands(2)

type Place = 'above' | 'below' | 'right'
type Layout = {
  w: number
  h: number
  r: number
  nodes: Record<NodeId, { x: number; y: number; place: Place }>
  edges: Record<EdgeId, { d: string; label: { x: number; y: number }; anchor: 'middle' | 'start' }>
  labelWidth: number
}

const desktop: Layout = {
  w: 1128,
  h: 486,
  r: 25,
  labelWidth: 262,
  nodes: {
    claim: { x: 90, y: 124, place: 'above' },
    passage: { x: 480, y: 124, place: 'above' },
    old: { x: 870, y: 124, place: 'above' },
    new: { x: 870, y: 364, place: 'below' },
    person: { x: 480, y: 364, place: 'below' },
    fix: { x: 90, y: 364, place: 'below' },
  },
  edges: {
    stated: { d: 'M 90 124 C 220 190, 350 190, 480 124', label: { x: 285, y: 177 }, anchor: 'middle' },
    asserts: { d: 'M 480 124 C 610 190, 740 190, 870 124', label: { x: 675, y: 177 }, anchor: 'middle' },
    superseded: { d: 'M 870 124 C 1070 140, 1070 348, 870 364', label: { x: 1020, y: 248 }, anchor: 'middle' },
    owned: { d: 'M 870 364 C 740 298, 610 298, 480 364', label: { x: 675, y: 319 }, anchor: 'middle' },
    routed: { d: 'M 90 364 C 220 298, 350 298, 480 364', label: { x: 285, y: 319 }, anchor: 'middle' },
  },
}

// On a phone the walk runs down a single spine, labels to the right.
const SPINE = 34
const ys = { claim: 40, passage: 228, old: 416, new: 604, person: 792, fix: 980 }
const phone: Layout = {
  w: 360,
  h: 1060,
  r: 21,
  labelWidth: 286,
  nodes: {
    claim: { x: SPINE, y: ys.claim, place: 'right' },
    passage: { x: SPINE, y: ys.passage, place: 'right' },
    old: { x: SPINE, y: ys.old, place: 'right' },
    new: { x: SPINE, y: ys.new, place: 'right' },
    person: { x: SPINE, y: ys.person, place: 'right' },
    fix: { x: SPINE, y: ys.fix, place: 'right' },
  },
  edges: {
    stated: { d: `M ${SPINE} ${ys.claim} V ${ys.passage}`, label: { x: 74, y: ys.claim + 140 }, anchor: 'start' },
    asserts: { d: `M ${SPINE} ${ys.passage} V ${ys.old}`, label: { x: 74, y: ys.passage + 140 }, anchor: 'start' },
    superseded: { d: `M ${SPINE} ${ys.old} V ${ys.new}`, label: { x: 74, y: ys.old + 140 }, anchor: 'start' },
    owned: { d: `M ${SPINE} ${ys.new} V ${ys.person}`, label: { x: 74, y: ys.new + 140 }, anchor: 'start' },
    routed: { d: `M ${SPINE} ${ys.fix} V ${ys.person}`, label: { x: 74, y: ys.person + 140 }, anchor: 'start' },
  },
}

/** What each node looks like once the walk reaches it. Drawn around 0,0 at radius r. */
function NodeFace({ id, r }: { id: NodeId; r: number }) {
  const k = r / 25
  switch (id) {
    case 'claim':
      return (
        <g>
          <circle r={r} fill="var(--ink)" />
          <g fill="var(--paper)" transform={`scale(${k})`}>
            <rect x="-10" y="-7" width="20" height="3.5" rx="1.75" />
            <rect x="-10" y="-1.5" width="20" height="3.5" rx="1.75" />
            <rect x="-10" y="4" width="12" height="3.5" rx="1.75" />
          </g>
        </g>
      )
    case 'passage':
      return (
        <g>
          <circle r={r} fill="var(--marker)" />
          <g fill="var(--ink)" transform={`scale(${k})`}>
            <rect x="-10" y="-7" width="20" height="3.5" rx="1.75" />
            <rect x="-10" y="-1.5" width="20" height="3.5" rx="1.75" />
            <rect x="-10" y="4" width="12" height="3.5" rx="1.75" />
          </g>
        </g>
      )
    case 'old':
      return (
        <g>
          <circle r={r} fill="var(--proof-soft)" stroke="var(--proof)" strokeWidth="1.5" />
          <circle r={7 * k} fill="var(--proof)" opacity="0.35" />
        </g>
      )
    case 'new':
      return (
        <g>
          <circle r={r} fill="var(--cobalt)" />
          <path d="M -8 0.5 L -2.5 6 L 8.5 -5" transform={`scale(${k})`} fill="none" stroke="var(--paper)" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
        </g>
      )
    case 'person':
      return (
        <g>
          <circle r={r} fill="var(--night)" />
          <g transform={`scale(${k})`} fill="var(--paper)">
            <circle cy="-5" r="5.5" />
            <path d="M -10 11 C -10 3.5, 10 3.5, 10 11 Z" />
          </g>
        </g>
      )
    case 'fix':
      return (
        <g>
          <circle r={r} fill="var(--cobalt-soft)" stroke="var(--cobalt)" strokeWidth="1.5" />
          <path d="M -8 5 L 0 -6 L 8 5" transform={`scale(${k})`} fill="none" stroke="var(--cobalt)" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
        </g>
      )
  }
}

function NodeLabel({ id, layout, run, reduce }: { id: NodeId; layout: Layout; run: boolean; reduce: boolean }) {
  const n = layout.nodes[id]
  const t = info[id]
  const style: CSSProperties =
    n.place === 'right'
      ? { left: `${((n.x + layout.r + 16) / layout.w) * 100}%`, top: `${((n.y - layout.r + 2) / layout.h) * 100}%`, width: `${(layout.labelWidth / layout.w) * 100}%` }
      : {
          left: `${((n.x - layout.r) / layout.w) * 100}%`,
          top: `${((n.place === 'above' ? n.y - layout.r - 14 : n.y + layout.r + 14) / layout.h) * 100}%`,
          width: layout.labelWidth,
          transform: n.place === 'above' ? 'translateY(-100%)' : undefined,
        }
  return (
    <motion.div
      className="absolute"
      style={style}
      initial={reduce ? false : { opacity: 0.3 }}
      animate={run ? { opacity: 1 } : undefined}
      transition={{ duration: 0.4, delay: reduce ? 0 : litAt[id] }}
    >
      <p className="text-[13px] font-medium text-muted">{t.kind}</p>
      <p className="mt-0.5 text-[15.5px] leading-snug font-semibold tracking-[-0.01em] text-ink">
        {id === 'old' ? (
          <motion.span
            className="[box-decoration-break:clone] bg-no-repeat"
            style={{ backgroundImage: 'linear-gradient(var(--proof), var(--proof))', backgroundPosition: '0 58%' }}
            initial={reduce ? false : { backgroundSize: '0% 2px' }}
            animate={run ? { backgroundSize: '100% 2px' } : undefined}
            transition={{ duration: 0.5, delay: reduce ? 0 : STRUCK, ease }}
          >
            {t.title}
          </motion.span>
        ) : (
          t.title
        )}
      </p>
      <p className="mt-0.5 text-[13px] leading-snug text-muted">{t.detail}</p>
    </motion.div>
  )
}

function GraphWalk({ layout, className = '', payoff }: { layout: Layout; className?: string; payoff?: ReactNode }) {
  const { ref, run, reduce } = useSeen<HTMLDivElement>(0.35)
  const later = (t: number) => (reduce ? 0 : t)
  const ids = Object.keys(layout.nodes) as NodeId[]

  return (
    <div ref={ref} className={`relative ${className}`}>
      <svg viewBox={`0 0 ${layout.w} ${layout.h}`} className="block h-auto w-full" role="img" aria-label="A claim walked through the graph to the fact that replaced it and the person who owns the fix">
        {/* Edges: a faint track, inked in as the walk passes */}
        {walk.map((e, i) => {
          const { d } = layout.edges[e.id]
          return (
            <g key={e.id}>
              <path d={d} fill="none" stroke="var(--line-strong)" strokeWidth="1.5" strokeDasharray="3 5" strokeLinecap="round" />
              <motion.path
                d={d}
                fill="none"
                stroke={e.id === 'routed' ? 'var(--cobalt)' : 'var(--ink)'}
                strokeWidth="2"
                strokeLinecap="round"
                initial={reduce ? false : { pathLength: 0 }}
                animate={run ? { pathLength: 1 } : undefined}
                transition={{ duration: reduce ? 0 : TRAVEL, delay: later(leaves(i)), ease: [0.45, 0, 0.25, 1] }}
              />
            </g>
          )
        })}

        {/* Relationship names, with the three steps marked where they happen */}
        {walk.map((e, i) => {
          const { label, anchor } = layout.edges[e.id]
          const width = rel[e.id].length * 7.25
          const left = anchor === 'middle' ? label.x - width / 2 : label.x
          return (
            <motion.g key={e.id} initial={reduce ? false : { opacity: 0.45 }} animate={run ? { opacity: 1 } : undefined} transition={{ duration: 0.3, delay: later(leaves(i)) }}>
              {e.step && (
                <g transform={`translate(${left - 17} ${label.y - 4.5})`}>
                  <circle r="11" fill="var(--ink)" />
                  <text y="4.5" textAnchor="middle" fontSize="12.5" fontWeight="700" fill="var(--paper)">
                    {e.step}
                  </text>
                </g>
              )}
              <rect x={left - 5} y={label.y - 13} width={width + 10} height={18} rx="5" fill="var(--paper)" />
              <text x={label.x} y={label.y} textAnchor={anchor} className="font-mono" fontSize="12" fontWeight="600" fill="var(--ink)" style={{ fontVariantLigatures: 'none' }}>
                {rel[e.id]}
              </text>
            </motion.g>
          )
        })}

        {/* Nodes: a dashed outline until the walk reaches them */}
        {ids.map((id) => {
          const n = layout.nodes[id]
          return (
            <g key={id} transform={`translate(${n.x} ${n.y})`}>
              <circle r={layout.r} fill="var(--paper)" stroke="var(--line-strong)" strokeWidth="1.5" strokeDasharray="3 4" />
              {!reduce && (
                <motion.circle
                  r={layout.r}
                  fill="none"
                  stroke={id === 'old' ? 'var(--proof)' : id === 'fix' || id === 'new' ? 'var(--cobalt)' : 'var(--ink)'}
                  strokeWidth="1.5"
                  initial={{ scale: 1, opacity: 0 }}
                  animate={run ? { scale: [1, 1.7], opacity: [0.6, 0] } : undefined}
                  transition={{ duration: 0.9, delay: litAt[id], ease: 'easeOut' }}
                />
              )}
              <motion.g
                initial={reduce ? false : { scale: 0.4, opacity: 0 }}
                animate={run ? { scale: 1, opacity: 1 } : undefined}
                transition={{ duration: 0.45, delay: later(litAt[id]), ease: [0.34, 1.45, 0.64, 1] }}
              >
                <NodeFace id={id} r={layout.r} />
              </motion.g>
              {id === 'old' && (
                <motion.line
                  x1={-layout.r - 6}
                  y1={layout.r * 0.55}
                  x2={layout.r + 6}
                  y2={-layout.r * 0.55}
                  stroke="var(--proof)"
                  strokeWidth="3"
                  strokeLinecap="round"
                  initial={reduce ? false : { pathLength: 0 }}
                  animate={run ? { pathLength: 1 } : undefined}
                  transition={{ duration: 0.45, delay: later(STRUCK), ease }}
                />
              )}
            </g>
          )
        })}

        {/* The ink dot that does the walking */}
        {!reduce &&
          walk.map((e, i) => (
            <Traveller
              key={e.id}
              d={layout.edges[e.id].d}
              run={run}
              delay={leaves(i)}
              duration={TRAVEL}
              r={6}
              fill={e.id === 'routed' ? 'var(--cobalt)' : 'var(--ink)'}
            />
          ))}
      </svg>

      {ids.map((id) => (
        <NodeLabel key={id} id={id} layout={layout} run={run} reduce={reduce} />
      ))}

      {payoff && (
        <motion.div
          className="absolute top-1/2 left-[42.5%] -translate-x-1/2 -translate-y-1/2"
          initial={reduce ? false : { opacity: 0, y: 8 }}
          animate={run ? { opacity: 1, y: 0 } : undefined}
          transition={{ duration: 0.5, delay: later(STRUCK + 0.2), ease }}
        >
          {payoff}
        </motion.div>
      )}
    </div>
  )
}

/** The sentence as the answer now prints it: the stale words struck, the current one written in. */
function Corrected({ size = 'text-[24px] whitespace-nowrap' }: { size?: string }) {
  return (
    <div className="text-center">
      <p className="text-[13.5px] font-semibold text-proof">Out of date</p>
      <p className={`mt-1 font-display ${size} leading-tight font-semibold tracking-[-0.03em] text-balance text-ink`}>
        Session replay belongs to <span className="text-faint line-through decoration-proof decoration-2">Product Analytics</span>{' '}
        <span className="relative text-cobalt">
          Replay.
          <span aria-hidden="true" className="absolute -bottom-2.5 left-0 text-[15px] font-bold text-cobalt">
            ^
          </span>
        </span>
      </p>
    </div>
  )
}

const steps = [
  ['Find where it was said', 'Full-text search finds the passage the sentence came from. A sentence with no passage was never said.'],
  ['Walk forward in time', 'Facts carry the dates they held. If a newer fact replaced this one, the graph has the edge, and the answer says so.'],
  ['Route the fix', 'Whoever owns the page that is now wrong gets the change, with the evidence attached.'],
]

const QUERY = `MATCH (c:Claim {id: $claim})-[:STATED_IN]->(p:Passage)
MATCH (p)-[:ASSERTS]->(f:Fact)
OPTIONAL MATCH chain = (f)-[:SUPERSEDED_BY*1..5]->(now:Fact)
WHERE now.valid_to IS NULL
RETURN p.text,
       f.valid_to IS NULL AS current,
       nodes(chain) AS since`

export function HowItChecks() {
  return (
    <Slab id="check" tone="paper-2" className="py-24 sm:py-32">
      <Container>
        <SectionTitle
          title="One sentence, walked through the graph."
          lede="Search finds the words. Only a graph knows that one fact replaced another, when it happened, and whose page is now wrong."
        />

        <div
          className="mt-14 rounded-[24px] bg-paper px-5 pt-8 pb-6 ring-1 ring-line sm:px-8 lg:px-10 lg:pt-10"
          style={{ backgroundImage: 'radial-gradient(circle, rgb(13 14 18 / 0.09) 1px, transparent 1.2px)', backgroundSize: '22px 22px' }}
        >
          <GraphWalk layout={desktop} className="hidden lg:block" payoff={<Corrected />} />
          <GraphWalk layout={phone} className="mx-auto max-w-[420px] lg:hidden" />
          <div className="mt-8 flex justify-center px-2 lg:hidden">
            <Corrected size="text-[20px]" />
          </div>

          <ol className="mt-10 grid gap-x-10 gap-y-6 border-t border-line pt-7 md:grid-cols-3">
            {steps.map(([title, body], i) => (
              <li key={title} className="grid grid-cols-[30px_minmax(0,1fr)] gap-x-3">
                <span className="grid size-[22px] place-items-center rounded-full bg-ink text-[12.5px] font-bold text-paper">{i + 1}</span>
                <div>
                  <p className="text-[16px] font-semibold tracking-[-0.01em]">{title}</p>
                  <p className="mt-1 text-[14.5px] leading-relaxed text-pretty text-muted">{body}</p>
                </div>
              </li>
            ))}
          </ol>
        </div>

        <div className="mt-4 grid gap-4 lg:grid-cols-[minmax(0,0.8fr)_minmax(0,1.2fr)] lg:items-center">
          <div className="px-2 py-4 lg:px-6">
            <h3 className="font-display text-[28px] leading-tight font-semibold tracking-[-0.03em] text-balance">The whole check is one query.</h3>
            <p className="mt-3 max-w-[30rem] text-[16px] leading-relaxed text-pretty text-muted">
              FalkorDB follows <code className="font-mono text-[14px] text-ink">SUPERSEDED_BY</code> forward from the fact the passage asserts. If the walk ends
              somewhere newer, the sentence is out of date, and the answer cites what replaced it.
            </p>
          </div>
          <div className="overflow-hidden rounded-[22px] bg-night text-paper">
            <pre className="overflow-x-auto px-6 py-6 font-mono text-[13px] leading-[1.85] text-[#e4e6ec] [font-variant-ligatures:none] sm:px-7">{QUERY}</pre>
          </div>
        </div>
      </Container>
    </Slab>
  )
}
