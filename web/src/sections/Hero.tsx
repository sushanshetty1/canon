import { ArrowRight, ArrowUpRight, GithubLogo } from '@phosphor-icons/react'
import { AnimatePresence, motion, useReducedMotion } from 'motion/react'
import { useEffect, useState } from 'react'
import { Button, Container, REPO_URL, Slab, VerdictTag, Wordmark, type Verdict } from '../ui'

const ease = [0.22, 1, 0.36, 1] as const

type Line = { text: string; verdict: Verdict; source: string; quote: string }

// An example, not real PostHog data: it shows how one answer is proofread.
const lines: Line[] = [
  { text: 'Session replay is owned by the Replay team.', verdict: 'verified', source: 'ownership map', quote: 'session-replay: team-replay' },
  { text: 'The handbook lists it under Product Analytics.', verdict: 'stale', source: 'handbook / product-analytics', quote: 'we own insights and session replay' },
  { text: 'Ask the Replay team lead about recent changes.', verdict: 'verified', source: 'reviews and design docs', quote: 'reviewed the last replay RFC' },
]

// Steps of the proofread: which line the caret is on, and how far the check has gone.
const STEP_MS = [700, 750, 900, 750, 800, 750, 700]

function useProofread(reduce: boolean) {
  const [step, setStep] = useState(reduce ? 99 : 0)
  const [run, setRun] = useState(0)
  useEffect(() => {
    if (reduce) return
    setStep(0)
    const timers: number[] = []
    let at = 400
    STEP_MS.forEach((ms, i) => {
      at += ms
      timers.push(window.setTimeout(() => setStep(i + 1), at))
    })
    return () => timers.forEach((t) => window.clearTimeout(t))
  }, [reduce, run])
  return { step, replay: () => setRun((r) => r + 1) }
}

/** Line i is checked at step 2i+1 and resolved at step 2i+2. */
function verdictAt(i: number, step: number, final: Verdict): Verdict | null {
  if (step >= 2 * i + 2) return final
  if (step >= 2 * i + 1) return 'checking'
  return null
}

function AnswerSheet() {
  const reduce = !!useReducedMotion()
  const { step, replay } = useProofread(reduce)
  const caretLine = Math.min(2, Math.max(0, Math.floor((step - 1) / 2)))
  const done = step >= 7

  return (
    <div className="relative mx-auto w-full max-w-[600px] lg:mx-0">
      {/* The answer sheet */}
      <div className="ruled relative rounded-[22px] bg-paper p-0 shadow-[0_1px_2px_rgb(13_14_18/0.06),0_30px_70px_-30px_rgb(25_35_90/0.35)] ring-1 ring-line">
        <div className="border-b border-line px-6 pt-5 pb-4 sm:px-7 sm:pr-[200px]">
          <p className="font-mono text-[11.5px] text-faint">Asked · example</p>
          <p className="mt-1.5 font-display text-[19px] leading-snug font-semibold tracking-[-0.02em] text-ink sm:text-[21px]">Who owns session replay, and who should I ask?</p>
        </div>

        <ol className="relative px-6 py-3 sm:px-7">
          {/* The proofreader's caret, walking the gutter */}
          {!done && step > 0 && (
            <motion.span
              aria-hidden="true"
              className="absolute left-[18px] w-[3px] rounded-full bg-cobalt sm:left-[22px]"
              initial={false}
              animate={{ top: 24 + caretLine * 100, height: 30 }}
              transition={{ duration: 0.45, ease }}
            />
          )}
          {lines.map((line, i) => {
            const v = verdictAt(i, step, line.verdict)
            const struck = v === 'stale'
            return (
              <li key={line.text} className="grid min-h-[100px] grid-cols-[22px_minmax(0,1fr)] gap-x-3 py-3.5">
                <span className="pt-[3px] font-mono text-[12px] text-faint">{i + 1}</span>
                <div className="min-w-0">
                  <div>
                    <motion.p
                      className={`inline text-[16.5px] leading-snug transition-colors duration-500 ${v ? 'text-ink' : 'text-faint'} ${struck ? 'text-muted' : ''}`}
                      // The strike is a drawn stroke, not a toggle: it reads as a pen, and it follows wrapped lines.
                      style={{
                        backgroundImage: 'linear-gradient(var(--proof), var(--proof))',
                        backgroundRepeat: 'no-repeat',
                        backgroundPosition: '0 58%',
                        boxDecorationBreak: 'clone',
                        WebkitBoxDecorationBreak: 'clone',
                      }}
                      initial={false}
                      animate={{ backgroundSize: struck ? '100% 2px' : '0% 2px' }}
                      transition={{ duration: reduce ? 0 : 0.6, ease }}
                    >
                      {line.text}
                    </motion.p>
                  </div>
                  <div className="mt-2.5 flex min-h-6 min-w-0 flex-wrap items-center gap-x-2.5 gap-y-1.5 text-[12.5px] text-muted">
                    <AnimatePresence mode="popLayout">
                      {v && (
                        <motion.span
                          key={v}
                          initial={reduce ? false : { opacity: 0, scale: 0.85 }}
                          animate={{ opacity: 1, scale: 1 }}
                          exit={{ opacity: 0, scale: 0.9 }}
                          transition={{ duration: 0.3, ease }}
                        >
                          <VerdictTag verdict={v} />
                        </motion.span>
                      )}
                    </AnimatePresence>
                    <motion.span
                      className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1"
                      initial={false}
                      animate={{ opacity: v && v !== 'checking' ? 1 : 0 }}
                      transition={{ duration: 0.4 }}
                    >
                    <span className="font-mono text-faint">{line.source}</span>
                    <span className={`rounded-[3px] px-1 font-mono text-[12px] ${struck ? 'bg-proof-soft text-proof line-through decoration-proof/60' : 'bg-marker-soft text-ink'}`}>
                      "{line.quote}"
                    </span>
                    </motion.span>
                  </div>
                  {struck && (
                    <motion.p
                      className="mt-2 font-display text-[15px] font-semibold text-proof italic"
                      initial={reduce ? false : { opacity: 0, x: -6 }}
                      animate={{ opacity: 1, x: 0 }}
                      transition={{ duration: 0.4, delay: reduce ? 0 : 0.35, ease }}
                    >
                      ‸ moved to the Replay team, after this page was written
                    </motion.p>
                  )}
                </div>
              </li>
            )
          })}
        </ol>

        <div className="flex items-center justify-end gap-4 rounded-b-[22px] border-t border-line bg-paper-2 px-6 py-3 sm:px-7">
          <p className="text-[13.5px] text-muted">
            <span className="font-semibold text-ink">2 verified, 1 out of date</span>
          </p>
          <button
            type="button"
            onClick={replay}
            className="shrink-0 rounded-full bg-paper px-3 py-1.5 font-mono text-[11.5px] text-muted shadow-[inset_0_0_0_1px_var(--line-strong)] transition-colors hover:text-ink"
          >
            Run again
          </button>
        </div>
      </div>

      {/* The newer source, pinned to the sheet like a proof slip */}
      <motion.div
        className="absolute -top-10 -right-3 hidden w-[230px] rounded-[16px] bg-paper p-4 shadow-[0_18px_40px_-18px_rgb(25_35_90/0.4)] ring-1 ring-line sm:block lg:-right-10"
        initial={reduce ? false : { opacity: 0, y: 10, rotate: 2 }}
        animate={done ? { opacity: 1, y: 0, rotate: 2 } : { opacity: 0, y: 10, rotate: 2 }}
        transition={{ duration: 0.5, ease }}
      >
        <p className="font-mono text-[11px] text-faint">ownership map · newer</p>
        <div className="mt-2 space-y-1 font-mono text-[12.5px] leading-relaxed">
          <p className="rounded-[4px] bg-proof-soft px-1.5 text-proof">- session-replay: product-analytics</p>
          <p className="rounded-[4px] bg-cobalt-soft px-1.5 text-cobalt">+ session-replay: replay</p>
        </div>
      </motion.div>

      {/* The fix, routed to its owner */}
      <motion.div
        className="absolute -bottom-16 -left-4 hidden w-[280px] rounded-[16px] bg-night p-4 text-paper shadow-[0_22px_50px_-20px_rgb(13_14_18/0.6)] sm:block lg:-left-12"
        initial={reduce ? false : { opacity: 0, y: 12, rotate: -1.5 }}
        animate={done ? { opacity: 1, y: 0, rotate: -1.5 } : { opacity: 0, y: 12, rotate: -1.5 }}
        transition={{ duration: 0.5, delay: reduce ? 0 : 0.25, ease }}
      >
        <div className="flex items-center gap-3">
          <span className="grid size-9 shrink-0 place-items-center rounded-full bg-cobalt font-mono text-[12px] font-bold">RL</span>
          <div className="min-w-0">
            <p className="text-[14px] font-semibold">Fix routed to the Replay lead</p>
            <p className="text-[12.5px] text-[#a3a8b3]">Owner of the handbook page, by evidence</p>
          </div>
        </div>
        <div className="mt-3 flex items-center justify-between rounded-[10px] bg-night-2 px-3 py-2">
          <span className="font-mono text-[11.5px] text-[#a3a8b3]">1 line to change</span>
          <span className="inline-flex items-center gap-1 font-mono text-[11.5px] font-semibold text-marker">
            File issue <ArrowUpRight size={12} weight="bold" />
          </span>
        </div>
      </motion.div>
    </div>
  )
}

// What each verdict means, read beside the sheet.
const legend: [Verdict, string][] = [
  ['verified', 'A source says it, and nothing newer replaced it.'],
  ['stale', 'A newer source replaced it. Canon shows which.'],
  ['disputed', 'Two current sources disagree.'],
  ['unsupported', 'Nothing backs it, so Canon does not say it.'],
]

export function Nav() {
  const links = [
    ['How it checks', '#check'],
    ['Product', '#product'],
    ['Demo company', '#company'],
  ]
  return (
    <header className="relative z-10">
      <Container className="flex h-20 items-center justify-between">
        <a href="/" className="text-ink" aria-label="Canon home">
          <Wordmark />
        </a>
        <nav aria-label="Sections" className="hidden items-center gap-1 md:flex">
          {links.map(([label, href]) => (
            <a key={href} href={href} className="rounded-full px-4 py-2 text-[14.5px] font-medium text-muted transition-colors hover:bg-paper-2 hover:text-ink">
              {label}
            </a>
          ))}
        </nav>
        <a
          href={REPO_URL}
          aria-label="Canon on GitHub"
          className="grid size-11 place-items-center rounded-full text-ink shadow-[inset_0_0_0_1.5px_var(--line-strong)] transition-shadow hover:shadow-[inset_0_0_0_1.5px_var(--ink)]"
        >
          <GithubLogo size={19} weight="bold" />
        </a>
      </Container>
    </header>
  )
}

export function Hero() {
  const reduce = useReducedMotion()
  return (
    <Slab tone="paper" className="pb-20 sm:pb-24">
      <Nav />
      <Container className="pt-8 sm:pt-12 lg:pt-14">
        <motion.div initial={reduce ? false : { opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.7, ease }}>
          <p className="font-mono text-[12.5px] text-muted">A company brain, built on FalkorDB</p>
          <h1 className="display mt-5 max-w-[1100px] text-[46px] text-ink sm:text-[64px] lg:text-[84px]">
            Every answer, checked against <span className="marker">what's true today.</span>
          </h1>
        </motion.div>
      </Container>
      <Container className="mt-12 grid items-start gap-x-16 gap-y-16 lg:mt-16 lg:grid-cols-[minmax(0,0.62fr)_minmax(0,1fr)]">
        <motion.div initial={reduce ? false : { opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.7, delay: 0.08, ease }} className="lg:pt-2">
          <p className="max-w-[26rem] text-[18.5px] leading-relaxed text-muted text-pretty">
            Canon connects your docs, tickets and chats into one graph, then checks each sentence it tells you: sourced, current, owned.
          </p>
          <div className="mt-10 flex flex-wrap gap-3">
            <Button href="#check" variant="ink">
              See how it checks <ArrowRight size={16} weight="bold" className="transition-transform group-hover:translate-x-0.5" />
            </Button>
            <Button href={REPO_URL} variant="line">
              View on GitHub
            </Button>
          </div>
          <dl className="mt-14 grid max-w-[26rem] grid-cols-2 gap-x-6 gap-y-5 border-t border-line pt-7">
            {legend.map(([verdict, meaning]) => (
              <div key={verdict}>
                <dt>
                  <VerdictTag verdict={verdict} />
                </dt>
                <dd className="mt-2 text-[13.5px] leading-snug text-muted">{meaning}</dd>
              </div>
            ))}
          </dl>
        </motion.div>
        <motion.div
          className="pt-4 pb-2 sm:px-6 sm:pt-8 sm:pb-16 lg:px-0 lg:pt-0"
          initial={reduce ? false : { opacity: 0, y: 24 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.8, delay: 0.1, ease }}
        >
          <AnswerSheet />
        </motion.div>
      </Container>
    </Slab>
  )
}
