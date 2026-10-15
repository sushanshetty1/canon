// The running order, led by the voice. The narration is one continuous read: each scene's line starts a breath after
// the previous one ends (one deliberate pause sits before the benchmark). A scene begins `voiceAt` seconds before its
// line, so the transition plays under the voice, and it lasts until the next scene has finished coming in over it.
// The order, transitions and pacing live in scenes.json, which scripts/stills.mjs reads too.

import { createContext, useContext } from 'react'
import { FPS } from './brand'
import plan from './scenes.json'
import timing from './timing.json'

export type Into = { kind: 'none' } | { kind: 'sweep' } | { kind: 'lift' } | { kind: 'stretch' } | { kind: 'card'; old: string; next: string }
type Kind = Into['kind']

export type SceneDef = { id: string; into: Into; pauseBefore?: number }

export const SCENES = plan.scenes as SceneDef[]
/** How long each kind of transition overlaps the scene before it, in seconds. */
export const OVERLAP = plan.overlap as Record<Kind, number>
const VOICE_AT = plan.voiceAt as Record<Kind, number>

type Chunk = { text: string; start: number; end: number }
type VoiceScene = { file: string; duration: number; chunks: Chunk[]; words: { w: string; start: number; end: number }[] }
const voice = (timing as unknown as { scenes: Record<string, VoiceScene> }).scenes

/** `delay` is when the scene's voice starts, in seconds from the scene's start. */
export type Placed = SceneDef & { start: number; dur: number; delay: number; voice: VoiceScene; next?: SceneDef }

export function placed(): { scenes: Placed[]; total: number } {
  // When each line is spoken, end to end.
  const voiceStart: number[] = []
  SCENES.forEach((s, i) => {
    if (i === 0) voiceStart.push(VOICE_AT[s.into.kind])
    else voiceStart.push(voiceStart[i - 1] + voice[SCENES[i - 1].id].duration + plan.breath + (s.pauseBefore ?? 0))
  })
  const starts = SCENES.map((s, i) => voiceStart[i] - VOICE_AT[s.into.kind])
  const out: Placed[] = SCENES.map((s, i) => {
    const next = SCENES[i + 1]
    const end = next ? starts[i + 1] + OVERLAP[next.into.kind] : voiceStart[i] + voice[s.id].duration + plan.hold
    return { ...s, start: starts[i], dur: end - starts[i], delay: VOICE_AT[s.into.kind], voice: voice[s.id], next }
  })
  const last = out[out.length - 1]
  return { scenes: out, total: last.start + last.dur }
}

export const toFrames = (sec: number) => Math.round(sec * FPS)

/** Inside a scene: when its voice says chunk i (seconds from the scene's start), and how long the scene is. */
export type SceneTime = { c: (i: number) => number; ce: (i: number) => number; word: (w: string, after?: number) => number; dur: number; delay: number }

export function sceneTime(p: Placed): SceneTime {
  const d = p.delay
  return {
    c: (i) => d + p.voice.chunks[Math.min(i, p.voice.chunks.length - 1)].start,
    ce: (i) => d + p.voice.chunks[Math.min(i, p.voice.chunks.length - 1)].end,
    word: (w, after = 0) => {
      const hit = p.voice.words.find((x) => x.w.toLowerCase().startsWith(w.toLowerCase()) && x.start + d >= after)
      return hit ? d + hit.start : after
    },
    dur: p.dur,
    delay: d,
  }
}

export const SceneContext = createContext<SceneTime | null>(null)
export function useSceneTime(): SceneTime {
  const s = useContext(SceneContext)
  if (!s) throw new Error('no scene')
  return s
}
