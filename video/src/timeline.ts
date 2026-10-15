// The running order. Every scene is as long as its voice (plus any room the footage needs), and scenes overlap
// by their transition, so the cut lands on the phrase end and the next voice comes in under the transition.

import { createContext, useContext } from 'react'
import { FPS } from './brand'
import timing from './timing.json'

export type Into = { kind: 'none' } | { kind: 'sweep' } | { kind: 'lift' } | { kind: 'stretch' } | { kind: 'card'; old: string; next: string }

export type SceneDef = {
  id: string
  /** Seconds before the voice starts (a section card plays first). */
  delay?: number
  /** Seconds after the voice ends, for footage that needs to finish. */
  extra?: number
  into: Into
}

export const SCENES: SceneDef[] = [
  { id: 'open', into: { kind: 'none' }, extra: 0.3 },
  { id: 'problem', into: { kind: 'stretch' }, extra: 0.4 },
  { id: 'idea', into: { kind: 'card', old: 'Cited', next: 'Checked.' }, delay: 0.6, extra: 0.2 },
  { id: 'graph', into: { kind: 'lift' }, extra: 0.3 },
  { id: 'ask', into: { kind: 'card', old: 'Search', next: 'Ask.' }, delay: 0.6, extra: 0.2 },
  { id: 'dispute', into: { kind: 'sweep' }, extra: 1.0 },
  { id: 'fix', into: { kind: 'card', old: 'Report', next: 'Fix.' }, delay: 0.6, extra: 1.2 },
  { id: 'whoknows', into: { kind: 'card', old: 'Org chart', next: 'Evidence.' }, delay: 0.6, extra: 0.4 },
  { id: 'busfactor', into: { kind: 'sweep' }, extra: 1.8 },
  { id: 'decisions', into: { kind: 'lift' }, extra: 0.8 },
  { id: 'connect', into: { kind: 'card', old: 'Demo', next: 'Your company.' }, delay: 0.6, extra: 2.0 },
  { id: 'numbers', into: { kind: 'card', old: 'Claimed', next: 'Measured.' }, delay: 0.6, extra: 0.6 },
  { id: 'close', into: { kind: 'lift' }, extra: 2.4 },
]

/** How long each kind of transition overlaps the scene before it, in seconds. */
export const OVERLAP: Record<Into['kind'], number> = { none: 0, sweep: 0.8, lift: 0.8, stretch: 0.7, card: 0.55 }

type Chunk = { text: string; start: number; end: number }
type VoiceScene = { file: string; duration: number; lead: number; chunks: Chunk[]; words: { w: string; start: number; end: number }[] }
const voice = (timing as unknown as { scenes: Record<string, VoiceScene> }).scenes

export type Placed = SceneDef & { start: number; dur: number; voice: VoiceScene; next?: SceneDef }

export function placed(): { scenes: Placed[]; total: number } {
  let t = 0
  const out: Placed[] = []
  SCENES.forEach((s, i) => {
    const v = voice[s.id]
    const dur = (s.delay ?? 0) + v.duration + (s.extra ?? 0)
    if (i > 0) t -= OVERLAP[s.into.kind]
    out.push({ ...s, start: t, dur, voice: v, next: SCENES[i + 1] })
    t += dur
  })
  return { scenes: out, total: t }
}

export const toFrames = (sec: number) => Math.round(sec * FPS)

/** Inside a scene: when its voice says chunk i (seconds from the scene's start), and how long the scene is. */
export type SceneTime = { c: (i: number) => number; ce: (i: number) => number; word: (w: string, after?: number) => number; dur: number; delay: number }

export function sceneTime(p: Placed): SceneTime {
  const d = p.delay ?? 0
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
