// The fix queue: every page that says something the graph knows has changed, drawn as a proof sheet. The stale
// line is struck in proof red, the checked correction is written above it in cobalt, the newer fact it comes from
// sits beneath, and the margin says who it goes to and why. A person approves it (Canon files the issue) or
// dismisses it with a reason.

import { ArrowUpRight, Check } from '@phosphor-icons/react'
import { AnimatePresence, motion, useReducedMotion } from 'motion/react'
import { useEffect, useMemo, useRef, useState, type FormEvent, type ReactNode } from 'react'
import { approveFix, dismissFix, fixes as getFixes, type Fix, type FixFilter, type FixList, type Routed } from './api'
import { ease } from './Answer'
import { formatDate, kindLabel, plural } from './text'
import type { Workspace } from './workspaces'

// --- Page text --------------------------------------------------------------------------------------

const TOKEN = /(`[^`]+`)|(\*\*[^*]+\*\*)|(~~.+?~~)|(!?\[[^\]]*\]\([^)\s]+\))/g

/** The bits of Markdown pages and issues use, inline: code, bold, struck text and links. */
function Inline({ md, links = false }: { md: string; links?: boolean }) {
  const out: ReactNode[] = []
  let last = 0
  for (const m of md.matchAll(TOKEN)) {
    const at = m.index ?? 0
    if (at > last) out.push(md.slice(last, at))
    const t = m[0]
    if (m[1]) out.push(<code key={at} className="rounded-[4px] bg-paper-2 px-1 font-mono text-[0.84em]">{t.slice(1, -1)}</code>)
    else if (m[2]) out.push(<strong key={at} className="font-semibold"><Inline md={t.slice(2, -2)} links={links} /></strong>)
    else if (m[3]) out.push(<s key={at} className="decoration-proof decoration-2"><Inline md={t.slice(2, -2)} links={links} /></s>)
    else {
      const [, label, href] = /^!?\[([^\]]*)\]\(([^)\s]+)\)$/.exec(t) ?? []
      out.push(
        links && !t.startsWith('!') ? (
          <a key={at} href={href} target="_blank" rel="noreferrer" className="text-cobalt underline decoration-cobalt/30 underline-offset-[3px] hover:decoration-cobalt">
            {label}
          </a>
        ) : (
          label
        ),
      )
    }
    last = at + t.length
  }
  if (last < md.length) out.push(md.slice(last))
  return <>{out}</>
}

const bare = (line: string) => line.replace(/^\s*(?:[-*+]\s+|#{1,6}\s+|>\s*)/, '')

function clip(text: string, max: number, from: 'start' | 'end'): string {
  if (text.length <= max) return text
  if (from === 'end') return text.slice(0, text.lastIndexOf(' ', max)) + ' …'
  const cut = text.slice(text.length - max)
  return '… ' + cut.slice(cut.indexOf(' ') + 1)
}

/** The line in its passage: a heading if the passage has one, and one sentence either side of it. */
function around(passage: string, old: string) {
  const at = passage.indexOf(old)
  if (at === -1) return { heading: '', before: '', after: '' }
  let before = passage.slice(0, at)
  let heading = ''
  const firstBreak = before.indexOf('\n')
  if (firstBreak > 0 && firstBreak < 90 && !/[.!?]$/.test(before.slice(0, firstBreak).trim())) heading = bare(before.slice(0, firstBreak).trim())
  before = bare(before.slice(before.lastIndexOf('\n') + 1)).trimEnd()
  const ends = [...before.matchAll(/[.!?]["')\]]?\s+/g)].map((m) => (m.index ?? 0) + m[0].length)
  if (ends.length) before = '… ' + before.slice(ends[ends.length - 1])
  let after = passage.slice(at + old.length)
  const lineEnd = after.indexOf('\n')
  if (lineEnd !== -1) after = after.slice(0, lineEnd)
  after = after.trimStart()
  const stop = /[.!?]["')\]]?(\s|$)/.exec(after)
  if (stop && stop.index + 1 < after.trimEnd().length - 1) after = after.slice(0, stop.index + stop[0].trimEnd().length) + ' …'
  return { heading, before: clip(before, 220, 'start'), after: clip(after, 220, 'end') }
}

// --- Marks ------------------------------------------------------------------------------------------

/** The proofreader's caret, pointing up from the struck line to the correction written above it. */
function Caret() {
  return (
    <svg viewBox="0 0 14 12" className="mt-[9px] h-[12px] w-[14px] text-cobalt" aria-hidden="true">
      <path d="M1.5 10.5 7 2.2 12.5 10.5" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

function Proof({ fix }: { fix: Fix }) {
  const reduce = useReducedMotion()
  const passage = fix.passage.text ?? ''
  const old = fix.old ?? fix.stale[0]?.fact ?? ''
  const { heading, before, after } = fix.old ? around(passage, fix.old) : { heading: '', before: '', after: '' }
  const row = 'col-start-2 min-w-0'
  return (
    <div className="ruled grid grid-cols-[22px_minmax(0,1fr)] text-[17px] leading-[32px] sm:grid-cols-[30px_minmax(0,1fr)] sm:text-[18px]">
      {heading && <p className={`${row} text-[14px] font-semibold text-muted`}>{heading}</p>}
      {before && (
        <p className={`${row} text-muted`}>
          <Inline md={before} />
        </p>
      )}
      {fix.new ? (
        <motion.p
          className={`${row} font-medium text-cobalt`}
          initial={reduce ? false : { opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, delay: 0.15, ease }}
        >
          <span className="sr-only">Correction: </span>
          <Inline md={fix.new} />
        </motion.p>
      ) : (
        <p className={`${row} text-[15px] text-muted`}>No correction passed the check, so there is nothing to file. Fix the page by hand, or dismiss this.</p>
      )}
      <span className="col-start-1 row-span-1">{fix.new && <Caret />}</span>
      {fix.old ? (
        <p className="min-w-0 text-ink/65">
          <span className="sr-only">The page says: </span>
          <span className="line-through decoration-proof decoration-2">
            <Inline md={bare(old)} />
          </span>
        </p>
      ) : (
        <p className="min-w-0 text-ink/80">
          <span className="text-[15px] text-muted">The graph read this page as saying: </span>
          <span className="underline decoration-proof decoration-wavy decoration-1 underline-offset-[6px]">{old}</span>
        </p>
      )}
      {after && (
        <p className={`${row} text-muted`}>
          <Inline md={after} />
        </p>
      )}
    </div>
  )
}

function Evidence({ fix }: { fix: Fix }) {
  if (!fix.evidence.length) return null
  return (
    <div className="mt-7 space-y-4">
      {fix.evidence.map((e) => (
        <div key={e.fact_id} className="grid grid-cols-[22px_minmax(0,1fr)] sm:grid-cols-[30px_minmax(0,1fr)]">
          <span className="mt-[10px] h-[5px] w-3.5 rounded-full bg-cobalt" aria-hidden="true" />
          <div className="min-w-0">
            <p className="text-[13.5px] font-semibold text-cobalt">
              Holds now, per the {kindLabel(e.kind).toLowerCase()}
              {e.valid_from && <span className="font-normal text-muted"> since {formatDate(e.valid_from)}</span>}
            </p>
            <p className="mt-1.5 text-[15.5px] leading-[1.6] text-ink">
              <mark className="marker text-ink">{e.fact}</mark>
            </p>
            {e.url && (
              <a
                href={e.url}
                target="_blank"
                rel="noreferrer"
                className="mt-1.5 inline-flex max-w-full items-center gap-1 rounded text-[13.5px] text-muted transition-colors hover:text-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cobalt"
              >
                <span className="truncate">{e.title}</span>
                <ArrowUpRight size={12} weight="bold" className="shrink-0" />
              </a>
            )}
          </div>
        </div>
      ))}
    </div>
  )
}

// A GitHub handle has no colon; people from other sources (`slack:...`, `id:...`) and named-only people do.
const handleLink = (handle: string) => !handle.includes(':')

function Owner({ fix }: { fix: Fix }) {
  const teams = fix.routed.filter((r) => r.kind === 'team')
  const alone = fix.routed.filter((r) => r.kind === 'person' && !r.team)
  const leads = (t: Routed) => fix.routed.filter((r) => r.kind === 'person' && r.team === t.key)
  return (
    <div>
      <p className="text-[13.5px] font-semibold text-muted">Goes to</p>
      <ul className="mt-2 space-y-2.5">
        {teams.map((t) => (
          <li key={t.key}>
            <p className="text-[18px] leading-snug font-semibold tracking-[-0.01em] text-ink">{t.name}</p>
            {leads(t).map((p) => (
              <p key={p.key} className="text-[14.5px] text-muted">
                Led by{' '}
                {handleLink(p.key) ? (
                  <a href={`https://github.com/${p.key}`} target="_blank" rel="noreferrer" className="text-cobalt hover:text-cobalt-deep">
                    {p.key}
                  </a>
                ) : (
                  p.name
                )}
              </p>
            ))}
          </li>
        ))}
        {alone.map((p) => (
          <li key={p.key}>
            <p className="text-[18px] leading-snug font-semibold tracking-[-0.01em] text-ink">{p.name}</p>
            {handleLink(p.key) && p.name !== p.key && <p className="text-[14.5px] text-muted">{p.key}</p>}
          </li>
        ))}
        {!fix.routed.length && <li className="text-[15px] text-muted">Nobody in the graph owns this page.</li>}
      </ul>
      {fix.reason && <p className="mt-3 text-[14px] leading-relaxed text-muted">{fix.reason}</p>}
    </div>
  )
}

// --- The issue --------------------------------------------------------------------------------------

/** The issue body as GitHub would show it: quotes, lists, rules and the inline marks. */
function IssueBody({ body }: { body: string }) {
  const blocks: ReactNode[] = []
  let list: string[] = []
  const flush = (key: number) => {
    if (!list.length) return
    blocks.push(
      <ul key={`l${key}`} className="list-disc space-y-1 pl-5">
        {list.map((l, i) => (
          <li key={i}>
            <Inline md={l} links />
          </li>
        ))}
      </ul>,
    )
    list = []
  }
  body.split('\n').forEach((line, i) => {
    if (line.startsWith('- ')) return void list.push(line.slice(2))
    flush(i)
    if (!line.trim()) return
    if (line.trim() === '---') blocks.push(<hr key={i} className="border-line" />)
    else if (line.startsWith('> '))
      blocks.push(
        <blockquote key={i} className="border-l-[3px] border-line-strong pl-3 text-ink">
          <Inline md={line.slice(2)} links />
        </blockquote>,
      )
    else if (/^_.*_$/.test(line)) blocks.push(<p key={i} className="text-muted italic">{line.slice(1, -1)}</p>)
    else
      blocks.push(
        <p key={i}>
          <Inline md={line} links />
        </p>,
      )
  })
  flush(-1)
  return <div className="space-y-3 text-[14.5px] leading-[1.6] text-ink">{blocks}</div>
}

function IssuePreview({ fix }: { fix: Fix }) {
  const issue = fix.issue
  return (
    <div className="mt-8 rounded-[20px] bg-paper-2 p-5 sm:p-7">
      <p className="text-[13.5px] text-muted">
        {issue.dry_run ? (
          <>
            The issue Canon would file in <span className="font-semibold text-ink">{issue.repo}</span>. Dry run: nothing was sent to GitHub.
          </>
        ) : (
          <>
            Filed in <span className="font-semibold text-ink">{issue.repo}</span>
          </>
        )}
      </p>
      <h4 className="mt-3 text-[18px] leading-snug font-semibold tracking-[-0.01em] text-ink">{issue.title}</h4>
      <div className="mt-4 border-t border-line pt-4">{issue.body && <IssueBody body={issue.body} />}</div>
    </div>
  )
}

// --- Actions ----------------------------------------------------------------------------------------

const REPO_KEY = 'canon-fix-repo'
const REPO = /^[A-Za-z0-9][A-Za-z0-9-]*\/[A-Za-z0-9._-]+$/

function savedRepo(): string {
  try {
    return window.localStorage.getItem(REPO_KEY) ?? ''
  } catch {
    return ''
  }
}

const primary =
  'inline-flex h-10 items-center justify-center gap-2 rounded-full bg-ink px-4 text-[14px] font-semibold whitespace-nowrap text-paper transition-[background-color,opacity] hover:bg-[#23252d] active:translate-y-px disabled:opacity-40 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cobalt'
const secondary =
  'inline-flex h-10 items-center justify-center rounded-full px-4 text-[14px] font-semibold whitespace-nowrap text-ink shadow-[inset_0_0_0_1.5px_var(--line-strong)] transition-shadow hover:shadow-[inset_0_0_0_1.5px_var(--ink)] disabled:opacity-40 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cobalt'
const field =
  'w-full rounded-[12px] bg-paper px-3.5 text-[15px] text-ink shadow-[inset_0_0_0_1.5px_var(--line-strong)] outline-none transition-shadow placeholder:text-faint focus:shadow-[inset_0_0_0_1.5px_var(--cobalt)]'

type Mode = 'idle' | 'approve' | 'dismiss'

function Actions({ ws, fix, dryRun, onDone }: { ws: string; fix: Fix; dryRun: boolean; onDone: (f: Fix, said: string) => void }) {
  const [mode, setMode] = useState<Mode>('idle')
  const [repo, setRepo] = useState(savedRepo)
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const open = (m: Mode) => {
    setError(null)
    setMode(m)
  }

  const run = async (e: FormEvent, act: () => Promise<Fix>, said: (f: Fix) => string) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const f = await act()
      onDone(f, said(f))
    } catch (err) {
      setError((err as Error).message)
      setBusy(false)
    }
  }

  const file = (e: FormEvent) =>
    run(
      e,
      () => {
        try {
          window.localStorage.setItem(REPO_KEY, repo.trim())
        } catch {
          // private window
        }
        return approveFix(ws, fix.id, repo.trim())
      },
      (f) => (f.issue.dry_run ? `Dry run: the issue for ${f.page.title} is shown below.` : `Filed in ${f.issue.repo}.`),
    )
  const drop = (e: FormEvent) => run(e, () => dismissFix(ws, fix.id, reason.trim()), () => 'Dismissed.')

  if (mode === 'approve')
    return (
      <form onSubmit={file} className="space-y-3">
        <label htmlFor={`repo-${fix.id}`} className="block text-[13.5px] font-semibold text-ink">
          File an issue in
        </label>
        <input
          id={`repo-${fix.id}`}
          autoFocus
          value={repo}
          onChange={(e) => setRepo(e.target.value)}
          placeholder="owner/repository"
          autoComplete="off"
          spellCheck={false}
          className={`${field} h-11`}
        />
        <p className="text-[13px] leading-relaxed text-muted">
          A repository you can push to, never PostHog's.{dryRun && ' Dry run is on: you will see the issue, and nothing reaches GitHub.'}
        </p>
        {error && <p className="text-[13.5px] leading-relaxed text-proof">{error}</p>}
        <div className="flex flex-wrap gap-2">
          <button type="submit" disabled={busy || !REPO.test(repo.trim())} className={primary}>
            {busy ? 'Filing' : dryRun ? 'Show the issue' : 'File the issue'}
          </button>
          <button type="button" onClick={() => open('idle')} disabled={busy} className={secondary}>
            Cancel
          </button>
        </div>
      </form>
    )

  if (mode === 'dismiss')
    return (
      <form onSubmit={drop} className="space-y-3">
        <label htmlFor={`why-${fix.id}`} className="block text-[13.5px] font-semibold text-ink">
          Why is this not a fix?
        </label>
        <textarea
          id={`why-${fix.id}`}
          autoFocus
          rows={3}
          maxLength={500}
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          placeholder="The page is being retired"
          className={`${field} resize-none py-2.5 leading-snug`}
        />
        {error && <p className="text-[13.5px] leading-relaxed text-proof">{error}</p>}
        <div className="flex flex-wrap gap-2">
          <button type="submit" disabled={busy || !reason.trim()} className={primary}>
            {busy ? 'Dismissing' : 'Dismiss'}
          </button>
          <button type="button" onClick={() => open('idle')} disabled={busy} className={secondary}>
            Cancel
          </button>
        </div>
      </form>
    )

  return (
    <div className="flex flex-wrap gap-2">
      {fix.new && (
        <button type="button" onClick={() => open('approve')} className={primary}>
          Approve and file
        </button>
      )}
      <button type="button" onClick={() => open('dismiss')} className={secondary}>
        Dismiss
      </button>
      {fix.issue.error && <p className="w-full pt-1 text-[13.5px] leading-relaxed text-proof">{fix.issue.error}</p>}
    </div>
  )
}

function Outcome({ fix }: { fix: Fix }) {
  if (fix.status === 'filed') {
    const real = !fix.issue.dry_run && fix.issue.url
    return (
      <div>
        <p className="flex items-center gap-2 text-[15px] font-semibold text-cobalt">
          <Check size={15} weight="bold" /> {fix.issue.dry_run ? 'Approved, dry run' : 'Filed'}
        </p>
        <p className="mt-1 text-[14px] leading-relaxed text-muted">
          {fix.approved_by && <>By {fix.approved_by}, </>}
          {formatDate(fix.issue.filed_at)}.{' '}
          {real ? (
            <a href={fix.issue.url!} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 font-semibold text-cobalt hover:text-cobalt-deep">
              Open the issue in {fix.issue.repo} <ArrowUpRight size={12} weight="bold" />
            </a>
          ) : (
            <>The issue for {fix.issue.repo} is below.</>
          )}
        </p>
      </div>
    )
  }
  if (fix.status === 'dismissed')
    return (
      <div>
        <p className="text-[15px] font-semibold text-ink">Dismissed</p>
        <p className="mt-1 text-[14px] text-muted">
          {fix.dismissed.by && <>By {fix.dismissed.by}, </>}
          {formatDate(fix.dismissed.at)}
        </p>
        {fix.dismissed.reason && <p className="mt-2 border-l-2 border-line-strong pl-3 text-[14.5px] leading-relaxed text-ink">{fix.dismissed.reason}</p>}
      </div>
    )
  return <p className="text-[15px] font-semibold text-ink">The page no longer says this.</p>
}

// --- The sheet --------------------------------------------------------------------------------------

function FixRow({ ws, fix, dryRun, first, onDone }: { ws: string; fix: Fix; dryRun: boolean; first: boolean; onDone: (f: Fix, said: string) => void }) {
  const live = fix.status === 'open' || fix.status === 'approved'
  return (
    <article className={first ? 'mt-8' : 'mt-10 border-t border-line pt-10'} aria-label={`Out of date line on ${fix.page.title}`}>
      <div className="grid gap-x-12 gap-y-8 min-[1100px]:grid-cols-[minmax(0,1fr)_300px]">
        <div className="min-w-0">
          <Proof fix={fix} />
          <Evidence fix={fix} />
        </div>
        <aside className="min-w-0 space-y-6 border-t border-line pt-7 min-[1100px]:border-t-0 min-[1100px]:border-l min-[1100px]:pt-0 min-[1100px]:pl-8">
          <Owner fix={fix} />
          <AnimatePresence mode="wait" initial={false}>
            <motion.div key={fix.status} initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} transition={{ duration: 0.25, ease }}>
              {live ? <Actions ws={ws} fix={fix} dryRun={dryRun} onDone={onDone} /> : <Outcome fix={fix} />}
            </motion.div>
          </AnimatePresence>
        </aside>
      </div>
      {fix.status === 'filed' && fix.issue.body && <IssuePreview fix={fix} />}
    </article>
  )
}

const LINE_WORD: Record<FixFilter, string> = { open: 'out of date', filed: 'filed', dismissed: 'dismissed' }

function PageSheet({ ws, fixes, filter, dryRun, onDone }: { ws: string; fixes: Fix[]; filter: FixFilter; dryRun: boolean; onDone: (f: Fix, said: string) => void }) {
  const page = fixes[0].page
  const reduce = useReducedMotion()
  return (
    <motion.section
      className="slab bg-paper px-6 pt-8 pb-10 sm:px-10 sm:pt-10 lg:px-12"
      aria-label={page.title ?? 'Page'}
      initial={reduce ? false : { opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5, ease }}
    >
      <header className="flex flex-wrap items-end justify-between gap-x-8 gap-y-3">
        <div className="min-w-0">
          <p className="text-[13.5px] text-muted">
            {kindLabel(page.kind)}
            {page.updated_at && <> · edited {formatDate(page.updated_at)}</>}
            {page.author && !page.author.includes(':') && <> by {page.author}</>}
          </p>
          <h2 className="display mt-2 text-[30px] text-balance text-ink sm:text-[40px]">{page.title}</h2>
          <p className="mt-2 text-[15px] text-muted">
            {plural(fixes.length, 'line')} {LINE_WORD[filter]}
          </p>
        </div>
        {page.url && (
          <a
            href={page.url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 rounded text-[14px] font-semibold whitespace-nowrap text-cobalt hover:text-cobalt-deep focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cobalt"
          >
            Open the page <ArrowUpRight size={13} weight="bold" />
          </a>
        )}
      </header>
      {fixes.map((f, i) => (
        <FixRow key={f.id} ws={ws} fix={f} dryRun={dryRun} first={i === 0} onDone={onDone} />
      ))}
    </motion.section>
  )
}

// --- The screen -------------------------------------------------------------------------------------

const FILTERS: { key: FixFilter; label: string }[] = [
  { key: 'open', label: 'Open' },
  { key: 'filed', label: 'Filed' },
  { key: 'dismissed', label: 'Dismissed' },
]

const EMPTY: Record<FixFilter, [string, string]> = {
  open: ['Every page agrees with the graph.', 'When a page says something the graph knows has changed, its correction lands here, checked and routed to its owner.'],
  filed: ['Nothing filed yet.', 'Approve an open fix and Canon files it as an issue, in a repository you choose.'],
  dismissed: ['Nothing dismissed.', 'Fixes someone turns down are kept here with their reason.'],
}

function Skeleton() {
  return (
    <div aria-hidden="true" className="space-y-3">
      {[0, 1].map((i) => (
        <div key={i} className="slab bg-paper px-6 pt-10 pb-12 sm:px-10 lg:px-12">
          <div className="h-3.5 w-40 animate-pulse rounded-full bg-paper-2" />
          <div className="mt-4 h-9 w-[min(420px,70%)] animate-pulse rounded-[10px] bg-paper-2" />
          <div className="mt-12 grid gap-12 min-[1100px]:grid-cols-[minmax(0,1fr)_300px]">
            <div className="space-y-4">
              {[92, 70, 84].map((w, j) => (
                <div key={j} className="h-4 animate-pulse rounded-full bg-paper-2" style={{ width: `${w - i * 8}%` }} />
              ))}
            </div>
            <div className="space-y-3">
              <div className="h-4 w-24 animate-pulse rounded-full bg-paper-2" />
              <div className="h-5 w-40 animate-pulse rounded-full bg-paper-2" />
            </div>
          </div>
        </div>
      ))}
    </div>
  )
}

/** How to read a proof sheet, written in its own marks. */
function Key() {
  return (
    <ul className="flex flex-col gap-2 text-[14.5px] text-muted sm:flex-row sm:flex-wrap sm:gap-x-8">
      <li>
        <span className="text-ink/65 line-through decoration-proof decoration-2">Struck</span> is what the page says
      </li>
      <li>
        <span className="font-medium text-cobalt">Written above</span> is the correction, checked against the newer fact
      </li>
      <li>
        <mark className="marker text-ink">Highlighted</mark> is the fact that holds now
      </li>
    </ul>
  )
}

type Loaded = { key: string; list: FixList | null; error: string | null }

export function FixQueue({ ws }: { ws: Workspace }) {
  const [filter, setFilter] = useState<FixFilter>('open')
  const [loaded, setLoaded] = useState<Loaded | null>(null)
  const [attempt, setAttempt] = useState(0)
  const [announcement, setAnnouncement] = useState('')
  const top = useRef<HTMLHeadingElement>(null)
  const key = `${ws.slug}:${filter}:${attempt}`

  useEffect(() => {
    const ctrl = new AbortController()
    getFixes(ws.slug, filter, ctrl.signal).then(
      (list) => setLoaded({ key, list, error: null }),
      (e: Error) => e.name !== 'AbortError' && setLoaded({ key, list: null, error: e.message }),
    )
    return () => ctrl.abort()
  }, [ws.slug, filter, key])

  const ready = loaded?.key === key ? loaded : null
  const list = ready?.list ?? null

  const pages = useMemo(() => {
    const groups = new Map<string, Fix[]>()
    for (const f of list?.fixes ?? []) {
      const id = f.page.id ?? f.id
      groups.set(id, [...(groups.get(id) ?? []), f])
    }
    return [...groups.values()]
  }, [list])

  const done = (f: Fix, said: string) => {
    setAnnouncement(said)
    setLoaded((l) => {
      if (!l?.list) return l
      const before = l.list.fixes.find((x) => x.id === f.id)
      const counts = { ...l.list.counts }
      if (before && before.status !== f.status) {
        counts[before.status] = Math.max(0, (counts[before.status] ?? 0) - 1)
        counts[f.status] = (counts[f.status] ?? 0) + 1
      }
      return { ...l, list: { ...l.list, counts, fixes: l.list.fixes.map((x) => (x.id === f.id ? f : x)) } }
    })
  }

  const count = (k: FixFilter) => (list ? (k === 'open' ? list.counts.open + list.counts.approved : list.counts[k]) : null)
  const open = count('open')
  const openPages = filter === 'open' ? pages.length : null

  let lede = 'When a page says something the graph knows has changed, Canon drafts the correction from the newer fact, checks it, and sends it to whoever owns the page.'
  if (open && openPages !== null && filter === 'open')
    lede = `${plural(open, 'line')} on ${plural(openPages, 'page')} ${open === 1 ? 'says' : 'say'} something the graph knows has changed. Each correction is drafted from the newer fact and checked against it before it reaches you.`

  return (
    <main className="flex min-w-0 flex-1 flex-col gap-3">
      <div role="status" aria-live="polite" className="sr-only">
        {announcement}
      </div>
      <section className="slab bg-paper px-6 pt-8 pb-7 sm:px-10 sm:pt-12 lg:px-12">
        <h1 ref={top} className="display text-[38px] text-ink sm:text-[54px]">
          Fix queue
        </h1>
        <p className="mt-4 max-w-[680px] text-[17px] leading-relaxed text-pretty text-muted sm:text-[18px]">{lede}</p>
        <div className="mt-6 max-sm:hidden">
          <Key />
        </div>
        <div className="mt-8 flex flex-col gap-4 border-t border-line pt-6 min-[1100px]:flex-row min-[1100px]:items-center min-[1100px]:justify-between">
          <div role="tablist" aria-label="Fixes" className="flex shrink-0 gap-1.5">
            {FILTERS.map((f) => {
              const n = count(f.key)
              const on = f.key === filter
              return (
                <button
                  key={f.key}
                  type="button"
                  role="tab"
                  aria-selected={on}
                  onClick={() => setFilter(f.key)}
                  className={`inline-flex h-10 items-center gap-2 rounded-full px-4 text-[14.5px] transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cobalt ${on ? 'bg-ink font-semibold text-paper' : 'text-muted hover:bg-paper-2 hover:text-ink'}`}
                >
                  {f.label}
                  {n !== null && <span className={`tabular-nums ${on ? 'text-paper/60' : 'text-faint'}`}>{n}</span>}
                </button>
              )
            })}
          </div>
          {list?.dry_run && <p className="text-[13.5px] text-faint">Dry run is on: approving shows the issue Canon would file, and nothing reaches GitHub.</p>}
        </div>
      </section>

      {!ready && <Skeleton />}

      {ready?.error && (
        <section className="slab bg-paper px-6 py-10 sm:px-10 lg:px-12">
          <p className="text-[18px] leading-relaxed text-ink">{ready.error}</p>
          <button type="button" onClick={() => setAttempt((a) => a + 1)} className="mt-3 text-[15px] font-semibold text-cobalt hover:text-cobalt-deep">
            Try again
          </button>
        </section>
      )}

      {list && !pages.length && (
        <section className="slab bg-paper px-6 py-12 sm:px-10 sm:py-16 lg:px-12">
          <div className="ruled max-w-[560px] text-[18px] leading-[32px]">
            <p className="font-medium text-cobalt">{EMPTY[filter][0]}</p>
            <p className="text-muted">{EMPTY[filter][1]}</p>
          </div>
        </section>
      )}

      {pages.map((fs) => (
        <PageSheet key={fs[0].page.id ?? fs[0].id} ws={ws.slug} fixes={fs} filter={filter} dryRun={!!list?.dry_run} onDone={done} />
      ))}
    </main>
  )
}
