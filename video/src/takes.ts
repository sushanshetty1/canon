// A take is a recorded scene of the site: frames as Chrome painted them, and the log of what the script did.
// Written by capture/lib.mjs into public/captures/<name>/take.json.

import { useEffect, useState } from 'react'
import { continueRender, delayRender, staticFile } from 'remotion'

export type Rect = { x: number; y: number; w: number; h: number }
type Event = { t: number; type: string; x?: number; y?: number; name?: string; rect?: Rect; label?: string }

export type Take = {
  name: string
  viewport: { width: number; height: number }
  scale: number
  duration: number
  frames: [string, number][]
  events: Event[]
  moves: { t: number; x: number; y: number }[]
  clicks: { t: number; x: number; y: number }[]
  downs: { t: number }[]
  hideCursor: boolean
}

const cache = new Map<string, Take>()
const pending = new Map<string, Promise<Take>>()

function prepare(raw: Omit<Take, 'moves' | 'clicks' | 'downs' | 'hideCursor'>): Take {
  const moves = raw.events.filter((e) => e.type === 'move').map((e) => ({ t: e.t, x: e.x!, y: e.y! }))
  const clicks = raw.events.filter((e) => e.type === 'click').map((e) => ({ t: e.t, x: e.x!, y: e.y! }))
  const downs = raw.events.filter((e) => e.type === 'down').map((e) => ({ t: e.t }))
  return { ...raw, moves, clicks, downs, hideCursor: raw.events.some((e) => e.type === 'hide-cursor') }
}

function load(name: string): Promise<Take> {
  if (!pending.has(name)) {
    pending.set(
      name,
      fetch(staticFile(`captures/${name}/take.json`))
        .then((r) => r.json())
        .then((raw) => {
          const take = prepare(raw)
          cache.set(name, take)
          return take
        }),
    )
  }
  return pending.get(name)!
}

export function useTake(name: string): Take | null {
  const [take, setTake] = useState<Take | null>(() => cache.get(name) ?? null)
  const [handle] = useState(() => (cache.has(name) ? null : delayRender(`take ${name}`)))
  useEffect(() => {
    if (take) return
    load(name).then(
      (t) => {
        setTake(t)
        if (handle !== null) continueRender(handle)
      },
      (e) => {
        console.error(e)
        if (handle !== null) continueRender(handle)
      },
    )
  }, [name, take, handle])
  return take
}

/** The frame on screen at take time t: the last one painted at or before t. */
export function frameAt(take: Take, t: number): string {
  const f = take.frames
  let lo = 0
  let hi = f.length - 1
  if (t <= f[0][1]) return staticFile(`captures/${take.name}/${f[0][0]}`)
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1
    if (f[mid][1] <= t) lo = mid
    else hi = mid - 1
  }
  return staticFile(`captures/${take.name}/${f[lo][0]}`)
}

/** Where the pointer was at take time t, in CSS pixels of the viewport. */
export function pointerAt(take: Take, t: number): { x: number; y: number } | null {
  const m = take.moves
  if (!m.length) return null
  if (t <= m[0].t) return m[0]
  let lo = 0
  let hi = m.length - 1
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1
    if (m[mid].t <= t) lo = mid
    else hi = mid - 1
  }
  const a = m[lo]
  const b = m[lo + 1]
  if (!b) return a
  const p = Math.min(1, Math.max(0, (t - a.t) / Math.max(1e-6, b.t - a.t)))
  return { x: a.x + (b.x - a.x) * p, y: a.y + (b.y - a.y) * p }
}

/** A mark the take logged: an element's rectangle at the moment it was named. */
export function mark(take: Take, name: string): Rect | null {
  const e = [...take.events].reverse().find((x) => x.type === 'mark' && x.name === name)
  return e?.rect ?? null
}

export function eventTime(take: Take, type: string, name?: string): number | null {
  const e = take.events.find((x) => x.type === type && (name === undefined || x.name === name || x.label === name))
  return e ? e.t : null
}
