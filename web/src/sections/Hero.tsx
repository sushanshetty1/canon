import { ArrowRight, GithubLogo } from '@phosphor-icons/react'
import { motion, useReducedMotion } from 'motion/react'
import { Button, Container, REPO_URL, Slab, Wordmark } from '../ui'

const ease = [0.22, 1, 0.36, 1] as const

// The board covers January to October; "today" sits halfway through October.
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct']
const TODAY = 9.5 // in months from the start of January
const SPAN = 10.4 // the board shows a little past today
const SWEEP = 3.4 // seconds for today's line to travel from January to today

type Bar = { from: number; to?: number; label: string; tone: 'current' | 'ended' | 'disputed' }
type Row = { topic: string; bars: Bar[]; pin?: { at: number; label: string } }

// An example company over ten months. Facts are bars that span the months they held.
const rows: Row[] = [
  {
    topic: 'Who owns session replay',
    bars: [
      { from: 0, to: 5.6, label: 'Product Analytics', tone: 'ended' },
      { from: 5.6, label: 'Replay team', tone: 'current' },
    ],
    pin: { at: 6.75, label: 'Handbook still says Product Analytics' },
  },
  {
    topic: 'How feature flags evaluate',
    bars: [
      { from: 0, to: 3.8, label: 'Remote by default', tone: 'ended' },
      { from: 3.8, label: 'Local by default', tone: 'current' },
    ],
  },
  {
    topic: 'Deploying on Fridays',
    bars: [
      { from: 1.2, label: 'Allowed', tone: 'disputed' },
      { from: 7.2, label: 'Frozen', tone: 'disputed' },
    ],
  },
  {
    topic: 'Query rate limits',
    bars: [
      { from: 1.9, to: 3.4, label: 'Proposed', tone: 'ended' },
      { from: 3.4, label: 'Accepted in an RFC', tone: 'current' },
    ],
  },
]

const pct = (months: number) => `${(months / SPAN) * 100}%`
/** When the sweep reaches a moment in the year. */
const at = (months: number) => (months / TODAY) * SWEEP

const barTone = {
  current: 'bg-cobalt text-paper',
  disputed: 'bg-amber-soft text-amber ring-1 ring-inset ring-[#ecc98a]',
  ended: 'text-faint',
}

function TimelineBar({ bar, row, reduce }: { bar: Bar; row: number; reduce: boolean }) {
  const end = bar.to ?? SPAN
  const stacked = bar.tone === 'disputed'
  const grow = Math.max(0.35, at(Math.min(end, TODAY)) - at(bar.from))
  return (
    <motion.div
      className="absolute"
      style={{
        left: `calc(${pct(bar.from)} + 3px)`,
        width: `calc(${pct(end - bar.from)} - 6px)`,
        top: stacked ? (bar.from > 5 ? '52%' : '4%') : '12%',
        height: stacked ? '44%' : '76%',
      }}
      // A bar grows with time: it reaches its end when today's line does.
      initial={reduce ? false : { clipPath: 'inset(0 100% 0 0 round 12px)' }}
      animate={{ clipPath: 'inset(0 0% 0 0 round 12px)' }}
      transition={{ duration: reduce ? 0 : grow, delay: reduce ? 0 : at(bar.from) + row * 0.03, ease: 'linear' }}
    >
      {/* Every fact starts out current. One that a later fact replaced turns grey and struck the moment it is replaced:
          it stays on record, it just stops being true. */}
      <div className={`relative flex h-full items-center overflow-hidden rounded-[12px] px-3.5 ${bar.tone === 'ended' ? barTone.current : barTone[bar.tone]}`}>
        <span className="truncate text-[14px] font-semibold">{bar.label}</span>
        {bar.tone === 'ended' && (
          <motion.div
            className="absolute inset-0 flex items-center rounded-[12px] px-3.5 text-faint"
            style={{ backgroundImage: 'repeating-linear-gradient(135deg, var(--paper-2) 0 7px, #e7e9ee 7px 8px)', boxShadow: 'inset 0 0 0 1px var(--line)' }}
            initial={reduce ? false : { opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: reduce ? 0 : 0.35, delay: reduce ? 0 : at(end) + row * 0.03 }}
          >
            <span className="truncate text-[14px] font-semibold line-through decoration-faint/60">{bar.label}</span>
          </motion.div>
        )}
      </div>
    </motion.div>
  )
}

function KnowledgeTimeline() {
  const reduce = !!useReducedMotion()
  return (
    <div className="relative">
      {/* Months */}
      <div className="relative h-8 lg:ml-[220px]">
        {MONTHS.map((m, i) => (
          <span key={m} className="absolute top-0 pl-2 text-[13px] font-medium text-faint" style={{ left: pct(i) }}>
            {m}
          </span>
        ))}
      </div>

      <div className="relative">
        {/* Month rules */}
        <div className="pointer-events-none absolute inset-y-0 right-0 left-0 lg:left-[220px]" aria-hidden="true">
          {MONTHS.map((m, i) => (
            <span key={m} className="absolute inset-y-0 w-px bg-line" style={{ left: pct(i) }} />
          ))}
        </div>

        {rows.map((row, r) => (
          <div key={row.topic} className="relative grid grid-cols-1 border-t border-line py-3 lg:grid-cols-[220px_minmax(0,1fr)]">
            <div className="pb-2 lg:self-center lg:pr-6 lg:pb-0">
              <p className="text-[15px] font-semibold tracking-[-0.01em] text-ink">{row.topic}</p>
              {row.bars.some((b) => b.tone === 'disputed') && (
                <motion.p
                  className="mt-0.5 text-[13px] font-semibold text-amber"
                  initial={reduce ? false : { opacity: 0 }}
                  animate={{ opacity: 1 }}
                  transition={{ duration: 0.4, delay: reduce ? 0 : at(7.2) + 0.2 }}
                >
                  Two current answers
                </motion.p>
              )}
            </div>
            <div className="relative h-[58px]">
              {row.bars.map((bar) => (
                <TimelineBar key={bar.label} bar={bar} row={r} reduce={reduce} />
              ))}
              {row.pin && (
                <motion.div
                  className="absolute -top-2.5 z-10"
                  style={{ left: pct(row.pin.at) }}
                  initial={reduce ? false : { opacity: 0, scale: 0.6 }}
                  animate={{ opacity: 1, scale: 1 }}
                  transition={{ duration: 0.4, delay: reduce ? 0 : at(row.pin.at) + 0.1, ease }}
                >
                  <span className="relative flex items-center gap-2 rounded-full bg-proof py-1 pr-3 pl-1 text-[12.5px] font-semibold whitespace-nowrap text-paper shadow-[0_8px_20px_-8px_rgb(224_57_44/0.6)]">
                    <span className="grid size-5 place-items-center rounded-full bg-paper text-[11px] font-bold text-proof">!</span>
                    {row.pin.label}
                  </span>
                </motion.div>
              )}
            </div>
          </div>
        ))}

        {/* Today: a line that walks the year, then stays where the answers are read */}
        <div className="pointer-events-none absolute inset-y-0 right-0 left-0 lg:left-[220px]" aria-hidden="true">
          <motion.div
            className="absolute -top-9 bottom-0 w-0"
            initial={reduce ? false : { left: '0%' }}
            animate={{ left: pct(TODAY) }}
            transition={{ duration: reduce ? 0 : SWEEP, ease: 'linear' }}
          >
            <span className="absolute top-0 -translate-x-1/2 rounded-full bg-ink px-2.5 py-1 text-[12px] font-semibold text-paper">Today</span>
            <span className="absolute top-7 bottom-0 left-0 w-[2px] -translate-x-1/2 bg-ink" />
          </motion.div>
        </div>
      </div>
    </div>
  )
}

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

/** The proofreader's correction: the stale phrase is struck in red, the current word follows. */
function Correction() {
  const reduce = !!useReducedMotion()
  return (
    <span className="whitespace-nowrap">
      <span className="relative text-faint">
        in March
        <motion.span
          aria-hidden="true"
          className="absolute top-[54%] left-[-2%] h-[0.09em] w-[104%] origin-left rounded-full bg-proof"
          initial={reduce ? false : { scaleX: 0 }}
          animate={{ scaleX: 1 }}
          transition={{ duration: 0.55, delay: reduce ? 0 : 0.7, ease }}
        />
      </span>{' '}
      <motion.span
        className="inline-block text-cobalt"
        initial={reduce ? false : { opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5, delay: reduce ? 0 : 1.15, ease }}
      >
        today.
      </motion.span>
    </span>
  )
}

export function Hero() {
  const reduce = useReducedMotion()
  return (
    <Slab tone="paper" className="pb-14 sm:pb-16">
      <Nav />
      <Container className="pt-8 sm:pt-12 lg:pt-12">
        <motion.h1
          className="display max-w-[1180px] text-[46px] text-ink sm:text-[66px] lg:text-[80px]"
          initial={reduce ? false : { opacity: 0, y: 14 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7, ease }}
        >
          Every answer, checked against what's true <Correction />
        </motion.h1>
        <motion.div
          className="mt-9 flex flex-col gap-7 lg:flex-row lg:items-center lg:justify-between"
          initial={reduce ? false : { opacity: 0, y: 14 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7, delay: 0.1, ease }}
        >
          <p className="max-w-[34rem] text-[18px] leading-relaxed text-muted text-pretty">
            Canon reads your docs, tickets and chats into one graph that knows when each fact held, and checks every sentence it tells you against it.
          </p>
          <div className="flex shrink-0 flex-wrap gap-3">
            <Button href="#check" variant="ink">
              See how it checks <ArrowRight size={16} weight="bold" className="transition-transform group-hover:translate-x-0.5" />
            </Button>
            <Button href={REPO_URL} variant="line">
              View on GitHub
            </Button>
          </div>
        </motion.div>
      </Container>
      <Container className="mt-14 sm:mt-16">
        <KnowledgeTimeline />
        <p className="mt-6 text-[14px] text-faint">An example company over ten months. Each bar is a fact, for as long as it held.</p>
      </Container>
    </Slab>
  )
}
