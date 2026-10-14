// The Canon app: a slim rail on the page, and the screen on a sheet of paper beside it.

import { Bus, CaretUpDown, Check, ClockCounterClockwise, Question, Signpost, UsersThree, Wrench, type Icon } from '@phosphor-icons/react'
import { AnimatePresence, motion } from 'motion/react'
import { useEffect, useRef, useState } from 'react'
import { Wordmark } from '../ui'
import { isMock, stats as getStats, type Stats } from './api'
import { Ask } from './Ask'
import { navigate } from './router'
import { plural } from './text'
import { saveWorkspace, savedWorkspace, WORKSPACES, type Workspace } from './workspaces'
import './app.css'

const NAV: { label: string; icon: Icon; soon?: boolean }[] = [
  { label: 'Ask', icon: Question },
  { label: 'Who knows', icon: UsersThree, soon: true },
  { label: 'Bus factor', icon: Bus, soon: true },
  { label: 'Decisions', icon: Signpost, soon: true },
  { label: 'Catch me up', icon: ClockCounterClockwise, soon: true },
  { label: 'Fix queue', icon: Wrench, soon: true },
]

function WorkspaceSwitcher({ ws, onChange, compact = false }: { ws: Workspace; onChange: (w: Workspace) => void; compact?: boolean }) {
  const [open, setOpen] = useState(false)
  const root = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const away = (e: PointerEvent) => !root.current?.contains(e.target as Node) && setOpen(false)
    const esc = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false)
    window.addEventListener('pointerdown', away)
    window.addEventListener('keydown', esc)
    return () => {
      window.removeEventListener('pointerdown', away)
      window.removeEventListener('keydown', esc)
    }
  }, [open])

  return (
    <div ref={root} className="relative">
      <button
        type="button"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={`Workspace: ${ws.label}`}
        onClick={() => setOpen((o) => !o)}
        className={`flex items-center justify-between gap-2 rounded-[14px] bg-paper text-left text-[14.5px] font-semibold tracking-[-0.01em] text-ink transition-shadow hover:shadow-[inset_0_0_0_1.5px_var(--line-strong)] focus-visible:outline-2 focus-visible:outline-cobalt ${compact ? 'h-10 px-3.5' : 'h-12 w-full px-4'}`}
      >
        <span className="truncate">{ws.label}</span>
        <CaretUpDown size={15} weight="bold" className="shrink-0 text-faint" />
      </button>
      <AnimatePresence>
        {open && (
          <motion.ul
            role="listbox"
            aria-label="Workspaces"
            className={`absolute top-full z-30 mt-2 min-w-[220px] rounded-[16px] bg-paper p-1.5 shadow-[0_18px_50px_-18px_rgb(13_14_18/0.35),0_0_0_1px_var(--line)] ${compact ? 'right-0' : 'left-0 w-full'}`}
            initial={{ opacity: 0, y: -4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            transition={{ duration: 0.16 }}
          >
            {WORKSPACES.map((w) => (
              <li key={w.slug} role="option" aria-selected={w.slug === ws.slug}>
                <button
                  type="button"
                  onClick={() => {
                    setOpen(false)
                    onChange(w)
                  }}
                  className="flex h-10 w-full items-center justify-between rounded-[11px] px-3 text-left text-[14.5px] font-medium text-ink hover:bg-paper-2 focus-visible:bg-paper-2 focus-visible:outline-none"
                >
                  {w.label}
                  {w.slug === ws.slug && <Check size={14} weight="bold" className="text-cobalt" />}
                </button>
              </li>
            ))}
          </motion.ul>
        )}
      </AnimatePresence>
    </div>
  )
}

/** What is in the workspace's graph, in the colours of the marks. */
function GraphStats({ ws }: { ws: Workspace }) {
  const [state, setState] = useState<{ slug: string; stats: Stats | null } | null>(null)
  useEffect(() => {
    const ctrl = new AbortController()
    getStats(ws.slug, ctrl.signal).then(
      (stats) => setState({ slug: ws.slug, stats }),
      (e: Error) => e.name !== 'AbortError' && setState({ slug: ws.slug, stats: null }),
    )
    return () => ctrl.abort()
  }, [ws.slug])

  if (!state || state.slug !== ws.slug) return <div className="h-[104px]" aria-hidden="true" />
  const s = state.stats
  if (!s) return <p className="px-3 text-[13px] leading-relaxed text-faint">{ws.name} is not in the graph yet.</p>
  const rows = [
    { tone: 'bg-cobalt', text: `${plural(s.current_facts, 'fact')} current` },
    { tone: 'bg-proof', text: `${plural(s.stale_pages, 'page')} out of date` },
    { tone: 'bg-amber', text: plural(s.disputes, 'dispute') },
  ]
  return (
    <div className="px-3">
      <p className="text-[13px] text-muted">
        {plural(s.labels.Fact ?? 0, 'fact')} in {plural(s.labels.Document ?? 0, 'document')}
      </p>
      <ul className="mt-3 space-y-2">
        {rows.map((r) => (
          <li key={r.text} className="flex items-center gap-2.5 text-[13px] text-ink">
            <span className={`h-[5px] w-4 rounded-full ${r.tone}`} aria-hidden="true" />
            {r.text}
          </li>
        ))}
      </ul>
    </div>
  )
}

function Rail({ ws, onWorkspace }: { ws: Workspace; onWorkspace: (w: Workspace) => void }) {
  return (
    <aside className="sticky top-3 hidden h-[calc(100dvh-24px)] w-[228px] shrink-0 flex-col min-[900px]:flex">
      <a href="/" className="flex h-12 items-center px-3 text-ink" aria-label="Canon home">
        <Wordmark />
      </a>
      <div className="mt-5">
        <WorkspaceSwitcher ws={ws} onChange={onWorkspace} />
      </div>
      <nav aria-label="Canon" className="mt-6">
        <ul className="space-y-0.5">
          {NAV.map(({ label, icon: Glyph, soon }) => (
            <li key={label}>
              {soon ? (
                <span aria-disabled="true" className="flex h-10 cursor-default items-center gap-3 px-3 text-[14.5px] text-faint">
                  <Glyph size={17} className="shrink-0" />
                  <span className="flex-1">{label}</span>
                  <span className="text-[12.5px] text-[#a9adb5]">soon</span>
                </span>
              ) : (
                <a
                  href="/app"
                  aria-current="page"
                  onClick={(e) => {
                    e.preventDefault()
                    navigate('/app')
                  }}
                  className="flex h-10 items-center gap-3 rounded-[12px] bg-paper px-3 text-[14.5px] font-semibold text-ink"
                >
                  <Glyph size={17} weight="bold" className="shrink-0 text-cobalt" />
                  {label}
                </a>
              )}
            </li>
          ))}
        </ul>
      </nav>
      <div className="mt-auto space-y-6 pb-2">
        <GraphStats ws={ws} />
        <div className="space-y-1.5 px-3 text-[13px]">
          {isMock() && <p className="text-faint">Playing a recorded answer</p>}
          <a href="/" className="text-muted transition-colors hover:text-ink">
            Back to the site
          </a>
        </div>
      </div>
    </aside>
  )
}

export default function CanonApp() {
  const [ws, setWs] = useState(savedWorkspace)
  const change = (w: Workspace) => {
    saveWorkspace(w)
    setWs(w)
  }

  return (
    <div className="flex min-h-[100dvh] gap-3 bg-page p-2 sm:p-3">
      <Rail ws={ws} onWorkspace={change} />
      <div className="flex min-w-0 flex-1 flex-col gap-2">
        <header className="flex h-12 items-center justify-between px-2 min-[900px]:hidden">
          <a href="/" className="text-ink" aria-label="Canon home">
            <Wordmark />
          </a>
          <WorkspaceSwitcher ws={ws} onChange={change} compact />
        </header>
        <div className="flex min-w-0 flex-1">
          <Ask key={ws.slug} ws={ws} />
        </div>
      </div>
    </div>
  )
}
