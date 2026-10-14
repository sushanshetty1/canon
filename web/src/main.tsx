import { lazy, StrictMode, Suspense } from 'react'
import { createRoot } from 'react-dom/client'
import { App } from './App'
import { isAppPath, usePath } from './app/router'
import './index.css'

// `/app` is the product; everything else is the site. The app loads only when it is opened.
const CanonApp = lazy(() => import('./app/App'))

function Root() {
  const path = usePath()
  if (!isAppPath(path)) return <App />
  return (
    <Suspense fallback={<div className="min-h-[100dvh] bg-page" />}>
      <CanonApp />
    </Suspense>
  )
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <Root />
  </StrictMode>,
)
