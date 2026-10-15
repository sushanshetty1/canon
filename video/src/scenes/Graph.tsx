// How the check works, drawn the way the site's "How it checks" section draws it: one sentence of an answer, the
// passage it was stated in, the fact that passage asserts, the newer fact that replaced it, and who owns it now.
// The check walks the path; the replaced fact is struck the moment the walk finds what replaced it. Then the one
// query FalkorDB runs for every sentence, and the four verdicts.

import { interpolate } from 'remotion'
import { C, DISPLAY, MONO, SANS, easeInOut } from '../brand'
import { PaperSlab, Verdict, clamp, pop, ramp, useSec } from '../components/ui'
import { useSceneTime } from '../timeline'

type Id = 'claim' | 'passage' | 'old' | 'next' | 'team'
type P = { x: number; y: number }
const N: Record<Id, P> = {
  claim: { x: 210, y: 300 },
  passage: { x: 760, y: 300 },
  old: { x: 1310, y: 300 },
  next: { x: 1310, y: 640 },
  team: { x: 760, y: 640 },
}
const R = 34

const INFO: Record<Id, { kind: string; title: string; detail: string; place: 'above' | 'below' }> = {
  claim: { kind: 'Sentence', title: '“The PostHog AI team owns the MCP server.”', detail: 'One sentence of an answer', place: 'above' },
  passage: { kind: 'Passage', title: '“The PostHog AI team owns the MCP server, …”', detail: 'Handbook, AI products, Sep 23', place: 'above' },
  old: { kind: 'Fact', title: 'PostHog AI owns the MCP server', detail: 'Replaced', place: 'above' },
  next: { kind: 'Fact', title: 'Context & MCP owns the MCP server', detail: 'Ownership map, since Sep 17. Current.', place: 'below' },
  team: { kind: 'Team', title: 'Context & MCP', detail: 'Owns it today', place: 'below' },
}

type E = { from: Id; to: Id; rel: string; d: string; lx: number; ly: number }
const EDGES: E[] = [
  { from: 'claim', to: 'passage', rel: 'STATED_IN', d: 'M 210 300 C 390 380, 580 380, 760 300', lx: 485, ly: 360 },
  { from: 'passage', to: 'old', rel: 'ASSERTS', d: 'M 760 300 C 940 380, 1130 380, 1310 300', lx: 1035, ly: 360 },
  { from: 'old', to: 'next', rel: 'SUPERSEDED_BY', d: 'M 1310 300 C 1520 330, 1520 610, 1310 640', lx: 1468, ly: 470 },
  { from: 'next', to: 'team', rel: 'OWNED_BY', d: 'M 1310 640 C 1130 560, 940 560, 760 640', lx: 1035, ly: 582 },
]

/** A point along an SVG cubic path string of the form above. */
function along(d: string, t: number): P {
  const n = d.match(/-?\d+(\.\d+)?/g)!.map(Number)
  const [x0, y0, x1, y1, x2, y2, x3, y3] = n
  const u = 1 - t
  return {
    x: u * u * u * x0 + 3 * u * u * t * x1 + 3 * u * t * t * x2 + t * t * t * x3,
    y: u * u * u * y0 + 3 * u * u * t * y1 + 3 * u * t * t * y2 + t * t * t * y3,
  }
}

function Face({ id, struck }: { id: Id; struck: number }) {
  switch (id) {
    case 'claim':
      return (
        <g>
          <circle r={R} fill={C.ink} />
          <rect x={-14} y={-10} width={28} height={5} rx={2.5} fill={C.paper} />
          <rect x={-14} y={-2} width={28} height={5} rx={2.5} fill={C.paper} />
          <rect x={-14} y={6} width={17} height={5} rx={2.5} fill={C.paper} />
        </g>
      )
    case 'passage':
      return (
        <g>
          <circle r={R} fill={C.marker} />
          <rect x={-14} y={-10} width={28} height={5} rx={2.5} fill={C.ink} />
          <rect x={-14} y={-2} width={28} height={5} rx={2.5} fill={C.ink} />
          <rect x={-14} y={6} width={17} height={5} rx={2.5} fill={C.ink} />
        </g>
      )
    case 'old':
      return (
        <g>
          <circle r={R} fill={struck > 0 ? C.proofSoft : C.cobalt} stroke={struck > 0 ? C.proof : 'none'} strokeWidth={2} />
          <circle r={10} fill={struck > 0 ? C.proof : C.paper} opacity={struck > 0 ? 0.4 : 1} />
          <line x1={-R - 6} y1={R * 0.55} x2={(-R - 6) + (2 * R + 12) * struck} y2={R * 0.55 - R * 1.1 * struck} stroke={C.proof} strokeWidth={4} strokeLinecap="round" opacity={struck > 0 ? 1 : 0} />
        </g>
      )
    case 'next':
      return (
        <g>
          <circle r={R} fill={C.cobalt} />
          <path d="M -12 1 L -4 9 L 13 -8" fill="none" stroke={C.paper} strokeWidth={4.5} strokeLinecap="round" strokeLinejoin="round" />
        </g>
      )
    case 'team':
      return (
        <g>
          <circle r={R} fill={C.night} />
          <circle cy={-7} r={8} fill={C.paper} />
          <path d="M -15 16 C -15 4, 15 4, 15 16 Z" fill={C.paper} />
        </g>
      )
  }
}

export function Graph() {
  const { sec: s, fps } = useSec()
  const { c, dur } = useSceneTime()

  // When each part arrives, keyed to the voice.
  const appear: Record<Id, number> = { claim: 0.35, passage: c(0) + 1.2, old: c(0) + 2.6, next: c(1) + 0.6, team: c(1) + 2.4 }
  const edgeAt = [c(0) + 1.0, c(0) + 2.4, c(1) + 0.4, c(1) + 2.2]
  // The walk: one hop per edge, from "a path" to "today".
  const walkStart = c(2) + 0.7
  const hop = (c(3) + 1.8 - walkStart) / 4
  const walk = interpolate(s, [walkStart, walkStart + hop * 4], [0, 4], { ...clamp, easing: easeInOut })
  const reached = (k: number) => walk >= k
  const struck = ramp(s, walkStart + hop * 3 - 0.05, 0.4)
  const today = pop(s, walkStart + hop * 3, fps, { damping: 14, stiffness: 160, mass: 0.7 })

  // The query, then the verdicts.
  const shift = interpolate(s, [c(4) - 0.4, c(4) + 0.5], [0, 1], { ...clamp, easing: easeInOut })
  const code = pop(s, c(4) - 0.1, fps, { damping: 22, stiffness: 120, mass: 0.9 })
  const typed = interpolate(s, [c(4) + 0.2, c(4) + 1.7], [0, 1], clamp)
  const verdicts = (k: number) => pop(s, c(5) + 1.6 + k * 0.16, fps, { damping: 15, stiffness: 170, mass: 0.7 })
  const lines = ['MATCH (f:Fact) WHERE f.id IN $ids', 'MATCH (f)-[:SUPERSEDED_BY*1..6]->(n:Fact)', 'WHERE NOT (n)-[:SUPERSEDED_BY]->()', 'RETURN f.id, n.id']
  const totalChars = lines.join('').length
  let budget = Math.floor(typed * totalChars)

  const dot = walk > 0 && walk < 4 ? along(EDGES[Math.min(3, Math.floor(walk))].d, walk - Math.floor(walk)) : null
  void dur

  return (
    <PaperSlab>
      <div style={{ position: 'absolute', left: 80, top: 62, fontFamily: DISPLAY, fontWeight: 600, fontSize: 46, letterSpacing: '-0.04em', opacity: ramp(s, 0.15, 0.6) * (1 - shift) }}>
        One sentence, walked through the graph.
      </div>
      <div
        style={{
          position: 'absolute',
          inset: 0,
          transform: `translate(${-shift * 0}px, ${-shift * 62}px) scale(${1 - shift * 0.16})`,
          transformOrigin: '50% 0%',
        }}
      >
        <svg width={1600} height={900} style={{ position: 'absolute', left: 0, top: 0, overflow: 'visible' }}>
          <defs>
            <pattern id="dots" width="26" height="26" patternUnits="userSpaceOnUse">
              <circle cx="2" cy="2" r="1.4" fill="rgba(13,14,18,0.08)" />
            </pattern>
          </defs>
          <rect x={60} y={170} width={1480} height={640} rx={26} fill="url(#dots)" opacity={ramp(s, 0.2, 0.8)} />
          {EDGES.map((e, k) => {
            const p = ramp(s, edgeAt[k], 0.7)
            const walked = reached(k + 1)
            return (
              <g key={e.rel}>
                <path d={e.d} fill="none" stroke={walked ? C.ink : C.lineStrong} strokeWidth={walked ? 3 : 2.5} pathLength={1} strokeDasharray={1} strokeDashoffset={1 - p} />
                <g opacity={ramp(s, edgeAt[k] + 0.35, 0.4)} transform={`translate(${e.lx} ${e.ly})`}>
                  <rect x={-(e.rel.length * 6.6 + 18)} y={-17} width={e.rel.length * 13.2 + 36} height={34} rx={17} fill={C.paper} stroke={walked ? C.ink : C.line} strokeWidth={1.5} />
                  <text x={0} y={6} textAnchor="middle" fontFamily={MONO} fontWeight={600} fontSize={17} fill={walked ? C.ink : C.muted}>
                    {e.rel}
                  </text>
                </g>
              </g>
            )
          })}
          {(Object.keys(N) as Id[]).map((id) => {
            const p = pop(s, appear[id], fps, { damping: 15, stiffness: 160, mass: 0.7 })
            const lit = id === 'claim' ? 1 : ramp(s, walkStart + hop * ['claim', 'passage', 'old', 'next', 'team'].indexOf(id) - 0.05, 0.25)
            return (
              <g key={id} transform={`translate(${N[id].x} ${N[id].y}) scale(${p})`} opacity={p}>
                <circle r={R + 10} fill="none" stroke={id === 'old' && struck > 0 ? C.proof : C.cobalt} strokeWidth={3} opacity={walk > 0 ? lit * 0.35 : 0} />
                <Face id={id} struck={id === 'old' ? struck : 0} />
              </g>
            )
          })}
          {dot && <circle cx={dot.x} cy={dot.y} r={11} fill={C.cobalt} stroke={C.paper} strokeWidth={3.5} />}
        </svg>

        {(Object.keys(N) as Id[]).map((id) => {
          const info = INFO[id]
          const p = ramp(s, appear[id] + 0.1, 0.5)
          const above = info.place === 'above'
          return (
            <div
              key={id}
              style={{
                position: 'absolute',
                left: id === 'old' || id === 'next' ? N[id].x + R - 380 : N[id].x - R,
                textAlign: id === 'old' || id === 'next' ? 'right' : 'left',
                top: above ? undefined : N[id].y + R + 18,
                bottom: above ? 900 - (N[id].y - R - 18) : undefined,
                width: 380,
                opacity: p,
                transform: `translateY(${(1 - p) * 10}px)`,
              }}
            >
              <div style={{ fontFamily: SANS, fontSize: 18, fontWeight: 500, color: C.muted }}>{info.kind}</div>
              <div style={{ marginTop: 3, fontFamily: SANS, fontSize: 22, fontWeight: 600, lineHeight: 1.3, letterSpacing: '-0.01em', color: id === 'old' && struck > 0 ? C.faint : C.ink }}>
                <span
                  style={{
                    backgroundImage: `linear-gradient(${C.proof}, ${C.proof})`,
                    backgroundRepeat: 'no-repeat',
                    backgroundPosition: '0 58%',
                    backgroundSize: id === 'old' ? `${struck * 100}% 3px` : '0% 3px',
                    boxDecorationBreak: 'clone',
                    WebkitBoxDecorationBreak: 'clone',
                  }}
                >
                  {info.title}
                </span>
              </div>
              <div style={{ marginTop: 3, fontFamily: SANS, fontSize: 18, color: id === 'old' && struck > 0 ? C.proof : id === 'next' ? C.cobalt : C.faint, fontWeight: id === 'next' || (id === 'old' && struck > 0) ? 600 : 400 }}>
                {info.detail}
              </div>
            </div>
          )
        })}

        {/* Today, beside what holds now */}
        <div
          style={{
            position: 'absolute',
            left: N.next.x + R + 18,
            top: N.next.y - 17,
            transform: `scale(${today})`,
            transformOrigin: '0 50%',
            opacity: today,
            background: C.ink,
            color: C.paper,
            fontFamily: SANS,
            fontWeight: 600,
            fontSize: 17,
            padding: '6px 13px 7px',
            borderRadius: 99,
          }}
        >
          Today
        </div>
      </div>

      {/* The query */}
      <div
        style={{
          position: 'absolute',
          left: 80,
          right: 80,
          bottom: 40,
          height: 214,
          borderRadius: 22,
          background: C.night,
          padding: '26px 34px',
          transform: `translateY(${(1 - code) * 280}px)`,
          display: 'flex',
          gap: 40,
        }}
      >
        <div style={{ flex: 1 }}>
          <div style={{ fontFamily: SANS, fontSize: 18, color: '#a3a8b3', marginBottom: 12 }}>FalkorDB, for every sentence</div>
          {lines.map((l, i) => {
            const shown = l.slice(0, Math.max(0, budget))
            budget -= l.length
            return (
              <div key={i} style={{ fontFamily: MONO, fontSize: 22, lineHeight: 1.55, color: C.paper, whiteSpace: 'pre', fontVariantLigatures: 'none', fontFeatureSettings: '"calt" 0, "liga" 0' }}>
                {shown
                  .split(/(SUPERSEDED_BY|MATCH|WHERE NOT|WHERE|RETURN|IN)/)
                  .map((part, k) => (
                    <span key={k} style={{ color: part === 'SUPERSEDED_BY' ? '#8ea0ff' : /^(MATCH|WHERE NOT|WHERE|RETURN|IN)$/.test(part) ? '#a3a8b3' : C.paper }}>
                      {part}
                    </span>
                  ))}
              </div>
            )
          })}
        </div>
        <div style={{ width: 430, borderLeft: `1px solid ${C.nightLine}`, paddingLeft: 34, display: 'flex', flexDirection: 'column', justifyContent: 'center', gap: 14 }}>
          <div style={{ fontFamily: SANS, fontSize: 18, color: '#a3a8b3', opacity: ramp(s, c(5) + 1.3, 0.4) }}>The graph decides</div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10 }}>
            {(['verified', 'stale', 'disputed', 'removed'] as const).map((k, i) => (
              <span key={k} style={{ transform: `scale(${0.7 + 0.3 * verdicts(i)})`, opacity: verdicts(i), display: 'inline-block' }}>
                <Verdict kind={k} size={19} />
              </span>
            ))}
          </div>
        </div>
      </div>
    </PaperSlab>
  )
}
