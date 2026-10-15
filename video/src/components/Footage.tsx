// A take on its slab: the frames, time-warped to the voice, with a camera that springs into the region being
// discussed, a cursor drawn from the take's log, click ripples, and rings on the elements the voice names.

import type { CSSProperties, ReactNode } from 'react'
import { AbsoluteFill, Img, interpolate, spring, useCurrentFrame, useVideoConfig } from 'remotion'
import { C, DISPLAY, SANS, SLAB, ease } from '../brand'
import { frameAt, pointerAt, type Rect, type Take, useTake } from '../takes'

export type Warp = [number, number][]
export type Shot = { at: number; rect?: Rect | null; pad?: number; max?: number; stiffness?: number }
export type Ring = { at: number; until: number; rect: Rect; kind?: 'ring' | 'underline'; color?: string; pad?: number }
export type Label = { at: number; until: number; title: string; sub?: string }

const VW = 1600
const VH = 900

/** Scene seconds to take seconds. Equal scene times on consecutive points make a cut. */
export function warpAt(warp: Warp, s: number): number {
  if (s <= warp[0][0]) return warp[0][1]
  for (let i = 0; i < warp.length - 1; i++) {
    const [s0, t0] = warp[i]
    const [s1, t1] = warp[i + 1]
    if (s >= s0 && s < s1) return t0 + ((s - s0) / (s1 - s0)) * (t1 - t0)
  }
  return warp[warp.length - 1][1] + (s - warp[warp.length - 1][0])
}

/** The scene time at which the take reaches t, for clicks. */
function sceneTimeOf(warp: Warp, t: number): number | null {
  for (let i = 0; i < warp.length - 1; i++) {
    const [s0, t0] = warp[i]
    const [s1, t1] = warp[i + 1]
    if (s1 > s0 && t1 > t0 && t >= t0 && t <= t1) return s0 + ((t - t0) / (t1 - t0)) * (s1 - s0)
  }
  const [sl, tl] = warp[warp.length - 1]
  if (t >= tl) return sl + (t - tl)
  return null
}

function cuts(warp: Warp): { at: number; before: number }[] {
  const out: { at: number; before: number }[] = []
  for (let i = 0; i < warp.length - 1; i++) if (warp[i + 1][0] === warp[i][0]) out.push({ at: warp[i][0], before: warp[i][1] })
  return out
}

type Cam = { cx: number; cy: number; s: number }
const FULL: Cam = { cx: VW / 2, cy: VH / 2, s: 1 }

function camFor(shot: Shot): Cam {
  if (!shot.rect) return FULL
  const pad = shot.pad ?? 36
  const r = shot.rect
  const s = Math.max(1, Math.min(shot.max ?? 2.2, VW / (r.w + pad * 2), VH / (r.h + pad * 2)))
  const hw = VW / 2 / s
  const hh = VH / 2 / s
  const cx = Math.min(VW - hw, Math.max(hw, r.x + r.w / 2))
  const cy = Math.min(VH - hh, Math.max(hh, r.y + r.h / 2))
  return { cx, cy, s }
}

export function cameraAt(shots: Shot[], sec: number, fps: number): Cam {
  let cam = FULL
  for (const shot of shots) {
    if (sec < shot.at) break
    const p = spring({ frame: (sec - shot.at) * fps, fps, config: { damping: 200, stiffness: shot.stiffness ?? 70, mass: 1 } })
    const to = camFor(shot)
    const ls = Math.log(cam.s) + (Math.log(to.s) - Math.log(cam.s)) * p
    cam = { cx: cam.cx + (to.cx - cam.cx) * p, cy: cam.cy + (to.cy - cam.cy) * p, s: Math.exp(ls) }
  }
  return cam
}

export const toScreen = (cam: Cam, x: number, y: number) => ({ x: (x - cam.cx) * cam.s + VW / 2, y: (y - cam.cy) * cam.s + VH / 2 })

function Cursor({ x, y, press }: { x: number; y: number; press: number }) {
  return (
    <svg
      width={30}
      height={30}
      viewBox="0 0 24 24"
      style={{ position: 'absolute', left: x - 5, top: y - 3, transform: `scale(${1 - press * 0.14})`, transformOrigin: '5px 3px', filter: 'drop-shadow(0 3px 6px rgba(13,14,18,0.28))' }}
    >
      <path d="M5 3 L5 19.2 L9.3 15.3 L12.1 21.4 L15 20.1 L12.3 14.1 L18.2 14.1 Z" fill={C.ink} stroke={C.paper} strokeWidth={1.6} strokeLinejoin="round" />
    </svg>
  )
}

export function RingMark({ ring, cam, sec, fps }: { ring: Ring; cam: Cam; sec: number; fps: number }) {
  if (sec < ring.at - 0.05 || sec > ring.until + 0.5) return null
  const pad = ring.pad ?? 10
  const a = toScreen(cam, ring.rect.x - pad, ring.rect.y - pad)
  const b = toScreen(cam, ring.rect.x + ring.rect.w + pad, ring.rect.y + ring.rect.h + pad)
  const draw = interpolate(sec - ring.at, [0, 0.55], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: ease })
  const out = interpolate(sec, [ring.until, ring.until + 0.4], [1, 0], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' })
  const color = ring.color ?? C.cobalt
  const w = b.x - a.x
  const h = b.y - a.y
  if (ring.kind === 'underline') {
    return (
      <div style={{ position: 'absolute', left: a.x, top: b.y - 2, width: w * draw, height: 5, borderRadius: 3, background: color, opacity: out }} />
    )
  }
  const r = Math.min(16, h / 2)
  const per = 2 * (w + h)
  return (
    <svg style={{ position: 'absolute', left: a.x - 4, top: a.y - 4, overflow: 'visible', opacity: out }} width={w + 8} height={h + 8}>
      <rect x={4} y={4} width={w} height={h} rx={r} fill="none" stroke={color} strokeOpacity={0.18} strokeWidth={10} strokeDasharray={per} strokeDashoffset={per * (1 - draw)} />
      <rect x={4} y={4} width={w} height={h} rx={r} fill="none" stroke={color} strokeWidth={3} strokeDasharray={per} strokeDashoffset={per * (1 - draw)} strokeLinecap="round" />
    </svg>
  )
}

export function LowerThird({ label, sec, fps }: { label: Label; sec: number; fps: number }) {
  if (sec < label.at || sec > label.until + 0.5) return null
  const p = spring({ frame: (sec - label.at) * fps, fps, config: { damping: 18, stiffness: 140, mass: 0.8 } })
  const out = interpolate(sec, [label.until, label.until + 0.4], [1, 0], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' })
  const bar = interpolate(sec - label.at, [0.1, 0.6], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: ease })
  return (
    <div
      style={{
        position: 'absolute',
        left: 28,
        bottom: 28,
        padding: '16px 22px 17px 22px',
        background: C.paper,
        borderRadius: 18,
        boxShadow: '0 18px 44px -18px rgba(13,14,18,0.38), 0 0 0 1px rgba(13,14,18,0.06)',
        transform: `translateY(${(1 - p) * 26}px)`,
        opacity: Math.min(1, p * 3) * out,
        maxWidth: 560,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <span style={{ width: 22 * bar, height: 6, borderRadius: 3, background: C.cobalt, display: 'inline-block' }} />
        <span style={{ fontFamily: DISPLAY, fontWeight: 600, fontSize: 29, letterSpacing: '-0.03em', color: C.ink }}>{label.title}</span>
      </div>
      {label.sub && <div style={{ marginTop: 6, fontFamily: SANS, fontSize: 18.5, lineHeight: 1.35, color: C.muted }}>{label.sub}</div>}
    </div>
  )
}

export function FootageFrame({ children, style }: { children: ReactNode; style?: CSSProperties }) {
  return (
    <div
      style={{
        position: 'absolute',
        left: SLAB.x,
        top: SLAB.y,
        width: SLAB.w,
        height: SLAB.h,
        borderRadius: SLAB.r,
        overflow: 'hidden',
        background: C.page,
        boxShadow: '0 40px 90px -40px rgba(13,14,18,0.45), 0 0 0 1px rgba(13,14,18,0.07)',
        ...style,
      }}
    >
      {children}
    </div>
  )
}

export function Footage({
  take: name,
  warp,
  shots = [],
  rings = [],
  labels = [],
  cursor = true,
  from = 0,
  children,
}: {
  take: string
  warp: Warp
  shots?: Shot[]
  rings?: Ring[]
  labels?: Label[]
  cursor?: boolean
  /** Scene seconds at which this footage's own clock starts. */
  from?: number
  children?: ReactNode
}) {
  const frame = useCurrentFrame()
  const { fps } = useVideoConfig()
  const take: Take | null = useTake(name)
  const sec = frame / fps - from
  if (!take) return null
  const t = warpAt(warp, sec)
  const cam = cameraAt(shots, sec, fps)
  const src = frameAt(take, t)
  const transform = `translate(${VW / 2}px, ${VH / 2}px) scale(${cam.s}) translate(${-cam.cx}px, ${-cam.cy}px)`

  // A cut dissolves for a quarter second.
  const cut = cuts(warp).find((c) => sec >= c.at && sec < c.at + 0.3)
  const fade = cut ? interpolate(sec - cut.at, [0, 0.3], [1, 0], { easing: ease }) : 0

  const p = cursor && !take.hideCursor ? pointerAt(take, t) : null
  const ptr = p ? toScreen(cam, p.x, p.y) : null
  const down = take.downs.find((d) => t >= d.t && t < d.t + 0.18)
  const press = down ? Math.sin(((t - down.t) / 0.18) * Math.PI) : 0
  const ripples = take.clicks
    .map((c) => ({ c, s: sceneTimeOf(warp, c.t) }))
    .filter((r) => r.s !== null && sec >= r.s && sec < r.s + 0.7)

  return (
    <AbsoluteFill>
      <div style={{ position: 'absolute', left: 0, top: 0, width: VW, height: VH, transformOrigin: '0 0', transform }}>
        <Img src={src} style={{ position: 'absolute', left: 0, top: 0, width: VW, height: VH }} />
        {cut && <Img src={frameAt(take, cut.before)} style={{ position: 'absolute', left: 0, top: 0, width: VW, height: VH, opacity: fade }} />}
      </div>
      {rings.map((r, i) => (
        <RingMark key={i} ring={r} cam={cam} sec={sec} fps={fps} />
      ))}
      {ripples.map(({ c, s }, i) => {
        const age = sec - (s as number)
        const q = toScreen(cam, c.x, c.y)
        const k = interpolate(age, [0, 0.7], [0, 1], { easing: ease })
        return (
          <div
            key={i}
            style={{
              position: 'absolute',
              left: q.x - 8 - 30 * k,
              top: q.y - 8 - 30 * k,
              width: 16 + 60 * k,
              height: 16 + 60 * k,
              borderRadius: '50%',
              border: `3px solid ${C.cobalt}`,
              opacity: (1 - k) * 0.85,
              background: `rgba(44,70,232,${0.12 * (1 - k)})`,
            }}
          />
        )
      })}
      {ptr && <Cursor x={ptr.x} y={ptr.y} press={press} />}
      {labels.map((l, i) => (
        <LowerThird key={i} label={l} sec={sec} fps={fps} />
      ))}
      {children}
    </AbsoluteFill>
  )
}
