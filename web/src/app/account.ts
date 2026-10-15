// Who is signed in, the workspaces they can open, and the jobs that fill a workspace from GitHub.

import { useCallback, useEffect, useState } from 'react'

export type Me = {
  user: { login: string; name: string; dev: boolean; private_repos?: boolean } | null
  signin: boolean
  dev_login: boolean
  /** Where on GitHub a user grants or requests Canon's access to an organisation. */
  app_access_url?: string | null
}

/** An error from the API, with the server's short reason and a link that fixes it, when it gave them. */
export class ApiError extends Error {
  status: number
  reason: string | null
  link: string | null
  constructor(message: string, status: number, reason: string | null = null, link: string | null = null) {
    super(message)
    this.status = status
    this.reason = reason
    this.link = link
  }
}

export type Job = {
  id: string
  kind: 'create' | 'sync' | 'upload'
  status: 'running' | 'done' | 'failed'
  step: string | null
  step_label: string
  progress: number
  counts: Record<string, number>
  error: string | null
  started_at: string | null
  finished_at: string | null
}

export type ServerWorkspace = {
  slug: string
  name: string
  repo: string | null
  public: boolean
  role: string | null
  /** Made from a private repository. */
  private?: boolean
  job?: Job | null
  suggestions?: string[]
}

export type Repo = {
  full_name: string
  owner: string
  owner_kind: 'user' | 'org'
  name: string
  private: boolean
  description: string
  pushed_at: string | null
  archived: boolean
}

export type RepoOwner = { login: string; kind: 'user' | 'org'; count: number }

export type RepoList = {
  connected: boolean
  private: boolean
  login: string
  truncated: boolean
  owners: RepoOwner[]
  groups: { owner: string; kind: 'user' | 'org'; you: boolean; repos: Repo[] }[]
  page: number
  pages: number
  total: number
  size: number
}

export type Member = { login: string; name: string; role: 'owner' | 'member'; you: boolean }

export type Members = {
  role: 'owner' | 'member' | null
  private: boolean
  repo: string | null
  members: Member[]
  invites: { login: string; at: string | null }[]
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(path, { ...init, headers: { accept: 'application/json', 'content-type': 'application/json', ...init?.headers } })
  } catch (e) {
    if ((e as Error).name === 'AbortError') throw e
    throw new Error('Canon could not be reached. Try again in a moment.')
  }
  if (!res.ok) {
    let detail = ''
    let reason: string | null = null
    let link: string | null = null
    try {
      const body = await res.json()
      detail = typeof body?.detail === 'string' ? body.detail : ''
      reason = typeof body?.reason === 'string' ? body.reason : null
      link = typeof body?.link === 'string' && body.link.startsWith('https://github.com/') ? body.link : null
    } catch {
      // not JSON
    }
    throw new ApiError(detail || (res.status === 401 ? 'Sign in first.' : 'Canon could not do that. Try again in a moment.'), res.status, reason, link)
  }
  return (await res.json()) as T
}

export const getMe = (signal?: AbortSignal) => call<Me>('/api/me', { signal })
export const listWorkspaces = (signal?: AbortSignal) => call<{ public: ServerWorkspace[]; own: ServerWorkspace[] }>('/api/workspaces', { signal })
export const createWorkspace = (repo: string) =>
  call<{ workspace: ServerWorkspace; job: Job | null; created: boolean }>('/api/workspaces', { method: 'POST', body: JSON.stringify({ repo }) })
export const syncWorkspace = (ws: string) => call<{ job: Job }>(`/api/w/${encodeURIComponent(ws)}/sync`, { method: 'POST' })
export const latestJob = (ws: string, signal?: AbortSignal) => call<{ job: Job | null }>(`/api/w/${encodeURIComponent(ws)}/jobs/latest`, { signal })
export const signOut = () => call<{ ok: boolean }>('/auth/logout', { method: 'POST' })

export function listRepos({ q = '', owner = '', page = 1 }: { q?: string; owner?: string; page?: number }, signal?: AbortSignal) {
  const query = new URLSearchParams({ q, owner, page: String(page) })
  return call<RepoList>(`/api/github/repos?${query}`, { signal })
}

const membersPath = (ws: string) => `/api/w/${encodeURIComponent(ws)}/members`
export const getMembers = (ws: string, signal?: AbortSignal) => call<Members>(membersPath(ws), { signal })
export const inviteMember = (ws: string, login: string) =>
  call<Members & { status: 'invited' | 'member'; login: string }>(membersPath(ws), { method: 'POST', body: JSON.stringify({ login }) })
export const removeMember = (ws: string, login: string) =>
  call<Members | { left: true }>(`${membersPath(ws)}/${encodeURIComponent(login)}`, { method: 'DELETE' })

/** Where sign-in goes, and comes back to. */
export function signInUrl(me: Me | null, next = window.location.pathname): string | null {
  if (!me) return null
  const back = encodeURIComponent(next)
  if (me.signin) return `/auth/github?next=${back}`
  if (me.dev_login) return `/auth/dev-login?next=${back}`
  return null
}

/** The second GitHub step: connect private and organisation repositories (`repo read:org`). */
export function connectUrl(me: Me | null, next = '/app/new'): string | null {
  if (!me?.signin) return null
  return `/auth/github?access=private&next=${encodeURIComponent(next)}`
}

export function useMe() {
  const [me, setMe] = useState<Me | null>(null)
  const load = useCallback((signal?: AbortSignal) => {
    getMe(signal).then(setMe, (e: Error) => e.name !== 'AbortError' && setMe({ user: null, signin: false, dev_login: false }))
  }, [])
  useEffect(() => {
    const ctrl = new AbortController()
    load(ctrl.signal)
    return () => ctrl.abort()
  }, [load])
  return { me, reload: () => load() }
}

/** The workspace's latest job, polled while one runs. `kick` starts polling again after a new job begins. */
export function useJob(ws: string | null, { initial = null }: { initial?: Job | null } = {}) {
  const [job, setJob] = useState<Job | null>(initial)
  const [tick, setTick] = useState(0)
  useEffect(() => {
    if (!ws) return
    let stopped = false
    let timer: number | undefined
    const ctrl = new AbortController()
    const poll = () => {
      latestJob(ws, ctrl.signal).then(
        ({ job }) => {
          if (stopped) return
          setJob(job)
          if (job?.status === 'running') timer = window.setTimeout(poll, 900)
        },
        () => {
          if (!stopped) timer = window.setTimeout(poll, 3000)
        },
      )
    }
    poll()
    return () => {
      stopped = true
      ctrl.abort()
      window.clearTimeout(timer)
    }
  }, [ws, tick])
  return { job, kick: () => setTick((t) => t + 1), setJob }
}

/** "3 hours ago", from an ISO time. */
export function ago(iso: string | null | undefined): string {
  if (!iso) return ''
  const seconds = Math.max(0, (Date.now() - Date.parse(iso)) / 1000)
  if (seconds < 60) return 'just now'
  const units: [number, string][] = [
    [86400, 'day'],
    [3600, 'hour'],
    [60, 'minute'],
  ]
  for (const [size, name] of units) {
    if (seconds >= size) {
      const n = Math.floor(seconds / size)
      return `${n} ${name}${n === 1 ? '' : 's'} ago`
    }
  }
  return 'just now'
}
