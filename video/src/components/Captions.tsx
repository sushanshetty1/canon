// Captions: the voice's own chunks, timed by the voice's alignment, in the brand sans, two lines at most,
// in the band under the slab.

import { interpolate, useCurrentFrame, useVideoConfig } from 'remotion'
import { C, SANS, SLAB } from '../brand'
import type { Placed } from '../timeline'

type Cue = { text: string; start: number; end: number }

export function cues(scenes: Placed[]): Cue[] {
  const out: Cue[] = []
  for (const s of scenes) for (const c of s.voice.chunks) out.push({ text: c.text, start: s.start + (s.delay ?? 0) + c.start, end: s.start + (s.delay ?? 0) + c.end })
  // Hold each caption until the next begins when the gap is short, so the band never flickers empty mid-thought.
  return out.map((c, i) => {
    const next = out[i + 1]
    const hold = next && next.start - c.end < 0.7 ? next.start - 0.04 : c.end + 0.35
    return { ...c, start: c.start - 0.06, end: hold }
  })
}

export function Captions({ list }: { list: Cue[] }) {
  const frame = useCurrentFrame()
  const { fps } = useVideoConfig()
  const t = frame / fps
  const cue = list.find((c) => t >= c.start && t < c.end)
  if (!cue) return null
  const age = t - cue.start
  const left = cue.end - t
  const inP = interpolate(age, [0, 0.18], [0, 1], { extrapolateRight: 'clamp' })
  const outP = interpolate(left, [0, 0.12], [0, 1], { extrapolateRight: 'clamp' })
  return (
    <div
      style={{
        position: 'absolute',
        left: 0,
        right: 0,
        top: SLAB.y + SLAB.h + 14,
        bottom: 14,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
      }}
    >
      <div
        style={{
          maxWidth: 1460,
          textAlign: 'center',
          fontFamily: SANS,
          fontWeight: 560,
          fontSize: 31,
          lineHeight: 1.32,
          letterSpacing: '-0.005em',
          color: C.ink,
          opacity: Math.min(inP, outP),
          transform: `translateY(${(1 - inP) * 6}px)`,
          textWrap: 'balance',
        }}
      >
        {cue.text}
      </div>
    </div>
  )
}
