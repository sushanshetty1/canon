// The signed-in user's GitHub repositories, grouped by owner: theirs first, then each organisation. The server reads
// GitHub with the user's token; the page only ever sees the list.

import { ArrowRight, ArrowUpRight, CaretLeft, CaretRight, GithubLogo, MagnifyingGlass } from '@phosphor-icons/react'
import { useEffect, useState } from 'react'
import { ago, ApiError, connectUrl, listRepos, signInUrl, type Me, type RepoList } from './account'

function incompleteGrant(): boolean {
  try {
    return new URLSearchParams(window.location.search).get('connect') === 'incomplete'
  } catch {
    return false
  }
}

/** The second GitHub step, said plainly: what it asks for, and that Canon only reads. */
export function ConnectPrivate({ me }: { me: Me }) {
  const url = connectUrl(me)
  const [incomplete] = useState(incompleteGrant)
  if (!url) return null
  return (
    <div className="rounded-[20px] bg-paper-2 px-5 py-5 sm:px-6 sm:py-6">
      <p className="text-[16px] font-semibold text-ink">Private and organisation repositories</p>
      <p className="mt-1.5 max-w-[640px] text-[15px] leading-relaxed text-pretty text-muted">
        Connect them to make a workspace from a private repository, or one an organisation owns. GitHub has no read-only permission for
        private repositories, so it will ask for full access. Canon only reads them: it never pushes code or changes a setting.
      </p>
      {incomplete && <p className="mt-3 text-[14.5px] text-proof">GitHub did not grant access to private repositories. You can try again.</p>}
      <a
        href={url}
        className="mt-4 inline-flex min-h-11 items-center gap-2.5 rounded-full bg-ink px-5 py-2.5 text-[14.5px] leading-snug font-semibold text-paper transition-colors hover:bg-[#23252d] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cobalt"
      >
        <GithubLogo size={17} weight="bold" className="shrink-0" />
        Connect private and organisation repositories
      </a>
    </div>
  )
}

function Skeleton() {
  return (
    <ul aria-hidden="true" className="border-t border-line">
      {Array.from({ length: 5 }, (_, i) => (
        <li key={i} className="flex h-[70px] flex-col justify-center gap-2 border-b border-line px-1">
          <div className="h-3.5 animate-pulse rounded bg-paper-2" style={{ width: `${28 + ((i * 17) % 30)}%` }} />
          <div className="h-3 animate-pulse rounded bg-paper-2" style={{ width: `${45 + ((i * 23) % 35)}%` }} />
        </li>
      ))}
    </ul>
  )
}


export function RepoPicker({ me, busy, onPick }: { me: Me; busy: boolean; onPick: (repo: string) => void }) {
  const [text, setText] = useState('')
  const [q, setQ] = useState('')
  const [owner, setOwner] = useState('')
  const [page, setPage] = useState(1)
  const [state, setState] = useState<{ key: string; data: RepoList | null; error: ApiError | null } | null>(null)
  const key = `${q}\n${owner}\n${page}`

  useEffect(() => {
    const t = window.setTimeout(() => setQ(text.trim()), 180)
    return () => window.clearTimeout(t)
  }, [text])

  useEffect(() => {
    const ctrl = new AbortController()
    listRepos({ q, owner, page }, ctrl.signal).then(
      (data) => setState({ key, data, error: null }),
      (e: ApiError) => e.name !== 'AbortError' && setState((prev) => ({ key, data: prev?.data ?? null, error: e })),
    )
    return () => ctrl.abort()
  }, [key, q, owner, page])

  // The last list stays on screen while the next one loads, so typing never flashes an empty page.
  const loading = state?.key !== key
  const data = state?.data ?? null
  const error = state?.error ?? null

  if (data && !data.connected) {
    return (
      <p className="max-w-[560px] text-[15px] leading-relaxed text-muted">
        A development sign-in has no GitHub account, so there is no list of repositories here. Type a public one above.
      </p>
    )
  }

  const from = data ? (data.page - 1) * data.size + 1 : 0
  const to = data ? Math.min(data.total, data.page * data.size) : 0
  const go = (p: number) => setPage(p)
  const filter = (o: string) => {
    setOwner(o)
    setPage(1)
  }

  return (
    <section aria-labelledby="repos-title">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div className="min-w-0">
          <h2 id="repos-title" className="text-[20px] font-semibold tracking-[-0.02em] text-ink">
            Your repositories
          </h2>
          <p className="mt-1 text-[14.5px] text-muted">Most recently pushed first. Pick one and Canon starts reading it.</p>
        </div>
        <label className="relative block w-full sm:w-[280px]">
          <span className="sr-only">Search your repositories</span>
          <MagnifyingGlass size={16} weight="bold" className="pointer-events-none absolute top-1/2 left-4 -translate-y-1/2 text-faint" aria-hidden="true" />
          <input
            type="search"
            value={text}
            onChange={(e) => {
              setText(e.target.value)
              setPage(1)
            }}
            placeholder="Search"
            autoComplete="off"
            spellCheck={false}
            className="h-11 w-full rounded-full bg-paper-2 pr-4 pl-10 text-[15px] text-ink outline-none placeholder:text-faint focus:shadow-[inset_0_0_0_1.5px_var(--ink)]"
          />
        </label>
      </div>

      {data && !data.private && (
        <div className="mt-6">
          <ConnectPrivate me={me} />
        </div>
      )}

      {data && data.owners.length > 1 && (
        <div role="radiogroup" aria-label="Owner" className="-mx-1 mt-6 flex flex-wrap gap-1">
          {[{ login: '', label: 'All', count: data.owners.reduce((n, o) => n + o.count, 0) }, ...data.owners.map((o) => ({ login: o.login, label: o.login === data.login ? 'You' : o.login, count: o.count }))].map((o) => {
            const on = owner === o.login
            return (
              <button
                key={o.login || 'all'}
                type="button"
                role="radio"
                aria-checked={on}
                onClick={() => filter(o.login)}
                className={`inline-flex h-9 items-center gap-1.5 rounded-full px-3.5 text-[14px] transition-colors focus-visible:outline-2 focus-visible:outline-cobalt ${on ? 'bg-ink font-semibold text-paper' : 'text-muted hover:bg-paper-2 hover:text-ink'}`}
              >
                {o.label}
                <span className={`tabular-nums ${on ? 'text-paper/70' : 'text-faint'}`}>{o.count}</span>
              </button>
            )
          })}
        </div>
      )}

      <div className={`mt-5 transition-opacity duration-200 ${loading && data ? 'opacity-60' : ''}`} aria-busy={loading}>
        {!data && !error && <Skeleton />}
        {error && !loading && (
          <div className="pb-6 text-[15px]">
            <p className="text-ink">{error.message}</p>
            {error.reason === 'reauth' && signInUrl(me, '/app/new') && (
              <a href={signInUrl(me, '/app/new')!} className="mt-2 inline-block font-semibold text-cobalt hover:text-cobalt-deep">
                Sign in again
              </a>
            )}
          </div>
        )}
        {data && data.total === 0 && (
          <p className="border-t border-line py-6 text-[15px] text-muted">
            {q ? `No repository matches “${q}”.` : `GitHub lists no repositories for ${data.login} yet.`}
          </p>
        )}
        {data?.groups.map((g) => (
          <div key={`${g.owner}-${data.page}`} className="mt-7 first:mt-0">
            <p className="flex items-baseline gap-2 pb-2.5 text-[14px]">
              <span className="font-semibold text-ink">{g.you ? 'You' : g.owner}</span>
              <span className="text-faint">{g.you ? g.owner : g.kind === 'org' ? 'Organisation' : 'Shared with you'}</span>
            </p>
            <ul className="border-t border-line">
              {g.repos.map((r) => (
                <li key={r.full_name} className="border-b border-line">
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => onPick(r.full_name)}
                    aria-label={`Make a workspace from ${r.full_name}${r.private ? ', private' : ''}`}
                    className="group grid w-full grid-cols-[minmax(0,1fr)_auto] items-center gap-x-5 py-3.5 text-left transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cobalt disabled:cursor-wait"
                  >
                    <span className="min-w-0">
                      <span className="flex items-baseline gap-2">
                        <span className="truncate text-[16px] font-semibold text-ink transition-colors group-hover:text-cobalt">{r.name}</span>
                        {r.private && <span className="shrink-0 text-[13px] text-faint">Private</span>}
                        {r.archived && <span className="shrink-0 text-[13px] text-faint">Archived</span>}
                      </span>
                      <span className="mt-0.5 block truncate text-[14px] text-muted">{r.description || r.full_name}</span>
                    </span>
                    <span className="flex items-center gap-3 text-[13px] text-faint">
                      <span className="hidden tabular-nums sm:inline">{r.pushed_at ? `Pushed ${ago(r.pushed_at)}` : ''}</span>
                      <ArrowRight size={16} weight="bold" className="text-cobalt opacity-0 transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100" />
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>

      {data && data.pages > 1 && (
        <nav aria-label="Pages" className="mt-5 flex items-center justify-between gap-4 text-[14px]">
          <p className="text-faint tabular-nums">
            {from} to {to} of {data.total}
          </p>
          <div className="flex gap-1">
            <button
              type="button"
              disabled={data.page <= 1}
              onClick={() => go(data.page - 1)}
              className="inline-flex h-9 items-center gap-1 rounded-full px-3 text-muted transition-colors hover:bg-paper-2 hover:text-ink disabled:opacity-35 disabled:hover:bg-transparent"
            >
              <CaretLeft size={13} weight="bold" />
              Previous
            </button>
            <button
              type="button"
              disabled={data.page >= data.pages}
              onClick={() => go(data.page + 1)}
              className="inline-flex h-9 items-center gap-1 rounded-full px-3 text-muted transition-colors hover:bg-paper-2 hover:text-ink disabled:opacity-35 disabled:hover:bg-transparent"
            >
              Next
              <CaretRight size={13} weight="bold" />
            </button>
          </div>
        </nav>
      )}

      {data && (data.private || data.truncated) && (
        <div className="mt-6 space-y-1.5 text-[14px] leading-relaxed text-muted">
          {data.truncated && <p>This is the 500 most recently pushed. Type owner/name above for any other.</p>}
          {data.private && me.app_access_url && (
            <p>
              An organisation missing? It may limit which OAuth apps can read its repositories.{' '}
              <a href={me.app_access_url} target="_blank" rel="noreferrer" className="inline-flex items-baseline gap-0.5 font-semibold text-cobalt hover:text-cobalt-deep">
                Request access on GitHub
                <ArrowUpRight size={12} weight="bold" className="self-center" />
              </a>
            </p>
          )}
        </div>
      )}
    </section>
  )
}
