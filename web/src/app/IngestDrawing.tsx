// A repository being read into a graph, drawn from the job's progress: each source's line carries dots while it
// is read, and the graph grows as its counts do. The same picture as the site's Sources section, on paper.

import { animate, motion, useReducedMotion } from 'motion/react'
import { useEffect, useMemo, useRef, type ReactNode } from 'react'
import type { Job } from './account'

const STROKE = '#8b909a'
const FILL = 'var(--paper-2)'

const glyphs: Record<string, ReactNode> = {
  docs: (
    <>
      <path d="M4 2 H26 L36 12 V46 H4 Z" fill={FILL} stroke={STROKE} strokeWidth="1.5" strokeLinejoin="round" />
      <path d="M26 2 V12 H36" fill="none" stroke={STROKE} strokeWidth="1.5" strokeLinejoin="round" />
      <rect x="9" y="17" width="17" height="4" rx="2" fill="var(--ink)" />
      <rect x="9" y="26" width="22" height="2.5" rx="1.25" fill={STROKE} />
      <rect x="9" y="32" width="22" height="2.5" rx="1.25" fill={STROKE} />
      <rect x="9" y="38" width="14" height="2.5" rx="1.25" fill={STROKE} />
    </>
  ),
  codeowners: (
    <>
      <g fill="none" stroke={STROKE} strokeWidth="1.5">
        <path d="M20 13 V22 M8 22 H32 M8 22 V31 M20 22 V31 M32 22 V31" />
      </g>
      <rect x="13" y="3" width="14" height="10" rx="3" fill="var(--marker)" stroke="#d9b400" strokeWidth="1" />
      <rect x="3" y="31" width="10" height="10" rx="3" fill={FILL} stroke={STROKE} strokeWidth="1.5" />
      <rect x="15" y="31" width="10" height="10" rx="3" fill={FILL} stroke={STROKE} strokeWidth="1.5" />
      <rect x="27" y="31" width="10" height="10" rx="3" fill={FILL} stroke={STROKE} strokeWidth="1.5" />
    </>
  ),
  pulls: (
    <>
      <rect x="4" y="2" width="32" height="44" rx="4" fill={FILL} stroke={STROKE} strokeWidth="1.5" />
      <g fill="none" stroke="var(--ink)" strokeWidth="1.5" strokeLinecap="round">
        <circle cx="13" cy="12" r="3" />
        <circle cx="13" cy="36" r="3" />
        <circle cx="27" cy="36" r="3" />
        <path d="M13 15 V33" />
        <path d="M27 33 V22 Q27 17 22 17 H18" />
      </g>
    </>
  ),
  issues: (
    <>
      <rect x="4" y="2" width="32" height="44" rx="4" fill={FILL} stroke={STROKE} strokeWidth="1.5" />
      <circle cx="14" cy="14" r="5" fill="none" stroke="var(--ink)" strokeWidth="1.5" />
      <circle cx="14" cy="14" r="1.6" fill="var(--ink)" />
      <rect x="9" y="26" width="22" height="2.5" rx="1.25" fill={STROKE} />
      <rect x="9" y="32" width="16" height="2.5" rx="1.25" fill={STROKE} />
    </>
  ),
  contributors: (
    <>
      <rect x="4" y="2" width="32" height="44" rx="4" fill={FILL} stroke={STROKE} strokeWidth="1.5" />
      <rect x="9" y="9" width="16" height="3.5" rx="1.75" fill="var(--ink)" />
      {[0, 1, 2].map((r) => [0, 1].map((c) => <circle key={`${r}${c}`} cx={14 + c * 12} cy={22 + r * 8} r="2.6" fill={STROKE} />))}
    </>
  ),
}

type SourceKey = 'docs' | 'codeowners' | 'pulls' | 'issues' | 'contributors'

const SOURCES: { key: SourceKey; name: string; unit: [string, string]; step: string }[] = [
  { key: 'docs', name: 'Docs', unit: ['page', 'pages'], step: 'docs' },
  { key: 'codeowners', name: 'CODEOWNERS', unit: ['version', 'versions'], step: 'codeowners' },
  { key: 'pulls', name: 'Pull requests', unit: ['merged', 'merged'], step: 'activity' },
  { key: 'issues', name: 'Issues', unit: ['issue', 'issues'], step: 'activity' },
  { key: 'contributors', name: 'Contributors', unit: ['person', 'people'], step: 'people' },
]

const ORDER = ['clone', 'docs', 'codeowners', 'activity', 'people', 'write', 'extract', 'link', 'judge']

type Kind = 'page' | 'fact' | 'person' | 'area' | 'team' | 'old'
type Slot = { x: number; y: number; kind: Kind; rank: number; link: number }

type Layout = {
  viewBox: [number, number]
  row: (i: number) => { x: number; y: number }
  glyph: number
  nameSize: number
  route: (i: number) => string
  hub: { x: number; y: number }
  /** The graph fans out from the hub: which way it faces (radians), how wide, how far, and how squashed. */
  fan: { facing: number; spread: number; inner: number; outer: number; sx: number; sy: number }
  k: number
}

const desktop: Layout = {
  viewBox: [1000, 430],
  row: (i) => ({ x: 0, y: 14 + i * 84 }),
  glyph: 1,
  nameSize: 16,
  route: (i) => {
    const y = 14 + i * 84 + 24
    return `M 214 ${y} C 380 ${y}, 420 215, 540 215`
  },
  hub: { x: 540, y: 215 },
  fan: { facing: 0, spread: 1.38, inner: 46, outer: 440, sx: 1, sy: 0.5 },
  k: 1,
}

const RAIL = (i: number) => 336 - i * 16
const phone: Layout = {
  viewBox: [360, 650],
  row: (i) => ({ x: 0, y: 4 + i * 50 }),
  glyph: 0.74,
  nameSize: 15,
  route: (i) => {
    const y = 4 + i * 50 + 18
    const x = RAIL(i)
    return `M 196 ${y} H ${x - 10} Q ${x} ${y} ${x} ${y + 10} V 270 C ${x} 300, 180 290, 180 318`
  },
  hub: { x: 180, y: 318 },
  fan: { facing: Math.PI / 2, spread: 1.32, inner: 40, outer: 318, sx: 0.56, sy: 1 },
  k: 0.78,
}

// The kinds of node in turn, so each kind spreads over the whole graph.
const PATTERN: Kind[] = ['page', 'fact', 'page', 'person', 'fact', 'area', 'page', 'fact', 'person', 'team', 'page', 'fact']
const SLOTS = 108

/** Places for every node the graph can show, nearest the repository first, so the graph grows outward from it. */
function slotsFor(layout: Layout): Slot[] {
  const { facing, spread, inner, outer, sx, sy } = layout.fan
  const out: Slot[] = []
  const ranks: Record<Kind, number> = { page: 0, fact: 0, person: 0, area: 0, team: 0, old: 0 }
  for (let i = 0; i < SLOTS; i++) {
    const r = inner + (outer - inner) * Math.sqrt((i + 0.5) / SLOTS)
    const a = facing + (((i * 0.6180339887 + 0.31) % 1) * 2 - 1) * spread
    const kind = PATTERN[i % PATTERN.length]
    out.push({ x: layout.hub.x + Math.cos(a) * r * sx, y: layout.hub.y + Math.sin(a) * r * sy, kind, rank: ranks[kind]++, link: -1 })
  }
  return out
}

/** Each shown node hangs off the nearest shown node placed before it, or the hub. */
function links(slots: Slot[], on: boolean[], hub: { x: number; y: number }): number[] {
  return slots.map((s, i) => {
    if (!on[i]) return -1
    let best = -1
    let dist = Math.hypot(s.x - hub.x, s.y - hub.y) * 0.8
    for (let j = 0; j < i; j++) {
      if (!on[j]) continue
      const d = Math.hypot(s.x - slots[j].x, s.y - slots[j].y)
      if (d < dist) {
        dist = d
        best = j
      }
    }
    return best
  })
}

/** How many nodes of each kind to show for the job's counts: grows fast at first, then slowly, up to every slot. */
function shown(counts: Record<string, number>): Record<Kind, number> {
  const c = (k: string) => counts[k] ?? 0
  const cap: Record<Kind, number> = { page: 36, fact: 36, person: 18, area: 9, team: 9, old: 0 }
  const scale = (n: number, full: number, kind: Kind) => (n <= 0 ? 0 : Math.max(1, Math.min(cap[kind], Math.round(cap[kind] * Math.sqrt(Math.min(n, full) / full)))))
  const pages = Math.max(c('documents'), c('docs') + c('codeowners') + c('pulls') + c('issues'))
  return {
    page: scale(pages, 400, 'page'),
    fact: scale(Math.max(c('facts'), c('codeowners') ? c('codeowners') * 2 : 0), 600, 'fact'),
    person: scale(Math.max(c('people'), c('contributors')), 150, 'person'),
    // Areas and teams are few: one node each, once the graph knows them.
    area: Math.min(cap.area, c('areas') || Math.ceil(c('codeowners') / 3)),
    team: Math.min(cap.team, c('teams') || (c('codeowners') ? 1 : 0)),
    old: Math.min(4, c('stale')),
  }
}

/** Dots that run along a path over and over while `active`. */
function Flow({ d, active, color, count = 3, duration = 1.5 }: { d: string; active: boolean; color: string; count?: number; duration?: number }) {
  const path = useRef<SVGPathElement>(null)
  const dots = useRef<(SVGCircleElement | null)[]>([])
  const reduce = useReducedMotion()
  useEffect(() => {
    const p = path.current
    if (!active || reduce || !p) return
    const length = p.getTotalLength()
    const controls = dots.current.map((dot, i) =>
      animate(0, 1, {
        duration,
        delay: (i * duration) / count,
        repeat: Infinity,
        ease: [0.45, 0, 0.55, 1],
        onUpdate: (v) => {
          if (!dot) return
          const pt = p.getPointAtLength(v * length)
          dot.setAttribute('cx', String(pt.x))
          dot.setAttribute('cy', String(pt.y))
          dot.style.opacity = String(Math.min(1, Math.sin(v * Math.PI) * 2.2))
        },
      }),
    )
    const dotsNow = dots.current
    return () => {
      controls.forEach((c) => c.stop())
      dotsNow.forEach((dot) => dot && (dot.style.opacity = '0'))
    }
  }, [active, reduce, count, duration])
  return (
    <g aria-hidden="true">
      <path ref={path} d={d} fill="none" stroke="none" />
      {Array.from({ length: count }, (_, i) => (
        <circle key={i} ref={(el) => void (dots.current[i] = el)} r={i === 0 ? 4 : 3} fill={color} style={{ opacity: 0 }} />
      ))}
    </g>
  )
}

function Node({ kind, k }: { kind: Kind; k: number }) {
  const s = (v: number) => v * k
  switch (kind) {
    case 'person':
      return <circle r={s(6.5)} fill="var(--paper)" stroke="var(--ink)" strokeWidth="1.5" />
    case 'team':
      return <circle r={s(10)} fill="var(--ink)" />
    case 'area':
      return <circle r={s(8.5)} fill="var(--marker)" stroke="#d9b400" strokeWidth="1" />
    case 'page':
      return <rect x={-s(7)} y={-s(8.5)} width={s(14)} height={s(17)} rx="2.5" fill="var(--paper)" stroke="#a3a8b3" strokeWidth="1.4" />
    case 'fact':
      return <circle r={s(5)} fill="var(--cobalt)" />
    case 'old':
      return (
        <g>
          <circle r={s(5)} fill="#c3c7ce" />
          <line x1={-s(8)} y1={s(4)} x2={s(8)} y2={-s(4)} stroke="var(--proof)" strokeWidth="2" strokeLinecap="round" />
        </g>
      )
  }
}

const pop = { type: 'spring', stiffness: 420, damping: 22 } as const

function Drawing({ layout, job, repo, className }: { layout: Layout; job: Job | null; repo: string; className: string }) {
  const reduce = useReducedMotion()
  const slots = useMemo(() => slotsFor(layout), [layout])
  const counts = job?.counts ?? {}
  const show = shown(counts)
  const stepAt = ORDER.indexOf(job?.step ?? 'clone')
  const running = job?.status === 'running'
  // The first stale facts are drawn as replaced: a struck dot where a fact was.
  const visible = slots.map((s) => {
    if (s.kind === 'fact' && s.rank < show.old) return { on: s.rank < show.fact, kind: 'old' as Kind }
    return { on: s.rank < show[s.kind], kind: s.kind }
  })
  const [w, h] = layout.viewBox
  const at = (i: number) => (i < 0 ? layout.hub : slots[i])
  const linked = links(slots, visible.map((v) => v.on), layout.hub)

  return (
    <svg viewBox={`0 0 ${w} ${h}`} className={className} role="img" aria-label={`${repo} being read into a graph`}>
      {SOURCES.map((s, i) => {
        const own = ORDER.indexOf(s.step)
        const reading = running && (s.step === job?.step || job?.step === 'write' || (s.key === 'docs' && job?.step === 'extract'))
        const done = stepAt > own || job?.status === 'done'
        return (
          <g key={s.key}>
            <path d={layout.route(i)} fill="none" stroke={reading ? 'var(--ink)' : done ? '#a3a8b3' : 'var(--line-strong)'} strokeWidth={reading ? 1.6 : 1.3} style={{ transition: 'stroke 0.4s' }} />
            <Flow d={layout.route(i)} active={reading} color={job?.step === 'extract' ? 'var(--cobalt)' : 'var(--ink)'} duration={job?.step === 'write' ? 1.1 : 1.6} />
          </g>
        )
      })}

      {/* Edges, each once both its ends are shown */}
      {slots.map((s, i) => {
        const on = visible[i].on
        const p = at(on ? linked[i] : -1)
        const replaced = visible[i].kind === 'old'
        return (
          <motion.line
            key={`e${i}`}
            x1={p.x}
            y1={p.y}
            x2={s.x}
            y2={s.y}
            stroke={replaced ? 'var(--proof)' : '#c3c7ce'}
            strokeWidth={replaced ? 1.4 : 1.1}
            strokeDasharray={replaced ? '3 3' : undefined}
            initial={false}
            animate={{ opacity: on ? 1 : 0 }}
            transition={{ duration: reduce ? 0 : 0.5, delay: reduce ? 0 : 0.15 }}
          />
        )
      })}

      {slots.map((s, i) => (
        <g key={`n${i}`} transform={`translate(${s.x} ${s.y})`}>
          <motion.g initial={false} animate={visible[i].on ? { scale: 1, opacity: 1 } : { scale: 0, opacity: 0 }} transition={reduce ? { duration: 0 } : pop}>
            <Node kind={visible[i].kind} k={layout.k} />
          </motion.g>
        </g>
      ))}

      {/* The repository the graph grows from */}
      <g transform={`translate(${layout.hub.x} ${layout.hub.y})`}>
        <circle r={13 * layout.k + 6} fill="var(--paper)" />
        <rect x={-12 * layout.k} y={-12 * layout.k} width={24 * layout.k} height={24 * layout.k} rx={7 * layout.k} fill="var(--ink)" />
        <rect x={-6 * layout.k} y={-5 * layout.k} width={12 * layout.k} height={2.6 * layout.k} rx={1.3 * layout.k} fill="var(--cobalt)" />
        <rect x={-6 * layout.k} y={-0.5 * layout.k} width={9 * layout.k} height={2.6 * layout.k} rx={1.3 * layout.k} fill="var(--paper)" />
        <rect x={-6 * layout.k} y={4 * layout.k} width={6 * layout.k} height={2.6 * layout.k} rx={1.3 * layout.k} fill="var(--proof)" />
      </g>

      {SOURCES.map((s, i) => {
        const { x, y } = layout.row(i)
        const g = layout.glyph
        const n = counts[s.key]
        const own = ORDER.indexOf(s.step)
        // A sync reads only what changed in docs, issues and pull requests; CODEOWNERS and people are read whole.
        const changes = job?.kind === 'sync' && (s.key === 'docs' || s.key === 'pulls' || s.key === 'issues')
        const label =
          n === undefined
            ? stepAt >= own && running
              ? 'reading'
              : ''
            : changes
              ? n
                ? `${n.toLocaleString()} changed`
                : 'no changes'
              : `${n.toLocaleString()} ${n === 1 ? s.unit[0] : s.unit[1]}`
        return (
          <g key={s.key} transform={`translate(${x} ${y})`}>
            <g transform={`scale(${g})`}>{glyphs[s.key]}</g>
            <text x={52 * g + 6} y={g === 1 ? 20 : 15} fontSize={layout.nameSize} fontWeight={600} fill="var(--ink)">
              {s.name}
            </text>
            <text x={52 * g + 6} y={g === 1 ? 40 : 33} fontSize={g === 1 ? 13.5 : 13} fill="var(--muted)" style={{ fontVariantNumeric: 'tabular-nums' }}>
              {label}
            </text>
          </g>
        )
      })}
    </svg>
  )
}

export function IngestDrawing({ job, repo }: { job: Job | null; repo: string }) {
  return (
    <>
      <Drawing layout={desktop} job={job} repo={repo} className="hidden h-auto w-full lg:block" />
      <Drawing layout={phone} job={job} repo={repo} className="mx-auto h-auto w-full max-w-[460px] lg:hidden" />
    </>
  )
}

export function Legend() {
  const items: [Kind, string][] = [
    ['page', 'Page'],
    ['person', 'Person'],
    ['team', 'Team'],
    ['area', 'Area'],
    ['fact', 'Fact'],
    ['old', 'Out of date'],
  ]
  return (
    <ul className="flex flex-wrap gap-x-5 gap-y-2 text-[13.5px] text-muted">
      {items.map(([kind, label]) => (
        <li key={kind} className="flex items-center gap-2">
          <svg viewBox="-12 -12 24 24" className="size-[18px]" aria-hidden="true">
            <Node kind={kind} k={1} />
          </svg>
          {label}
        </li>
      ))}
    </ul>
  )
}
