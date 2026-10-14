// Ask: a question goes in, the answer comes back a sentence at a time, and each sentence is checked against the
// graph before it takes its mark. Clicking a sentence shows where it comes from.

import { ArrowRight } from '@phosphor-icons/react'
import { AnimatePresence, motion, useDragControls, useReducedMotion } from 'motion/react'
import { useCallback, useEffect, useReducer, useRef, useState, type FormEvent, type KeyboardEvent } from 'react'
import { ask, isMock, type AskEvent } from './api'
import { Answer, ease, Removed, Tally } from './Answer'
import { SourcePanel } from './SourcePanel'
import { initial, reduce, type AskState } from './state'
import { plural } from './text'
import type { Workspace } from './workspaces'

function useWide() {
  const query = '(min-width: 900px)'
  const [wide, setWide] = useState(() => window.matchMedia(query).matches)
  useEffect(() => {
    const m = window.matchMedia(query)
    const update = () => setWide(m.matches)
    m.addEventListener('change', update)
    return () => m.removeEventListener('change', update)
  }, [])
  return wide
}

const spoken: Record<string, string> = { verified: 'verified', stale: 'out of date', disputed: 'disputed', unsupported: 'removed, nothing in the graph backs it' }

function QuestionField({ ws, onAsk }: { ws: Workspace; onAsk: (q: string) => void }) {
  const [value, setValue] = useState('')
  const field = useRef<HTMLTextAreaElement>(null)

  // The field grows with the question, so a long one wraps in display type instead of scrolling.
  useEffect(() => {
    const el = field.current
    if (!el) return
    el.style.height = '0px'
    el.style.height = `${el.scrollHeight}px`
  }, [value])

  useEffect(() => field.current?.focus({ preventScroll: true }), [])

  const submit = (e?: FormEvent) => {
    e?.preventDefault()
    if (value.trim()) onAsk(value.trim())
  }
  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) submit(e)
  }

  return (
    <form onSubmit={submit}>
      <label htmlFor="question" className="sr-only">
        Your question for {ws.name}
      </label>
      <div className="flex items-end gap-4 border-b-[1.5px] border-line-strong pb-4 transition-colors focus-within:border-ink">
        <textarea
          id="question"
          ref={field}
          rows={1}
          value={value}
          onChange={(e) => setValue(e.target.value.replace(/\n/g, ' '))}
          onKeyDown={onKey}
          maxLength={500}
          placeholder={`Ask how ${ws.name} works`}
          className="display min-w-0 flex-1 resize-none overflow-hidden bg-transparent text-[34px] leading-[1.08] text-ink caret-cobalt outline-none placeholder:text-[#b9bdc5] sm:text-[52px] lg:text-[60px]"
        />
        <button
          type="submit"
          disabled={!value.trim()}
          aria-label="Ask"
          className="mb-1 grid size-12 shrink-0 place-items-center rounded-full bg-ink text-paper transition-[background-color,opacity,transform] duration-200 hover:bg-[#23252d] active:translate-y-px disabled:opacity-20 sm:size-14"
        >
          <ArrowRight size={20} weight="bold" />
        </button>
      </div>
      <div className="mt-6 flex flex-col items-start gap-2.5 text-[16px] sm:flex-row sm:flex-wrap sm:items-baseline sm:gap-x-7">
        <span className="text-faint">Try</span>
        {ws.suggestions.map((q) => (
          <button
            key={q}
            type="button"
            onClick={() => onAsk(q)}
            className="rounded text-left text-muted underline decoration-line-strong decoration-1 underline-offset-[5px] transition-colors hover:text-ink hover:decoration-ink focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-cobalt"
          >
            {q}
          </button>
        ))}
      </div>
    </form>
  )
}

/** How to read an answer, written in the marks themselves. */
function Key() {
  return (
    <ul className="flex flex-col gap-2.5 text-[14.5px] text-muted sm:flex-row sm:flex-wrap sm:gap-x-8">
      <li>
        <span className="text-ink underline decoration-cobalt decoration-[1.5px] underline-offset-[5px]">Underlined</span> checks out
      </li>
      <li>
        <span className="text-muted line-through decoration-proof decoration-2">Struck</span> <span className="text-cobalt">then corrected</span> is out of date
      </li>
      <li>
        <span className="rounded-[3px] bg-[var(--amber-marker)] px-1 text-ink">Highlighted</span> means two sources disagree
      </li>
    </ul>
  )
}

function Progress({ state }: { state: AskState }) {
  const reduce = useReducedMotion()
  const total = state.sentences.length
  const checked = state.sentences.filter((s) => s.verdict).length
  const finished = state.phase !== 'asking'
  const ev = state.evidence
  const value = finished ? 1 : !ev ? 0.1 : !total ? 0.32 : 0.4 + (0.6 * checked) / total

  let label = 'Searching the graph'
  if (ev) {
    const read = `${plural(ev.facts, 'fact')} in ${plural(ev.documents, 'document')}`
    label = ev.facts === 0 ? 'Nothing found in the graph' : finished ? `Read ${read}` : `Reading ${read}`
  } else if (state.phase === 'error') label = 'Stopped'

  return (
    <div className="mt-6">
      <div className="flex items-baseline justify-between gap-4 text-[14px]">
        <span className="text-muted">{label}</span>
        {!finished && total > 0 && (
          <span className="text-faint tabular-nums">
            Checked {checked} of {total}
          </span>
        )}
      </div>
      <div className="relative mt-2.5 h-px overflow-hidden bg-line" aria-hidden="true">
        <motion.div
          className="absolute inset-y-0 left-0 w-full origin-left"
          initial={reduce ? false : { scaleX: 0 }}
          animate={{ scaleX: value, backgroundColor: finished ? 'var(--line-strong)' : 'var(--ink)' }}
          transition={{ duration: reduce ? 0 : 0.6, ease }}
        />
      </div>
    </div>
  )
}

export function Ask({ ws }: { ws: Workspace }) {
  const [state, dispatch] = useReducer(reduce, initial)
  const [selected, setSelected] = useState<number | null>(null)
  const [announcement, setAnnouncement] = useState('')
  const run = useRef<AbortController | null>(null)
  const panel = useRef<HTMLDivElement>(null)
  const opener = useRef<HTMLElement | null>(null)
  const wide = useWide()
  const reduceMotion = useReducedMotion()
  const sheetDrag = useDragControls()

  const start = useCallback(
    (question: string) => {
      run.current?.abort()
      const ctrl = new AbortController()
      run.current = ctrl
      setSelected(null)
      setAnnouncement('Checking the answer.')
      dispatch({ type: 'start', question })
      const onEvent = (event: AskEvent) => {
        if (ctrl.signal.aborted) return
        dispatch({ type: 'event', event })
        if (event.type === 'verdict') setAnnouncement(`Sentence ${event.index + 1}: ${spoken[event.verdict]}.`)
        if (event.type === 'empty') setAnnouncement('Nothing in the graph answers that.')
        if (event.type === 'done') {
          const c = event.counts
          const parts = (['verified', 'stale', 'disputed', 'unsupported'] as const).filter((k) => c[k]).map((k) => `${c[k]} ${spoken[k].split(',')[0]}`)
          setAnnouncement(`Checked: ${parts.join(', ')}.`)
        }
      }
      ask(ws.slug, question, onEvent, ctrl.signal).catch((e: Error) => {
        if (e.name === 'AbortError') return
        dispatch({ type: 'fail', message: e.message })
        setAnnouncement(e.message)
      })
    },
    [ws.slug],
  )

  useEffect(() => () => run.current?.abort(), [])

  const reset = () => {
    run.current?.abort()
    setSelected(null)
    dispatch({ type: 'reset' })
  }

  const select = (index: number) => {
    if (selected === index) return close()
    opener.current = document.activeElement as HTMLElement | null
    setSelected(index)
  }

  const close = useCallback(() => {
    setSelected(null)
    opener.current?.focus({ preventScroll: true })
  }, [])

  // Esc closes the sources.
  useEffect(() => {
    if (selected === null) return
    const onKey = (e: globalThis.KeyboardEvent) => e.key === 'Escape' && close()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [selected, close])

  // The open panel takes focus, so a keyboard user lands on the sources.
  useEffect(() => {
    if (selected !== null) panel.current?.focus({ preventScroll: true })
  }, [selected])

  const current = state.sentences.find((s) => s.index === selected && s.verdict) ?? null
  const asked = state.phase !== 'idle'
  const noKey = state.error?.startsWith('Answers are off') ?? false
  const missing = state.error?.includes('not in the graph') ?? false

  return (
    <div className="flex min-h-full min-w-0 flex-1 gap-3">
      <main className="slab relative flex min-w-0 flex-1 flex-col bg-paper">
        <div role="status" aria-live="polite" className="sr-only">
          {announcement}
        </div>

        {!asked ? (
          <div className="flex flex-1 flex-col px-6 pt-10 pb-8 sm:px-12 lg:px-16">
            <div className="mx-auto w-full max-w-[880px] pt-[14vh] pb-16 sm:pt-[22vh]">
              <QuestionField ws={ws} onAsk={start} />
            </div>
            <div className="mx-auto mt-auto w-full max-w-[880px] border-t border-line pt-6">
              <Key />
            </div>
          </div>
        ) : (
          <div className="mx-auto w-full max-w-[780px] px-6 pt-5 pb-20 sm:px-12">
            <div className="flex h-11 items-center justify-between gap-4">
              <span className="text-[14px] text-muted">Asked {ws.name}</span>
              <button
                type="button"
                onClick={reset}
                className="inline-flex h-10 items-center rounded-full px-4 text-[14px] font-semibold text-ink shadow-[inset_0_0_0_1.5px_var(--line-strong)] transition-shadow hover:shadow-[inset_0_0_0_1.5px_var(--ink)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cobalt"
              >
                New question
              </button>
            </div>

            <motion.h1
              className="display mt-10 text-[34px] text-pretty text-ink sm:mt-14 sm:text-[50px]"
              initial={reduceMotion ? false : { opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.5, ease }}
            >
              {state.question}
            </motion.h1>

            <Progress state={state} />

            <div className="mt-10">
              {state.phase === 'asking' && !state.sentences.length && (state.evidence?.facts ?? 0) > 0 && (
                <p className="text-[19px] leading-[1.75] sm:text-[22px]">
                  <span className="pending">Drafting an answer from these facts</span>
                </p>
              )}

              {state.sentences.length > 0 && (
                <Answer sentences={state.sentences} selected={selected} onSelect={select} />
              )}

              {state.phase === 'empty' && (
                <motion.div initial={reduceMotion ? false : { opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5, ease }}>
                  <p className="display text-[28px] text-ink sm:text-[34px]">Nothing in the graph answers that.</p>
                  {state.people.length ? (
                    <ul className="mt-6 space-y-3">
                      {state.people.map((p) => (
                        <li key={p.handle} className="text-[18px] leading-relaxed text-muted sm:text-[20px]">
                          Ask <span className="font-semibold text-ink">{p.name}</span>: {p.why.charAt(0).toLowerCase() + p.why.slice(1)}
                          {!p.handle.startsWith('name:') && (
                            <a
                              href={`https://github.com/${p.handle}`}
                              target="_blank"
                              rel="noreferrer"
                              className="ml-2 text-[15px] text-cobalt hover:text-cobalt-deep"
                            >
                              @{p.handle}
                            </a>
                          )}
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="mt-4 text-[18px] leading-relaxed text-muted">Nobody in the graph owns this either. Try naming an area or a team.</p>
                  )}
                </motion.div>
              )}

              {state.phase === 'error' && (
                <div>
                  <p className="text-[18px] leading-relaxed text-ink">{state.error}</p>
                  <div className="mt-4 flex flex-wrap gap-x-6 gap-y-2 text-[15px]">
                    {!missing && (
                      <button type="button" onClick={() => start(state.question)} className="font-semibold text-cobalt hover:text-cobalt-deep">
                        Try again
                      </button>
                    )}
                    {noKey && !isMock() && (
                      <a href="?mock=1" className="font-semibold text-muted hover:text-ink">
                        Play the recorded demo instead
                      </a>
                    )}
                  </div>
                </div>
              )}

              {(state.phase === 'done' || state.phase === 'asking') && state.sentences.length > 0 && (
                <div className="mt-10 space-y-4 border-t border-line pt-5">
                  <Removed sentences={state.sentences} selected={selected} onSelect={select} />
                  {state.phase === 'done' && state.counts && <Tally counts={state.counts} />}
                </div>
              )}
            </div>
          </div>
        )}
      </main>

      {/* The sources: a sheet of their own beside the answer, or a bottom sheet on a narrow screen. */}
      <AnimatePresence>
        {wide && current && (
          <motion.aside
            key="panel"
            aria-labelledby="panel-title"
            className="slab sticky top-3 h-[calc(100dvh-24px)] w-[min(470px,42vw)] shrink-0 overflow-y-auto bg-paper px-7 pt-7 pb-10"
            initial={reduceMotion ? false : { opacity: 0, x: 28 }}
            animate={{ opacity: 1, x: 0 }}
            exit={reduceMotion ? { opacity: 0 } : { opacity: 0, x: 28 }}
            transition={{ duration: 0.4, ease }}
          >
            <SourcePanel ref={panel} ws={ws.slug} sentence={current} onClose={close} />
          </motion.aside>
        )}
      </AnimatePresence>
      <AnimatePresence>
        {!wide && current && (
          <>
            <motion.div
              key="scrim"
              className="fixed inset-0 z-40 bg-night/30"
              onClick={close}
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.25 }}
            />
            <motion.div
              key="sheet"
              role="dialog"
              aria-modal="true"
              aria-labelledby="panel-title"
              className="fixed inset-x-0 bottom-0 z-50 flex max-h-[86dvh] flex-col rounded-t-[26px] bg-paper shadow-[0_-20px_60px_-20px_rgb(13_14_18/0.35)]"
              initial={reduceMotion ? false : { y: '100%' }}
              animate={{ y: 0 }}
              exit={reduceMotion ? { opacity: 0 } : { y: '100%' }}
              transition={{ duration: 0.45, ease }}
              drag={reduceMotion ? false : 'y'}
              dragListener={false}
              dragControls={sheetDrag}
              dragConstraints={{ top: 0, bottom: 0 }}
              dragElastic={{ top: 0, bottom: 0.6 }}
              onDragEnd={(_, info) => (info.offset.y > 120 || info.velocity.y > 600) && close()}
            >
              {/* The handle drags the sheet down to close it; the sources below scroll. */}
              <div className="flex touch-none justify-center pt-3 pb-2" aria-hidden="true" onPointerDown={(e) => sheetDrag.start(e)}>
                <span className="h-1 w-10 rounded-full bg-line-strong" />
              </div>
              <div className="sheet-scroll overflow-y-auto px-5 pt-2 pb-10">
                <SourcePanel ref={panel} ws={ws.slug} sentence={current} onClose={close} />
              </div>
            </motion.div>
          </>
        )}
      </AnimatePresence>
    </div>
  )
}
