import type { CSSProperties, ReactNode } from 'react'
import { interpolate, spring, useCurrentFrame, useVideoConfig } from 'remotion'
import { C, DISPLAY, SANS, SLAB, ease } from '../brand'

export const clamp = { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' } as const

/** Seconds since the start of the current Sequence. */
export function useSec() {
  const frame = useCurrentFrame()
  const { fps } = useVideoConfig()
  return { sec: frame / fps, fps, frame }
}

/** 0 to 1 along the site's ease, from `at` for `dur` seconds. */
export const ramp = (sec: number, at: number, dur = 0.5, easing = ease) => interpolate(sec, [at, at + dur], [0, 1], { ...clamp, easing })

/** A settled spring from `at`. */
export const pop = (sec: number, at: number, fps: number, config = { damping: 20, stiffness: 140, mass: 0.9 }) =>
  sec < at ? 0 : spring({ frame: (sec - at) * fps, fps, config })

/** A sheet of paper on the page, where a scene draws. Children use slab coordinates (1600 x 900). */
export function PaperSlab({ children, style, tone = 'paper' }: { children?: ReactNode; style?: CSSProperties; tone?: 'paper' | 'night' }) {
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
        background: tone === 'night' ? C.night : C.paper,
        color: tone === 'night' ? C.paper : C.ink,
        boxShadow: '0 40px 90px -40px rgba(13,14,18,0.42), 0 0 0 1px rgba(13,14,18,0.06)',
        ...style,
      }}
    >
      {children}
    </div>
  )
}

export function Mark({ height = 30 }: { height?: number }) {
  return (
    <svg viewBox="0 0 40 30" height={height} width={(height * 40) / 30}>
      <rect x="0" y="0" width="40" height="7" rx="3.5" fill={C.cobalt} />
      <rect x="0" y="11.5" width="30" height="7" rx="3.5" fill={C.ink} />
      <rect x="0" y="23" width="20" height="7" rx="3.5" fill={C.proof} />
    </svg>
  )
}

export function Wordmark({ size = 40, color = C.ink }: { size?: number; color?: string }) {
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: size * 0.32 }}>
      <svg viewBox="0 0 40 30" height={size * 0.8} width={(size * 0.8 * 40) / 30}>
        <rect x="0" y="0" width="40" height="7" rx="3.5" fill={C.cobalt} />
        <rect x="0" y="11.5" width="30" height="7" rx="3.5" fill={color} />
        <rect x="0" y="23" width="20" height="7" rx="3.5" fill={C.proof} />
      </svg>
      <span style={{ fontFamily: DISPLAY, fontWeight: 600, fontSize: size, letterSpacing: '-0.035em', color }}>Canon</span>
    </span>
  )
}

export function Verdict({ kind, size = 22 }: { kind: 'verified' | 'stale' | 'disputed' | 'removed'; size?: number }) {
  const map = {
    verified: { label: 'Verified', bg: C.cobalt, fg: C.paper },
    stale: { label: 'Out of date', bg: C.proof, fg: C.paper },
    disputed: { label: 'Disputed', bg: C.amberSoft, fg: C.amber },
    removed: { label: 'Removed', bg: C.paper2, fg: C.muted },
  }[kind]
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        height: size * 1.75,
        padding: `0 ${size * 0.62}px`,
        borderRadius: size * 0.5,
        background: map.bg,
        color: map.fg,
        fontFamily: SANS,
        fontWeight: 600,
        fontSize: size,
        whiteSpace: 'nowrap',
      }}
    >
      {map.label}
    </span>
  )
}

/** A word or phrase struck in proof red, drawing left to right as p goes 0 to 1. */
export function Struck({ children, p, color = C.faint, thickness = 0.09 }: { children: ReactNode; p: number; color?: string; thickness?: number }) {
  return (
    <span style={{ position: 'relative', color, display: 'inline-block' }}>
      {children}
      <span
        style={{
          position: 'absolute',
          left: '-2%',
          top: '54%',
          height: `${thickness}em`,
          width: `${104 * p}%`,
          background: C.proof,
          borderRadius: 99,
        }}
      />
    </span>
  )
}

/** Text written in from the left, as a correction is. */
export function Written({ children, p, style }: { children: ReactNode; p: number; style?: CSSProperties }) {
  return (
    <span style={{ display: 'inline-block', clipPath: `inset(-25% ${(1 - p) * 100}% -35% 0)`, transform: `translateY(${(1 - p) * 0.12}em)`, ...style }}>{children}</span>
  )
}
