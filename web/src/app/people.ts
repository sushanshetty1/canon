// Shared pieces of the people screens: words for evidence, a width measure for drawings, and the screen width.

import { useEffect, useRef, useState } from 'react'
import type { Act, Evidence } from './api'

/** Evidence counts as a short phrase: "wrote 41, reviewed 2, commented on 6". */
export function evidencePhrase(e: Evidence): string {
  const parts: string[] = []
  if (e.decided) parts.push(`decided ${e.decided}`)
  if (e.authored) parts.push(`wrote ${e.authored}`)
  if (e.reviewed) parts.push(`reviewed ${e.reviewed}`)
  if (e.commented) parts.push(`commented on ${e.commented}`)
  if (!parts.length) return e.member ? 'on the owning team' : ''
  return parts.join(', ')
}

const VERB: Record<Act['rel'], string> = { decided: 'Decided', authored: 'Wrote', reviewed: 'Reviewed', commented: 'Commented' }

/** What someone did on a document, in words: an issue is opened rather than written. */
export function actLabel(rel: Act['rel'], kind: string | null): string {
  if (rel === 'authored' && kind === 'issue') return 'Opened'
  if (rel === 'authored' && kind === 'handbook') return 'Edited'
  return VERB[rel]
}

/** The weight each kind of evidence carries in a score, before recency (see server/src/canon/people/expertise.py). */
export const WEIGHTS = { decided: 4, authored: 3, reviewed: 2, commented: 1, member: 2 } as const

/** A first name, for labels in a drawing: "Matheus Vinicius" is "Matheus". Handles stay whole. */
export function shortName(name: string, handle: string): string {
  if (!name || name === handle) return handle
  return name.split(/\s+/)[0]
}

/** The width of an element, kept current as it resizes. */
export function useWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null)
  const [width, setWidth] = useState(0)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const ro = new ResizeObserver(([entry]) => setWidth(Math.round(entry.contentRect.width)))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])
  return { ref, width }
}

export function useWide(query = '(min-width: 900px)') {
  const [wide, setWide] = useState(() => window.matchMedia(query).matches)
  useEffect(() => {
    const m = window.matchMedia(query)
    const update = () => setWide(m.matches)
    m.addEventListener('change', update)
    return () => m.removeEventListener('change', update)
  }, [query])
  return wide
}

/** The `area` in the address bar, kept in step with the screen without adding history entries. */
export function readArea(): string | null {
  try {
    return new URLSearchParams(window.location.search).get('area')
  } catch {
    return null
  }
}

export function writeArea(slug: string) {
  const url = new URL(window.location.href)
  if (url.searchParams.get('area') === slug) return
  url.searchParams.set('area', slug)
  window.history.replaceState(null, '', url.pathname + url.search)
}
