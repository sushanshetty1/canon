import { ArrowBendDownRight, ArrowRight, GitPullRequest, MagnifyingGlass, UsersThree } from '@phosphor-icons/react'
import { motion, useReducedMotion } from 'motion/react'
import type { ReactNode } from 'react'
import { Container, SectionTitle, Slab, VerdictTag } from '../ui'

const ease = [0.22, 1, 0.36, 1] as const

function Cell({ title, body, className = '', tone = 'paper', children, delay = 0 }: {
  title: string
  body: string
  className?: string
  tone?: 'paper' | 'night' | 'cobalt' | 'marker' | 'paper-2'
  children: ReactNode
  delay?: number
}) {
  const reduce = useReducedMotion()
  const tones = {
    paper: 'bg-paper ring-1 ring-line',
    'paper-2': 'bg-paper-2',
    night: 'bg-night text-paper',
    cobalt: 'bg-cobalt text-paper',
    marker: 'bg-marker-soft ring-1 ring-[#f0dc84]',
  }
  const muted = tone === 'night' || tone === 'cobalt' ? 'text-white/70' : 'text-muted'
  return (
    <motion.article
      className={`flex min-w-0 flex-col overflow-hidden rounded-[22px] ${tones[tone]} ${className}`}
      initial={reduce ? false : { opacity: 0, y: 18 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, amount: 0.25 }}
      transition={{ duration: 0.6, delay, ease }}
    >
      <div className="p-7 sm:p-8">
        <h3 className="font-display text-[24px] font-semibold tracking-[-0.03em]">{title}</h3>
        <p className={`mt-2 max-w-[40ch] text-[15.5px] leading-relaxed text-pretty ${muted}`}>{body}</p>
      </div>
      <div className="mt-auto px-7 pb-7 sm:px-8 sm:pb-8">{children}</div>
    </motion.article>
  )
}

function AskMini() {
  return (
    <div className="rounded-[16px] bg-paper p-4 text-ink shadow-[0_20px_40px_-24px_rgb(10_20_80/0.6)]">
      <div className="flex items-center gap-3 rounded-[12px] bg-paper-2 px-4 py-3">
        <MagnifyingGlass size={17} weight="bold" className="text-muted" />
        <span className="text-[15px]">Why did we move feature flags to local evaluation?</span>
      </div>
      <ul className="mt-3 space-y-2.5 px-1">
        {(
          [
            ['verified', 'A design doc proposed it to cut request latency.'],
            ['verified', 'It was accepted, and two pull requests shipped it.'],
            ['disputed', 'The docs page and a newer issue disagree on the default.'],
          ] as const
        ).map(([v, text]) => (
          <li key={text} className="flex items-start gap-3">
            <VerdictTag verdict={v} className="mt-px" />
            <span className="text-[14px] leading-snug text-ink">{text}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

function BusFactorMini() {
  // Two independent people reach the area; a third only through one of them. The flow is 2.
  return (
    <div>
      <div className="flex items-end gap-4">
        <span className="font-display text-[92px] leading-[0.8] font-semibold tracking-[-0.05em] text-marker">2</span>
        <span className="pb-1 text-[14px] leading-snug text-white/70">people could still answer for session replay if anyone else left.</span>
      </div>
      <svg viewBox="0 0 260 90" className="mt-6 h-auto w-full" aria-hidden="true">
        <g stroke="#3a3f4b" strokeWidth="1.5" fill="none">
          <path d="M40 45 C 90 45, 100 18, 150 18" />
          <path d="M40 45 C 90 45, 100 72, 150 72" />
          <path d="M150 18 L 220 18" />
          <path d="M150 72 L 220 72" />
        </g>
        <g stroke="var(--marker)" strokeWidth="2.5" fill="none" strokeLinecap="round">
          <path d="M40 45 C 90 45, 100 18, 150 18 L 220 18" strokeDasharray="4 5" />
          <path d="M40 45 C 90 45, 100 72, 150 72 L 220 72" strokeDasharray="4 5" />
        </g>
        <circle cx="40" cy="45" r="9" fill="var(--paper)" />
        <circle cx="150" cy="18" r="6" fill="#5b606b" />
        <circle cx="150" cy="72" r="6" fill="#5b606b" />
        <circle cx="228" cy="18" r="9" fill="var(--marker)" />
        <circle cx="228" cy="72" r="9" fill="var(--marker)" />
      </svg>
      <p className="mt-2 font-mono text-[11.5px] text-white/50">algo.maxFlow from the area to the people who know it</p>
    </div>
  )
}

function KnowsMini() {
  const people = [
    ['MK', 'Reviewed the last 3 replay changes', 'var(--cobalt)'],
    ['AJ', 'Wrote the replay design doc', 'var(--ink)'],
    ['TS', 'Answers replay questions on the forum', '#8b909a'],
  ]
  return (
    <ul className="space-y-2.5">
      {people.map(([who, why, bg], i) => (
        <li key={who} className="flex items-center gap-3 rounded-[14px] bg-paper px-3 py-2.5 ring-1 ring-line">
          <span className="grid size-8 shrink-0 place-items-center rounded-full font-mono text-[11px] font-bold text-paper" style={{ background: bg }}>
            {who}
          </span>
          <span className="min-w-0 flex-1 text-[13.5px] leading-snug">{why}</span>
          <span className="font-mono text-[11px] text-faint">#{i + 1}</span>
        </li>
      ))}
    </ul>
  )
}

function FixMini() {
  return (
    <div className="relative">
      <div className="absolute inset-x-6 -bottom-3 h-full rounded-[16px] bg-paper/60 ring-1 ring-[#f0dc84]" aria-hidden="true" />
      <div className="relative rounded-[16px] bg-paper p-5 ring-1 ring-[#f0dc84]">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <VerdictTag verdict="stale" />
          <span className="font-mono text-[11.5px] text-faint">handbook / product-analytics</span>
        </div>
        <p className="mt-3 text-[15px] leading-snug">
          <span className="text-proof line-through decoration-proof/60">Product Analytics owns session replay</span>
          <ArrowBendDownRight size={14} weight="bold" className="mx-1.5 inline text-faint" />
          <span className="bg-marker-soft px-1">Replay owns session replay</span>
        </p>
        <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-line pt-4">
          <span className="flex items-center gap-2 text-[13.5px] text-muted">
            <UsersThree size={16} weight="bold" /> Routed to the page's owner
          </span>
          <span className="inline-flex h-9 items-center gap-2 rounded-full bg-ink px-4 text-[13.5px] font-semibold text-paper">
            <GitPullRequest size={15} weight="bold" /> File the fix
          </span>
        </div>
      </div>
    </div>
  )
}

function DecisionsMini() {
  const events = [
    ['Proposed', 'Design doc opened for review', 'bg-paper ring-1 ring-line-strong'],
    ['Accepted', 'Merged after review', 'bg-cobalt'],
    ['Shipped', 'Implemented in two pull requests', 'bg-cobalt'],
    ['Replaced', 'A later design doc changed the default', 'bg-proof'],
  ]
  return (
    <ol className="relative space-y-4 pl-6">
      <span className="absolute top-2 bottom-2 left-[5px] w-px bg-line-strong" aria-hidden="true" />
      {events.map(([state, what, dot]) => (
        <li key={state} className="relative">
          <span className={`absolute top-1.5 -left-6 size-[11px] rounded-full ${dot}`} />
          <p className="text-[14.5px] font-semibold">{state}</p>
          <p className="text-[13.5px] text-muted">{what}</p>
        </li>
      ))}
    </ol>
  )
}

function CatchUpMini() {
  const changes = [
    ['Owner changed', 'Session replay moved to the Replay team'],
    ['Decision replaced', 'A design doc on flag defaults was superseded'],
    ['Page edited', 'Onboarding guide rewritten, and some claims changed'],
  ]
  return (
    <ul className="space-y-2">
      {changes.map(([kind, what]) => (
        <li key={kind} className="flex items-start gap-3 rounded-[14px] bg-paper px-4 py-3 ring-1 ring-line">
          <ArrowRight size={15} weight="bold" className="mt-[3px] shrink-0 text-cobalt" />
          <div className="min-w-0">
            <p className="text-[13.5px] font-semibold">{kind}</p>
            <p className="text-[13.5px] leading-snug text-muted">{what}</p>
          </div>
        </li>
      ))}
    </ul>
  )
}

export function Product() {
  return (
    <Slab id="product" tone="paper" className="py-24 sm:py-32">
      <Container>
        <SectionTitle
          title="What a team asks Canon every day."
          lede="Questions about who, why and what changed. Each answer is checked the same way, and each one cites where it came from."
        />
        <div className="mt-14 grid gap-4 lg:grid-cols-6">
          <Cell className="lg:col-span-4" tone="cobalt" title="Ask anything about the company" body="Plain questions, answered claim by claim. Every sentence carries its verdict and its source.">
            <AskMini />
          </Cell>
          <Cell className="lg:col-span-2" tone="night" title="Bus factor" body="For each area, how many people could still answer if the rest left." delay={0.05}>
            <BusFactorMini />
          </Cell>
          <Cell className="lg:col-span-2" tone="paper-2" title="Who actually knows" body="Ranked by what people did: reviewed, wrote, decided, answered. Not by job title." delay={0.05}>
            <KnowsMini />
          </Cell>
          <Cell className="lg:col-span-4" tone="marker" title="The fix queue" body="When a page goes out of date, Canon drafts the change and sends it to whoever owns that page. A person approves it." delay={0.1}>
            <FixMini />
          </Cell>
          <Cell className="lg:col-span-3" tone="paper" title="Decisions, with their history" body="Every design doc from proposal to replacement, with the pull requests that shipped it." delay={0.05}>
            <DecisionsMini />
          </Cell>
          <Cell className="lg:col-span-3" tone="paper-2" title="Catch me up" body="Back from leave? See what changed since a date: owners, decisions, and pages that now say something different." delay={0.1}>
            <CatchUpMini />
          </Cell>
        </div>
      </Container>
    </Slab>
  )
}
