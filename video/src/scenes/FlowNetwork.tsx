// Bus factor as FalkorDB computes it: a maximum flow from an area, through its documents (each can back one
// person), to the people who know it, and into a sink (each person counts once). The worked example is the one in
// docs/bus-factor.md: Alice wrote #1 and #2; Bob and Carol only reviewed #1. Three people know the area; the flow
// is 2; the cut is {#1, Alice}.

import { interpolate } from 'remotion'
import { C, DISPLAY, MONO, SANS, ease, easeInOut } from '../brand'
import { PaperSlab, clamp, pop, ramp, useSec } from '../components/ui'
import { useSceneTime } from '../timeline'

type P = { x: number; y: number }
const AREA: P = { x: 250, y: 540 }
const D1: P = { x: 640, y: 440 }
const D2: P = { x: 640, y: 660 }
const ALICE: P = { x: 1030, y: 380 }
const BOB: P = { x: 1030, y: 545 }
const CAROL: P = { x: 1030, y: 710 }
const SINK: P = { x: 1380, y: 545 }

const curve = (a: P, b: P) => `M ${a.x} ${a.y} C ${a.x + (b.x - a.x) * 0.5} ${a.y}, ${a.x + (b.x - a.x) * 0.5} ${b.y}, ${b.x} ${b.y}`

type Edge = { id: string; a: P; b: P; wide?: boolean }
const EDGES: Edge[] = [
  { id: 'a1', a: AREA, b: D1 },
  { id: 'a2', a: AREA, b: D2 },
  { id: '1a', a: D1, b: ALICE, wide: true },
  { id: '1b', a: D1, b: BOB, wide: true },
  { id: '1c', a: D1, b: CAROL, wide: true },
  { id: '2a', a: D2, b: ALICE, wide: true },
  { id: 'as', a: ALICE, b: SINK },
  { id: 'bs', a: BOB, b: SINK },
  { id: 'cs', a: CAROL, b: SINK },
]

/** A point along a cubic edge, t from 0 to 1. */
function along(e: Edge, t: number): P {
  const mx = e.a.x + (e.b.x - e.a.x) * 0.5
  const p0 = e.a
  const p1 = { x: mx, y: e.a.y }
  const p2 = { x: mx, y: e.b.y }
  const p3 = e.b
  const u = 1 - t
  return {
    x: u * u * u * p0.x + 3 * u * u * t * p1.x + 3 * u * t * t * p2.x + t * t * t * p3.x,
    y: u * u * u * p0.y + 3 * u * u * t * p1.y + 3 * u * t * t * p2.y + t * t * t * p3.y,
  }
}
const edge = (id: string) => EDGES.find((e) => e.id === id)!

/** A unit of flow walking a path of edges. */
function unitAt(path: string[], p: number): P | null {
  if (p <= 0 || p >= 1) return null
  const k = Math.min(path.length - 1, Math.floor(p * path.length))
  return along(edge(path[k]), p * path.length - k)
}

function Person({ p, name, on, cut, s }: { p: P; name: string; on: number; cut: number; s: number }) {
  void s
  return (
    <g transform={`translate(${p.x} ${p.y}) scale(${on})`} opacity={on}>
      <circle r={26} fill={C.paper} stroke={cut > 0 ? C.proof : C.ink} strokeWidth={3} />
      <circle r={9} cy={-5} fill={cut > 0 ? C.proof : C.ink} />
      <path d="M -14 15 C -14 4, 14 4, 14 15" fill={cut > 0 ? C.proof : C.ink} />
      <text x={40} y={8} fontFamily={SANS} fontWeight={600} fontSize={24} fill={C.ink}>
        {name}
      </text>
    </g>
  )
}

function Doc({ p, name, on, cut }: { p: P; name: string; on: number; cut: number }) {
  return (
    <g transform={`translate(${p.x} ${p.y}) scale(${on})`} opacity={on}>
      <rect x={-22} y={-28} width={44} height={56} rx={9} fill={C.paper} stroke={cut > 0 ? C.proof : C.ink} strokeWidth={3} />
      <rect x={-11} y={-12} width={22} height={4} rx={2} fill={cut > 0 ? C.proof : C.ink} />
      <rect x={-11} y={-2} width={22} height={4} rx={2} fill={C.lineStrong} />
      <rect x={-11} y={8} width={14} height={4} rx={2} fill={C.lineStrong} />
      <text x={0} y={60} textAnchor="middle" fontFamily={SANS} fontWeight={600} fontSize={22} fill={C.ink}>
        {name}
      </text>
    </g>
  )
}

export function FlowNetwork({ until }: { until: number }) {
  const { sec: s, fps } = useSec()
  const { c } = useSceneTime()
  if (s > until + 0.1) return null

  const t0 = 0.5
  const n = (k: number) => pop(s, t0 + k * 0.12, fps, { damping: 16, stiffness: 150, mass: 0.7 })
  const draw = (k: number) => ramp(s, t0 + 0.5 + k * 0.08, 0.6)
  const flowA = interpolate(s, [c(1) + 0.2, c(1) + 2.2], [0, 1], { ...clamp, easing: easeInOut })
  const flowB = interpolate(s, [c(1) + 1.1, c(1) + 3.1], [0, 1], { ...clamp, easing: easeInOut })
  const carried = (id: string) => {
    const a = ['a2', '2a', 'as'].includes(id) ? ramp(s, c(1) + 0.2 + ['a2', '2a', 'as'].indexOf(id) * 0.66, 0.5) : 0
    const b = ['a1', '1b', 'bs'].includes(id) ? ramp(s, c(1) + 1.1 + ['a1', '1b', 'bs'].indexOf(id) * 0.66, 0.5) : 0
    return Math.max(a, b)
  }
  const result = pop(s, c(1) + 3.2, fps, { damping: 14, stiffness: 160, mass: 0.7 })
  const cut = ramp(s, c(2) + 0.2, 0.9)
  const cutMark = ramp(s, c(2) + 0.9, 0.4)
  const carolDim = ramp(s, c(1) + 2.6, 0.5)


  return (
    <PaperSlab>
      <div style={{ position: 'absolute', left: 80, top: 66, fontFamily: DISPLAY, fontWeight: 600, fontSize: 52, letterSpacing: '-0.04em', opacity: ramp(s, 0.2, 0.6) }}>
        Bus factor is a maximum flow.
      </div>
      <div style={{ position: 'absolute', left: 82, top: 140, width: 900, fontFamily: SANS, fontSize: 22, lineHeight: 1.45, color: C.muted, opacity: ramp(s, 0.45, 0.6) }}>
        A document can back one person, however many people touched it. Each person counts once.
      </div>
      <div
        style={{
          position: 'absolute',
          right: 80,
          top: 74,
          fontFamily: MONO,
          fontSize: 19,
          color: C.paper,
          background: C.night,
          padding: '10px 16px',
          borderRadius: 12,
          opacity: ramp(s, c(0) + 1.6, 0.5),
        }}
      >
        CALL algo.maxFlow(…)
      </div>

      <svg width={1600} height={900} style={{ position: 'absolute', left: 0, top: 0 }}>
        {EDGES.map((e, k) => {
          const d = curve(e.a, e.b)
          const len = 900
          const dim = e.id === '1c' || e.id === 'cs' ? 1 - carolDim * 0.65 : 1
          return (
            <g key={e.id} opacity={dim}>
              <path d={d} fill="none" stroke={e.wide ? '#d9dce2' : C.lineStrong} strokeWidth={e.wide ? 9 : 3} strokeLinecap="round" strokeDasharray={len} strokeDashoffset={len * (1 - draw(k))} />
              <path d={d} fill="none" stroke={C.cobalt} strokeWidth={e.wide ? 5 : 4} strokeLinecap="round" strokeDasharray={len} strokeDashoffset={len * (1 - carried(e.id))} />
            </g>
          )
        })}

        {/* Units of flow */}
        {[unitAt(['a2', '2a', 'as'], flowA), unitAt(['a1', '1b', 'bs'], flowB)].map((p, i) =>
          p ? <circle key={i} cx={p.x} cy={p.y} r={10} fill={C.cobalt} stroke={C.paper} strokeWidth={3} /> : null,
        )}

        {/* The area */}
        <g transform={`translate(${AREA.x} ${AREA.y}) scale(${n(0)})`} opacity={n(0)}>
          <circle r={40} fill={C.marker} />
          <text x={0} y={78} textAnchor="middle" fontFamily={SANS} fontWeight={600} fontSize={24} fill={C.ink}>
            The area
          </text>
        </g>
        <Doc p={D1} name="#1" on={n(1)} cut={cutMark} />
        <Doc p={D2} name="#2" on={n(2)} cut={0} />
        <Person p={ALICE} name="Alice" on={n(3)} cut={cutMark} s={s} />
        <Person p={BOB} name="Bob" on={n(4)} cut={0} s={s} />
        <Person p={CAROL} name="Carol" on={n(5)} cut={0} s={s} />
        <g transform={`translate(${SINK.x} ${SINK.y}) scale(${n(6)})`} opacity={n(6)}>
          <circle r={22} fill={C.night} />
          <text x={0} y={60} textAnchor="middle" fontFamily={SANS} fontWeight={600} fontSize={22} fill={C.muted}>
            counted
          </text>
        </g>
      </svg>

      {/* The minimum cut: the edge into #1 and the edge out of Alice, each struck through */}
      <svg width={1600} height={900} style={{ position: 'absolute', left: 0, top: 0 }}>
        {[
          { e: 'a1', k: 0 },
          { e: 'as', k: 1 },
        ].map(({ e, k }) => {
          const m = along(edge(e), 0.5)
          const p = ramp(s, c(2) + 0.2 + k * 0.35, 0.45)
          return (
            <g key={e} transform={`translate(${m.x} ${m.y}) rotate(-62)`}>
              <line x1={-58 * p} y1={0} x2={58 * p} y2={0} stroke={C.proof} strokeWidth={6} strokeLinecap="round" />
              <circle r={14 * p} fill={C.paper} stroke={C.proof} strokeWidth={3.5} opacity={p} />
              <path d="M -5 -5 L 5 5 M 5 -5 L -5 5" stroke={C.proof} strokeWidth={3} strokeLinecap="round" opacity={p} transform="rotate(62)" />
            </g>
          )
        })}
      </svg>

      <div style={{ position: 'absolute', left: 82, bottom: 52, fontFamily: SANS, fontSize: 20, color: C.faint, opacity: ramp(s, 1.6, 0.6) }}>
        Example: Alice wrote #1 and #2. Bob and Carol only reviewed #1.
      </div>

      <div
        style={{
          position: 'absolute',
          right: 80,
          bottom: 52,
          textAlign: 'right',
          transform: `scale(${0.85 + 0.15 * result})`,
          transformOrigin: '100% 100%',
          opacity: result,
        }}
      >
        <div style={{ fontFamily: SANS, fontSize: 20, color: C.muted }}>Three people know it. The flow is</div>
        <div style={{ fontFamily: DISPLAY, fontWeight: 600, fontSize: 92, letterSpacing: '-0.04em', color: C.cobalt, lineHeight: 1 }}>2</div>
        <div style={{ marginTop: 6, fontFamily: SANS, fontWeight: 600, fontSize: 20, color: C.proof, opacity: cutMark }}>It hinges on #1 and Alice</div>
      </div>
      {void ease}
    </PaperSlab>
  )
}
