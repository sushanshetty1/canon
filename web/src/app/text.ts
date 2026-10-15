// Small helpers for showing graph values as words, and for finding a fact's words in its passage.

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

/** "2026-06-18" as "Jun 18, 2026". Parsed by hand so no time zone moves the day. */
export function formatDate(iso: string | null | undefined, { year = true } = {}): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso ?? '')
  if (!m) return ''
  const label = `${MONTHS[Number(m[2]) - 1]} ${Number(m[3])}`
  return year ? `${label}, ${m[1]}` : label
}

/** Months since the start of year 0, as a fraction, for placing a date on a timeline. */
export function monthsOf(iso: string): number {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso)
  if (!m) return 0
  return Number(m[1]) * 12 + Number(m[2]) - 1 + (Number(m[3]) - 1) / 31
}

export const MONTH_NAMES = MONTHS

const KINDS: Record<string, string> = {
  ownership_map: 'Ownership map',
  team_page: 'Team page',
  handbook: 'Handbook',
  rfc: 'RFC',
  pull: 'Pull request',
  issue: 'Issue',
  linear_issue: 'Linear issue',
  jira_issue: 'Jira issue',
  forum: 'Forum thread',
  discussion: 'Discussion',
  comment_thread: 'Comment thread',
  slack_thread: 'Slack thread',
  doc: 'Doc',
  wiki: 'Wiki page',
  notion_page: 'Notion page',
  confluence_page: 'Confluence page',
  upload: 'Uploaded page',
  adr: 'Decision record',
  release: 'Release',
  roster: 'Team roster',
}

export const kindLabel = (kind: string | null | undefined) => (kind ? (KINDS[kind] ?? kind.replace(/_/g, ' ')) : 'Document')

/** "team:product-analytics" as "Product analytics"; a policy value as a sentence. */
export function valueLabel(value: string | null | undefined): string {
  const bare = (value ?? '').replace(/^(team|person|area|topic):(name:)?/, '').replace(/-/g, ' ').trim()
  return bare ? bare[0].toUpperCase() + bare.slice(1) : ''
}

export const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`

// --- Highlighting ---------------------------------------------------------------------------------

const QUIET = new Set(
  'a an the is are was were be been of to in on at by for with as and or its it this that these those our we us they their there from into s'.split(' '),
)

const stem = (w: string) => w.toLowerCase().replace(/(ing|ed|es|s)$/, '')
const same = (a: string, b: string) => a === b || (a.length >= 4 && b.length >= 4 && a.slice(0, 5) === b.slice(0, 5))

export type Piece = { text: string; hit: boolean }

/** The passage split into pieces, with the stretch that says the fact marked as a hit.
 *  It picks the passage sentence sharing the most words with the fact and marks it from its first shared word
 *  to its last. When nothing lines up well enough, `whole` is true and the caller marks the whole passage. */
export function highlight(passage: string, fact: string | null | undefined): { pieces: Piece[]; whole: boolean } {
  const want = [...new Set((fact ?? '').match(/[a-z0-9]+/gi)?.map(stem).filter((w) => w.length > 1 && !QUIET.has(w)) ?? [])]
  const whole = { pieces: [{ text: passage, hit: false }], whole: true }
  if (!want.length || !passage) return whole

  let best: { start: number; end: number; score: number; from: number; to: number } | null = null
  const sentence = /[^.!?]+[.!?]*/g
  for (let s = sentence.exec(passage); s; s = sentence.exec(passage)) {
    const words = [...s[0].matchAll(/[a-z0-9]+/gi)]
    const hits = words.filter((w) => want.some((x) => same(stem(w[0]), x)))
    const score = new Set(hits.map((w) => stem(w[0]))).size
    if (hits.length && (!best || score > best.score)) {
      const first = hits[0]
      const last = hits[hits.length - 1]
      const lead = s[0].length - s[0].trimStart().length
      const from = s.index + lead
      const to = s.index + s[0].trimEnd().replace(/[.!?]+$/, '').length
      best = { start: s.index + first.index!, end: s.index + last.index! + last[0].length, score, from, to }
    }
  }
  if (!best || best.score < Math.min(2, want.length) || best.score / want.length < 0.34) return whole

  // When the shared words cover most of their sentence, mark the whole sentence: it is the fact, reworded.
  if ((best.end - best.start) / Math.max(best.to - best.from, 1) >= 0.6) {
    best.start = best.from
    best.end = Math.max(best.end, best.to)
  }
  // Take the sentence's closing punctuation along, so the mark ends where the thought does.
  const tail = /^[.!?]/.test(passage.slice(best.end)) ? 1 : 0
  const pieces: Piece[] = [
    { text: passage.slice(0, best.start), hit: false },
    { text: passage.slice(best.start, best.end + tail), hit: true },
    { text: passage.slice(best.end + tail), hit: false },
  ].filter((p) => p.text)
  return { pieces, whole: false }
}
