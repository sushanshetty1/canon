// The opening: PostHog's own knowledge, January to today, as facts that hold for a time. Today's line walks the
// year; a fact that a newer one replaced turns grey and is struck; a page that still says the old owner is flagged.
// The headline is the site's, with its correction.

import { interpolate } from 'remotion'
import { C, DISPLAY, SANS } from '../brand'
import { PaperSlab, Struck, Written, clamp, pop, ramp, useSec } from '../components/ui'

const MONTHS = ['Jan 2026', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov']
const SPAN = 11 // months shown, from January 1; the last weeks are ahead of today
const TODAY = 9.47 // October 15
const X0 = 410
const X1 = 1530
const ROW0 = 424
const ROW_H = 116
const SWEEP_AT = 1.25
const SWEEP = 3.8

const x = (m: number) => X0 + ((X1 - X0) * m) / SPAN
/** Where today's line is, in months, at scene time s. */
const lineAt = (s: number) => interpolate(s, [SWEEP_AT, SWEEP_AT + SWEEP], [0, TODAY], clamp)
/** When the line reaches month m. */
const reach = (m: number) => SWEEP_AT + (m / TODAY) * SWEEP

type Bar = { from: number; to?: number; label: string; tone: 'fact' | 'disputed'; lane?: 0 | 1 }
type Row = { topic: string; note?: string; bars: Bar[] }

// From the PostHog graph: the ownership map's history of each area, and two handbook pages that disagree.
const ROWS: Row[] = [
  {
    topic: 'Who owns the MCP server',
    bars: [
      { from: 0, to: 5.07, label: 'PostHog AI', tone: 'fact' },
      { from: 5.07, to: 5.93, label: 'Signals', tone: 'fact' },
      { from: 5.93, to: 8.55, label: 'Self-Driving', tone: 'fact' },
      { from: 8.55, label: 'Context & MCP', tone: 'fact' },
    ],
  },
  {
    topic: 'Who owns the AI gateway',
    bars: [
      { from: 4.7, to: 8.5, label: 'AI Gateway team', tone: 'fact' },
      { from: 8.5, label: 'Agent Infrastructure', tone: 'fact' },
    ],
  },
  {
    topic: 'How often growth reviews run',
    note: 'Two current answers',
    bars: [
      { from: 4.9, label: 'Every four weeks', tone: 'disputed', lane: 0 },
      { from: 8.7, label: 'Quarterly', tone: 'disputed', lane: 1 },
    ],
  },
]

export const PIN = { at: 8.73, label: 'Handbook still says PostHog AI' }
/** The pin's rectangle in slab coordinates, for the next scene to grow from. */
export const PIN_RECT = { x: x(PIN.at) - 338, y: ROW0 - 20, w: 338, h: 38 }

function BarView({ bar, row, s }: { bar: Bar; row: number; s: number }) {
  const line = lineAt(s)
  if (line <= bar.from) return null
  const shown = bar.to !== undefined ? Math.min(bar.to, line) : line + (SPAN - TODAY) * ramp(s, SWEEP_AT + SWEEP, 0.7)
  const left = x(bar.from) + 3
  const width = Math.max(0, x(shown) - x(bar.from) - 6)
  const replaced = bar.to !== undefined ? ramp(s, reach(bar.to), 0.35) : 0
  const stacked = bar.tone === 'disputed'
  const top = ROW0 + row * ROW_H + (stacked ? (bar.lane === 1 ? 50 : 8) : 14)
  const height = stacked ? 40 : 62
  const base: React.CSSProperties = {
    position: 'absolute',
    left,
    top,
    width,
    height,
    borderRadius: 13,
    overflow: 'hidden',
    display: 'flex',
    alignItems: 'center',
    padding: '0 14px',
    fontFamily: SANS,
    fontWeight: 600,
    fontSize: stacked ? 16 : 17,
    whiteSpace: 'nowrap',
  }
  if (stacked) return <div style={{ ...base, background: C.amberSoft, color: C.amber, boxShadow: 'inset 0 0 0 1.5px #ecc98a' }}>{bar.label}</div>
  return (
    <div style={{ ...base, padding: 0 }}>
      <div style={{ position: 'absolute', inset: 0, background: C.cobalt, color: C.paper, display: 'flex', alignItems: 'center', padding: '0 14px' }}>{bar.label}</div>
      <div
        style={{
          position: 'absolute',
          inset: 0,
          opacity: replaced,
          display: 'flex',
          alignItems: 'center',
          padding: '0 14px',
          color: C.faint,
          backgroundImage: `repeating-linear-gradient(135deg, ${C.paper2} 0 7px, #e7e9ee 7px 8px)`,
          boxShadow: `inset 0 0 0 1px ${C.line}`,
          borderRadius: 13,
        }}
      >
        <span style={{ textDecoration: 'line-through', textDecorationColor: 'rgba(139,144,154,0.7)' }}>{bar.label}</span>
      </div>
    </div>
  )
}

export function Open() {
  const { sec: s, fps } = useSec()
  const slab = pop(s, 0, fps, { damping: 24, stiffness: 90, mass: 1 })
  const head = ramp(s, 0.25, 0.8)
  const strike = ramp(s, 0.95, 0.5)
  const today = ramp(s, 1.3, 0.55)
  const line = lineAt(s)
  const pin = pop(s, reach(PIN.at) + 0.05, fps, { damping: 14, stiffness: 170, mass: 0.7 })
  const glow = s > reach(PIN.at) + 0.5 ? 0.5 + 0.5 * Math.sin((s - reach(PIN.at)) * 4) : 0

  return (
    <PaperSlab style={{ transform: `translateY(${(1 - slab) * 60}px)`, opacity: Math.min(1, s / 0.35) }}>
      <div
        style={{
          position: 'absolute',
          left: 80,
          top: 74,
          width: 1440,
          fontFamily: DISPLAY,
          fontWeight: 600,
          fontSize: 82,
          letterSpacing: '-0.045em',
          lineHeight: 1.0,
          opacity: head,
          transform: `translateY(${(1 - head) * 16}px)`,
        }}
      >
        Every answer, checked against
        <br />
        what's true{' '}
        <Struck p={strike} color={C.faint}>
          in March
        </Struck>{' '}
        <Written p={today} style={{ color: C.cobalt }}>
          today.
        </Written>
      </div>

      {/* Months */}
      {MONTHS.map((m, i) => (
        <div key={m} style={{ position: 'absolute', left: x(i) + 8, top: ROW0 - 44, fontFamily: SANS, fontWeight: 500, fontSize: 16, color: C.faint, opacity: ramp(s, 0.6 + i * 0.03, 0.4) }}>
          {m}
        </div>
      ))}
      {MONTHS.map((m, i) => (
        <div key={`r${m}`} style={{ position: 'absolute', left: x(i), top: ROW0, width: 1, height: ROW_H * ROWS.length, background: C.line, opacity: ramp(s, 0.6, 0.4) }} />
      ))}

      {ROWS.map((row, r) => (
        <div key={row.topic}>
          <div style={{ position: 'absolute', left: 80, right: 70, top: ROW0 + r * ROW_H, height: 1, background: C.line, opacity: ramp(s, 0.55 + r * 0.05, 0.4) }} />
          <div style={{ position: 'absolute', left: 80, top: ROW0 + r * ROW_H + (row.note ? 32 : 44), width: 310, opacity: ramp(s, 0.6 + r * 0.08, 0.5) }}>
            <div style={{ fontFamily: SANS, fontWeight: 600, fontSize: 20, letterSpacing: '-0.01em', color: C.ink }}>{row.topic}</div>
            {row.note && <div style={{ marginTop: 4, fontFamily: SANS, fontWeight: 600, fontSize: 16, color: C.amber, opacity: ramp(s, reach(8.7) + 0.15, 0.4) }}>{row.note}</div>}
          </div>
          {row.bars.map((b) => (
            <BarView key={b.label} bar={b} row={r} s={s} />
          ))}
        </div>
      ))}

      {/* The handbook page that still names the old owner */}
      <div
        style={{
          position: 'absolute',
          left: PIN_RECT.x,
          top: PIN_RECT.y,
          height: PIN_RECT.h,
          width: PIN_RECT.w,
          transformOrigin: '100% 50%',
          transform: `scale(${0.6 + 0.4 * pin})`,
          opacity: pin,
          display: 'flex',
          alignItems: 'center',
          gap: 9,
          padding: '0 14px 0 5px',
          borderRadius: 99,
          background: C.proof,
          color: C.paper,
          fontFamily: SANS,
          fontWeight: 600,
          fontSize: 16,
          whiteSpace: 'nowrap',
          boxShadow: `0 10px 26px -8px rgba(224,57,44,${0.45 + glow * 0.25})`,
          zIndex: 3,
        }}
      >
        <span style={{ width: 27, height: 27, borderRadius: 99, background: C.paper, color: C.proof, display: 'grid', placeItems: 'center', fontWeight: 700, fontSize: 15 }}>!</span>
        {PIN.label}
      </div>

      {/* Today */}
      <div style={{ position: 'absolute', left: x(line), top: ROW0 - 52, height: ROW_H * ROWS.length + 52, width: 0, opacity: ramp(s, SWEEP_AT - 0.2, 0.3) }}>
        <div style={{ position: 'absolute', left: -1.25, top: 34, bottom: 0, width: 2.5, background: C.ink }} />
        <div style={{ position: 'absolute', left: 0, top: 0, transform: 'translateX(-50%)', background: C.ink, color: C.paper, fontFamily: SANS, fontWeight: 600, fontSize: 15, padding: '5px 12px 6px', borderRadius: 99 }}>Today</div>
      </div>

      <div style={{ position: 'absolute', left: 80, top: ROW0 + ROWS.length * ROW_H + 26, fontFamily: SANS, fontSize: 17, color: C.faint, opacity: ramp(s, 2.0, 0.6) }}>
        PostHog, January to today. Each bar is a fact, for as long as it held.
      </div>
    </PaperSlab>
  )
}
