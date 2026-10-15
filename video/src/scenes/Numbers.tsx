// The benchmark, from README.md and bench/results/haiku-sonnet-judge: 56 PostHog questions with known answers,
// three systems on the same model. The stale traps land last.

import { interpolate } from 'remotion'
import { C, DISPLAY, SANS, ease } from '../brand'
import { PaperSlab, Struck, clamp, pop, ramp, useSec } from '../components/ui'
import { CONTENT_AT } from '../components/Transitions'
import { useSceneTime } from '../timeline'

const COLS = [
  { name: 'Canon', x: 540, correct: 98, stale: 0, traps: 13, tone: C.cobalt },
  { name: 'Same evidence, no graph', x: 900, correct: 95, stale: 2, traps: 10, tone: C.ink },
  { name: 'Search and summarise', x: 1220, correct: 20, stale: 5, traps: 0, tone: C.proof },
]
const COL_W = 300

function Counter({ to, p, suffix = '' }: { to: number; p: number; suffix?: string }) {
  return (
    <>
      {Math.round(to * p)}
      {suffix}
    </>
  )
}

export function Numbers() {
  const { sec: s, fps } = useSec()
  const { c, dur } = useSceneTime()
  void dur
  const head = ramp(s, CONTENT_AT - 0.1, 0.6)
  const row1 = interpolate(s, [c(1) - 0.2, c(1) + 1.4], [0, 1], { ...clamp, easing: ease })
  const row2 = interpolate(s, [c(1) + 2.6, c(1) + 3.8], [0, 1], { ...clamp, easing: ease })
  const row3 = ramp(s, c(2) - 0.1, 0.6)
  const canonFill = (k: number) => pop(s, c(3) + 0.05 + k * 0.07, fps, { damping: 13, stiffness: 190, mass: 0.6 })
  const canonNum = pop(s, c(3) + 0.15, fps, { damping: 10, stiffness: 160, mass: 0.8 })
  const baselineFill = (k: number) => ramp(s, c(2) + 0.6 + k * 0.05, 0.3)
  const searchNum = pop(s, c(4), fps, { damping: 10, stiffness: 160, mass: 0.8 })
  const searchStrike = ramp(s, c(4) + 0.55, 0.45)

  const label = (y: number, text: string, sub: string, p: number) => (
    <div style={{ position: 'absolute', left: 80, top: y, width: 420, opacity: p }}>
      <div style={{ fontFamily: SANS, fontWeight: 600, fontSize: 25, letterSpacing: '-0.01em' }}>{text}</div>
      <div style={{ marginTop: 4, fontFamily: SANS, fontSize: 18, color: C.muted }}>{sub}</div>
    </div>
  )

  return (
    <PaperSlab>
      <div style={{ position: 'absolute', left: 80, top: 62, opacity: head, transform: `translateY(${(1 - head) * 12}px)` }}>
        <div style={{ fontFamily: DISPLAY, fontWeight: 600, fontSize: 54, letterSpacing: '-0.04em' }}>56 PostHog questions, known answers.</div>
        <div style={{ marginTop: 10, fontFamily: SANS, fontSize: 21, color: C.muted }}>The same model answers for every system, Claude Haiku 5.5. Claude Sonnet 5.5 grades.</div>
      </div>

      {/* Column heads */}
      {COLS.map((col, i) => (
        <div key={col.name} style={{ position: 'absolute', left: col.x, top: 230, width: COL_W, fontFamily: SANS, fontWeight: 600, fontSize: 20, color: i === 0 ? C.cobalt : C.muted, opacity: ramp(s, CONTENT_AT + 0.3 + i * 0.1, 0.5) }}>
          {col.name}
        </div>
      ))}
      <div style={{ position: 'absolute', left: 80, right: 80, top: 272, height: 1, background: C.line, opacity: head }} />

      {/* Correct answers */}
      {label(300, 'Correct answers', 'of 56', row1 > 0 ? 1 : 0)}
      {COLS.map((col, i) => (
        <div key={col.name} style={{ position: 'absolute', left: col.x, top: 296, width: COL_W, opacity: row1 > 0 ? 1 : 0 }}>
          <div style={{ fontFamily: DISPLAY, fontWeight: 600, fontSize: 52, letterSpacing: '-0.04em', color: i === 0 ? C.cobalt : C.ink }}>
            <Counter to={col.correct} p={row1} suffix="%" />
          </div>
          <div style={{ marginTop: 8, height: 10, borderRadius: 5, background: C.paper2 }}>
            <div style={{ height: 10, borderRadius: 5, width: `${col.correct * row1}%`, background: i === 0 ? C.cobalt : C.lineStrong }} />
          </div>
        </div>
      ))}
      <div style={{ position: 'absolute', left: 80, right: 80, top: 404, height: 1, background: C.line, opacity: row1 > 0 ? 1 : 0 }} />

      {/* Out of date stated as current */}
      {label(430, 'Out-of-date answers stated as current', 'lower is better', row2 > 0 ? 1 : 0)}
      {COLS.map((col, i) => (
        <div key={col.name} style={{ position: 'absolute', left: col.x, top: 428, width: COL_W, opacity: row2 > 0 ? 1 : 0 }}>
          <div style={{ fontFamily: DISPLAY, fontWeight: 600, fontSize: 52, letterSpacing: '-0.04em', color: i === 0 ? C.cobalt : C.ink }}>
            <Counter to={col.stale} p={row2} suffix="%" />
          </div>
          <div style={{ marginTop: 8, height: 10, borderRadius: 5, background: C.paper2 }}>
            <div style={{ height: 10, borderRadius: 5, width: `${col.stale * 4 * row2}%`, background: C.proof }} />
          </div>
        </div>
      ))}
      <div style={{ position: 'absolute', left: 80, right: 80, top: 536, height: 1, background: C.line, opacity: row2 > 0 ? 1 : 0 }} />

      {/* Stale traps */}
      {label(566, 'Stale traps answered correctly', 'the handbook names an owner the ownership map has since changed', row3)}
      {COLS.map((col, i) => {
        const fill = (k: number) => (i === 0 ? canonFill(k) : i === 1 ? (k < col.traps ? baselineFill(k) : 0) : 0)
        const numP = i === 0 ? canonNum : i === 1 ? baselineFill(9) : searchNum
        return (
          <div key={col.name} style={{ position: 'absolute', left: col.x, top: 560, width: COL_W, opacity: row3 }}>
            <div
              style={{
                fontFamily: DISPLAY,
                fontWeight: 600,
                fontSize: i === 1 ? 60 : 78,
                whiteSpace: 'nowrap',
                letterSpacing: '-0.045em',
                lineHeight: 1,
                color: i === 0 ? C.cobalt : i === 2 ? C.proof : C.ink,
                transform: `scale(${0.7 + 0.3 * numP})`,
                transformOrigin: '0 100%',
                opacity: numP,
                height: 92,
                display: 'flex',
                alignItems: 'flex-end',
              }}
            >
              {i === 2 ? (
                <Struck p={searchStrike} color={C.proof} thickness={0.06}>
                  0 of 13
                </Struck>
              ) : (
                `${col.traps} of 13`
              )}
            </div>
            <div style={{ marginTop: 20, display: 'grid', gridTemplateColumns: 'repeat(13, 1fr)', gap: 5, width: COL_W - 10 }}>
              {Array.from({ length: 13 }, (_, k) => {
                const f = fill(k)
                return (
                  <div
                    key={k}
                    style={{
                      height: 30,
                      borderRadius: 6,
                      background: i === 0 ? C.cobalt : i === 1 ? C.ink : 'transparent',
                      boxShadow: `inset 0 0 0 2px ${i === 2 ? (searchNum > 0 ? C.proof : C.lineStrong) : C.lineStrong}`,
                      opacity: i === 2 ? 0.35 + 0.65 * searchNum : 1,
                      transform: i === 0 ? `scale(${0.4 + 0.6 * Math.max(0.0001, f)})` : undefined,
                      backgroundColor: i === 2 ? 'transparent' : f > 0.02 ? (i === 0 ? C.cobalt : C.ink) : C.paper2,
                    }}
                  />
                )
              })}
            </div>
          </div>
        )
      })}

      <div style={{ position: 'absolute', left: 80, bottom: 40, fontFamily: SANS, fontSize: 18, color: C.faint, opacity: ramp(s, c(2), 0.6) }}>
        Every question, answer and grade: bench/results/haiku-sonnet-judge in the repository.
      </div>
    </PaperSlab>
  )
}
