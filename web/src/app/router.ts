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

/** Go to a path in the app, keeping the query (so `?mock=1` survives). */
export function navigate(to: string) {
  if (to === window.location.pathname) return
  window.history.pushState(null, '', to + window.location.search)
  window.dispatchEvent(new PopStateEvent('popstate'))
}
