// Connect a source: pick a tool the company writes in, make a token the way that tool asks, and watch Canon read it.
// Below, every source the workspace reads, when it last synced, what it read, and anything that went wrong.

import {
  ArrowRight,
  ArrowsClockwise,
  BookOpenText,
  FileText,
  GithubLogo,
  Kanban,
  NotionLogo,
  SlackLogo,
  Ticket,
  UploadSimple,
  X,
  type Icon,
} from '@phosphor-icons/react'
import { motion, useReducedMotion } from 'motion/react'
import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent, type ReactNode } from 'react'
import { ago, signInUrl, useJob, type Me } from './account'
import {
  createBlankWorkspace,
  createConnection,
  listConnections,
  removeConnection,
  syncConnection,
  uploadFiles,
  type Connection,
  type ConnectionJob,
  type SourceKind,
} from './connections'
import { plural } from './text'
import { fromServer, type Workspace } from './workspaces'

const ease = [0.22, 1, 0.36, 1] as const

/** A scope, a token prefix or an address: the only monospace on the page. */
const Code = ({ children }: { children: ReactNode }) => (
  <code className="rounded-[6px] bg-paper-2 px-1.5 py-[1px] font-mono text-[0.84em] whitespace-nowrap text-ink">{children}</code>
)

const Out = ({ href, children }: { href: string; children: ReactNode }) => (
  <a href={href} target="_blank" rel="noreferrer" className="font-medium text-cobalt underline decoration-cobalt/30 underline-offset-[3px] hover:decoration-cobalt">
    {children}
  </a>
)

type Field = {
  key: 'secret' | 'site' | 'email' | 'channels' | 'projects' | 'spaces'
  label: string
  placeholder: string
  hint?: string
  optional?: boolean
  mono?: boolean
}

type Source = {
  kind: SourceKind
  name: string
  icon: Icon
  group: 'Chats' | 'Docs' | 'Tickets' | 'Files'
  line: string
  reads: string
  steps: ReactNode[]
  fields: Field[]
}

const ATLASSIAN_TOKEN: ReactNode[] = [
  <>
    Open <Out href="https://id.atlassian.com/manage-profile/security/api-tokens">Atlassian API tokens</Out> and choose Create API token. Name it Canon.
  </>,
  <>Copy the token. It reads what your account can read, so use an account that can see what Canon should read.</>,
  <>
    Give your site, like <Code>acme.atlassian.net</Code>, and the email of that account. The email is kept sealed with the token.
  </>,
]

const SOURCES: Source[] = [
  {
    kind: 'slack',
    name: 'Slack',
    icon: SlackLogo,
    group: 'Chats',
    line: 'Threads and conversations in the channels you invite it to',
    reads:
      'Each thread, and each channel’s day of conversation, in the channels the app is invited to, from the last 90 days and then whatever is new. Who wrote what, so a person is one person across your tools.',
    steps: [
      <>
        Open <Out href="https://api.slack.com/apps">api.slack.com/apps</Out>, choose Create New App, then From scratch, and pick your workspace.
      </>,
      <>
        Under OAuth &amp; Permissions, add the bot token scopes <Code>channels:history</Code> <Code>channels:read</Code> <Code>users:read</Code>. For
        private channels add <Code>groups:history</Code> <Code>groups:read</Code>, and to match people across tools add <Code>users:read.email</Code>.
      </>,
      <>
        Choose Install to Workspace, then copy the Bot User OAuth Token. It starts with <Code>xoxb-</Code>.
      </>,
      <>
        In each channel Canon should read, type <Code>/invite @YourApp</Code>.
      </>,
    ],
    fields: [
      { key: 'secret', label: 'Bot User OAuth Token', placeholder: 'xoxb-…', mono: true },
      { key: 'channels', label: 'Only these channels', placeholder: 'eng, decisions', optional: true, hint: 'Leave empty to read every channel the app is in.' },
    ],
  },
  {
    kind: 'notion',
    name: 'Notion',
    icon: NotionLogo,
    group: 'Docs',
    line: 'Pages and databases shared with the integration',
    reads:
      'Every page shared with the integration, read block by block, dated by when it was last edited. A database row with an owner and a status tells Canon who owns that work, with no model guessing.',
    steps: [
      <>
        Open <Out href="https://www.notion.so/profile/integrations">Notion integrations</Out>, choose New integration, make it Internal and pick your
        workspace.
      </>,
      <>Under Capabilities, keep Read content and choose Read user information including email addresses.</>,
      <>
        Copy the Internal Integration Secret. It starts with <Code>ntn_</Code>.
      </>,
      <>On each page or database Canon should read, open the ••• menu, then Connections, and add the integration. Pages under it come along.</>,
    ],
    fields: [{ key: 'secret', label: 'Internal Integration Secret', placeholder: 'ntn_…', mono: true }],
  },
  {
    kind: 'linear',
    name: 'Linear',
    icon: Kanban,
    group: 'Tickets',
    line: 'Teams, projects and issues, with their history',
    reads:
      'Teams and their members, projects and their leads, and issues with their comments. Every state change and reassignment is dated, so Canon can say who had an issue and when that changed.',
    steps: [
      <>In Linear, open Settings, then Account, then Security &amp; access.</>,
      <>Under Personal API keys choose New API key. Name it Canon. When asked, read access is enough.</>,
      <>
        Copy the key. It starts with <Code>lin_api_</Code>.
      </>,
    ],
    fields: [{ key: 'secret', label: 'Personal API key', placeholder: 'lin_api_…', mono: true }],
  },
  {
    kind: 'jira',
    name: 'Jira',
    icon: Ticket,
    group: 'Tickets',
    line: 'Projects and their leads, issues and comments',
    reads: 'Projects with their leads, and issues updated in the last six months with their descriptions, comments, status and who reported and has each.',
    steps: ATLASSIAN_TOKEN,
    fields: [
      { key: 'site', label: 'Site', placeholder: 'acme.atlassian.net' },
      { key: 'email', label: 'Account email', placeholder: 'you@company.com' },
      { key: 'secret', label: 'API token', placeholder: 'Paste the token', mono: true },
      { key: 'projects', label: 'Only these projects', placeholder: 'OPS, ENG', optional: true, hint: 'Project keys. Leave empty for every project.' },
    ],
  },
  {
    kind: 'confluence',
    name: 'Confluence',
    icon: BookOpenText,
    group: 'Docs',
    line: 'Spaces and their pages',
    reads: 'Every current page in your spaces, dated by its latest version, with who owns it and who edited it last.',
    steps: ATLASSIAN_TOKEN,
    fields: [
      { key: 'site', label: 'Site', placeholder: 'acme.atlassian.net' },
      { key: 'email', label: 'Account email', placeholder: 'you@company.com' },
      { key: 'secret', label: 'API token', placeholder: 'Paste the token', mono: true },
      { key: 'spaces', label: 'Only these spaces', placeholder: 'ENG, HR', optional: true, hint: 'Space keys. Leave empty for every space.' },
    ],
  },
  {
    kind: 'upload',
    name: 'Files',
    icon: FileText,
    group: 'Files',
    line: 'Markdown, text, HTML, PDF and Word, or a zip of them',
    reads:
      'Each file becomes a document dated by when it was last changed. Upload a file of the same name again and Canon reads the new version, closing what the old one said rather than losing it.',
    steps: [],
    fields: [],
  },
]

const sourceOf = (kind: string) => SOURCES.find((s) => s.kind === kind) ?? SOURCES[SOURCES.length - 1]

function useSearch(): URLSearchParams {
  const [search, setSearch] = useState(() => window.location.search)
  useEffect(() => {
    const update = () => setSearch(window.location.search)
    window.addEventListener('popstate', update)
    return () => window.removeEventListener('popstate', update)
  }, [])
  return useMemo(() => new URLSearchParams(search), [search])
}

function setSearch(query: string) {
  window.history.replaceState(null, '', `/app/connect${query}`)
  window.dispatchEvent(new PopStateEvent('popstate'))
}

// ----- naming a new workspace -----------------------------------------------------------------------------------

function NameWorkspace({ me, own, onMade }: { me: Me | null; own: Workspace[]; onMade: (w: Workspace) => void }) {
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const signIn = signInUrl(me, '/app/connect?new=1')

  if (!me?.user) {
    return (
      <div>
        <p className="max-w-[560px] text-[17px] leading-relaxed text-muted">Sign in to make a workspace of your own. Its sources and what Canon reads from them are private to you.</p>
        {signIn && (
          <a href={signIn} className="mt-6 inline-flex h-12 items-center gap-2.5 rounded-full bg-ink px-6 text-[15px] font-semibold text-paper transition-colors hover:bg-[#23252d]">
            <GithubLogo size={18} weight="bold" />
            {me?.signin ? 'Sign in with GitHub' : 'Sign in for development'}
          </a>
        )}
      </div>
    )
  }

  const submit = (e: FormEvent) => {
    e.preventDefault()
    if (!name.trim() || busy) return
    setBusy(true)
    setError(null)
    createBlankWorkspace(name.trim()).then(
      ({ workspace }) => onMade(fromServer({ ...workspace, role: 'owner' })),
      (err: Error) => {
        setError(err.message)
        setBusy(false)
      },
    )
  }

  return (
    <form onSubmit={submit}>
      <label htmlFor="ws-name" className="text-[15px] text-muted">
        Name the workspace, usually your company
      </label>
      <div className="mt-3 flex items-end gap-4 border-b-[1.5px] border-line-strong pb-4 transition-colors focus-within:border-ink">
        <input
          id="ws-name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          maxLength={60}
          autoComplete="organization"
          placeholder="Acme"
          className="display min-w-0 flex-1 bg-transparent text-[34px] leading-[1.08] text-ink caret-cobalt outline-none placeholder:text-[#b9bdc5] sm:text-[52px]"
        />
        <button
          type="submit"
          disabled={name.trim().length < 2 || busy}
          aria-label="Make the workspace"
          className="mb-1 grid size-12 shrink-0 place-items-center rounded-full bg-ink text-paper transition-[background-color,opacity] duration-200 hover:bg-[#23252d] disabled:opacity-20 sm:size-14"
        >
          <ArrowRight size={20} weight="bold" />
        </button>
      </div>
      {error && <p className="mt-4 text-[16px] text-proof">{error}</p>}
      {own.length > 0 && (
        <p className="mt-6 text-[15.5px] leading-relaxed text-muted">
          Or add sources to{' '}
          {own.map((w, i) => (
            <span key={w.slug}>
              {i > 0 && (i === own.length - 1 ? ' or ' : ', ')}
              <button type="button" onClick={() => onMade(w)} className="font-semibold text-ink underline decoration-line-strong underline-offset-[5px] hover:decoration-ink">
                {w.label}
              </button>
            </span>
          ))}
          .
        </p>
      )}
    </form>
  )
}

// ----- the sources ----------------------------------------------------------------------------------------------

function Glyph({ source, on, size = 'md' }: { source: Source; on?: boolean; size?: 'md' | 'lg' }) {
  const I = source.icon
  const box = size === 'lg' ? 'size-14 rounded-[16px]' : 'size-10 rounded-[12px]'
  return (
    <span className={`grid shrink-0 place-items-center transition-colors ${box} ${on ? 'bg-ink text-paper' : 'bg-paper-2 text-ink'}`} aria-hidden="true">
      <I size={size === 'lg' ? 28 : 21} weight={source.kind === 'slack' || source.kind === 'notion' ? 'fill' : 'regular'} />
    </span>
  )
}

function Picker({ selected, counts, onPick }: { selected: SourceKind; counts: Partial<Record<SourceKind, number>>; onPick: (k: SourceKind) => void }) {
  return (
    <ul className="space-y-1" aria-label="Sources">
      {SOURCES.map((s) => {
        const on = s.kind === selected
        const n = counts[s.kind] ?? 0
        return (
          <li key={s.kind}>
            <button
              type="button"
              aria-pressed={on}
              onClick={() => onPick(s.kind)}
              className={`flex w-full items-center gap-3.5 rounded-[16px] px-3 py-3 text-left transition-colors focus-visible:outline-2 focus-visible:outline-cobalt ${on ? 'bg-paper-2' : 'hover:bg-paper-2/60'}`}
            >
              <Glyph source={s} on={on} />
              <span className="min-w-0 flex-1">
                <span className="flex items-baseline justify-between gap-3">
                  <span className="text-[15.5px] font-semibold text-ink">{s.name}</span>
                  {n > 0 && <span className="text-[13px] text-cobalt">Connected</span>}
                </span>
                <span className="mt-0.5 block text-[14px] leading-snug text-muted">{s.line}</span>
              </span>
            </button>
          </li>
        )
      })}
    </ul>
  )
}

function Steps({ steps }: { steps: ReactNode[] }) {
  return (
    <ol className="mt-4 space-y-3.5">
      {steps.map((step, i) => (
        <li key={i} className="flex gap-3.5 text-[15.5px] leading-relaxed text-ink">
          <span className="mt-[1px] grid size-6 shrink-0 place-items-center rounded-full bg-cobalt-soft text-[13px] font-semibold text-cobalt tabular-nums" aria-hidden="true">
            {i + 1}
          </span>
          <span className="min-w-0">{step}</span>
        </li>
      ))}
    </ol>
  )
}

function TokenForm({ source, ws, onStarted }: { source: Source; ws: string; onStarted: (job: ConnectionJob | null, c: Connection) => void }) {
  const [values, setValues] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = (e: FormEvent) => {
    e.preventDefault()
    if (busy) return
    const missing = source.fields.find((f) => !f.optional && !(values[f.key] ?? '').trim())
    if (missing) {
      setError(`Fill in ${missing.label.toLowerCase()}.`)
      return
    }
    setBusy(true)
    setError(null)
    const config: Record<string, unknown> = {}
    for (const f of source.fields) if (f.key !== 'secret' && values[f.key]?.trim()) config[f.key] = values[f.key].trim()
    createConnection(ws, { kind: source.kind, config, secret: (values.secret ?? '').trim() }).then(
      ({ connection, job }) => {
        setValues({})
        setBusy(false)
        onStarted(job, connection)
      },
      (err: Error) => {
        setError(err.message)
        setBusy(false)
      },
    )
  }

  return (
    <form onSubmit={submit} noValidate className="mt-8 border-t border-line pt-7">
      <div className="grid gap-5 sm:grid-cols-2">
        {source.fields.map((f) => (
          <div key={f.key} className={f.key === 'secret' || f.optional ? 'sm:col-span-2' : ''}>
            <label htmlFor={`f-${f.key}`} className="flex items-baseline justify-between text-[14.5px] text-muted">
              {f.label}
              {f.optional && <span className="text-[13px] text-faint">Optional</span>}
            </label>
            <input
              id={`f-${f.key}`}
              type={f.key === 'secret' ? 'password' : f.key === 'email' ? 'email' : 'text'}
              value={values[f.key] ?? ''}
              onChange={(e) => setValues((v) => ({ ...v, [f.key]: e.target.value }))}
              placeholder={f.placeholder}
              autoComplete={f.key === 'email' ? 'email' : 'off'}
              autoCapitalize="off"
              spellCheck={false}
              className={`mt-2 h-12 w-full rounded-[12px] border-[1.5px] border-line-strong bg-paper px-4 text-[16px] text-ink outline-none transition-colors placeholder:text-[#b3b7bf] focus:border-ink ${f.mono ? 'font-mono text-[14.5px] placeholder:font-sans placeholder:text-[16px]' : ''}`}
            />
            {f.hint && <p className="mt-1.5 text-[13.5px] text-faint">{f.hint}</p>}
          </div>
        ))}
      </div>
      {error && (
        <p role="alert" className="mt-5 text-[15.5px] leading-relaxed text-proof">
          {error}
        </p>
      )}
      <div className="mt-6 flex flex-col gap-3 sm:flex-row sm:items-center sm:gap-5">
        <button
          type="submit"
          disabled={busy}
          className="inline-flex h-12 w-fit items-center gap-2.5 rounded-full bg-ink px-6 text-[15px] font-semibold text-paper transition-colors hover:bg-[#23252d] disabled:opacity-60"
        >
          {busy ? 'Checking the token' : `Connect ${source.name}`}
          {!busy && <ArrowRight size={17} weight="bold" />}
        </button>
        <p className="text-[13.5px] leading-snug text-faint">Canon checks it with one call, then keeps it sealed. It is never shown again.</p>
      </div>
    </form>
  )
}

const ACCEPT = '.md,.markdown,.mdx,.txt,.html,.htm,.pdf,.docx,.zip'
const MAX_BYTES = 30 * 1024 * 1024

function size(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

function FileDrop({ ws, onStarted }: { ws: string; onStarted: (job: ConnectionJob | null, c: Connection) => void }) {
  const [files, setFiles] = useState<File[]>([])
  const [over, setOver] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const input = useRef<HTMLInputElement>(null)
  const total = files.reduce((n, f) => n + f.size, 0)

  const add = (list: FileList | null) => {
    if (!list) return
    setError(null)
    setFiles((prev) => {
      const byName = new Map(prev.map((f) => [f.name, f]))
      for (const f of Array.from(list)) byName.set(f.name, f)
      return [...byName.values()]
    })
  }

  const send = () => {
    if (!files.length || busy) return
    if (total > MAX_BYTES) {
      setError('An upload can be at most 30 MB. Send fewer files at a time.')
      return
    }
    setBusy(true)
    setError(null)
    uploadFiles(ws, files).then(
      ({ job, connection }) => {
        setFiles([])
        setBusy(false)
        onStarted(job, connection)
      },
      (err: Error) => {
        setError(err.message)
        setBusy(false)
      },
    )
  }

  return (
    <div className="mt-8">
      <label
        onDragOver={(e) => {
          e.preventDefault()
          setOver(true)
        }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => {
          e.preventDefault()
          setOver(false)
          add(e.dataTransfer.files)
        }}
        className={`flex min-h-[176px] cursor-pointer flex-col items-center justify-center rounded-[20px] border-[1.5px] border-dashed px-6 py-8 text-center transition-colors ${over ? 'border-cobalt bg-cobalt-soft/50' : 'border-line-strong bg-paper-2/50 hover:border-ink/40'}`}
      >
        <UploadSimple size={26} className={over ? 'text-cobalt' : 'text-ink'} />
        <span className="mt-3 text-[16.5px] font-semibold text-ink">Drop files here, or choose them</span>
        <span className="mt-1 text-[14px] text-muted">Markdown, text, HTML, PDF and Word, or a zip of them. Up to 30 MB at a time.</span>
        <input ref={input} type="file" multiple accept={ACCEPT} className="sr-only" onChange={(e) => add(e.target.files)} />
      </label>
      {files.length > 0 && (
        <ul className="mt-5 divide-y divide-line border-y border-line">
          {files.map((f) => (
            <li key={f.name} className="flex items-center gap-3 py-2.5 text-[15px]">
              <FileText size={17} className="shrink-0 text-faint" />
              <span className="min-w-0 flex-1 truncate text-ink">{f.name}</span>
              <span className="shrink-0 text-[13.5px] text-faint tabular-nums">{size(f.size)}</span>
              <button
                type="button"
                aria-label={`Leave out ${f.name}`}
                onClick={() => setFiles((all) => all.filter((x) => x !== f))}
                className="grid size-8 shrink-0 place-items-center rounded-full text-faint hover:bg-paper-2 hover:text-ink"
              >
                <X size={14} weight="bold" />
              </button>
            </li>
          ))}
        </ul>
      )}
      {error && (
        <p role="alert" className="mt-5 text-[15.5px] text-proof">
          {error}
        </p>
      )}
      {files.length > 0 && (
        <button
          type="button"
          onClick={send}
          disabled={busy}
          className="mt-6 inline-flex h-12 items-center gap-2.5 rounded-full bg-ink px-6 text-[15px] font-semibold text-paper transition-colors hover:bg-[#23252d] disabled:opacity-60"
        >
          {busy ? 'Sending' : `Read ${plural(files.length, 'file')}`}
          {!busy && <ArrowRight size={17} weight="bold" />}
        </button>
      )}
    </div>
  )
}

function Detail({ source, ws, onStarted }: { source: Source; ws: string; onStarted: (job: ConnectionJob | null, c: Connection) => void }) {
  return (
    <div>
      <div className="flex items-center gap-4">
        <Glyph source={source} on size="lg" />
        <div>
          <h2 className="display text-[32px] text-ink sm:text-[40px]">{source.name}</h2>
          {source.group !== source.name && <p className="mt-1 text-[14px] text-faint">{source.group}</p>}
        </div>
      </div>
      <p className="mt-6 max-w-[620px] text-[17px] leading-relaxed text-pretty text-muted">{source.reads}</p>
      {source.steps.length > 0 && (
        <div className="mt-8">
          <h3 className="text-[15px] font-semibold text-ink">Make a token</h3>
          <Steps steps={source.steps} />
        </div>
      )}
      {source.kind === 'upload' ? <FileDrop ws={ws} onStarted={onStarted} /> : <TokenForm key={source.kind} source={source} ws={ws} onStarted={onStarted} />}
    </div>
  )
}

// ----- what is connected ----------------------------------------------------------------------------------------

function countsLine(c: Connection): string {
  const n = c.counts
  if (!n.documents) return ''
  const parts = [plural(n.documents, 'document')]
  if (n.facts) parts.push(plural(n.facts, 'fact'))
  if (n.people) parts.push(plural(n.people, 'person', 'people'))
  return parts.join(', ')
}

function Row({
  c,
  job,
  busy,
  onSync,
  onRemove,
  onAddFiles,
}: {
  c: Connection
  job: ConnectionJob | null
  busy: boolean
  onSync: () => void
  onRemove: (documents: 'keep' | 'delete') => Promise<void>
  onAddFiles: () => void
}) {
  const reduce = useReducedMotion()
  const [asking, setAsking] = useState(false)
  const [removing, setRemoving] = useState(false)
  const source = sourceOf(c.kind)
  const running = job?.status === 'running' && job.connection === c.id
  const synced = c.last_synced_at ? `Synced ${ago(c.last_synced_at)}` : c.status === 'failed' ? 'Not synced yet' : 'Waiting for its first sync'
  const counts = countsLine(c)

  const remove = (documents: 'keep' | 'delete') => {
    setRemoving(true)
    onRemove(documents).finally(() => setRemoving(false))
  }

  return (
    <li className="py-5">
      <div className="flex gap-4">
        <Glyph source={source} />
        <div className="min-w-0 flex-1">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between sm:gap-6">
            <div className="min-w-0">
              <p className="truncate text-[16.5px] font-semibold text-ink">{c.label}</p>
              {running ? (
                <p className="mt-1 text-[14.5px] text-ink">{job.step_label}</p>
              ) : (
                <p className={`mt-1 text-[14.5px] ${c.status === 'failed' ? 'text-proof' : 'text-muted'}`}>
                  {c.status === 'failed' ? 'The last sync stopped' : synced}
                  {counts && c.status !== 'failed' && <span className="text-faint">. {counts}</span>}
                </p>
              )}
            </div>
            {!running && !asking && (
              <div className="flex shrink-0 items-center gap-5 text-[14.5px]">
                {c.kind === 'upload' ? (
                  <button type="button" onClick={onAddFiles} className="inline-flex items-center gap-1.5 font-semibold text-cobalt hover:text-cobalt-deep">
                    <UploadSimple size={14} weight="bold" />
                    Add files
                  </button>
                ) : (
                  <button type="button" onClick={onSync} disabled={busy} className="inline-flex items-center gap-1.5 font-semibold text-cobalt hover:text-cobalt-deep disabled:text-faint">
                    <ArrowsClockwise size={14} weight="bold" />
                    Sync now
                  </button>
                )}
                <button type="button" onClick={() => setAsking(true)} disabled={busy} className="text-muted hover:text-ink disabled:text-faint">
                  Remove
                </button>
              </div>
            )}
          </div>
          {running && (
            <div className="relative mt-3 h-[3px] max-w-[420px] overflow-hidden rounded-full bg-line" aria-hidden="true">
              <motion.div
                className="absolute inset-y-0 left-0 w-full origin-left rounded-full bg-ink"
                initial={false}
                animate={{ scaleX: Math.max(0.04, job.progress) }}
                transition={{ duration: reduce ? 0 : 0.5, ease }}
              />
            </div>
          )}
          {c.status === 'failed' && c.error && <p className="mt-2 max-w-[640px] text-[14.5px] leading-relaxed text-ink">{c.error}</p>}
          {c.notes.length > 0 && !running && (
            <ul className="mt-2 max-w-[640px] space-y-1 text-[14px] leading-relaxed text-faint">
              {c.notes.slice(0, 3).map((n) => (
                <li key={n}>{n}</li>
              ))}
              {c.notes.length > 3 && <li>{plural(c.notes.length - 3, 'more note')}</li>}
            </ul>
          )}
          {asking && (
            <div className="mt-4 rounded-[16px] bg-paper-2 p-4 sm:p-5">
              <p className="text-[15px] leading-relaxed text-ink">
                Remove {c.label}? Canon stops reading it. What it already read can stay as history, or go.
              </p>
              <div className="mt-4 flex flex-col gap-2.5 sm:flex-row sm:flex-wrap sm:items-center sm:gap-3">
                <button
                  type="button"
                  disabled={removing}
                  onClick={() => remove('keep')}
                  className="inline-flex h-10 w-fit items-center rounded-full bg-ink px-4 text-[14px] font-semibold text-paper hover:bg-[#23252d] disabled:opacity-60"
                >
                  Remove, keep what it read
                </button>
                <button
                  type="button"
                  disabled={removing}
                  onClick={() => remove('delete')}
                  className="inline-flex h-10 w-fit items-center rounded-full px-4 text-[14px] font-semibold text-proof shadow-[inset_0_0_0_1.5px_var(--proof)] hover:bg-proof-soft disabled:opacity-60"
                >
                  Remove and delete its documents
                </button>
                <button type="button" onClick={() => setAsking(false)} className="h-10 w-fit px-2 text-[14px] text-muted hover:text-ink">
                  Cancel
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </li>
  )
}

// ----- the screen -----------------------------------------------------------------------------------------------

type Loaded = { slug: string; connections: Connection[]; error: string | null }

export function Connect({
  ws,
  own,
  me,
  onWorkspace,
  onCreated,
  onSynced,
}: {
  ws: Workspace
  own: Workspace[]
  me: Me | null
  onWorkspace: (w: Workspace) => void
  onCreated: () => void
  onSynced: () => void
}) {
  const search = useSearch()
  const wanted = search.get('ws')
  const fresh = search.get('new') === '1'
  const target = fresh ? null : (own.find((w) => w.slug === (wanted ?? ws.slug)) ?? (wanted && wanted === ws.slug && ws.own ? ws : null))
  const slug = target?.slug ?? null

  // Opened from a link with ?ws=: the switcher shows that workspace too.
  useEffect(() => {
    if (target && target.slug !== ws.slug) onWorkspace(target)
  }, [target, ws.slug, onWorkspace])

  const [selected, setSelected] = useState<SourceKind>('slack')
  const [loaded, setLoaded] = useState<Loaded | null>(null)
  const [attempt, setAttempt] = useState(0)
  const [actionError, setActionError] = useState<string | null>(null)
  const { job: rawJob, kick, setJob } = useJob(slug)
  const job = rawJob as ConnectionJob | null
  const detail = useRef<HTMLDivElement>(null)

  const load = useCallback(
    (signal?: AbortSignal) => {
      if (!slug) return
      listConnections(slug, signal).then(
        (r) => setLoaded({ slug, connections: r.connections, error: null }),
        (e: Error) => e.name !== 'AbortError' && setLoaded({ slug, connections: [], error: e.message }),
      )
    },
    [slug],
  )

  useEffect(() => {
    const ctrl = new AbortController()
    load(ctrl.signal)
    return () => ctrl.abort()
  }, [load, attempt])

  // When a sync finishes, read the list again (counts, errors), and let the rest of the app refresh.
  const was = useRef<string | null>(null)
  useEffect(() => {
    const status = job?.status ?? null
    if (was.current === 'running' && status && status !== 'running') {
      load()
      onSynced()
    }
    was.current = status
  }, [job?.status, load, onSynced])

  const ready = loaded?.slug === slug ? loaded : null
  const connections = ready?.connections ?? []
  const counts = useMemo(() => {
    const out: Partial<Record<SourceKind, number>> = {}
    for (const c of connections) out[c.kind] = (out[c.kind] ?? 0) + 1
    return out
  }, [connections])

  const started = (next: ConnectionJob | null, c: Connection) => {
    setLoaded((l) => (l ? { ...l, connections: [...l.connections.filter((x) => x.id !== c.id), c] } : l))
    if (next) setJob(next)
    kick()
  }

  const pick = (k: SourceKind) => {
    setSelected(k)
    if (window.matchMedia('(max-width: 1023px)').matches) {
      requestAnimationFrame(() => detail.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }))
    }
  }

  const sync = (c: Connection) => {
    if (!slug) return
    setActionError(null)
    syncConnection(slug, c.id).then(
      ({ job: next, connection }) => started(next, connection),
      (e: Error) => setActionError(e.message),
    )
  }

  const remove = (c: Connection, documents: 'keep' | 'delete') => {
    if (!slug) return Promise.resolve()
    setActionError(null)
    return removeConnection(slug, c.id, documents).then(
      () => {
        setLoaded((l) => (l ? { ...l, connections: l.connections.filter((x) => x.id !== c.id) } : l))
        onSynced()
      },
      (e: Error) => setActionError(e.message),
    )
  }

  const made = (w: Workspace) => {
    onCreated()
    onWorkspace(w)
    setSearch(`?ws=${encodeURIComponent(w.slug)}`)
  }

  const source = sourceOf(selected)
  const running = job?.status === 'running'

  return (
    <main className="flex min-w-0 flex-1 flex-col gap-3">
      <section className="slab bg-paper px-6 pt-8 pb-8 sm:px-10 sm:pt-12 sm:pb-10 lg:px-12">
        {target && (
          <p className="text-[15px] text-muted">
            Sources for <span className="font-semibold text-ink">{target.label}</span>
          </p>
        )}
        <h1 className={`display text-[38px] text-ink sm:text-[54px] ${target ? 'mt-3' : ''}`}>{target ? 'Connect a source' : 'A workspace from your tools'}</h1>
        <p className="mt-4 max-w-[700px] text-[17px] leading-relaxed text-pretty text-muted sm:text-[18px]">
          Canon reads your chats, docs and tickets into one graph, dates every fact it finds, and reads each source again every hour, so answers follow
          what changed.
        </p>
        {!target && (
          <div className="mt-10 max-w-[760px]">
            <NameWorkspace me={me} own={own} onMade={made} />
          </div>
        )}
      </section>

      {target && slug && (
        <>
          <section className="slab bg-paper px-4 py-5 sm:px-6 sm:py-6 lg:px-6">
            <div className="grid gap-6 lg:grid-cols-[minmax(280px,340px)_1fr] lg:gap-10">
              <div className="lg:border-r lg:border-line lg:pr-6">
                <Picker selected={selected} counts={counts} onPick={pick} />
              </div>
              <motion.div
                ref={detail}
                key={selected}
                className="scroll-mt-4 px-2 pt-2 pb-4 sm:px-4 lg:py-6 lg:pr-8"
                initial={{ opacity: 0, y: 6 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.28, ease }}
              >
                <Detail source={source} ws={slug} onStarted={started} />
              </motion.div>
            </div>
          </section>

          <section className="slab bg-paper px-6 pt-8 pb-4 sm:px-10 lg:px-12" aria-labelledby="connected">
            <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1">
              <h2 id="connected" className="display text-[28px] text-ink sm:text-[34px]">
                Connected
              </h2>
              {connections.some((c) => c.kind !== 'upload') && <p className="text-[14px] text-faint">Each source is read again every hour.</p>}
            </div>
            {actionError && (
              <p role="alert" className="mt-4 text-[15px] text-proof">
                {actionError}
              </p>
            )}
            {!ready ? (
              <div className="h-24" aria-hidden="true" />
            ) : ready.error ? (
              <div className="py-6">
                <p className="text-[16px] text-ink">{ready.error}</p>
                <button type="button" onClick={() => setAttempt((a) => a + 1)} className="mt-2 text-[15px] font-semibold text-cobalt hover:text-cobalt-deep">
                  Try again
                </button>
              </div>
            ) : connections.length === 0 ? (
              <p className="py-6 text-[16px] leading-relaxed text-muted">Nothing yet. Pick a source above and connect it; its first sync starts right away.</p>
            ) : (
              <ul className="divide-y divide-line">
                {connections.map((c) => (
                  <Row
                    key={c.id}
                    c={c}
                    job={job}
                    busy={running}
                    onSync={() => sync(c)}
                    onRemove={(documents) => remove(c, documents)}
                    onAddFiles={() => pick('upload')}
                  />
                ))}
              </ul>
            )}
          </section>
        </>
      )}
    </main>
  )
}
