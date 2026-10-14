import { motion, useInView, useReducedMotion } from 'motion/react'
import { useEffect, useRef, useState } from 'react'
import { Container, SectionTitle, Slab, VerdictTag } from '../ui'

const ease = [0.22, 1, 0.36, 1] as const

type Tone = 'ink' | 'marker' | 'proof' | 'cobalt' | 'night'
type Node = { id: string; kind: string; title: string; detail: string; tone: Tone }

// One sentence, walked through the graph, in the order the check visits it.
const nodes: Node[] = [
  { id: 'claim', kind: 'Claim', title: 'The handbook lists it under Product Analytics', detail: 'one sentence of the answer', tone: 'ink' },
  { id: 'passage', kind: 'Passage', title: '"we own insights and session replay"', detail: 'handbook / product-analytics', tone: 'marker' },
  { id: 'old', kind: 'Fact', title: 'Product Analytics owns session replay', detail: 'valid until the ownership change', tone: 'proof' },
  { id: 'new', kind: 'Fact', title: 'Replay owns session replay', detail: 'valid since then, still current', tone: 'cobalt' },
  { id: 'owner', kind: 'Person', title: 'Replay team lead', detail: 'owns the page that is now wrong', tone: 'night' },
]
const labels = ['STATED_IN', 'ASSERTS', 'SUPERSEDED_BY', 'OWNED_BY']

const toneClass: Record<Tone, string> = {
  ink: 'bg-paper ring-1 ring-line-strong',
  marker: 'bg-marker-soft ring-1 ring-[#efd55c]',
  proof: 'bg-proof-soft ring-1 ring-[#f3b7b0]',
  cobalt: 'bg-cobalt-soft ring-1 ring-[#b9c3fa]',
  night: 'bg-night text-paper',
}

const steps = [
  ['Find where it was said', 'Full-text search finds the passage the sentence came from. A sentence with no passage is never said.'],
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

function NodeCard({ node, on, active }: { node: Node; on: boolean; active: boolean }) {
  const dim = node.tone === 'night' ? 'text-[#a3a8b3]' : 'text-muted'
  return (
    <motion.div
      className={`rounded-[16px] px-4 py-3.5 ${toneClass[node.tone]}`}
      initial={false}
      animate={{ opacity: on ? 1 : 0.32, y: on ? 0 : 6, scale: active ? 1.025 : 1 }}
      transition={{ duration: 0.45, ease }}
    >
      <span className={`font-mono text-[11px] ${dim}`}>{node.kind}</span>
      <p className={`mt-1 text-[14.5px] leading-snug font-semibold ${node.tone === 'proof' ? 'text-proof line-through decoration-proof/50' : ''}`}>{node.title}</p>
      <p className={`mt-1 text-[12.5px] leading-snug ${dim}`}>{node.detail}</p>
    </motion.div>
  )
}

/** A connector that inks in when the walk reaches it. `dir` is the way the walk travels. */
function Edge({ label, on, dir }: { label: string; on: boolean; dir: 'right' | 'left' | 'down' }) {
  const vertical = dir === 'down'
  return (
    <div className={`relative flex items-center justify-center ${vertical ? 'h-full min-h-[84px] flex-col' : 'h-full'}`}>
      <span className={`absolute bg-line-strong ${vertical ? 'inset-y-0 left-1/2 w-px -translate-x-1/2' : 'inset-x-0 top-1/2 h-px -translate-y-1/2'}`} />
      <motion.span
        className={`absolute bg-ink ${vertical ? 'inset-y-0 left-1/2 w-[2px] origin-top -translate-x-1/2' : `inset-x-0 top-1/2 h-[2px] -translate-y-1/2 ${dir === 'left' ? 'origin-right' : 'origin-left'}`}`}
        initial={false}
        animate={vertical ? { scaleY: on ? 1 : 0 } : { scaleX: on ? 1 : 0 }}
        transition={{ duration: 0.5, ease }}
      />
      <span
        className={`relative rounded-full px-2 py-0.5 font-mono text-[10.5px] font-semibold whitespace-nowrap transition-colors duration-500 ${on ? 'bg-ink text-paper' : 'bg-paper-2 text-faint ring-1 ring-line'}`}
      >
        {label}
      </span>
    </div>
  )
}

/** The walk, laid out as a 3 x 3 grid: across the top, down the right, back along the bottom. */
function GraphWalk() {
  const ref = useRef<HTMLDivElement>(null)
  const seen = useInView(ref, { once: true, amount: 0.4 })
  const reduce = !!useReducedMotion()
  const [lit, setLit] = useState(reduce ? 6 : 0)
  useEffect(() => {
    if (!seen || reduce) return
    const timers = [0, 1, 2, 3, 4, 5].map((i) => window.setTimeout(() => setLit(i + 1), 300 + i * 620))
    return () => timers.forEach((t) => window.clearTimeout(t))
  }, [seen, reduce])
  const on = (i: number) => lit > i
  const [claim, passage, old, fresh, owner] = nodes

  return (
    <div ref={ref} className="grid grid-cols-[minmax(0,1fr)_118px_minmax(0,1fr)_118px_minmax(0,1fr)] grid-rows-[auto_84px_auto]">
      <NodeCard node={claim} on={on(0)} active={lit === 1} />
      <Edge label={labels[0]} on={on(1)} dir="right" />
      <NodeCard node={passage} on={on(1)} active={lit === 2} />
      <Edge label={labels[1]} on={on(2)} dir="right" />
      <NodeCard node={old} on={on(2)} active={lit === 3} />

      <div className="col-span-4" />
      <Edge label={labels[2]} on={on(3)} dir="down" />

      <motion.div
        className="flex flex-col justify-center rounded-[16px] border border-dashed border-line-strong px-4 py-3.5"
        initial={false}
        animate={{ opacity: on(5) ? 1 : 0.32 }}
        transition={{ duration: 0.45, ease }}
      >
        <span className="font-mono text-[11px] text-muted">Result</span>
        <p className="mt-1.5 flex flex-wrap items-center gap-2 text-[14px] leading-snug">
          <VerdictTag verdict="stale" /> cites the newer fact, and the fix goes to its owner.
        </p>
      </motion.div>
      <Edge label="ROUTED_TO" on={on(5)} dir="left" />
      <NodeCard node={owner} on={on(4)} active={lit === 5} />
      <Edge label={labels[3]} on={on(4)} dir="left" />
      <NodeCard node={fresh} on={on(3)} active={lit === 4} />
    </div>
  )
}

/** On a phone the walk reads top to bottom. */
function GraphList() {
  const order = [0, 1, 2, 3, 4]
  return (
    <ol className="space-y-2">
      {order.map((i) => {
        const n = nodes[i]
        return (
          <li key={n.id}>
            <div className={`rounded-[16px] px-4 py-3 ${toneClass[n.tone]}`}>
              <span className={`font-mono text-[11px] ${n.tone === 'night' ? 'text-[#a3a8b3]' : 'text-muted'}`}>{n.kind}</span>
              <p className={`mt-1 text-[15px] font-semibold ${n.tone === 'proof' ? 'text-proof line-through decoration-proof/50' : ''}`}>{n.title}</p>
              <p className={`text-[13px] ${n.tone === 'night' ? 'text-[#a3a8b3]' : 'text-muted'}`}>{n.detail}</p>
            </div>
            {i < labels.length && <p className="py-1.5 pl-4 font-mono text-[11px] font-semibold text-muted">{labels[i]}</p>}
          </li>
        )
      })}
    </ol>
  )
}

export function HowItChecks() {
  return (
    <Slab id="check" tone="paper-2" className="py-24 sm:py-32">
      <Container>
        <SectionTitle
          title="One sentence, walked through the graph."
          lede="Search finds the words. Only a graph knows that one fact replaced another, when it happened, and whose page is now wrong."
        />
        <div className="mt-14 rounded-[22px] bg-paper p-5 ring-1 ring-line sm:p-8">
          <div className="hidden lg:block">
            <GraphWalk />
          </div>
          <div className="lg:hidden">
            <GraphList />
          </div>
        </div>
        <div className="mt-4 grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.15fr)]">
          <ol className="grid gap-px overflow-hidden rounded-[22px] bg-line ring-1 ring-line">
            {steps.map(([title, body], i) => (
              <li key={title} className="grid grid-cols-[36px_minmax(0,1fr)] gap-x-3 bg-paper px-6 py-5">
                <span className="grid size-7 place-items-center rounded-full bg-ink font-mono text-[12px] font-semibold text-paper">{i + 1}</span>
                <div>
                  <p className="text-[16px] font-semibold tracking-[-0.01em]">{title}</p>
                  <p className="mt-1 text-[14.5px] leading-relaxed text-muted text-pretty">{body}</p>
                </div>
              </li>
            ))}
          </ol>
          <div className="flex flex-col overflow-hidden rounded-[22px] bg-night text-paper">
            <div className="flex items-center justify-between border-b border-night-line px-6 py-3.5">
              <span className="font-mono text-[12px] text-[#a3a8b3]">The check, in Cypher</span>
              <span className="font-mono text-[12px] text-marker">FalkorDB</span>
            </div>
            <pre className="flex-1 overflow-x-auto px-6 py-6 font-mono text-[13px] leading-[1.85] text-[#e4e6ec] [font-variant-ligatures:none]">{QUERY}</pre>
          </div>
        </div>
      </Container>
    </Slab>
  )
}
