// Three transition families, all in Canon's own marks:
//   card   the proofreader's strike across the outgoing slab, then a sheet with the old word struck in red and the
//          cobalt correction written in, which lifts away to the next scene;
//   sweep  the Today line walks across the frame and the next scene is already there behind it;
//   lift   the slab lifts and slides away as the next one rises into place.

import type { ReactNode } from 'react'
import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from 'remotion'
import { C, DISPLAY, SANS, SLAB, W, ease, easeIn, easeInOut } from '../brand'
import { OVERLAP, type Into, type Placed } from '../timeline'

const clamp = { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' } as const

/** The section card's clock, in seconds from the start of the incoming scene. */
export const CARD = { rise: [0.12, 0.62], strike: [0.5, 0.8], write: [0.72, 1.12], lift: [1.3, 1.78] } as const
/** When a carded scene's own content shows under the lifting card. */
export const CONTENT_AT = 1.22

function Card({ old, next, sec, fps }: { old: string; next: string; sec: number; fps: number }) {
  const rise = spring({ frame: (sec - CARD.rise[0]) * fps, fps, config: { damping: 22, stiffness: 120, mass: 0.9 } })
  const strike = interpolate(sec, CARD.strike as unknown as number[], [0, 1], { ...clamp, easing: ease })
  const write = interpolate(sec, CARD.write as unknown as number[], [0, 1], { ...clamp, easing: ease })
  const lift = interpolate(sec, CARD.lift as unknown as number[], [0, 1], { ...clamp, easing: easeIn })
  if (sec > CARD.lift[1] + 0.05) return null
  const y = (1 - rise) * 1000 - lift * 140
  const size = old.length + next.length > 16 ? 112 : 132
  return (
    <div
      style={{
        position: 'absolute',
        left: SLAB.x,
        top: SLAB.y,
        width: SLAB.w,
        height: SLAB.h,
        borderRadius: SLAB.r,
        background: C.paper,
        transform: `translateY(${y}px) scale(${1 + lift * 0.03})`,
        opacity: 1 - lift,
        boxShadow: '0 50px 110px -40px rgba(13,14,18,0.5), 0 0 0 1px rgba(13,14,18,0.06)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        backgroundImage: 'repeating-linear-gradient(to bottom, transparent 0, transparent 47px, rgba(13,14,18,0.04) 47px, rgba(13,14,18,0.04) 48px)',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'baseline', gap: size * 0.32, fontFamily: DISPLAY, fontWeight: 600, fontSize: size, letterSpacing: '-0.045em', lineHeight: 1 }}>
        <span style={{ position: 'relative', color: C.faint }}>
          {old}
          <span
            style={{
              position: 'absolute',
              left: '-3%',
              top: '52%',
              height: size * 0.085,
              width: `${106 * strike}%`,
              background: C.proof,
              borderRadius: 99,
              transform: 'rotate(-2deg)',
              transformOrigin: 'left center',
            }}
          />
        </span>
        <span style={{ color: C.cobalt, clipPath: `inset(-20% ${(1 - write) * 100}% -30% 0)`, transform: `translateY(${(1 - write) * 14}px)`, display: 'inline-block' }}>{next}</span>
      </div>
    </div>
  )
}

/** The proofreader's strike, drawn across a slab that is going out of date. */
function Strike({ p }: { p: number }) {
  return (
    <div
      style={{
        position: 'absolute',
        left: SLAB.x + 70,
        top: SLAB.y + SLAB.h * 0.48,
        width: (SLAB.w - 140) * p,
        height: 11,
        borderRadius: 99,
        background: C.proof,
        transform: 'rotate(-1.4deg)',
        transformOrigin: 'left center',
        boxShadow: '0 6px 18px -6px rgba(224,57,44,0.55)',
      }}
    />
  )
}

function TodayLine({ x }: { x: number }) {
  return (
    <div style={{ position: 'absolute', left: x, top: 0, bottom: 0, width: 0 }}>
      <div style={{ position: 'absolute', left: -1.5, top: 0, bottom: 0, width: 3, background: C.ink }} />
      <div style={{ position: 'absolute', left: -1.5, top: 0, bottom: 0, width: 46, transform: 'translateX(-46px)', background: 'linear-gradient(to right, rgba(44,70,232,0), rgba(44,70,232,0.10))' }} />
      <div
        style={{
          position: 'absolute',
          top: SLAB.y + 18,
          left: 0,
          transform: 'translateX(-50%)',
          background: C.ink,
          color: C.paper,
          fontFamily: SANS,
          fontWeight: 600,
          fontSize: 19,
          padding: '6px 14px 7px',
          borderRadius: 99,
          whiteSpace: 'nowrap',
        }}
      >
        Today
      </div>
    </div>
  )
}

export function Transitioned({ scene, children }: { scene: Placed; children: ReactNode }) {
  const frame = useCurrentFrame()
  const { fps } = useVideoConfig()
  const sec = frame / fps
  const into: Into = scene.into
  const out: Into['kind'] | undefined = scene.next?.into.kind
  const outT = out ? OVERLAP[out] : 0
  const toEnd = scene.dur - sec

  // Exit: what this scene does while the next one comes in over it.
  let exitStyle: React.CSSProperties = {}
  let strike = 0
  const gone = outT - toEnd // seconds since the next scene began coming in
  if (out === 'lift' && gone > 0) {
    const q = interpolate(gone, [0, outT], [0, 1], { ...clamp, easing: easeIn })
    exitStyle = { transform: `translate(${-q * 260}px, ${-q * 70}px) scale(${1 - q * 0.12})`, opacity: 1 - q, filter: `blur(${q * 1.5}px)` }
  }
  if (out === 'card' && gone > 0) {
    strike = interpolate(gone, [0, 0.32], [0, 1], { ...clamp, easing: ease })
    const q = interpolate(gone, [outT * 0.5, outT], [0, 1], clamp)
    exitStyle = { transform: `scale(${1 - q * 0.04})`, opacity: 1 - q * 0.6 }
  }

  // Entrance.
  let enterStyle: React.CSSProperties = {}
  let overlay: ReactNode = null
  const T = OVERLAP[into.kind]
  if (into.kind === 'sweep' && sec < T + 0.05) {
    const x = interpolate(sec, [0, T], [0, 1], { ...clamp, easing: easeInOut })
    const px = x * (W + 60) - 30
    enterStyle = { clipPath: `inset(0 ${W - px}px 0 0)` }
    overlay = <TodayLine x={px} />
  }
  if (into.kind === 'lift') {
    const p = spring({ frame, fps, config: { damping: 20, stiffness: 95, mass: 1 } })
    enterStyle = { transform: `translateY(${(1 - p) * 220}px) scale(${0.94 + 0.06 * p})`, opacity: Math.min(1, sec / 0.25) }
  }
  if (into.kind === 'card') {
    const show = interpolate(sec, [CONTENT_AT - 0.05, CONTENT_AT + 0.15], [0, 1], clamp)
    const settle = interpolate(sec, [CONTENT_AT, CONTENT_AT + 0.7], [0.975, 1], { ...clamp, easing: ease })
    enterStyle = { opacity: show, transform: `scale(${settle})` }
    overlay = <Card old={into.old} next={into.next} sec={sec} fps={fps} />
  }

  return (
    <AbsoluteFill>
      <AbsoluteFill style={{ ...enterStyle }}>
        <AbsoluteFill style={{ ...exitStyle, transformOrigin: '50% 45%' }}>{children}</AbsoluteFill>
        {strike > 0 && <Strike p={strike} />}
      </AbsoluteFill>
      {overlay}
    </AbsoluteFill>
  )
}
