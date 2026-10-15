// The tools a workspace reads (Slack, Notion, Linear, Jira, Confluence) and the files uploaded to it.
// See server/src/canon/api/connections_routes.py. The server never sends a credential back.

import type { Job, ServerWorkspace } from './account'

export type SourceKind = 'slack' | 'notion' | 'linear' | 'jira' | 'confluence' | 'upload'

export type Connection = {
  id: string
  kind: SourceKind
  label: string
  config: Record<string, unknown>
  info: Record<string, string>
  status: 'new' | 'syncing' | 'ok' | 'failed'
  created_at: string | null
  created_by: string | null
  last_synced_at: string | null
  last_tried_at: string | null
  counts: { documents?: number; passages?: number; facts?: number; people?: number }
  notes: string[]
  error: string | null
}

export type ConnectionJob = Job & { connection?: string | null }

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(path, { ...init, headers: { accept: 'application/json', ...init?.headers } })
  } catch (e) {
    if ((e as Error).name === 'AbortError') throw e
    throw new Error('Canon could not be reached. Try again in a moment.')
  }
  if (!res.ok) {
    let detail = ''
    try {
      const body = await res.json()
      detail = typeof body?.detail === 'string' ? body.detail : ''
    } catch {
      // not JSON
    }
    throw new Error(detail || (res.status === 401 ? 'Sign in first.' : 'Canon could not do that. Try again in a moment.'))
  }
  return (await res.json()) as T
}

const json = (body: unknown): RequestInit => ({ method: 'POST', body: JSON.stringify(body), headers: { 'content-type': 'application/json' } })
const w = (ws: string) => `/api/w/${encodeURIComponent(ws)}`

export const listConnections = (ws: string, signal?: AbortSignal) =>
  call<{ connections: Connection[]; job: ConnectionJob | null; can_connect: boolean }>(`${w(ws)}/connections`, { signal })

export const createConnection = (ws: string, body: { kind: SourceKind; label?: string; config: Record<string, unknown>; secret: string }) =>
  call<{ connection: Connection; job: ConnectionJob | null }>(`${w(ws)}/connections`, json(body))

export const syncConnection = (ws: string, id: string) =>
  call<{ job: ConnectionJob; connection: Connection }>(`${w(ws)}/connections/${encodeURIComponent(id)}/sync`, { method: 'POST' })

export const removeConnection = (ws: string, id: string, documents: 'keep' | 'delete') =>
  call<{ removed: string; documents: number; kept: boolean }>(`${w(ws)}/connections/${encodeURIComponent(id)}?documents=${documents}`, { method: 'DELETE' })

export function uploadFiles(ws: string, files: File[]) {
  const form = new FormData()
  for (const f of files) form.append('files', f, f.name)
  form.append('modified', JSON.stringify(files.map((f) => f.lastModified || 0)))
  return call<{ job: ConnectionJob; connection: Connection }>(`${w(ws)}/files`, { method: 'POST', body: form })
}

export const createBlankWorkspace = (name: string) => call<{ workspace: ServerWorkspace }>('/api/workspaces/blank', json({ name }))
