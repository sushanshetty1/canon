import { Check, GithubLogo } from '@phosphor-icons/react'
import { motion } from 'motion/react'
import type { ReactNode } from 'react'
import { Container, SectionTitle, Slab } from '../ui'
import { Traveller, ease, useSeen } from './draw'

type Tone = 'paper' | 'paper-2' | 'night' | 'cobalt' | 'marker'

function Cell({ title, body, className = '', tone, center = false, children }: { title: string; body: ReactNode; className?: string; tone: Tone; center?: boolean; children: ReactNode }) {
  const tones: Record<Tone, string> = {
    paper: 'bg-paper ring-1 ring-line',
    'paper-2': 'bg-paper-2',
    night: 'bg-night text-paper',
    cobalt: 'bg-cobalt text-paper',
    marker: 'bg-marker-soft',
  }
  const muted = tone === 'night' ? 'text-[#a3a8b3]' : tone === 'cobalt' ? 'text-white/75' : 'text-muted'
  return (
    <article className={`flex min-w-0 flex-col rounded-[24px] p-6 sm:p-8 ${tones[tone]} ${className}`}>
      <h3 className="font-display text-[25px] leading-tight font-semibold tracking-[-0.03em]">{title}</h3>
      <p className={`mt-2 max-w-[44ch] text-[15.5px] leading-relaxed text-pretty ${muted}`}>{body}</p>
      <div className={`mt-8 flex flex-1 flex-col ${center ? 'justify-center' : 'justify-end'}`}>{children}</div>
    </article>
  )
}

/* ------------------------------------------------------------------ Ask */

type Verdict = 'verified' | 'stale' | 'disputed' | 'unsupported'

/** A proofreader's mark for the margin. */
function ProofMark({ v, size = 22 }: { v: Verdict; size?: number }) {
  return (
    <svg viewBox="0 0 22 22" width={size} height={size} aria-hidden="true" className="shrink-0">
      {v === 'verified' && (
        <>
          <circle cx="11" cy="11" r="11" fill="var(--cobalt)" />
          <path d="M6.5 11.2 L9.6 14.2 L15.6 8" fill="none" stroke="var(--paper)" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
        </>
      )}
      {v === 'stale' && (
        <>
          <circle cx="11" cy="11" r="11" fill="var(--proof)" />
          <path d="M6 11 H16" stroke="var(--paper)" strokeWidth="2.4" strokeLinecap="round" />
        </>
      )}
      {v === 'disputed' && (
        <>
          <circle cx="11" cy="11" r="11" fill="var(--amber)" />
          <path d="M8.6 8.6 a2.5 2.5 0 1 1 3.4 2.3 c-0.7 0.3 -1 0.8 -1 1.5 v0.4" fill="none" stroke="var(--paper)" strokeWidth="2" strokeLinecap="round" />
          <circle cx="11" cy="15.8" r="1.2" fill="var(--paper)" />
        </>
      )}
      {v === 'unsupported' && <circle cx="11" cy="11" r="9.8" fill="none" stroke="currentColor" strokeWidth="1.6" strokeDasharray="3 2.6" />}
    </svg>
  )
}

// An answer drawn as lines of text. Widths are percentages of the line.
const answer: { v: Verdict; bars: number[]; struck?: number }[] = [
  { v: 'verified', bars: [34, 22, 30] },
  { v: 'verified', bars: [26, 48] },
  { v: 'stale', bars: [22, 30, 20], struck: 1 },
  { v: 'disputed', bars: [36, 38] },
  { v: 'unsupported', bars: [28, 24] },
  { v: 'verified', bars: [40, 18] },
]

function AskSheet() {
  const { ref, run, reduce } = useSeen<HTMLDivElement>(0.4)
  const at = (i: number) => (reduce ? 0 : 0.35 + i * 0.42)
  return (
    <div ref={ref}>
      <div className="rounded-[18px] bg-paper p-5 text-ink sm:p-7">
        {/* The question */}
        <div className="flex items-center gap-2.5 border-b border-line pb-5">
          <span className="h-[12px] w-[44%] rounded-full bg-ink" />
          <span className="h-[12px] w-[18%] rounded-full bg-ink" />
        </div>
        <ul className="pt-2">
          {answer.map((line, i) => (
            <li key={i} className="grid grid-cols-[minmax(0,1fr)_22px] items-center gap-4 py-[11px] sm:gap-6">
              <div className="relative flex items-center gap-2">
                {line.v === 'disputed' && (
                  <motion.span
                    aria-hidden="true"
                    className="absolute -inset-x-1.5 -inset-y-[5px] origin-left rounded-[6px] bg-amber-soft"
                    initial={reduce ? false : { scaleX: 0 }}
                    animate={run ? { scaleX: 1 } : undefined}
                    transition={{ duration: 0.5, delay: at(i), ease }}
                  />
                )}
                {line.bars.map((w, j) => {
                  const struck = line.struck === j
                  return (
                    <span key={j} className="relative h-[10px]" style={{ width: `${w}%` }}>
                      <span
                        className={`absolute inset-0 rounded-full ${
                          line.v === 'unsupported' ? 'border-[1.5px] border-dashed border-line-strong' : struck ? 'bg-line' : line.v === 'disputed' ? 'bg-[#e6c27c]' : 'bg-line-strong'
                        }`}
                      />
                      {struck && (
                        <>
                          <motion.span
                            aria-hidden="true"
                            className="absolute top-1/2 -right-1 -left-1 h-[2.5px] origin-left -translate-y-1/2 rounded-full bg-proof"
                            initial={reduce ? false : { scaleX: 0 }}
                            animate={run ? { scaleX: 1 } : undefined}
                            transition={{ duration: 0.4, delay: at(i), ease }}
                          />
                          {/* The correction, written in above the line with a caret */}
                          <motion.span
                            className="absolute -top-[15px] left-[12%] h-[9px] w-[80%] rounded-full bg-cobalt"
                            initial={reduce ? false : { opacity: 0, y: 4 }}
                            animate={run ? { opacity: 1, y: 0 } : undefined}
                            transition={{ duration: 0.4, delay: at(i) + (reduce ? 0 : 0.35), ease }}
                          />
                          <motion.svg
                            viewBox="0 0 12 8"
                            className="absolute top-[13px] -left-[9px] h-[8px] w-[12px]"
                            initial={reduce ? false : { opacity: 0 }}
                            animate={run ? { opacity: 1 } : undefined}
                            transition={{ duration: 0.3, delay: at(i) + (reduce ? 0 : 0.35) }}
                            aria-hidden="true"
                          >
                            <path d="M1 7 L6 1.5 L11 7" fill="none" stroke="var(--cobalt)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                          </motion.svg>
                        </>
                      )}
                    </span>
                  )
                })}
              </div>
              <motion.span
                className="text-faint"
                initial={reduce ? false : { opacity: 0, scale: 0.4 }}
                animate={run ? { opacity: 1, scale: 1 } : undefined}
                transition={{ duration: 0.4, delay: at(i), ease: [0.34, 1.5, 0.64, 1] }}
              >
                <ProofMark v={line.v} />
              </motion.span>
            </li>
          ))}
        </ul>
      </div>
      <ul className="mt-5 flex flex-wrap gap-x-5 gap-y-2 text-[14px] text-white/85">
        {(
          [
            ['verified', 'Verified'],
            ['stale', 'Out of date'],
            ['disputed', 'Disputed'],
            ['unsupported', 'Not said'],
          ] as const
        ).map(([v, label]) => (
          <li key={v} className="flex items-center gap-2">
            <span className={`grid place-items-center rounded-full ${v === 'unsupported' ? 'text-white/70' : 'bg-paper'}`}>
              <ProofMark v={v} size={16} />
            </span>
            {label}
          </li>
        ))}
      </ul>
    </div>
  )
}

/* ------------------------------------------------------------------ Who actually knows */

// Evidence weight is the edge's thickness. An example area, not real people.
const AREA = { x: 160, y: 150 }
const knowers = [
  { x: 278, y: 62, w: 11, label: 'reviewed', top: true },
  { x: 42, y: 76, w: 6, label: 'wrote' },
  { x: 38, y: 236, w: 3.5, label: 'answered' },
  { x: 284, y: 238, w: 2.2, label: 'decided' },
  { x: 160, y: 20, w: 1.4 },
]

/** Where an edge label sits: at the middle of the edge, set along it, lifted clear of its stroke. */
function alongEdge(p: { x: number; y: number; w: number }) {
  const dx = p.x - AREA.x
  const dy = p.y - AREA.y
  const len = Math.hypot(dx, dy)
  let angle = (Math.atan2(dy, dx) * 180) / Math.PI
  if (angle > 90 || angle < -90) angle += 180
  // Lift the label to the upper side of the edge.
  let nx = -dy / len
  let ny = dx / len
  if (ny > 0) {
    nx = -nx
    ny = -ny
  }
  const lift = p.w / 2 + 7
  return { x: AREA.x + dx * 0.56 + nx * lift, y: AREA.y + dy * 0.56 + ny * lift, angle }
}

function WhoKnows() {
  const { ref, run, reduce } = useSeen<SVGSVGElement>(0.45)
  const later = (t: number) => (reduce ? 0 : t)
  const crown = 0.3 + knowers.length * 0.22 + 0.5
  return (
    <svg ref={ref} viewBox="0 0 320 290" className="mx-auto h-auto w-full max-w-[420px]" role="img" aria-label="People around an area, joined by edges as thick as their evidence">
      {knowers.map((p, i) => (
        <motion.line
          key={i}
          x1={AREA.x}
          y1={AREA.y}
          x2={p.x}
          y2={p.y}
          stroke={p.top ? 'var(--cobalt)' : 'var(--ink)'}
          strokeLinecap="round"
          initial={reduce ? false : { strokeWidth: 0.8, opacity: 0.3 }}
          animate={run ? { strokeWidth: p.w, opacity: 1 } : undefined}
          transition={{ duration: 0.7, delay: later(0.3 + i * 0.22), ease }}
        />
      ))}
      {knowers.map((p, i) => {
        if (!p.label) return null
        const l = alongEdge(p)
        return (
          <motion.text
            key={p.label}
            transform={`translate(${l.x} ${l.y}) rotate(${l.angle})`}
            textAnchor="middle"
            fontSize="12.5"
            fontWeight={p.top ? 650 : 500}
            fill={p.top ? 'var(--cobalt)' : 'var(--muted)'}
            initial={reduce ? false : { opacity: 0 }}
            animate={run ? { opacity: 1 } : undefined}
            transition={{ duration: 0.4, delay: later(0.5 + i * 0.22) }}
          >
            {p.label}
          </motion.text>
        )
      })}
      {knowers.map((p, i) => (
        <g key={i} transform={`translate(${p.x} ${p.y})`}>
          {p.top && (
            <motion.circle
              r="22"
              fill="none"
              stroke="var(--cobalt)"
              strokeWidth="1.5"
              initial={reduce ? false : { opacity: 0, scale: 0.6 }}
              animate={run ? { opacity: 1, scale: 1 } : undefined}
              transition={{ duration: 0.5, delay: later(crown), ease }}
            />
          )}
          <circle r={p.top ? 14 : 10} fill={p.top ? 'var(--cobalt)' : 'var(--paper)'} stroke={p.top ? 'none' : 'var(--ink)'} strokeWidth="2" />
        </g>
      ))}
      <circle cx={AREA.x} cy={AREA.y} r="22" fill="var(--marker)" stroke="var(--paper-2)" strokeWidth="5" />
      <text x={AREA.x} y={AREA.y + 44} textAnchor="middle" fontSize="13.5" fontWeight="600" fill="var(--ink)">
        Session replay
      </text>
      <motion.text
        x={278}
        y={26}
        textAnchor="middle"
        fontSize="12.5"
        fontWeight="600"
        fill="var(--cobalt)"
        initial={reduce ? false : { opacity: 0 }}
        animate={run ? { opacity: 1 } : undefined}
        transition={{ duration: 0.4, delay: later(crown + 0.1) }}
      >
        Ask them first
      </motion.text>
    </svg>
  )
}

/* ------------------------------------------------------------------ Bus factor */

const bus = {
  area: { x: 26, y: 84 },
  mid: [
    { x: 136, y: 38 },
    { x: 136, y: 130 },
  ],
  far: [
    { x: 262, y: 12 },
    { x: 262, y: 62 },
    { x: 262, y: 106 },
    { x: 262, y: 156 },
  ],
}
const curve = (a: { x: number; y: number }, b: { x: number; y: number }) => `M ${a.x} ${a.y} C ${(a.x + b.x) / 2} ${a.y}, ${(a.x + b.x) / 2} ${b.y}, ${b.x} ${b.y}`
const CUT_X = 76

function BusFactor() {
  const { ref, run, reduce } = useSeen<HTMLDivElement>(0.45)
  const later = (t: number) => (reduce ? 0 : t)
  const links: [number, number][] = [
    [0, 0],
    [0, 1],
    [0, 2],
    [1, 2],
    [1, 3],
  ]
  return (
    <div ref={ref}>
      <div className="flex items-end gap-4">
        <motion.span
          className="font-display text-[104px] leading-[0.78] font-semibold tracking-[-0.05em] text-paper"
          initial={reduce ? false : { opacity: 0, y: 10 }}
          animate={run ? { opacity: 1, y: 0 } : undefined}
          transition={{ duration: 0.5, delay: later(2.3), ease }}
        >
          2
        </motion.span>
        <span className="pb-1 text-[16px] leading-snug font-semibold">
          people could
          <br />
          still answer
        </span>
      </div>
      <svg viewBox="0 0 290 168" className="mt-7 h-auto w-full max-w-[440px]" role="img" aria-label="Two edges carry all the knowledge from the area to the people who know it; cutting them is the bus factor">
        {links.map(([m, f]) => (
          <path key={`${m}${f}`} d={curve(bus.mid[m], bus.far[f])} fill="none" stroke="#3a3f4b" strokeWidth="1.5" />
        ))}
        {bus.mid.map((m, i) => (
          <path key={i} d={curve(bus.area, m)} fill="none" stroke="var(--paper)" strokeWidth="3" strokeLinecap="round" />
        ))}
        {!reduce &&
          bus.mid.map((m, i) => [0, 1].map((j) => <Traveller key={`${i}${j}`} d={`${curve(bus.area, m)} ${curve(m, bus.far[i === 0 ? j : j + 2]).replace('M', 'L')}`} run={run} delay={0.2 + j * 0.45 + i * 0.12} duration={1.3} r={3.5} fill="var(--marker)" />))}
        {/* The minimum cut: the two edges every path has to cross */}
        <motion.line
          x1={CUT_X}
          y1="6"
          x2={CUT_X}
          y2="162"
          stroke="var(--proof)"
          strokeWidth="2.5"
          strokeDasharray="6 5"
          strokeLinecap="round"
          initial={reduce ? false : { pathLength: 0 }}
          animate={run ? { pathLength: 1 } : undefined}
          transition={{ duration: 0.6, delay: later(1.7), ease }}
        />
        {bus.mid.map((m, i) => (
          <motion.g
            key={i}
            initial={reduce ? false : { opacity: 0, scale: 0.4 }}
            animate={run ? { opacity: 1, scale: 1 } : undefined}
            transition={{ duration: 0.35, delay: later(2), ease }}
            style={{ transformOrigin: `${CUT_X}px ${curvePointY(bus.area, m)}px` }}
          >
            <circle cx={CUT_X} cy={curvePointY(bus.area, m)} r="7" fill="var(--proof)" />
            <path d={`M ${CUT_X - 3} ${curvePointY(bus.area, m) - 3} l 6 6 m 0 -6 l -6 6`} stroke="var(--paper)" strokeWidth="1.8" strokeLinecap="round" />
          </motion.g>
        ))}
        {bus.far.map((p, i) => (
          <circle key={i} cx={p.x} cy={p.y} r="8" fill="var(--night)" stroke="#7d828e" strokeWidth="1.5" />
        ))}
        {bus.mid.map((p, i) => (
          <circle key={i} cx={p.x} cy={p.y} r="10" fill="var(--paper)" />
        ))}
        <circle cx={bus.area.x} cy={bus.area.y} r="14" fill="var(--marker)" />
      </svg>
      <p className="mt-5 text-[14px] leading-relaxed text-[#a3a8b3]">
        The cut is <code className="font-mono text-[13px] text-paper">algo.maxFlow</code> from the area to everyone who knows it.
      </p>
    </div>
  )
}

/** Where a bus curve crosses the cut line. The curves are symmetric cubic Beziers, so solve for x numerically. */
function curvePointY(a: { x: number; y: number }, b: { x: number; y: number }) {
  const mx = (a.x + b.x) / 2
  const bez = (t: number, p0: number, p1: number, p2: number, p3: number) => (1 - t) ** 3 * p0 + 3 * (1 - t) ** 2 * t * p1 + 3 * (1 - t) * t ** 2 * p2 + t ** 3 * p3
  let lo = 0
  let hi = 1
  for (let i = 0; i < 30; i++) {
    const t = (lo + hi) / 2
    if (bez(t, a.x, mx, mx, b.x) < CUT_X) lo = t
    else hi = t
  }
  return bez(lo, a.y, a.y, b.y, b.y)
}

/* ------------------------------------------------------------------ Fix queue */

function Connector({ run, reduce, delay }: { run: boolean; reduce: boolean; delay: number }) {
  return (
    <div className="relative flex min-h-9 min-w-6 flex-1 items-center justify-center md:mb-7 md:self-center" aria-hidden="true">
      <span className="absolute inset-y-0 left-1/2 w-[2px] -translate-x-1/2 bg-ink/15 md:inset-x-0 md:inset-y-auto md:top-1/2 md:left-0 md:h-[2px] md:w-auto md:translate-x-0 md:-translate-y-1/2" />
      <motion.span
        className="absolute inset-y-0 left-1/2 w-[2px] origin-top -translate-x-1/2 bg-ink md:inset-x-0 md:inset-y-auto md:top-1/2 md:left-0 md:h-[2px] md:w-auto md:origin-left md:translate-x-0 md:-translate-y-1/2"
        initial={reduce ? false : { scale: 0 }}
        animate={run ? { scale: 1 } : undefined}
        transition={{ duration: 0.6, delay: reduce ? 0 : delay, ease: [0.45, 0, 0.25, 1] }}
      />
      <svg viewBox="0 0 10 10" className="absolute -bottom-0.5 left-1/2 size-2.5 -translate-x-1/2 rotate-90 md:top-1/2 md:right-[-2px] md:bottom-auto md:left-auto md:translate-x-0 md:-translate-y-1/2 md:rotate-0">
        <path d="M2 1 L8 5 L2 9" fill="none" stroke="var(--ink)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    </div>
  )
}

function Station({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex shrink-0 flex-col items-center">
      {children}
      <span className="mt-2.5 text-[13.5px] font-medium whitespace-nowrap text-ink/70 lg:text-[12.5px] xl:text-[13.5px]">{label}</span>
    </div>
  )
}

function FixQueue() {
  const { ref, run, reduce } = useSeen<HTMLDivElement>(0.45)
  const later = (t: number) => (reduce ? 0 : t)
  return (
    <div ref={ref} className="flex flex-col items-center md:flex-row md:items-center">
      <Station label="Handbook page">
        <div className="w-[200px] rounded-[14px] bg-paper p-5 lg:w-[150px] lg:p-4 xl:w-[200px] xl:p-5 shadow-[0_1px_0_rgb(13_14_18/0.06)] ring-1 ring-[#efd77a]">
          <span className="block h-[9px] w-[58%] rounded-full bg-ink" />
          <div className="mt-4 space-y-[13px]">
            <span className="block h-[7px] w-full rounded-full bg-line-strong" />
            <span className="relative block h-[7px] w-[86%] rounded-full bg-line">
              <motion.span
                className="absolute top-1/2 -right-1 -left-1 h-[2.5px] origin-left -translate-y-1/2 rounded-full bg-proof"
                initial={reduce ? false : { scaleX: 0 }}
                animate={run ? { scaleX: 1 } : undefined}
                transition={{ duration: 0.45, delay: later(0.3), ease }}
              />
              <motion.span
                className="absolute -top-[11px] left-[18%] h-[6px] w-[64%] rounded-full bg-cobalt"
                initial={reduce ? false : { opacity: 0, y: 4 }}
                animate={run ? { opacity: 1, y: 0 } : undefined}
                transition={{ duration: 0.4, delay: later(0.7), ease }}
              />
            </span>
            <span className="block h-[7px] w-[92%] rounded-full bg-line-strong" />
            <span className="block h-[7px] w-[74%] rounded-full bg-line-strong" />
            <span className="block h-[7px] w-full rounded-full bg-line-strong" />
            <span className="block h-[7px] w-[48%] rounded-full bg-line-strong" />
          </div>
        </div>
      </Station>
      <Connector run={run} reduce={reduce} delay={1.0} />
      <Station label="Page owner">
        <motion.div
          className="grid size-[60px] place-items-center rounded-full bg-night lg:size-[48px] xl:size-[60px]"
          initial={reduce ? false : { scale: 0.8, opacity: 0.4 }}
          animate={run ? { scale: 1, opacity: 1 } : undefined}
          transition={{ duration: 0.4, delay: later(1.6), ease: [0.34, 1.5, 0.64, 1] }}
        >
          <svg viewBox="-12 -12 24 24" className="size-7" aria-hidden="true">
            <circle cy="-4.5" r="5" fill="var(--paper)" />
            <path d="M -9.5 11 C -9.5 3.5, 9.5 3.5, 9.5 11 Z" fill="var(--paper)" />
          </svg>
        </motion.div>
      </Station>
      <Connector run={run} reduce={reduce} delay={1.8} />
      <Station label="A person approves">
        <div className="relative h-10 overflow-hidden rounded-full shadow-[inset_0_0_0_1.5px_var(--ink)]">
          <motion.span
            className="absolute inset-0 origin-left bg-ink"
            initial={reduce ? false : { scaleX: 0 }}
            animate={run ? { scaleX: 1 } : undefined}
            transition={{ duration: 0.5, delay: later(2.5), ease }}
          />
          <span className="relative flex h-full items-center gap-2 px-4 text-[14px] lg:px-3 xl:px-4 font-semibold text-ink">
            <Check size={15} weight="bold" />
            Approve
          </span>
          <motion.span
            className="absolute inset-0 flex items-center gap-2 px-4 text-[14px] lg:px-3 xl:px-4 font-semibold text-paper"
            initial={reduce ? false : { clipPath: 'inset(0 100% 0 0)' }}
            animate={run ? { clipPath: 'inset(0 0% 0 0)' } : undefined}
            transition={{ duration: 0.5, delay: later(2.5), ease }}
          >
            <Check size={15} weight="bold" />
            Approve
          </motion.span>
        </div>
      </Station>
      <Connector run={run} reduce={reduce} delay={3.1} />
      <Station label="Issue filed">
        <motion.div
          className="w-[148px] rounded-[14px] bg-paper p-4 ring-1 lg:w-[116px] lg:p-3 xl:w-[148px] xl:p-4 ring-[#efd77a]"
          initial={reduce ? false : { opacity: 0.35, y: 6 }}
          animate={run ? { opacity: 1, y: 0 } : undefined}
          transition={{ duration: 0.45, delay: later(3.7), ease }}
        >
          <div className="flex items-center gap-2">
            <GithubLogo size={18} weight="fill" className="text-ink" />
            <svg viewBox="0 0 16 16" className="size-4" aria-hidden="true">
              <circle cx="8" cy="8" r="6.5" fill="none" stroke="#1a7f37" strokeWidth="1.6" />
              <circle cx="8" cy="8" r="1.6" fill="#1a7f37" />
            </svg>
          </div>
          <span className="mt-3 block h-[7px] w-[88%] rounded-full bg-ink/80" />
          <span className="mt-2.5 block h-[6px] w-[64%] rounded-full bg-line-strong" />
          <span className="mt-2 block h-[6px] w-[80%] rounded-full bg-line-strong" />
        </motion.div>
      </Station>
    </div>
  )
}

/* ------------------------------------------------------------------ Decisions */

function DocShape({ tone }: { tone: 'old' | 'current' }) {
  const current = tone === 'current'
  return (
    <svg viewBox="0 0 64 80" className="h-auto w-full" aria-hidden="true">
      <path d="M3 3 H44 L61 20 V77 H3 Z" fill={current ? 'var(--cobalt)' : 'var(--paper-2)'} stroke={current ? 'var(--cobalt)' : 'var(--line-strong)'} strokeWidth="2" strokeLinejoin="round" />
      <path d="M44 3 V20 H61" fill="none" stroke={current ? 'var(--cobalt-soft)' : 'var(--line-strong)'} strokeWidth="2" strokeLinejoin="round" />
      <rect x="11" y="24" width="30" height="6" rx="3" fill={current ? 'var(--paper)' : 'var(--line-strong)'} />
      {[38, 47, 56].map((y, i) => (
        <rect key={y} x="11" y={y} width={i === 2 ? 26 : 42} height="4" rx="2" fill={current ? 'rgb(255 255 255 / 0.55)' : 'var(--line)'} />
      ))}
    </svg>
  )
}

const DOCS = ['First design doc', 'Revised', 'Current']
const docAppears = (i: number) => 0.2 + i * 0.75

/** "superseded by": an arrow down on a phone, across on anything wider. */
function SupersededBy({ i, run, reduce }: { i: number; run: boolean; reduce: boolean }) {
  return (
    <div className="flex items-center gap-3 py-1 pl-[25px] sm:min-w-0 sm:flex-1 sm:flex-col sm:gap-1.5 sm:px-1 sm:pt-[30px] sm:pb-0">
      <div className="relative h-9 w-[2px] sm:h-[2px] sm:w-full">
        <motion.span
          className="absolute inset-0 origin-top bg-ink sm:origin-left"
          initial={reduce ? false : { scale: 0 }}
          animate={run ? { scale: 1 } : undefined}
          transition={{ duration: 0.4, delay: reduce ? 0 : docAppears(i) + 0.4 }}
        />
        <svg viewBox="0 0 10 10" className="absolute -bottom-1 left-1/2 size-2.5 -translate-x-1/2 rotate-90 sm:top-1/2 sm:-right-1 sm:bottom-auto sm:left-auto sm:translate-x-0 sm:-translate-y-1/2 sm:rotate-0" aria-hidden="true">
          <path d="M2 1 L8 5 L2 9" fill="none" stroke="var(--ink)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </div>
      <span className="text-[12.5px] leading-tight whitespace-nowrap text-muted sm:text-center sm:whitespace-normal">superseded by</span>
    </div>
  )
}

function Decisions() {
  const { ref, run, reduce } = useSeen<HTMLDivElement>(0.45)
  const later = (t: number) => (reduce ? 0 : t)
  return (
    <div ref={ref}>
      <div className="flex flex-col sm:flex-row sm:items-start">
        {DOCS.map((name, i) => {
          const last = i === DOCS.length - 1
          return (
            <div key={name} className="contents">
              <div className="flex items-center gap-4 sm:w-[72px] sm:shrink-0 sm:flex-col sm:gap-2.5">
                <div className="relative w-[52px] shrink-0 sm:w-[72px]">
                  {/* Each doc arrives as the current one, then greys when the next one replaces it */}
                  <motion.div
                    initial={reduce ? false : { opacity: 0, y: 8 }}
                    animate={run ? { opacity: 1, y: 0 } : undefined}
                    transition={{ duration: 0.45, delay: later(docAppears(i)), ease }}
                  >
                    <DocShape tone="old" />
                  </motion.div>
                  {!reduce && !last && (
                    <motion.div
                      className="absolute inset-0"
                      initial={{ opacity: 0 }}
                      animate={run ? { opacity: [0, 1, 1, 0] } : undefined}
                      transition={{ duration: 0.85, times: [0, 0.1, 0.75, 1], delay: docAppears(i) }}
                    >
                      <DocShape tone="current" />
                    </motion.div>
                  )}
                  {last && (
                    <motion.div
                      className="absolute inset-0"
                      initial={reduce ? false : { opacity: 0 }}
                      animate={run ? { opacity: 1 } : undefined}
                      transition={{ duration: 0.3, delay: later(docAppears(i)) }}
                    >
                      <DocShape tone="current" />
                    </motion.div>
                  )}
                </div>
                <span className={`text-[13px] leading-tight font-medium sm:text-center ${last ? 'text-cobalt' : 'text-faint'}`}>{name}</span>
              </div>
              {!last && <SupersededBy i={i} run={run} reduce={reduce} />}
            </div>
          )
        })}
      </div>
      {/* The pull requests that shipped the current decision, branching off below it */}
      <div className="mt-1 flex items-end gap-3 sm:justify-end">
        <svg viewBox="0 0 72 74" className="order-first w-[52px] shrink-0 overflow-visible sm:order-last sm:w-[72px]" aria-hidden="true">
          <motion.path
            d="M 36 0 V 64"
            stroke="var(--cobalt)"
            strokeWidth="2.5"
            fill="none"
            initial={reduce ? false : { pathLength: 0 }}
            animate={run ? { pathLength: 1 } : undefined}
            transition={{ duration: 0.5, delay: later(2.1) }}
          />
          {['M 36 10 C 36 26, 10 22, 10 40', 'M 36 28 C 36 44, 62 40, 62 58'].map((d, i) => (
            <motion.path
              key={d}
              d={d}
              stroke="var(--cobalt)"
              strokeWidth="2.5"
              fill="none"
              initial={reduce ? false : { pathLength: 0 }}
              animate={run ? { pathLength: 1 } : undefined}
              transition={{ duration: 0.45, delay: later(2.3 + i * 0.2) }}
            />
          ))}
          {[
            [10, 45],
            [62, 63],
            [36, 69],
          ].map(([x, y], i) => (
            <motion.circle
              key={i}
              cx={x}
              cy={y}
              r="5"
              fill="var(--paper)"
              stroke="var(--cobalt)"
              strokeWidth="2.5"
              initial={reduce ? false : { opacity: 0 }}
              animate={run ? { opacity: 1 } : undefined}
              transition={{ duration: 0.3, delay: later(2.6 + i * 0.12) }}
            />
          ))}
        </svg>
        <motion.span
          className="pb-0.5 text-[13px] font-medium text-cobalt"
          initial={reduce ? false : { opacity: 0 }}
          animate={run ? { opacity: 1 } : undefined}
          transition={{ duration: 0.4, delay: later(2.6) }}
        >
          The pull requests that shipped it
        </motion.span>
      </div>
    </div>
  )
}

/* ------------------------------------------------------------------ Catch me up */

// Five months; you were away from mid July. Today is mid October.
const CM = ['Jun', 'Jul', 'Aug', 'Sep', 'Oct']
const C_SPAN = 5
const C_TODAY = 4.5
const C_FROM = 1.4
const cp = (m: number) => `${(m / C_SPAN) * 100}%`
const catchRows = [
  { change: 1.65, label: 'Decision replaced' },
  { change: 2.3, label: 'Owner changed' },
  { change: 2.95, label: 'Page edited' },
]

function CatchMeUp() {
  const { ref, run, reduce } = useSeen<HTMLDivElement>(0.45)
  const sweep = 1.6
  const when = (m: number) => (reduce ? 0 : 0.3 + ((m - C_FROM) / (C_TODAY - C_FROM)) * sweep)
  return (
    <div ref={ref} className="relative">
      <div className="relative h-6">
        {CM.map((m, i) => (
          <span key={m} className="absolute top-0 pl-1.5 text-[12.5px] font-medium text-faint" style={{ left: cp(i) }}>
            {m}
          </span>
        ))}
      </div>
      <div className="relative">
        <div className="pointer-events-none absolute inset-0" aria-hidden="true">
          {CM.map((m, i) => (
            <span key={m} className="absolute inset-y-0 w-px bg-line" style={{ left: cp(i) }} />
          ))}
          {/* The range you asked about */}
          <motion.span
            className="absolute -top-1 -bottom-1 origin-left rounded-[10px] bg-cobalt/[0.09] ring-[1.5px] ring-cobalt/40 ring-inset"
            style={{ left: cp(C_FROM), width: `calc(${cp(C_TODAY - C_FROM)} + 2px)` }}
            initial={reduce ? false : { scaleX: 0 }}
            animate={run ? { scaleX: 1 } : undefined}
            transition={{ duration: reduce ? 0 : sweep, delay: reduce ? 0 : 0.3, ease: 'linear' }}
          />
        </div>
        {catchRows.map((row) => (
          <div key={row.label} className="relative h-[46px] border-t border-line first:border-t-0">
            {/* Before the change */}
            <div
              className="absolute top-[9px] bottom-[9px] rounded-[9px] ring-1 ring-line ring-inset"
              style={{
                left: 'calc(0% + 2px)',
                width: `calc(${cp(row.change)} - 5px)`,
                backgroundImage: 'repeating-linear-gradient(135deg, var(--paper-2) 0 6px, #e7e9ee 6px 7px)',
              }}
            />
            {/* After it: what is true now, labelled with what changed */}
            <motion.div
              className="absolute top-[9px] bottom-[9px] flex items-center overflow-hidden rounded-[9px] bg-cobalt px-2.5"
              style={{ left: `calc(${cp(row.change)} + 2px)`, right: 2 }}
              initial={reduce ? false : { clipPath: 'inset(0 100% 0 0 round 9px)' }}
              animate={run ? { clipPath: 'inset(0 0% 0 0 round 9px)' } : undefined}
              transition={{ duration: reduce ? 0 : Math.max(0.3, when(C_TODAY) - when(row.change)), delay: when(row.change), ease: 'linear' }}
            >
              <span className="truncate text-[13px] font-semibold text-paper">{row.label}</span>
            </motion.div>
            <motion.span
              className="absolute top-1/2 z-10 size-3 -translate-x-1/2 -translate-y-1/2 rounded-full bg-paper ring-[2.5px] ring-ink"
              style={{ left: cp(row.change) }}
              initial={reduce ? false : { scale: 0 }}
              animate={run ? { scale: 1 } : undefined}
              transition={{ duration: 0.35, delay: when(row.change), ease: [0.34, 1.6, 0.64, 1] }}
            />
          </div>
        ))}
        {/* Today */}
        <span className="absolute -top-1 -bottom-1 w-[2px] -translate-x-1/2 bg-ink" style={{ left: cp(C_TODAY) }} aria-hidden="true" />
      </div>
      <div className="relative mt-3 h-6 text-[12.5px] font-semibold">
        <span className="absolute text-cobalt" style={{ left: cp(C_FROM) }}>
          Since you left
        </span>
        <span className="absolute -translate-x-full pr-1.5 text-ink" style={{ left: cp(C_TODAY + 0.5) }}>
          Today
        </span>
      </div>
    </div>
  )
}

export function Product() {
  return (
    <Slab id="product" tone="paper" className="py-24 sm:py-32">
      <Container>
        <SectionTitle
          title="What a team asks Canon every day."
          lede="Questions about who, why and what changed. Each answer is checked the same way, and each one cites where it came from."
        />
        <div className="mt-14 grid gap-4 lg:grid-cols-6">
          <Cell className="lg:col-span-4" tone="cobalt" title="Ask anything about the company" body="Plain questions, answered claim by claim. Every sentence gets a mark in the margin, and its source.">
            <AskSheet />
          </Cell>
          <Cell className="lg:col-span-2" tone="paper-2" center title="Who actually knows" body="Ranked by what people did: reviewed, wrote, decided, answered. Not by job title.">
            <WhoKnows />
          </Cell>
          <Cell className="lg:col-span-2" tone="night" title="Bus factor" body="For each area, how many people could still answer if the rest left.">
            <BusFactor />
          </Cell>
          <Cell
            className="lg:col-span-4"
            tone="marker"
            center
            title="The fix queue"
            body="When a page goes out of date, Canon drafts the change and sends it to whoever owns that page. Nothing is filed until a person approves it."
          >
            <FixQueue />
          </Cell>
          <Cell className="lg:col-span-3" tone="paper" title="Decisions, with their history" body="Every design doc from proposal to replacement, with the pull requests that shipped it.">
            <Decisions />
          </Cell>
          <Cell className="lg:col-span-3" tone="paper-2" title="Catch me up" body="Back from leave? Pick a date and see what changed since: owners, decisions, and pages that now say something different.">
            <CatchMeUp />
          </Cell>
        </div>
      </Container>
    </Slab>
  )
}
