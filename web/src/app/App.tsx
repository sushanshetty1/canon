// The Canon app: a slim rail on the page, and the screen on a sheet of paper beside it.

import { ArrowsClockwise, Bus, CaretUpDown, Check, ClockCounterClockwise, GithubLogo, Plus, Question, Signpost, Tray, UsersThree, Wrench, type Icon } from '@phosphor-icons/react'
import { AnimatePresence, motion } from 'motion/react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { Wordmark } from '../ui'
import { ago, listWorkspaces, signInUrl, signOut, syncWorkspace, useJob, useMe, type Me } from './account'
import { isMock, stats as getStats, type Stats } from './api'
import { Ask } from './Ask'
import { BusFactor } from './BusFactor'
import { CatchUp } from './CatchUp'
import { Decisions } from './Decisions'
import { FixQueue } from './FixQueue'
import { NewWorkspace } from './NewWorkspace'
import { Sources } from './Sources'
import { navigate, ROUTES, screenOf, usePath, type Screen } from './router'
import { plural } from './text'
import { WhoKnows } from './WhoKnows'
import { fromServer, saveWorkspace, savedWorkspace, WORKSPACES, type Workspace } from './workspaces'
import './app.css'

const NAV: { label: string; icon: Icon; screen?: Screen; soon?: boolean }[] = [
  { label: 'Ask', icon: Question, screen: 'ask' },
  { label: 'Who knows', icon: UsersThree, screen: 'whoKnows' },
  { label: 'Bus factor', icon: Bus, screen: 'busFactor' },
  { label: 'Decisions', icon: Signpost, screen: 'decisions' },
  { label: 'Catch me up', icon: ClockCounterClockwise, screen: 'catchUp' },
  { label: 'Fix queue', icon: Wrench, screen: 'fixQueue' },
  { label: 'Sources', icon: Tray, screen: 'sources' },
]

type Lists = { public: Workspace[]; own: Workspace[] }

function useWorkspaces(signedIn: string | null) {
  const [lists, setLists] = useState<Lists>({ public: WORKSPACES, own: [] })
  const load = useCallback((signal?: AbortSignal) => {
    listWorkspaces(signal).then(
      (r) => setLists({ public: r.public.map(fromServer), own: r.own.map(fromServer) }),
      () => undefined, // the static public list stands in
    )
  }, [])
  useEffect(() => {
    const ctrl = new AbortController()
    load(ctrl.signal)
    return () => ctrl.abort()
  }, [load, signedIn])
  return { lists, reload: () => load() }
}

function MenuItem({ w, current, onPick }: { w: Workspace; current: boolean; onPick: () => void }) {
  return (
    <li role="option" aria-selected={current}>
      <button
        type="button"
        onClick={onPick}
        className="flex h-10 w-full items-center justify-between gap-3 rounded-[11px] px-3 text-left text-[14.5px] font-medium text-ink hover:bg-paper-2 focus-visible:bg-paper-2 focus-visible:outline-none"
      >
        <span className="truncate">{w.label}</span>
        {current && <Check size={14} weight="bold" className="shrink-0 text-cobalt" />}
      </button>
    </li>
  )
}

function WorkspaceSwitcher({
  ws,
  lists,
  me,
  onChange,
  compact = false,
}: {
  ws: Workspace
  lists: Lists
  me: Me | null
  onChange: (w: Workspace) => void
  compact?: boolean
}) {
  const [open, setOpen] = useState(false)
  const root = useRef<HTMLDivElement>(null)
  const path = usePath()
  const creating = path === '/app/new'

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

  const pick = (w: Workspace) => {
    setOpen(false)
    onChange(w)
  }

  return (
    <div ref={root} className="relative">
      <button
        type="button"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={`Workspace: ${creating ? 'new workspace' : ws.label}`}
        onClick={() => setOpen((o) => !o)}
        className={`flex items-center justify-between gap-2 rounded-[14px] bg-paper text-left text-[14.5px] font-semibold tracking-[-0.01em] text-ink transition-shadow hover:shadow-[inset_0_0_0_1.5px_var(--line-strong)] focus-visible:outline-2 focus-visible:outline-cobalt ${compact ? 'h-10 max-w-[200px] px-3.5' : 'h-12 w-full px-4'}`}
      >
        <span className="truncate">{creating ? 'New workspace' : ws.label}</span>
        <CaretUpDown size={15} weight="bold" className="shrink-0 text-faint" />
      </button>
      <AnimatePresence>
        {open && (
          <motion.div
            className={`absolute top-full z-30 mt-2 w-[260px] rounded-[16px] bg-paper p-1.5 shadow-[0_18px_50px_-18px_rgb(13_14_18/0.35),0_0_0_1px_var(--line)] ${compact ? 'right-0' : 'left-0'}`}
            initial={{ opacity: 0, y: -4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            transition={{ duration: 0.16 }}
          >
            <p className="px-3 pt-2 pb-1 text-[12.5px] text-faint">Public</p>
            <ul role="listbox" aria-label="Public workspaces">
              {lists.public.map((w) => (
                <MenuItem key={w.slug} w={w} current={!creating && w.slug === ws.slug} onPick={() => pick(w)} />
              ))}
            </ul>
            {lists.own.length > 0 && (
              <>
                <p className="px-3 pt-3 pb-1 text-[12.5px] text-faint">Yours</p>
                <ul role="listbox" aria-label="Your workspaces">
                  {lists.own.map((w) => (
                    <MenuItem key={w.slug} w={w} current={!creating && w.slug === ws.slug} onPick={() => pick(w)} />
                  ))}
                </ul>
              </>
            )}
            <div className="mt-1.5 border-t border-line pt-1.5">
              <button
                type="button"
                onClick={() => {
                  setOpen(false)
                  navigate('/app/new')
                }}
                className="flex h-10 w-full items-center gap-2.5 rounded-[11px] px-3 text-left text-[14.5px] font-semibold text-cobalt hover:bg-paper-2 focus-visible:bg-paper-2 focus-visible:outline-none"
              >
                <Plus size={15} weight="bold" />
                New workspace from GitHub
              </button>
            </div>
            {compact && (
              <div className="mt-1.5 border-t border-line px-3 pt-3 pb-2">
                <Account me={me} />
              </div>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

/** What is in the workspace's graph, in the colours of the marks. */
function GraphStats({ ws, version }: { ws: Workspace; version: number }) {
  const [state, setState] = useState<{ key: string; stats: Stats | null } | null>(null)
  const key = `${ws.slug}:${version}`
  useEffect(() => {
    const ctrl = new AbortController()
    getStats(ws.slug, ctrl.signal).then(
      (stats) => setState({ key, stats }),
      (e: Error) => e.name !== 'AbortError' && setState({ key, stats: null }),
    )
    return () => ctrl.abort()
  }, [ws.slug, key])

  if (!state || state.key.split(':')[0] !== ws.slug) return <div className="h-[104px]" aria-hidden="true" />
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

/** For a workspace of your own: when it last read its repository, and a way to read what changed since. */
function Sync({ ws, onSynced }: { ws: Workspace; onSynced: () => void }) {
  const { job, kick, setJob } = useJob(ws.slug)
  const [error, setError] = useState<string | null>(null)
  const running = job?.status === 'running'
  const wasRunning = useRef(false)
  useEffect(() => {
    if (wasRunning.current && job?.status === 'done') onSynced()
    wasRunning.current = running
  }, [job?.status, running, onSynced])

  const start = () => {
    setError(null)
    syncWorkspace(ws.slug).then(
      ({ job }) => {
        setJob(job)
        kick()
      },
      (e: Error) => setError(e.message),
    )
  }

  return (
    <div className="px-3 text-[13px]">
      {running ? (
        <div>
          <p className="text-ink">{job.kind === 'create' ? 'Reading' : job.kind === 'upload' ? 'Reading an export' : 'Syncing'}: {job.step_label.toLowerCase()}</p>
          <div className="relative mt-2 h-[3px] overflow-hidden rounded-full bg-line" aria-hidden="true">
            <motion.div className="absolute inset-y-0 left-0 w-full origin-left rounded-full bg-ink" initial={false} animate={{ scaleX: Math.max(0.04, job.progress) }} />
          </div>
        </div>
      ) : (
        <div className="space-y-1.5">
          <p className={job?.status === 'failed' ? 'text-proof' : 'text-faint'}>
            {job?.status === 'failed' ? 'The last sync stopped' : job?.finished_at ? `Read from GitHub ${ago(job.finished_at)}` : ''}
          </p>
          <button type="button" onClick={start} className="inline-flex items-center gap-1.5 font-semibold text-cobalt hover:text-cobalt-deep">
            <ArrowsClockwise size={13} weight="bold" />
            Sync now
          </button>
        </div>
      )}
      {error && <p className="mt-2 text-proof">{error}</p>}
    </div>
  )
}

/** Who is signed in, or a way to sign in. */
function Account({ me }: { me: Me | null }) {
  const [failed] = useState(() => new URLSearchParams(window.location.search).get('signin') === 'failed')
  if (!me) return <div className="h-10" aria-hidden="true" />
  if (me.user) {
    const out = () => signOut().finally(() => window.location.assign('/app'))
    return (
      <div className="flex items-center gap-3">
        <span className="grid size-8 shrink-0 place-items-center rounded-full bg-cobalt text-[13px] font-semibold text-paper uppercase" aria-hidden="true">
          {me.user.login.slice(0, 1)}
        </span>
        <div className="min-w-0 flex-1 leading-tight">
          <p className="truncate text-[14px] font-semibold text-ink">{me.user.login}</p>
          <p className="text-[12.5px] text-faint">{me.user.dev ? 'Dev sign-in' : 'GitHub'}</p>
        </div>
        <button type="button" onClick={out} className="text-[13px] text-muted transition-colors hover:text-ink">
          Sign out
        </button>
      </div>
    )
  }
  const url = signInUrl(me)
  if (!url) return null
  return (
    <div>
      {failed && <p className="mb-2 text-[13px] text-proof">Sign-in did not finish. Try again.</p>}
      <a
        href={url}
        className="flex h-10 items-center justify-center gap-2 rounded-full bg-ink px-4 text-[14px] font-semibold text-paper transition-colors hover:bg-[#23252d]"
      >
        <GithubLogo size={16} weight="bold" />
        {me.signin ? 'Sign in with GitHub' : 'Dev sign-in'}
      </a>
    </div>
  )
}

function Rail({
  ws,
  screen,
  lists,
  me,
  creating,
  version,
  onWorkspace,
  onSynced,
}: {
  ws: Workspace
  screen: Screen
  lists: Lists
  me: Me | null
  creating: boolean
  version: number
  onWorkspace: (w: Workspace) => void
  onSynced: () => void
}) {
  const own = !creating && lists.own.some((w) => w.slug === ws.slug)
  return (
    <aside className="sticky top-3 z-20 hidden h-[calc(100dvh-24px)] w-[228px] shrink-0 flex-col min-[900px]:flex">
      <a href="/" className="flex h-12 items-center px-3 text-ink" aria-label="Canon home">
        <Wordmark />
      </a>
      <div className="mt-5">
        <WorkspaceSwitcher ws={ws} lists={lists} me={me} onChange={onWorkspace} />
      </div>
      <nav aria-label="Canon" className="mt-6">
        <ul className="space-y-0.5">
          {NAV.map(({ label, icon: Glyph, screen: to, soon }) => (
            <li key={label}>
              {soon || !to ? (
                <span aria-disabled="true" className="flex h-10 cursor-default items-center gap-3 px-3 text-[14.5px] text-faint">
                  <Glyph size={17} className="shrink-0" />
                  <span className="flex-1">{label}</span>
                  <span className="text-[12.5px] text-[#a9adb5]">soon</span>
                </span>
              ) : (
                <a
                  href={ROUTES[to]}
                  aria-current={!creating && to === screen ? 'page' : undefined}
                  onClick={(e) => {
                    e.preventDefault()
                    navigate(ROUTES[to])
                  }}
                  className={`flex h-10 items-center gap-3 rounded-[12px] px-3 text-[14.5px] transition-colors ${!creating && to === screen ? 'bg-paper font-semibold text-ink' : 'text-muted hover:bg-paper/60 hover:text-ink'}`}
                >
                  <Glyph size={17} weight={!creating && to === screen ? 'bold' : 'regular'} className={`shrink-0 ${!creating && to === screen ? 'text-cobalt' : ''}`} />
                  {label}
                </a>
              )}
            </li>
          ))}
        </ul>
      </nav>
      <div className="mt-auto space-y-6 pb-2">
        {!creating && <GraphStats ws={ws} version={version} />}
        {own && <Sync ws={ws} onSynced={onSynced} />}
        <div className="space-y-4 px-3">
          <Account me={me} />
          <div className="space-y-1.5 text-[13px]">
            {isMock() && <p className="text-faint">Playing a recorded answer</p>}
            <a href="/" className="text-muted transition-colors hover:text-ink">
              Back to the site
            </a>
          </div>
        </div>
      </div>
    </aside>
  )
}

/** The screens on a narrow window, where the rail is hidden. */
function MobileNav({ screen }: { screen: Screen }) {
  return (
    <nav aria-label="Canon" className="-mt-1 px-1 min-[900px]:hidden">
      <ul className="flex gap-1 overflow-x-auto">
        {NAV.filter((n) => n.screen && !n.soon).map(({ label, screen: to }) => (
          <li key={label} className="shrink-0">
            <a
              href={ROUTES[to!]}
              aria-current={to === screen ? 'page' : undefined}
              onClick={(e) => {
                e.preventDefault()
                navigate(ROUTES[to!])
              }}
              className={`inline-flex h-9 items-center rounded-full px-3.5 text-[14px] transition-colors ${to === screen ? 'bg-paper font-semibold text-ink' : 'text-muted hover:text-ink'}`}
            >
              {label}
            </a>
          </li>
        ))}
      </ul>
    </nav>
  )
}

export default function CanonApp() {
  const screen = screenOf(usePath())
  const creating = screen === 'newWorkspace'
  const { me } = useMe()
  const { lists, reload } = useWorkspaces(me?.user?.login ?? null)
  const [ws, setWs] = useState(savedWorkspace)
  const [version, setVersion] = useState(0)

  // A saved workspace that is no longer listed (signed out, or deleted) falls back to the first public one.
  useEffect(() => {
    if (!me || !ws.own) return
    const listed = lists.own.find((w) => w.slug === ws.slug)
    if (listed && listed !== ws) setWs(listed)
  }, [lists, me, ws])

  const change = (w: Workspace) => {
    saveWorkspace(w)
    setWs(w)
    if (creating) navigate('/app')
  }
  const synced = useCallback(() => setVersion((v) => v + 1), [])

  return (
    <div className="flex min-h-[100dvh] gap-3 bg-page p-2 sm:p-3">
      <Rail ws={ws} screen={screen} lists={lists} me={me} creating={creating} version={version} onWorkspace={change} onSynced={synced} />
      <div className="flex min-w-0 flex-1 flex-col gap-2">
        <header className="flex h-12 items-center justify-between px-2 min-[900px]:hidden">
          <a href="/" className="text-ink" aria-label="Canon home">
            <Wordmark />
          </a>
          <WorkspaceSwitcher ws={ws} lists={lists} me={me} onChange={change} compact />
        </header>
        <MobileNav screen={screen} />
        <div className="flex min-w-0 flex-1">
          {creating && (
            <NewWorkspace
              me={me}
              own={lists.own}
              onCreated={reload}
              onOpen={(w) => {
                reload()
                change(w)
              }}
            />
          )}
          {screen === 'ask' && <Ask key={ws.slug} ws={ws} />}
          {screen === 'whoKnows' && <WhoKnows key={ws.slug} ws={ws} />}
          {screen === 'busFactor' && <BusFactor key={ws.slug} ws={ws} />}
          {screen === 'decisions' && <Decisions key={ws.slug} ws={ws} />}
          {screen === 'catchUp' && <CatchUp key={ws.slug} ws={ws} />}
          {screen === 'fixQueue' && <FixQueue key={ws.slug} ws={ws} />}
          {screen === 'sources' && <Sources key={ws.slug} ws={ws} own={lists.own.some((w) => w.slug === ws.slug)} />}
        </div>
      </div>
    </div>
  )
}
