// The smallest router that works: the pathname picks the screen, `navigate` pushes history.

import { useEffect, useState } from 'react'

export function usePath(): string {
  const [path, setPath] = useState(() => window.location.pathname)
  useEffect(() => {
    const update = () => setPath(window.location.pathname)
    window.addEventListener('popstate', update)
    return () => window.removeEventListener('popstate', update)
  }, [])
  return path
}

export const isAppPath = (path: string) => path === '/app' || path.startsWith('/app/')

/** The app's screens by path. Anything else under /app opens Ask. */
export const ROUTES = {
  ask: '/app',
  whoKnows: '/app/who-knows',
  busFactor: '/app/bus-factor',
  fixQueue: '/app/fixes',
  decisions: '/app/decisions',
  catchUp: '/app/catch-up',
  newWorkspace: '/app/new',
} as const

export type Screen = keyof typeof ROUTES

export const screenOf = (path: string): Screen =>
  (Object.keys(ROUTES) as Screen[]).find((s) => ROUTES[s] === path.replace(/\/+$/, '')) ?? 'ask'

/** Go to a path in the app (it may carry its own query), keeping `?mock=1` when it is on. */
export function navigate(to: string) {
  const url = new URL(to, window.location.origin)
  const mock = new URLSearchParams(window.location.search).get('mock')
  if (mock && !url.searchParams.has('mock')) url.searchParams.set('mock', mock)
  const next = url.pathname + url.search
  if (next === window.location.pathname + window.location.search) return
  window.history.pushState(null, '', next)
  window.dispatchEvent(new PopStateEvent('popstate'))
}
