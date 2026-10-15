// The close: the same answer on a phone, then where to find Canon.

import { Img } from 'remotion'
import { C, DISPLAY, SANS } from '../brand'
import { warpAt } from '../components/Footage'
import { PaperSlab, Struck, Written, pop, ramp, useSec, Wordmark } from '../components/ui'
import { frameAt, useTake } from '../takes'
import { useSceneTime } from '../timeline'

const PHONE = { x: 170, y: 46, w: 372, scale: 372 / 390 }

function Phone({ s }: { s: number }) {
  const take = useTake('phone')
  const { c } = useSceneTime()
  if (!take) return null
  const t = warpAt(
    [
      [0, 0.9],
      [c(0) + 2.6, 4.8],
      [c(0) + 3.3, 6.3],
      [c(1) + 2.0, 9.0],
      [c(1) + 3.6, 12.6],
    ],
    s,
  )
  const h = 844 * PHONE.scale
  const bezel = 14
  return (
    <div
      style={{
        position: 'absolute',
        left: PHONE.x - bezel,
        top: PHONE.y - bezel,
        width: PHONE.w + bezel * 2,
        height: h + bezel * 2,
        borderRadius: 62,
        background: C.night,
        boxShadow: '0 50px 90px -40px rgba(13,14,18,0.6), inset 0 0 0 2px #2a2e37',
      }}
    >
      <div style={{ position: 'absolute', left: bezel, top: bezel, width: PHONE.w, height: h, borderRadius: 48, overflow: 'hidden', background: C.page }}>
        <Img src={frameAt(take, t)} style={{ width: PHONE.w, height: h }} />
      </div>
    </div>
  )
}

export function Close() {
  const { sec: s, fps } = useSec()
  const { c } = useSceneTime()
  const phone = pop(s, 0.1, fps, { damping: 20, stiffness: 90, mass: 1 })
  const word = ramp(s, c(0) - 0.1, 0.6)
  const strike = ramp(s, c(0) + 1.7, 0.45)
  const today = ramp(s, c(0) + 2.05, 0.5)
  const facts = (k: number) => ramp(s, c(1) + 0.15 + k * 0.45, 0.55)
  return (
    <PaperSlab>
      <div style={{ transform: `translateY(${(1 - phone) * 300}px)`, opacity: Math.min(1, s / 0.3) }}>
        <Phone s={s} />
      </div>
      <div style={{ position: 'absolute', left: 680, top: 120, width: 840 }}>
        <div style={{ opacity: word, transform: `translateY(${(1 - word) * 12}px)` }}>
          <Wordmark size={58} />
        </div>
        <div style={{ marginTop: 44, fontFamily: DISPLAY, fontWeight: 600, fontSize: 70, letterSpacing: '-0.045em', lineHeight: 1.02, opacity: ramp(s, c(0) + 0.5, 0.6) }}>
          Every answer, checked against what's true{' '}
          <Struck p={strike} color={C.faint}>
            in March
          </Struck>{' '}
          <Written p={today} style={{ color: C.cobalt }}>
            today.
          </Written>
        </div>
        <div style={{ marginTop: 64, display: 'grid', gap: 18 }}>
          {[
            { t: 'canon.sushans.dev', style: { fontFamily: DISPLAY, fontWeight: 600, fontSize: 40, letterSpacing: '-0.03em', color: C.cobalt } },
            { t: 'github.com/sushanshetty1/canon', style: { fontFamily: SANS, fontWeight: 600, fontSize: 27, color: C.ink } },
            { t: 'Built on FalkorDB', style: { fontFamily: SANS, fontWeight: 500, fontSize: 25, color: C.muted } },
            { t: 'FalkorDB Hackathon · Track 03, Company Brain', style: { fontFamily: SANS, fontWeight: 500, fontSize: 25, color: C.muted } },
          ].map((row, k) => (
            <div key={row.t} style={{ ...row.style, opacity: facts(k), transform: `translateY(${(1 - facts(k)) * 10}px)` }}>
              {row.t}
            </div>
          ))}
        </div>
      </div>
    </PaperSlab>
  )
}
