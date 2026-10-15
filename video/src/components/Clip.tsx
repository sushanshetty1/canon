// One take inside a scene, from `from` to `to` scene seconds. A clip that follows another rises in over it, the
// way the slabs lift; the one before settles back as it is covered.

import type { ComponentProps } from 'react'
import { AbsoluteFill, Sequence, interpolate, spring, useCurrentFrame, useVideoConfig } from 'remotion'
import { ease } from '../brand'
import { Footage, FootageFrame } from './Footage'

type Props = Omit<ComponentProps<typeof Footage>, 'from'> & { from: number; to: number; enter?: boolean; exit?: boolean }

const IN = 0.5

function Inner({ from, to, enter, exit, ...rest }: Props) {
  const frame = useCurrentFrame()
  const { fps } = useVideoConfig()
  const sec = frame / fps
  const len = to - from
  const p = enter ? spring({ frame, fps, config: { damping: 22, stiffness: 120, mass: 0.9 } }) : 1
  const leaving = exit ? interpolate(sec, [len - 0.05, len + IN], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: ease }) : 0
  return (
    <AbsoluteFill
      style={{
        transform: `translateY(${(1 - p) * 120}px) scale(${(0.96 + 0.04 * p) * (1 - leaving * 0.035)})`,
        opacity: enter ? Math.min(1, sec / 0.18) : 1,
        filter: leaving ? `brightness(${1 - leaving * 0.06})` : undefined,
      }}
    >
      <FootageFrame>
        <Footage {...rest} />
      </FootageFrame>
    </AbsoluteFill>
  )
}

/** Warps, shots, rings and labels in a clip are in scene seconds, like everything else in the scene. */
export function Clip(props: Props) {
  const { fps } = useVideoConfig()
  const start = Math.round(props.from * fps)
  const dur = Math.round((props.to - props.from + (props.exit ? IN + 0.1 : 0)) * fps)
  const shift = props.from
  const warp = props.warp.map(([s, t]) => [s - shift, t] as [number, number])
  const shots = props.shots?.map((x) => ({ ...x, at: x.at - shift }))
  const rings = props.rings?.map((x) => ({ ...x, at: x.at - shift, until: x.until - shift }))
  const labels = props.labels?.map((x) => ({ ...x, at: x.at - shift, until: x.until - shift }))
  return (
    <Sequence from={start} durationInFrames={Math.max(1, dur)} layout="none">
      <Inner {...props} warp={warp} shots={shots} rings={rings} labels={labels} />
    </Sequence>
  )
}
