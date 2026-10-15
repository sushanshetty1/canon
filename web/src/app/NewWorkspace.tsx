// New workspace from GitHub: pick one of your repositories or name any you can read (public, private or an
// organisation's), then watch it read into a graph of its own.

import { ArrowRight, ArrowUpRight, FileText, GithubLogo, Kanban, NotionLogo, SlackLogo } from '@phosphor-icons/react'
import { motion, useReducedMotion } from 'motion/react'
import { useEffect, useRef, useState, type FormEvent } from 'react'
import { ApiError, connectUrl, createWorkspace, signInUrl, syncWorkspace, useJob, type Job, type Me } from './account'
import { IngestDrawing, Legend } from './IngestDrawing'
import { navigate, ROUTES } from './router'
import { RepoPicker } from './RepoPicker'
import { plural } from './text'
import { fromServer, type Workspace } from './workspaces'

/** Why a repository was refused, and the one link that fixes it: GitHub's access page for an organisation that
 * limits OAuth apps, the second GitHub step, or signing in again. */
function Refused({ error, me }: { error: Error; me: Me | null }) {
  const reason = error instanceof ApiError ? error.reason : null
  const link = error instanceof ApiError ? error.link : null
  const action =
    reason === 'org_restricted' && link
      ? { href: link, label: 'Request access on GitHub', away: true }
      : reason === 'connect' && connectUrl(me)
        ? { href: connectUrl(me)!, label: 'Connect private and organisation repositories', away: false }
        : reason === 'reauth' && signInUrl(me, '/app/new')
          ? { href: signInUrl(me, '/app/new')!, label: 'Sign in again', away: false }
          : null
  return (
    <div role="alert" className="mt-4 max-w-[680px]">
      <p className="text-[16px] leading-relaxed text-proof">{error.message}</p>
      {action && (
        <a
          href={action.href}
          {...(action.away ? { target: '_blank', rel: 'noreferrer' } : {})}
          className="mt-2 inline-flex items-center gap-1 text-[15px] font-semibold text-cobalt hover:text-cobalt-deep"
        >
          {action.label}
          {action.away ? <ArrowUpRight size={13} weight="bold" /> : <ArrowRight size={13} weight="bold" />}
        </a>
      )}
    </div>
  )
}

const ease = [0.22, 1, 0.36, 1] as const
const EXAMPLES = ['cli/cli', 'pallets/flask', 'astral-sh/ruff']

function slugFromUrl(): string | null {
  try {
    return new URLSearchParams(window.location.search).get('ws')
  } catch {
    return null
  }
}

function RepoField({ me, onCreate, busy, error }: { me: Me | null; onCreate: (repo: string) => void; busy: boolean; error: Error | null }) {
  const [value, setValue] = useState('')
  const field = useRef<HTMLInputElement>(null)
  const signedIn = !!me?.user
  const signIn = signInUrl(me, '/app/new')
  useEffect(() => {
    if (signedIn) field.current?.focus({ preventScroll: true })
  }, [signedIn])

  const submit = (e?: FormEvent) => {
    e?.preventDefault()
    if (value.trim() && signedIn && !busy) onCreate(value.trim())
  }

  return (
    <form onSubmit={submit}>
      <label htmlFor="repo" className="text-[15px] text-muted">
        A GitHub repository
      </label>
      <div className="mt-3 flex items-end gap-4 border-b-[1.5px] border-line-strong pb-4 transition-colors focus-within:border-ink">
        <input
          id="repo"
          ref={field}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          disabled={!signedIn}
          autoComplete="off"
          autoCapitalize="off"
          spellCheck={false}
          maxLength={200}
          placeholder="owner/name"
          className="display min-w-0 flex-1 bg-transparent text-[34px] leading-[1.08] text-ink caret-cobalt outline-none placeholder:text-[#b9bdc5] disabled:cursor-not-allowed sm:text-[52px] lg:text-[60px]"
        />
        <button
          type="submit"
          disabled={!value.trim() || !signedIn || busy}
          aria-label="Make the workspace"
          className="mb-1 grid size-12 shrink-0 place-items-center rounded-full bg-ink text-paper transition-[background-color,opacity,transform] duration-200 hover:bg-[#23252d] active:translate-y-px disabled:opacity-20 sm:size-14"
        >
          <ArrowRight size={20} weight="bold" />
        </button>
      </div>
      {error && <Refused error={error} me={me} />}
      {signedIn ? (
        <div className="mt-6 flex flex-col items-start gap-2.5 text-[16px] sm:flex-row sm:flex-wrap sm:items-baseline sm:gap-x-7">
          <span className="text-faint">Try</span>
          {EXAMPLES.map((r) => (
            <button
              key={r}
              type="button"
              onClick={() => setValue(r)}
              className="rounded text-left text-muted underline decoration-line-strong decoration-1 underline-offset-[5px] transition-colors hover:text-ink hover:decoration-ink focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-cobalt"
            >
              {r}
            </button>
          ))}
        </div>
      ) : (
        <div className="mt-7">
          {signIn ? (
            <a
              href={signIn}
              className="inline-flex h-12 items-center gap-2.5 rounded-full bg-ink px-6 text-[15px] font-semibold text-paper transition-colors hover:bg-[#23252d]"
            >
              <GithubLogo size={18} weight="bold" />
              {me?.signin ? 'Sign in with GitHub' : 'Sign in for development'}
            </a>
          ) : (
            <p className="text-[16px] text-muted">{me ? 'Sign-in is not set up on this server yet.' : ''}</p>
          )}
          {signIn && <p className="mt-3 text-[14.5px] text-faint">A workspace is open only to the person who makes it and the people they invite.</p>}
        </div>
      )}
    </form>
  )
}

/** What the job is doing now, in a sentence, and how far along it is. */
function Status({ job, repo }: { job: Job | null; repo: string }) {
  const reduce = useReducedMotion()
  const c = job?.counts ?? {}
  let line = 'Starting'
  let detail = ''
  if (job?.status === 'failed') {
    line = 'Stopped'
    detail = job.error ?? 'Something went wrong.'
  } else if (job?.status === 'done') {
    line = `${repo} is ready`
    detail = [plural(c.documents ?? 0, 'document'), plural(c.facts ?? 0, 'fact'), plural(c.people ?? 0, 'person', 'people')].join(', ')
    if (c.stale) detail += `. ${plural(c.stale, 'statement')} already out of date.`
  } else if (job) {
    line = job.step_label
    if (job.step === 'extract' && c.to_extract) detail = `${(c.extracted ?? 0).toLocaleString()} of ${plural(c.to_extract, 'passage')}`
    else if (c.documents) detail = `${plural(c.documents, 'document')} in the graph`
  }
  const value = job?.status === 'done' ? 1 : Math.max(0.03, job?.progress ?? 0)
  return (
    <div>
      <div role="status" aria-live="polite" className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1">
        <h2 className={`display text-[30px] sm:text-[40px] ${job?.status === 'failed' ? 'text-proof' : 'text-ink'}`}>{line}</h2>
        {detail && <p className="text-[15px] text-muted tabular-nums">{detail}</p>}
      </div>
      <div className="relative mt-4 h-px overflow-hidden bg-line" aria-hidden="true">
        <motion.div
          className="absolute inset-y-0 left-0 w-full origin-left"
          initial={false}
          animate={{ scaleX: value, backgroundColor: job?.status === 'running' ? 'var(--ink)' : 'var(--line-strong)' }}
          transition={{ duration: reduce ? 0 : 0.6, ease }}
        />
      </div>
    </div>
  )
}

export function NewWorkspace({
  me,
  own,
  onOpen,
  onCreated,
}: {
  me: Me | null
  own: Workspace[]
  onOpen: (w: Workspace) => void
  onCreated: () => void
}) {
  const [slug, setSlug] = useState<string | null>(slugFromUrl)
  const [repo, setRepo] = useState<string>('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<Error | null>(null)
  const { job, kick, setJob } = useJob(slug)
  const reduce = useReducedMotion()
  const top = useRef<HTMLDivElement>(null)

  // Opened from a link with ?ws=: the repository's name comes from the workspace list.
  const known = own.find((w) => w.slug === slug)
  const name = repo || known?.repo || known?.name || slug || ''

  const create = (text: string) => {
    setBusy(true)
    setError(null)
    createWorkspace(text).then(
      ({ workspace, job, created }) => {
        setBusy(false)
        // A workspace you already belong to (a retry, a teammate's) opens, unless it is still reading or stopped.
        if (!created && job?.status !== 'running' && job?.status !== 'failed') {
          onOpen(fromServer(workspace))
          return
        }
        setRepo(workspace.repo ?? workspace.name)
        setJob(job)
        setSlug(workspace.slug)
        window.history.replaceState(null, '', `/app/new?ws=${encodeURIComponent(workspace.slug)}`)
        onCreated()
      },
      (e: Error) => {
        setError(e)
        setBusy(false)
        top.current?.scrollIntoView({ behavior: reduce ? 'auto' : 'smooth', block: 'start' })
      },
    )
  }

  const retry = () => {
    if (!slug) return
    syncWorkspace(slug).then(
      ({ job }) => {
        setJob(job)
        kick()
      },
      (e: Error) => setError(e),
    )
  }

  const workspace: Workspace | null = slug ? (known ?? { slug, name, label: name, suggestions: [], own: true, repo: name }) : null

  return (
    <main className="slab relative flex min-w-0 flex-1 flex-col bg-paper">
      {!slug ? (
        <div className="flex flex-1 flex-col px-6 pt-10 pb-8 sm:px-12 lg:px-16">
          <div ref={top} className="mx-auto w-full max-w-[880px] scroll-mt-6 pt-[6vh] pb-16 sm:pt-[9vh]">
            <h1 className="display text-[40px] text-balance text-ink sm:text-[56px]">New workspace from GitHub</h1>
            <p className="mt-5 max-w-[580px] text-[17px] leading-relaxed text-pretty text-muted">
              Canon reads the repository&rsquo;s Markdown docs, the history of its CODEOWNERS file, recent issues and pull requests, and its
              contributors, into a graph of its own. Only you and the people you invite can open it.
            </p>
            <div className="mt-12">
              <RepoField me={me} onCreate={create} busy={busy} error={error} />
            </div>
            {me?.user && (
              <div className="mt-16">
                <RepoPicker me={me} busy={busy} onPick={create} />
              </div>
            )}
            <a
              href={`${ROUTES.connect}?new=1`}
              onClick={(e) => {
                e.preventDefault()
                navigate(`${ROUTES.connect}?new=1`)
              }}
              className="group mt-16 flex items-center gap-4 border-t border-line pt-6 text-left"
            >
              <span className="flex shrink-0 -space-x-1.5" aria-hidden="true">
                {[SlackLogo, NotionLogo, Kanban, FileText].map((I, i) => (
                  <span key={i} className="grid size-9 place-items-center rounded-full bg-paper-2 text-ink ring-2 ring-paper">
                    <I size={17} weight={i < 2 ? 'fill' : 'regular'} />
                  </span>
                ))}
              </span>
              <span className="min-w-0 flex-1">
                <span className="block text-[16px] font-semibold text-ink group-hover:text-cobalt">No repository? Start from your tools</span>
                <span className="mt-0.5 block text-[14.5px] text-muted">Slack, Notion, Linear, Jira, Confluence, or files you upload.</span>
              </span>
              <ArrowRight size={18} weight="bold" className="shrink-0 text-faint transition-transform group-hover:translate-x-0.5 group-hover:text-cobalt" />
            </a>
          </div>
        </div>
      ) : (
        <motion.div
          className="mx-auto flex w-full max-w-[1080px] flex-1 flex-col px-5 pt-8 pb-10 sm:px-12 sm:pt-12"
          initial={reduce ? false : { opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, ease }}
        >
          <p className="text-[15px] text-muted">
            New workspace from{' '}
            <a href={`https://github.com/${name}`} target="_blank" rel="noreferrer" className="font-semibold text-ink hover:text-cobalt">
              {name}
            </a>
          </p>
          <div className="mt-8 sm:mt-10">
            <IngestDrawing job={job} repo={name} />
          </div>
          <div className="mt-8 sm:mt-10">
            <Status job={job} repo={name} />
          </div>
          <div className="mt-6 flex flex-col gap-6 sm:flex-row sm:items-center sm:justify-between">
            {job?.status === 'done' && workspace ? (
              <button
                type="button"
                onClick={() => onOpen(workspace)}
                className="inline-flex h-12 w-fit items-center gap-2.5 rounded-full bg-ink px-6 text-[15px] font-semibold text-paper transition-colors hover:bg-[#23252d]"
              >
                Ask {name} a question
                <ArrowRight size={17} weight="bold" />
              </button>
            ) : job?.status === 'failed' ? (
              <button type="button" onClick={retry} className="w-fit text-[15px] font-semibold text-cobalt hover:text-cobalt-deep">
                Try again
              </button>
            ) : (
              <p className="text-[14.5px] text-faint">This runs on the server. You can leave and come back.</p>
            )}
            <Legend />
          </div>
          {error && <Refused error={error} me={me} />}
        </motion.div>
      )}
    </main>
  )
}
