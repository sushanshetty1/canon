// Sources: what a workspace reads, drawn as an intake. Each kind of source (docs, tickets, chats, decisions, code
// owners, people) is a row with its own document shape; a band runs from it into one column, the graph, as thick as
// the facts it brought. A source that brought no facts yet is a dashed hairline. Below: each kind in words, where the
// workspace reads from, and, on a workspace of your own, a way to add a Slack or a Notion or Confluence export.

import { FileZip, GithubLogo, Plug, SlackLogo, UploadSimple, type Icon } from '@phosphor-icons/react'
import { motion, useInView, useReducedMotion } from 'motion/react'
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { ago, useJob } from './account'
import { SOURCES as CONNECTABLE } from './Connect'
import { sources as getSources, uploadExport, type Connection, type SourceFamily, type SourceKey, type SourcesView, type UploadKind } from './api'
import { ease } from './Answer'
import { useWide } from './Sheet'
import { formatDate, kindLabel } from './text'
import { Problem } from './WhoKnows'
import type { Workspace } from './workspaces'

const STROKE = '#8b909a'
const FILL = 'var(--paper-2)'

const NAMES: Record<SourceKey, string> = {
  docs: 'Docs',
  tickets: 'Tickets',
  chats: 'Chats',
  decisions: 'Decisions',
  code_owners: 'Code owners',
  people: 'People',
}

// One tone per kind of source, from the app's palette: the bands and the graph's column share them.
const TONES: Record<SourceKey, { fill: string; text: string }> = {
  docs: { fill: 'var(--cobalt)', text: 'var(--paper)' },
  decisions: { fill: 'var(--ink)', text: 'var(--paper)' },
  code_owners: { fill: 'var(--marker)', text: 'var(--ink)' },
  people: { fill: 'var(--amber)', text: 'var(--paper)' },
  tickets: { fill: '#8b909a', text: 'var(--paper)' },
  chats: { fill: '#8d9cf3', text: 'var(--ink)' },
}

/** Where a kind of source stands when two disagree: the graph, not a model, decides which wins. */
const RANK: Record<SourceKey, string> = {
  code_owners: 'The authority on who owns what. It outranks every other source.',
  decisions: 'An accepted decision outranks a page that says otherwise.',
  docs: 'Pages people keep up to date. Team pages outrank the handbook.',
  people: 'Who leads and belongs to each team, from published rosters.',
  tickets: 'What someone said on a day. A page outranks it when they disagree.',
  chats: 'What someone said on a day, with who said it. A page outranks it when they disagree.',
}

// Each kind of source has its own document shape, drawn in a 40 x 48 box.
const glyphs: Record<SourceKey, ReactNode> = {
  docs: (
    <>
      <path d="M4 2 H26 L36 12 V46 H4 Z" fill={FILL} stroke={STROKE} strokeWidth="1.5" strokeLinejoin="round" />
      <path d="M26 2 V12 H36" fill="none" stroke={STROKE} strokeWidth="1.5" strokeLinejoin="round" />
      <rect x="9" y="17" width="17" height="4" rx="2" fill="var(--ink)" />
      <rect x="9" y="26" width="22" height="2.5" rx="1.25" fill={STROKE} />
      <rect x="9" y="32" width="22" height="2.5" rx="1.25" fill={STROKE} />
      <rect x="9" y="38" width="14" height="2.5" rx="1.25" fill={STROKE} />
    </>
  ),
  tickets: (
    <>
      <rect x="4" y="2" width="32" height="44" rx="4" fill={FILL} stroke={STROKE} strokeWidth="1.5" />
      <circle cx="14" cy="14" r="5" fill="none" stroke="var(--ink)" strokeWidth="1.5" />
      <circle cx="14" cy="14" r="1.6" fill="var(--ink)" />
      <rect x="9" y="26" width="22" height="2.5" rx="1.25" fill={STROKE} />
      <rect x="9" y="32" width="16" height="2.5" rx="1.25" fill={STROKE} />
    </>
  ),
  chats: (
    <>
      <path d="M3 6 a4 4 0 0 1 4 -4 H25 a4 4 0 0 1 4 4 V18 a4 4 0 0 1 -4 4 H11 L6 27 V22 a4 4 0 0 1 -3 -4 Z" fill={FILL} stroke={STROKE} strokeWidth="1.5" strokeLinejoin="round" />
      <path d="M11 24 a4 4 0 0 1 4 -4 H33 a4 4 0 0 1 4 4 V36 a4 4 0 0 1 -3 4 V45 L29 40 H15 a4 4 0 0 1 -4 -4 Z" fill="var(--paper)" stroke="var(--ink)" strokeWidth="1.5" strokeLinejoin="round" />
      <rect x="16" y="27" width="15" height="2.5" rx="1.25" fill={STROKE} />
      <rect x="16" y="33" width="10" height="2.5" rx="1.25" fill={STROKE} />
    </>
  ),
  decisions: (
    <>
      <rect x="4" y="2" width="32" height="44" rx="4" fill={FILL} stroke={STROKE} strokeWidth="1.5" />
      <rect x="9" y="9" width="18" height="3.5" rx="1.75" fill="var(--ink)" />
      <rect x="9" y="17" width="22" height="2.5" rx="1.25" fill={STROKE} />
      <rect x="9" y="23" width="15" height="2.5" rx="1.25" fill={STROKE} />
      <circle cx="26" cy="36" r="6.5" fill="var(--cobalt)" />
      <path d="M23 36 L25.2 38.2 L29 34.2" fill="none" stroke="var(--paper)" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
    </>
  ),
  code_owners: (
    <>
      <g fill="none" stroke={STROKE} strokeWidth="1.5">
        <path d="M20 13 V22 M8 22 H32 M8 22 V31 M20 22 V31 M32 22 V31" />
      </g>
      <rect x="13" y="3" width="14" height="10" rx="3" fill="var(--marker)" stroke="#d9b400" strokeWidth="1" />
      <rect x="3" y="31" width="10" height="10" rx="3" fill={FILL} stroke={STROKE} strokeWidth="1.5" />
      <rect x="15" y="31" width="10" height="10" rx="3" fill={FILL} stroke={STROKE} strokeWidth="1.5" />
      <rect x="27" y="31" width="10" height="10" rx="3" fill={FILL} stroke={STROKE} strokeWidth="1.5" />
    </>
  ),
  people: (
    <>
      <circle cx="13" cy="15" r="6" fill={FILL} stroke="var(--ink)" strokeWidth="1.5" />
      <path d="M3 40 Q3 26 13 26 Q23 26 23 40 Z" fill={FILL} stroke="var(--ink)" strokeWidth="1.5" strokeLinejoin="round" />
      <circle cx="28" cy="19" r="5" fill={FILL} stroke={STROKE} strokeWidth="1.5" />
      <path d="M20 42 Q20 30 28 30 Q37 30 37 42 Z" fill={FILL} stroke={STROKE} strokeWidth="1.5" strokeLinejoin="round" />
    </>
  ),
}

const n = (v: number) => v.toLocaleString('en-US')
/** "2,152 facts": a count with its noun, the number grouped. */
const count = (v: number, one: string, many = `${one}s`) => `${n(v)} ${v === 1 ? one : many}`

// What each document kind is called, many at a time.
const MANY: Record<string, [string, string]> = {
  handbook: ['handbook page', 'handbook pages'],
  team_page: ['team page', 'team pages'],
  doc: ['doc', 'docs'],
  wiki: ['wiki page', 'wiki pages'],
  notion_page: ['Notion page', 'Notion pages'],
  confluence_page: ['Confluence page', 'Confluence pages'],
  upload: ['uploaded page', 'uploaded pages'],
  issue: ['issue', 'issues'],
  pull: ['pull request', 'pull requests'],
  linear_issue: ['Linear issue', 'Linear issues'],
  jira_issue: ['Jira issue', 'Jira issues'],
  forum: ['forum thread', 'forum threads'],
  discussion: ['discussion', 'discussions'],
  comment_thread: ['comment thread', 'comment threads'],
  slack_thread: ['Slack thread', 'Slack threads'],
  rfc: ['RFC', 'RFCs'],
  adr: ['decision record', 'decision records'],
  release: ['release', 'releases'],
  ownership_map: ['ownership map version', 'ownership map versions'],
  roster: ['team roster', 'team rosters'],
}
const kindCount = (kind: string, v: number) => {
  const [one, many] = MANY[kind] ?? [kindLabel(kind).toLowerCase(), `${kindLabel(kind).toLowerCase()}s`]
  return count(v, one, many)
}

/** What a kind of source holds, in a few words: "573 pages", "80 decisions", "237 people in 77 teams". */
function holds(f: SourceFamily): string {
  switch (f.key) {
    case 'docs':
      return count(f.documents, 'page')
    case 'tickets':
      return `${n(f.documents)} issues and pull requests`
    case 'chats':
      return count(f.documents, 'thread')
    case 'decisions':
      return f.decisions ? count(f.decisions, 'decision') : count(f.documents, 'record')
    case 'code_owners':
      return f.areas ? `${n(f.areas)} areas owned` : count(f.documents, 'version')
    case 'people':
      return f.teams ? `${n(f.people ?? 0)} people in ${count(f.teams, 'team')}` : count(f.people ?? 0, 'person', 'people')
  }
}

function when(f: SourceFamily): string {
  if (f.last_read) return `Read ${ago(f.last_read)}`
  if (f.newest) return `Newest from ${formatDate(f.newest)}`
  return ''
}

// ----- the intake --------------------------------------------------------------------------------------------------

type Layout = {
  width: number
  rowH: number
  top: number
  glyph: number
  textX: number
  nameSize: number
  subSize: number
  bandFrom: number
  barX: number
  barW: number
  labels: boolean
  barTop: number
  barH: number
  maxBand: number
}

const desktop: Layout = {
  width: 1000,
  rowH: 80,
  top: 10,
  glyph: 1,
  textX: 58,
  nameSize: 17,
  subSize: 13.5,
  bandFrom: 330,
  barX: 760,
  barW: 26,
  labels: true,
  barTop: 40,
  barH: 420,
  maxBand: 30,
}

const phone: Layout = {
  width: 360,
  rowH: 70,
  top: 6,
  glyph: 0.78,
  textX: 42,
  nameSize: 15,
  subSize: 12.5,
  bandFrom: 218,
  barX: 330,
  barW: 18,
  labels: false,
  barTop: 22,
  barH: 386,
  maxBand: 22,
}

type Band = { f: SourceFamily; y: number; top: number; h: number; t: number }

/** Where each kind of source's band starts and lands: a column split by facts, in row order. Kinds with no facts yet
 *  land as a hairline at the column's foot. */
function bands(families: SourceFamily[], L: Layout): Band[] {
  const total = families.reduce((s, f) => s + f.facts, 0) || 1
  const live = families.filter((f) => f.facts > 0)
  const gap = 4
  const room = L.barH - gap * Math.max(0, live.length - 1)
  const min = 4
  const raw = families.map((f) => (f.facts > 0 ? Math.max(min, (room * f.facts) / total) : 0))
  const scale = room / (raw.reduce((s, h) => s + h, 0) || 1)
  let at = L.barTop
  return families.map((f, i) => {
    const y = L.top + i * L.rowH + L.rowH / 2 - 4
    if (!f.facts) return { f, y, top: L.barTop + L.barH, h: 0, t: 0 }
    const h = raw[i] * scale
    const band = { f, y, top: at, h, t: Math.max(3, Math.min(L.maxBand, h)) }
    at += h + gap
    return band
  })
}

function bandPath(b: Band, L: Layout): string {
  const x0 = L.bandFrom
  const x1 = L.barX
  const mid = (x0 + x1) / 2
  const a = b.y - b.t / 2
  const c = b.y + b.t / 2
  return `M ${x0} ${a} C ${mid} ${a}, ${mid} ${b.top}, ${x1} ${b.top} L ${x1} ${b.top + b.h} C ${mid} ${b.top + b.h}, ${mid} ${c}, ${x0} ${c} Z`
}

function Intake({ view, layout: L, className }: { view: SourcesView; layout: Layout; className: string }) {
  const ref = useRef<SVGSVGElement>(null)
  const seen = useInView(ref, { once: true, amount: 0.3 })
  const reduce = !!useReducedMotion()
  const run = seen || reduce
  const fams = view.families
  const placed = bands(fams, L)
  const height = Math.max(L.top + fams.length * L.rowH, L.barTop + L.barH) + 12
  const totalFacts = fams.reduce((s, f) => s + f.facts, 0)
  const clip = `intake-clip-${L.width}`

  return (
    <svg ref={ref} viewBox={`0 0 ${L.width} ${height}`} className={className} role="img" aria-label="Each kind of source this workspace reads, and the facts it brought into the graph">
      <defs>
        <clipPath id={clip}>
          <motion.rect
            x={L.bandFrom - 2}
            y={0}
            height={height}
            initial={reduce ? false : { width: 0 }}
            animate={{ width: run ? L.barX - L.bandFrom + L.barW + 4 : 0 }}
            transition={{ duration: reduce ? 0 : 1.1, delay: reduce ? 0 : 0.15, ease }}
          />
        </clipPath>
      </defs>

      {/* Bands: from each kind of source into the graph, as thick as the facts it brought */}
      <g clipPath={`url(#${clip})`}>
        {placed.map((b) =>
          b.f.facts ? (
            <path key={b.f.key} d={bandPath(b, L)} fill={TONES[b.f.key].fill} opacity={0.22} />
          ) : (
            <path
              key={b.f.key}
              d={`M ${L.bandFrom} ${b.y} C ${(L.bandFrom + L.barX) / 2} ${b.y}, ${(L.bandFrom + L.barX) / 2} ${L.barTop + L.barH}, ${L.barX} ${L.barTop + L.barH}`}
              fill="none"
              stroke="var(--line-strong)"
              strokeWidth="1.3"
              strokeDasharray="4 5"
            />
          ),
        )}
        {placed.map((b) =>
          b.f.facts ? (
            <path
              key={`edge-${b.f.key}`}
              d={`M ${L.bandFrom} ${b.y} C ${(L.bandFrom + L.barX) / 2} ${b.y}, ${(L.bandFrom + L.barX) / 2} ${b.top + b.h / 2}, ${L.barX} ${b.top + b.h / 2}`}
              fill="none"
              stroke={TONES[b.f.key].fill === 'var(--marker)' ? '#d9b400' : TONES[b.f.key].fill}
              strokeWidth="1.3"
              opacity={0.75}
            />
          ) : null,
        )}
        {/* The graph: one column, split by the facts each kind of source stated */}
        {placed.map((b) =>
          b.f.facts ? <rect key={`bar-${b.f.key}`} x={L.barX} y={b.top} width={L.barW} height={b.h} rx={Math.min(5, b.h / 2)} fill={TONES[b.f.key].fill} /> : null,
        )}
      </g>

      {L.labels && (
        <motion.g initial={reduce ? false : { opacity: 0 }} animate={{ opacity: run ? 1 : 0 }} transition={{ duration: 0.4, delay: reduce ? 0 : 1.05 }}>
          <text x={L.barX} y={L.barTop - 16} fontSize="14" fontWeight="600" fill="var(--ink)">
            {n(totalFacts)} facts
          </text>
          {placed.map((b) =>
            b.f.facts && b.h >= 16 ? (
              <text key={`l-${b.f.key}`} x={L.barX + L.barW + 12} y={b.top + b.h / 2 + 4.5} fontSize="13.5" fill="var(--muted)" style={{ fontVariantNumeric: 'tabular-nums' }}>
                <tspan fontWeight="600" fill="var(--ink)">
                  {n(b.f.facts)}
                </tspan>{' '}
                from {NAMES[b.f.key].toLowerCase()}
              </text>
            ) : null,
          )}
        </motion.g>
      )}

      {/* The sources, each with its own shape */}
      {placed.map((b, i) => {
        const y = L.top + i * L.rowH
        const g = L.glyph
        const f = b.f
        const facts = f.facts ? `${count(f.facts, 'fact')}` : 'no facts yet'
        return (
          <g key={`row-${f.key}`}>
            <g transform={`translate(0 ${y + (L.rowH - 48 * g) / 2 - 4}) scale(${g})`}>{glyphs[f.key]}</g>
            <text x={L.textX} y={y + L.rowH / 2 - 12} fontSize={L.nameSize} fontWeight="600" fill="var(--ink)">
              {NAMES[f.key]}
            </text>
            <text x={L.textX} y={y + L.rowH / 2 + 8} fontSize={L.subSize} fill="var(--muted)" style={{ fontVariantNumeric: 'tabular-nums' }}>
              {holds(f)}
            </text>
            <text x={L.textX} y={y + L.rowH / 2 + 26} fontSize={L.subSize} fill={f.facts ? 'var(--ink)' : 'var(--faint)'} style={{ fontVariantNumeric: 'tabular-nums' }}>
              {facts}
            </text>
          </g>
        )
      })}
    </svg>
  )
}

// ----- each kind in words ------------------------------------------------------------------------------------------

const STATUS_WORDS: Record<string, string> = {
  accepted: 'in force',
  superseded: 'replaced',
  retired: 'out of date',
  proposed: 'open',
  withdrawn: 'closed',
  rejected: 'rejected',
}

function parts(f: SourceFamily): string {
  if (f.key === 'people') {
    const said = f.speakers ? `, ${count(f.speakers, 'person', 'people')} with words on record in a thread` : ''
    const teams = f.teams ? ` and ${count(f.teams, 'team')}` : ''
    return `${count(f.people ?? 0, 'person', 'people')}${teams}${said}.`
  }
  const kinds = f.kinds.map((k) => kindCount(k.kind, k.documents))
  let line = kinds.length ? `${kinds.join(', ')}.` : 'Nothing read yet.'
  if (f.key === 'decisions' && f.statuses) {
    const s = Object.entries(f.statuses)
      .sort((a, b) => b[1] - a[1])
      .map(([k, v]) => `${v} ${STATUS_WORDS[k] ?? k}`)
    if (s.length) line += ` Decisions: ${s.join(', ')}.`
  }
  const speakers = f.kinds.reduce((s, k) => s + k.speakers, 0)
  if (speakers) line += ` Words from ${count(speakers, 'person', 'people')}, each passage with who said it and when.`
  return line
}

function Details({ families }: { families: SourceFamily[] }) {
  return (
    <ol className="divide-y divide-line border-y border-line">
      {families.map((f) => (
        <li key={f.key} className="grid grid-cols-1 gap-x-8 gap-y-1.5 py-5 sm:grid-cols-[180px_minmax(0,1fr)] sm:py-6">
          <div className="flex items-center gap-2.5 self-start sm:pt-0.5">
            <span className="h-[5px] w-4 shrink-0 rounded-full" style={{ background: TONES[f.key].fill }} aria-hidden="true" />
            <h3 className="text-[16.5px] font-semibold tracking-[-0.01em] text-ink">{NAMES[f.key]}</h3>
          </div>
          <div className="min-w-0">
            <p className="text-[15.5px] leading-relaxed text-ink">{parts(f)}</p>
            <p className="mt-1 text-[14.5px] leading-relaxed text-muted">
              {f.facts ? `${count(f.facts, 'fact')}, ${n(f.current_facts)} current. ` : 'No facts from these yet. '}
              {RANK[f.key]}
            </p>
            {when(f) && <p className="mt-1 text-[13.5px] text-faint">{when(f)}</p>}
          </div>
        </li>
      ))}
    </ol>
  )
}

// ----- where it reads from, and adding an export ------------------------------------------------------------------

// An export upload is a zip; uploaded files and the live connectors draw the mark the Connect panel draws.
const CONNECTION_ICONS: Record<string, Icon> = {
  github: GithubLogo,
  ...Object.fromEntries(CONNECTABLE.map((s) => [s.kind, s.icon])),
}
const iconOf = (c: Connection): Icon => (c.kind === 'upload' && c.config.format ? FileZip : (CONNECTION_ICONS[c.kind] ?? Plug))

function connectionDetail(c: Connection): string {
  const cfg = c.config
  if (c.kind === 'github' && cfg.repo) return String(cfg.repo)
  if (c.kind === 'upload' && cfg.format) {
    const what = cfg.format === 'slack' ? count(Number(cfg.documents ?? 0), 'thread') : count(Number(cfg.documents ?? 0), 'page')
    return [cfg.filename, what].filter(Boolean).join(', ')
  }
  // Uploaded files and the live connectors: where, and how much of it is in the graph.
  const site = typeof cfg.site === 'string' ? cfg.site.replace(/^https:\/\//, '') : ''
  const docs = Number(cfg.documents ?? 0)
  return [site, docs ? count(docs, c.kind === 'upload' ? 'file' : 'document') : ''].filter(Boolean).join(', ')
}

/** A way into each live connector, on a workspace of your own. */
function ConnectRow({ onConnect }: { onConnect: (source: string) => void }) {
  return (
    <div className="mt-5">
      <p className="text-[14px] text-muted">Read it live, and again every hour</p>
      <ul className="mt-2.5 flex flex-wrap gap-2">
        {CONNECTABLE.map((s) => (
          <li key={s.kind}>
            <button
              type="button"
              onClick={() => onConnect(s.kind)}
              className="inline-flex h-10 items-center gap-2 rounded-full px-3.5 text-[14.5px] font-medium text-ink shadow-[inset_0_0_0_1.5px_var(--line-strong)] transition-shadow hover:shadow-[inset_0_0_0_1.5px_var(--ink)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cobalt"
            >
              <s.icon size={16} weight={s.kind === 'slack' || s.kind === 'notion' ? 'fill' : 'regular'} aria-hidden="true" />
              {s.kind === 'upload' ? 'Upload files' : `Connect ${s.name}`}
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}

function Connections({ items, onConnect }: { items: Connection[]; onConnect?: (source?: string) => void }) {
  if (!items.length) {
    return onConnect ? (
      <p className="text-[15px] leading-relaxed text-muted">Nothing is connected yet. Connect a tool your company writes in, or upload files.</p>
    ) : (
      <p className="text-[15px] leading-relaxed text-muted">Loaded from public sources by the people who run Canon.</p>
    )
  }
  return (
    <ul className="divide-y divide-line border-y border-line">
      {items.map((c) => {
        const Glyph = iconOf(c)
        const failed = c.status === 'failed'
        return (
          <li key={c.id} className="flex items-start gap-3.5 py-4">
            <span className="mt-0.5 grid size-9 shrink-0 place-items-center rounded-full bg-paper-2 text-ink" aria-hidden="true">
              <Glyph size={17} />
            </span>
            <div className="min-w-0 flex-1">
              {onConnect && c.kind !== 'github' && !(c.kind === 'upload' && c.config.format) ? (
                <button type="button" onClick={() => onConnect()} className="text-left text-[15.5px] font-semibold text-ink hover:text-cobalt">
                  {c.label}
                </button>
              ) : (
                <p className="text-[15.5px] font-semibold text-ink">{c.label}</p>
              )}
              <p className="truncate text-[14px] text-muted">{connectionDetail(c)}</p>
            </div>
            <p className={`shrink-0 pt-0.5 text-right text-[13.5px] ${failed ? 'text-proof' : 'text-faint'}`}>
              {failed ? (c.error ?? 'Stopped') : c.status === 'reading' ? 'Reading now' : c.last_synced_at ? `Read ${ago(c.last_synced_at)}` : ''}
            </p>
          </li>
        )
      })}
    </ul>
  )
}

const UPLOADS: { kind: UploadKind; title: string; detail: string; icon: Icon }[] = [
  { kind: 'slack', title: 'Add a Slack export', detail: 'The zip Slack makes from Settings, Import and export. Channels only.', icon: SlackLogo },
  { kind: 'pages', title: 'Add a Notion or Confluence export', detail: 'A Markdown or HTML export, as one zip.', icon: FileZip },
]

function Uploads({ ws, onRead }: { ws: Workspace; onRead: () => void }) {
  const { job, kick, setJob } = useJob(ws.slug)
  const [error, setError] = useState<string | null>(null)
  const [sending, setSending] = useState<UploadKind | null>(null)
  const inputs = useRef<Record<UploadKind, HTMLInputElement | null>>({ slack: null, pages: null })
  const running = job?.status === 'running'
  const wasRunning = useRef(false)
  useEffect(() => {
    if (wasRunning.current && job?.status === 'done') onRead()
    wasRunning.current = running
  }, [job?.status, running, onRead])

  const send = (kind: UploadKind, file: File | undefined) => {
    if (!file) return
    setError(null)
    setSending(kind)
    uploadExport(ws.slug, kind, file).then(
      ({ job }) => {
        setJob(job)
        kick()
      },
      (e: Error) => setError(e.message),
    ).finally(() => setSending(null))
  }

  return (
    <div>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        {UPLOADS.map((u) => (
          <div key={u.kind}>
            <input
              ref={(el) => void (inputs.current[u.kind] = el)}
              type="file"
              accept=".zip,application/zip"
              className="sr-only"
              aria-label={u.title}
              onChange={(e) => {
                send(u.kind, e.target.files?.[0])
                e.target.value = ''
              }}
            />
            <button
              type="button"
              disabled={running || sending !== null}
              onClick={() => inputs.current[u.kind]?.click()}
              className="flex w-full items-start gap-3.5 rounded-[18px] px-4 py-4 text-left shadow-[inset_0_0_0_1.5px_var(--line-strong)] transition-shadow hover:shadow-[inset_0_0_0_1.5px_var(--ink)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cobalt disabled:cursor-not-allowed disabled:opacity-50"
            >
              <span className="mt-0.5 grid size-9 shrink-0 place-items-center rounded-full bg-ink text-paper" aria-hidden="true">
                {sending === u.kind ? <UploadSimple size={16} weight="bold" /> : <u.icon size={17} weight="bold" />}
              </span>
              <span className="min-w-0">
                <span className="block text-[15.5px] font-semibold text-ink">{sending === u.kind ? 'Sending the export' : u.title}</span>
                <span className="mt-0.5 block text-[14px] leading-snug text-muted">{u.detail}</span>
              </span>
            </button>
          </div>
        ))}
      </div>
      <div className="mt-4 min-h-[44px] text-[14px]" aria-live="polite">
        {running ? (
          <div className="max-w-[460px]">
            <p className="text-ink">
              {job.kind === 'upload' ? 'Reading the export' : job.kind === 'create' ? 'Reading the repository' : 'Syncing'}: {job.step_label.toLowerCase()}
            </p>
            <div className="relative mt-2 h-[3px] overflow-hidden rounded-full bg-line" aria-hidden="true">
              <motion.div className="absolute inset-y-0 left-0 w-full origin-left rounded-full bg-ink" initial={false} animate={{ scaleX: Math.max(0.04, job.progress) }} />
            </div>
          </div>
        ) : job?.kind === 'upload' && job.status === 'failed' ? (
          <p className="text-proof">{job.error}</p>
        ) : job?.kind === 'upload' && job.status === 'done' && job.finished_at ? (
          <p className="text-muted">Last export read {ago(job.finished_at)}. Exports up to 50 MB.</p>
        ) : (
          <p className="text-faint">Exports up to 50 MB. Canon reads them into this workspace only.</p>
        )}
        {error && <p className="mt-2 text-proof">{error}</p>}
      </div>
    </div>
  )
}

// ----- the screen --------------------------------------------------------------------------------------------------

type Load = { status: 'loading' } | { status: 'error'; message: string } | { status: 'ready'; view: SourcesView }

function Waiting() {
  const reduce = useReducedMotion()
  return (
    <div className="space-y-5 py-10" role="status" aria-label="Counting what this workspace reads">
      {[0, 1, 2, 3].map((i) => (
        <motion.div
          key={i}
          className="h-[3px] rounded-full bg-line-strong"
          style={{ width: `${70 - i * 12}%` }}
          animate={reduce ? undefined : { opacity: [0.35, 1, 0.35] }}
          transition={{ duration: 1.6, repeat: Infinity, delay: i * 0.15 }}
        />
      ))}
      <p className="text-[14px] text-muted">Counting what this workspace reads</p>
    </div>
  )
}

export function Sources({
  ws,
  own,
  connect,
  onConnect,
}: {
  ws: Workspace
  own: boolean
  connect?: ReactNode
  onConnect?: (source?: string) => void
}) {
  const [load, setLoad] = useState<Load>({ status: 'loading' })
  const [version, setVersion] = useState(0)
  const wide = useWide()

  useEffect(() => {
    const ctrl = new AbortController()
    getSources(ws.slug, ctrl.signal).then(
      (view) => setLoad({ status: 'ready', view }),
      (e: Error) => e.name !== 'AbortError' && setLoad({ status: 'error', message: e.message }),
    )
    return () => ctrl.abort()
  }, [ws.slug, version])

  const reload = () => setVersion((v) => v + 1)
  const view = load.status === 'ready' ? load.view : null
  const kinds = view ? view.families.filter((f) => f.documents || f.facts || (f.key === 'people' && f.people)).length : 0
  const canUpload = !!view?.can_upload && own

  return (
    <main className="slab relative flex min-w-0 flex-1 flex-col bg-paper">
      <div className="mx-auto w-full max-w-[1040px] px-5 pt-8 pb-16 sm:px-10 sm:pt-12 lg:px-14">
        {load.status === 'error' ? (
          <Problem message={load.message} onRetry={reload} />
        ) : !view ? (
          <Waiting />
        ) : (
          <>
            <h1 className="display max-w-[820px] text-[38px] text-balance [overflow-wrap:anywhere] text-ink sm:text-[56px] lg:text-[64px]">What Canon reads in {ws.name}.</h1>
            <p className="mt-5 max-w-[660px] text-[16.5px] leading-relaxed text-muted sm:text-[18px]">
              {n(view.totals.documents)} documents from {count(kinds, 'kind')} of source, read into one graph of {count(view.totals.facts, 'fact')}. When two
              sources disagree, the graph decides which holds: the ownership map outranks a decision, a decision outranks a page, and a page outranks a
              ticket or a chat.
            </p>

            <div className="mt-10 sm:mt-12">
              {wide ? <Intake view={view} layout={desktop} className="h-auto w-full" /> : <Intake view={view} layout={phone} className="mx-auto h-auto w-full max-w-[460px]" />}
            </div>

            <section className="mt-12 sm:mt-16" aria-labelledby="kinds">
              <h2 id="kinds" className="mb-4 text-[15px] font-semibold text-ink">
                Each kind of source
              </h2>
              <Details families={view.families} />
            </section>

            <section className="mt-12 max-w-[760px] sm:mt-14" aria-labelledby="from">
              <div className="mb-4 flex items-center justify-between gap-4">
                <h2 id="from" className="text-[15px] font-semibold text-ink">
                  Where it reads from
                </h2>
                {connect}
              </div>
              <Connections items={view.connections} onConnect={onConnect} />
              {onConnect && <ConnectRow onConnect={onConnect} />}
            </section>

            {canUpload && (
              <section className="mt-12 max-w-[760px] sm:mt-14" aria-labelledby="add">
                <h2 id="add" className="text-[15px] font-semibold text-ink">
                  Add chats and docs from outside GitHub
                </h2>
                <p className="mt-1.5 mb-5 text-[15px] leading-relaxed text-muted">
                  Canon reads each Slack thread with who said what and when, and each page with its own date, then checks them against everything else.
                </p>
                <Uploads ws={ws} onRead={reload} />
              </section>
            )}
          </>
        )}
      </div>
    </main>
  )
}
