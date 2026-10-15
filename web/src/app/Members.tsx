// Who can open a workspace: its owner and the teammates they invite by GitHub handle. A sheet beside the screen on
// a wide window, a bottom sheet on a narrow one.

import { Lock, X } from '@phosphor-icons/react'
import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import { getMembers, inviteMember, removeMember, type Members as MemberList } from './account'
import { Sheet } from './Sheet'
import type { Workspace } from './workspaces'

function Initial({ login, you, invited = false }: { login: string; you?: boolean; invited?: boolean }) {
  const tone = invited ? 'text-faint shadow-[inset_0_0_0_1.5px_var(--line-strong)]' : you ? 'bg-cobalt text-paper' : 'bg-paper-2 text-ink'
  return (
    <span aria-hidden="true" className={`grid size-9 shrink-0 place-items-center rounded-full text-[13.5px] font-semibold uppercase ${tone}`}>
      {login.slice(0, 1)}
    </span>
  )
}

function Panel({ ws, onClose, onLeft }: { ws: Workspace; onClose: () => void; onLeft: () => void }) {
  const [list, setList] = useState<MemberList | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [said, setSaid] = useState<string | null>(null)
  const [handle, setHandle] = useState('')
  const [busy, setBusy] = useState<string | null>(null)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const ctrl = new AbortController()
    getMembers(ws.slug, ctrl.signal).then(setList, (e: Error) => e.name !== 'AbortError' && setError(e.message))
    return () => ctrl.abort()
  }, [ws.slug])
  useEffect(() => ref.current?.focus({ preventScroll: true }), [])

  const owner = list?.role === 'owner'
  const invite = (e: FormEvent) => {
    e.preventDefault()
    const login = handle.trim()
    if (!login || busy) return
    setBusy('invite')
    setError(null)
    setSaid(null)
    inviteMember(ws.slug, login).then(
      (r) => {
        setList(r)
        setHandle('')
        setSaid(r.status === 'member' ? `${r.login} is already a member.` : `Invited ${r.login}.`)
        setBusy(null)
      },
      (e: Error) => {
        setError(e.message)
        setBusy(null)
      },
    )
  }
  const remove = (login: string) => {
    setBusy(login)
    setError(null)
    setSaid(null)
    removeMember(ws.slug, login).then(
      (r) => {
        setBusy(null)
        if ('left' in r) onLeft()
        else setList(r)
      },
      (e: Error) => {
        setError(e.message)
        setBusy(null)
      },
    )
  }

  return (
    <div ref={ref} tabIndex={-1} className="outline-none">
      <header className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <p className="truncate text-[14px] text-muted">{ws.label}</p>
          <h2 id="members-title" className="mt-1.5 text-[24px] leading-tight font-semibold tracking-[-0.02em] text-ink">
            Members
          </h2>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close members"
          className="-mt-1 -mr-1 grid size-9 shrink-0 place-items-center rounded-full text-muted transition-colors hover:bg-paper-2 hover:text-ink focus-visible:outline-2 focus-visible:outline-cobalt"
        >
          <X size={17} weight="bold" />
        </button>
      </header>

      <p className="mt-4 flex gap-2.5 text-[14.5px] leading-relaxed text-muted">
        <Lock size={16} weight="bold" className="mt-[3px] shrink-0 text-ink" aria-hidden="true" />
        <span>
          Only members can open this workspace.
          {(list?.private ?? ws.private) && ' It was made from a private repository, so members see what Canon read from it.'}
        </span>
      </p>

      {!list && !error && (
        <div aria-hidden="true" className="mt-7 space-y-4">
          {[0, 1].map((i) => (
            <div key={i} className="flex items-center gap-3">
              <span className="size-9 animate-pulse rounded-full bg-paper-2" />
              <span className="h-3.5 w-32 animate-pulse rounded bg-paper-2" />
            </div>
          ))}
        </div>
      )}

      {list && (
        <ul className="mt-6 border-t border-line">
          {list.members.map((m) => (
            <li key={m.login} className="flex min-h-[60px] items-center gap-3 border-b border-line py-2.5">
              <Initial login={m.login} you={m.you} />
              <div className="min-w-0 flex-1 leading-tight">
                <p className="truncate text-[15px] font-semibold text-ink">
                  {m.login}
                  {m.you && <span className="font-normal text-faint"> (you)</span>}
                </p>
                <p className="mt-0.5 truncate text-[13px] text-faint">{m.role === 'owner' ? 'Owner' : m.name && m.name !== m.login ? m.name : 'Member'}</p>
              </div>
              {m.role !== 'owner' && (owner || m.you) && (
                <button
                  type="button"
                  disabled={busy === m.login}
                  onClick={() => remove(m.login)}
                  className="shrink-0 rounded-full px-3 py-1.5 text-[13.5px] text-muted transition-colors hover:bg-proof-soft hover:text-proof disabled:opacity-50"
                >
                  {m.you ? 'Leave' : 'Remove'}
                </button>
              )}
            </li>
          ))}
          {list.invites.map((i) => (
            <li key={`invite-${i.login}`} className="flex min-h-[60px] items-center gap-3 border-b border-line py-2.5">
              <Initial login={i.login} invited />
              <div className="min-w-0 flex-1 leading-tight">
                <p className="truncate text-[15px] font-semibold text-muted">{i.login}</p>
                <p className="mt-0.5 text-[13px] text-faint">Invited, joins at next sign-in</p>
              </div>
              <button
                type="button"
                disabled={busy === i.login}
                onClick={() => remove(i.login)}
                className="shrink-0 rounded-full px-3 py-1.5 text-[13.5px] text-muted transition-colors hover:bg-paper-2 hover:text-ink disabled:opacity-50"
              >
                Cancel
              </button>
            </li>
          ))}
        </ul>
      )}

      {owner && (
        <form onSubmit={invite} className="mt-8">
          <label htmlFor="invite-handle" className="text-[14px] font-semibold text-ink">
            Invite a teammate
          </label>
          <div className="mt-2.5 flex gap-2">
            <input
              id="invite-handle"
              value={handle}
              onChange={(e) => setHandle(e.target.value)}
              placeholder="GitHub handle"
              autoComplete="off"
              autoCapitalize="off"
              spellCheck={false}
              maxLength={60}
              className="h-11 min-w-0 flex-1 rounded-full bg-paper-2 px-4 text-[15px] text-ink outline-none placeholder:text-faint focus:shadow-[inset_0_0_0_1.5px_var(--ink)]"
            />
            <button
              type="submit"
              disabled={!handle.trim() || busy === 'invite'}
              className="h-11 shrink-0 rounded-full bg-ink px-5 text-[14.5px] font-semibold text-paper transition-[background-color,opacity] hover:bg-[#23252d] disabled:opacity-25"
            >
              Invite
            </button>
          </div>
          <p className="mt-2.5 text-[13.5px] leading-relaxed text-faint">They become a member the next time they sign in to Canon with GitHub.</p>
        </form>
      )}

      {said && (
        <p role="status" className="mt-4 text-[14.5px] text-ink">
          {said}
        </p>
      )}
      {error && (
        <p role="alert" className="mt-4 text-[14.5px] text-proof">
          {error}
        </p>
      )}
    </div>
  )
}

export function MembersSheet({ ws, open, onClose, onLeft }: { ws: Workspace; open: boolean; onClose: () => void; onLeft: () => void }) {
  const close = useCallback(() => onClose(), [onClose])
  return (
    <Sheet open={open} onClose={close} labelledBy="members-title" width="w-[min(420px,38vw)]">
      {open && <Panel key={ws.slug} ws={ws} onClose={close} onLeft={onLeft} />}
    </Sheet>
  )
}
