// The answer as a paragraph. Each sentence starts faint while its check runs, then takes its mark:
// a cobalt underline (verified), a proof-red strike with the current fact inserted after it (out of date),
// or an amber highlighter (disputed). Sentences nothing backs fold away and are listed under the answer.

import { CaretDown } from '@phosphor-icons/react'
import { AnimatePresence, motion, useReducedMotion } from 'motion/react'
import { useState, type KeyboardEvent, type ReactNode } from 'react'
import type { Counts } from './api'
import type { Sentence } from './state'
import { formatDate, plural } from './text'

export const ease = [0.22, 1, 0.36, 1] as const

const solid = (color: string) => `linear-gradient(${color}, ${color})`

/** Text split before its last word, so a mark after the sentence never wraps onto a line by itself. */
function lastWord(text: string): [string, string] {
  const at = text.trimEnd().lastIndexOf(' ')
  return at === -1 ? ['', text] : [text.slice(0, at + 1), text.slice(at + 1)]
}

/** A mark drawn behind or through the words, growing left to right across every line they span. */
function Drawn({ children, image, position, height, delay = 0, duration = 0.6, curve = ease, className = '' }: {
  children: ReactNode
  image: string
  position: string
  height: string
  delay?: number
  duration?: number
  curve?: typeof ease | 'linear' | 'easeOut'
  className?: string
}) {
  const reduce = useReducedMotion()
  return (
    <motion.span
      className={className}
      style={{ backgroundImage: image, backgroundRepeat: 'no-repeat', backgroundPosition: position, boxDecorationBreak: 'slice' }}
      initial={reduce ? false : { backgroundSize: `0% ${height}` }}
      animate={{ backgroundSize: `100% ${height}` }}
      transition={{ duration: reduce ? 0 : duration, delay: reduce ? 0 : delay, ease: curve }}
    >
      {children}
    </motion.span>
  )
}

function Check({ delay }: { delay: number }) {
  const reduce = useReducedMotion()
  return (
    <svg viewBox="0 0 12 10" className="mb-[0.08em] ml-[0.28em] inline-block h-[0.52em] w-auto align-baseline text-cobalt" aria-hidden="true">
      <motion.path
        d="M1.2 5.4 4.4 8.4 10.8 1.6"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        initial={reduce ? false : { pathLength: 0 }}
        animate={{ pathLength: 1 }}
        transition={{ duration: reduce ? 0 : 0.35, delay: reduce ? 0 : delay, ease: 'easeOut' }}
      />
    </svg>
  )
}

/** The proofreader's caret: a small inverted V under the line, where the correction goes in. */
function Caret() {
  return (
    <svg viewBox="0 0 10 8" className="mr-[0.22em] inline-block h-[0.4em] w-auto align-[-0.28em] text-cobalt" aria-hidden="true">
      <path d="M1 7.2 5 1.2 9 7.2" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

function Insertion({ sentence }: { sentence: Sentence }) {
  const reduce = useReducedMotion()
  const now = sentence.newer[0]
  if (!now?.fact) return null
  const space = now.fact.indexOf(' ')
  const [first, rest] = space === -1 ? [now.fact, ''] : [now.fact.slice(0, space), now.fact.slice(space)]
  return (
    // Inline, so the correction flows on the same line as the struck words; it rises into place from a little below.
    <motion.span
      className="relative text-cobalt"
      title={now.valid_from ? `Since ${formatDate(now.valid_from)}` : undefined}
      initial={reduce ? false : { opacity: 0, top: '0.35em' }}
      animate={{ opacity: 1, top: '0em' }}
      transition={{ duration: reduce ? 0 : 0.5, delay: reduce ? 0 : 0.55, ease }}
    >
      <span className="whitespace-nowrap">
        <Caret />
        {first}
      </span>
      {rest}
    </motion.span>
  )
}

const said: Record<string, string> = {
  verified: 'verified',
  stale: 'out of date',
  disputed: 'disputed: two sources disagree',
}

function Marked({ sentence, note }: { sentence: Sentence; note: boolean }) {
  switch (sentence.verdict) {
    case 'verified': {
      // The underline is drawn in two runs (the words, then the last word with its check) at one steady speed.
      const [head, tail] = lastWord(sentence.text)
      const total = 0.6
      const first = (total * head.length) / sentence.text.length
      const underline = { image: solid('rgb(44 70 232 / 0.55)'), position: '0 100%', height: '1.5px', className: 'pb-[0.08em]' }
      return (
        <>
          {head && (
            <Drawn {...underline} duration={first} curve="linear">
              {head}
            </Drawn>
          )}
          <span className="whitespace-nowrap">
            <Drawn {...underline} delay={first} duration={total - first} curve={head ? 'easeOut' : ease}>
              {tail}
            </Drawn>
            <Check delay={total} />
          </span>
        </>
      )
    }
    case 'stale':
      return (
        <>
          <Drawn image={solid('var(--proof)')} position="0 58%" height="2px" duration={0.55} className="text-muted transition-colors">
            {sentence.text}
          </Drawn>{' '}
          <Insertion sentence={sentence} />
        </>
      )
    case 'disputed':
      return (
        <>
          <Drawn
            image="linear-gradient(to bottom, transparent 10%, var(--amber-marker) 10%, var(--amber-marker) 94%, transparent 94%)"
            position="0 0"
            height="100%"
            duration={0.7}
            className="rounded-[0.12em]"
          >
            {sentence.text}
          </Drawn>
          {note && (
            <motion.span
              className="ml-[0.45em] text-[0.64em] font-semibold whitespace-nowrap text-amber"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ duration: 0.4, delay: 0.6 }}
            >
              two sources disagree
            </motion.span>
          )}
        </>
      )
    default:
      return <span className="pending">{sentence.text}</span>
  }
}

export function Answer({
  sentences,
  selected,
  onSelect,
}: {
  sentences: Sentence[]
  selected: number | null
  onSelect: (index: number) => void
}) {
  const reduce = useReducedMotion()
  const shown = sentences.filter((s) => s.verdict !== 'unsupported')

  const key = (index: number) => (e: KeyboardEvent) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault()
      onSelect(index)
    }
  }

  return (
    <p className="text-[19px] leading-[1.75] tracking-[-0.006em] text-pretty text-ink sm:text-[22px] sm:leading-[1.72]">
      <AnimatePresence initial={false}>
        {shown.map((s, i) => {
          const ready = s.verdict !== null
          const next = shown[i + 1]
          // Two sentences of one dispute in a row share one note, after the second.
          const shared = next?.verdict === 'disputed' && s.conflicting.some((c) => next.sources.some((n) => n.fact_id === c.fact_id))
          return (
            <motion.span
              key={s.index}
              role={ready ? 'button' : undefined}
              tabIndex={ready ? 0 : undefined}
              aria-pressed={ready ? selected === s.index : undefined}
              data-ready={ready}
              onClick={ready ? () => onSelect(s.index) : undefined}
              onKeyDown={ready ? key(s.index) : undefined}
              className="sentence"
              initial={reduce ? false : { opacity: 0 }}
              animate={{ opacity: selected !== null && selected !== s.index ? 0.38 : 1 }}
              exit={reduce ? { opacity: 0 } : { opacity: 0, filter: 'blur(3px)' }}
              transition={{ duration: 0.35, delay: reduce || ready ? 0 : 0.08 * i, ease }}
            >
              <Marked sentence={s} note={!shared} />
              {s.verdict && s.verdict !== 'unsupported' && <span className="sr-only"> ({said[s.verdict]})</span>}
              {i < shown.length - 1 ? ' ' : ''}
            </motion.span>
          )
        })}
      </AnimatePresence>
    </p>
  )
}

/** "1 sentence removed: nothing in the graph backs it", opening to show what was removed. */
export function Removed({ sentences, selected, onSelect }: { sentences: Sentence[]; selected: number | null; onSelect: (index: number) => void }) {
  const [open, setOpen] = useState(false)
  const reduce = useReducedMotion()
  const removed = sentences.filter((s) => s.verdict === 'unsupported')
  if (!removed.length) return null
  const failed = removed.every((s) => s.error)
  return (
    <motion.div initial={reduce ? false : { opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4, ease }}>
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className="group rounded-md text-left text-[15px] text-muted transition-colors hover:text-ink focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-cobalt"
      >
        {plural(removed.length, 'sentence')} removed: {failed ? 'the check could not run' : `nothing in the graph backs ${removed.length === 1 ? 'it' : 'them'}`}
        <CaretDown size={13} weight="bold" className={`ml-1.5 inline-block align-[-0.1em] transition-transform duration-300 ${open ? 'rotate-180' : ''}`} />
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.ul
            className="overflow-hidden"
            initial={reduce ? false : { height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={reduce ? { opacity: 0 } : { height: 0, opacity: 0 }}
            transition={{ duration: 0.35, ease }}
          >
            {removed.map((s) => (
              <li key={s.index} className="pt-3">
                <button
                  type="button"
                  onClick={() => onSelect(s.index)}
                  aria-pressed={selected === s.index}
                  className={`text-left text-[16px] leading-relaxed text-faint line-through decoration-faint/50 transition-colors hover:text-muted focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-cobalt ${selected === s.index ? 'text-muted' : ''}`}
                >
                  {s.text}
                </button>
                {s.error && <p className="mt-1 text-[13.5px] text-faint">{s.error}</p>}
              </li>
            ))}
          </motion.ul>
        )}
      </AnimatePresence>
    </motion.div>
  )
}

/** The quiet count at the end. Each word wears its own mark. */
export function Tally({ counts }: { counts: Counts }) {
  const reduce = useReducedMotion()
  const parts: ReactNode[] = []
  if (counts.verified) parts.push(<span key="v">{counts.verified} <span className="underline decoration-cobalt decoration-[1.5px] underline-offset-[5px]">verified</span></span>)
  if (counts.stale) parts.push(<span key="s">{counts.stale} <span className="text-proof">out of date</span></span>)
  if (counts.disputed) parts.push(<span key="d">{counts.disputed} <span className="rounded-[3px] bg-[var(--amber-marker)] px-1">disputed</span></span>)
  if (counts.unsupported) parts.push(<span key="u">{counts.unsupported} removed</span>)
  if (!parts.length) return null
  return (
    <motion.p
      className="text-[15px] text-muted"
      initial={reduce ? false : { opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.5, delay: reduce ? 0 : 0.2 }}
    >
      {parts.map((p, i) => (
        <span key={i}>
          {i > 0 && <span className="mx-2 text-faint">·</span>}
          {p}
        </span>
      ))}
    </motion.p>
  )
}
