import { ArrowUpRight } from '@phosphor-icons/react'
import { motion } from 'motion/react'
import { Button, Container, REPO_URL, Slab } from '../ui'
import { ease, useSeen } from './draw'

/** The headline's correction: the stale words are struck as they come into view. */
function Struck() {
  const { ref, run, reduce } = useSeen<HTMLSpanElement>(0.8)
  return (
    <span ref={ref} className="relative whitespace-nowrap text-faint">
      last quarter's
      <motion.span
        aria-hidden="true"
        className="absolute top-[54%] left-[-2%] h-[0.085em] w-[104%] origin-left rounded-full bg-proof"
        initial={reduce ? false : { scaleX: 0 }}
        animate={run ? { scaleX: 1 } : undefined}
        transition={{ duration: 0.6, delay: reduce ? 0 : 0.3, ease }}
      />
    </span>
  )
}

/** The mark, drawn one line at a time: checked, plain, out of date. */
function DrawnMark({ run, reduce }: { run: boolean; reduce: boolean }) {
  const bars = [
    { y: 0, w: 40, fill: 'var(--cobalt)' },
    { y: 11.5, w: 30, fill: 'var(--ink)' },
    { y: 23, w: 20, fill: 'var(--proof)' },
  ]
  return (
    <svg viewBox="0 0 40 30" className="h-[72px] w-auto sm:h-[96px]" aria-hidden="true">
      {bars.map((b, i) => (
        <motion.rect
          key={i}
          x="0"
          y={b.y}
          width={b.w}
          height="7"
          rx="3.5"
          fill={b.fill}
          style={{ transformOrigin: '0px 0px', transformBox: 'fill-box' }}
          initial={reduce ? false : { scaleX: 0 }}
          animate={run ? { scaleX: 1 } : undefined}
          transition={{ duration: 0.55, delay: reduce ? 0 : 0.2 + i * 0.28, ease }}
        />
      ))}
    </svg>
  )
}

/** A proof stamp, pressed onto the sheet once. */
function Stamp({ run, reduce }: { run: boolean; reduce: boolean }) {
  return (
    <motion.svg
      viewBox="0 0 140 140"
      className="size-[124px] shrink-0 text-cobalt sm:size-[140px]"
      role="img"
      aria-label="Checked today"
      initial={reduce ? false : { opacity: 0, scale: 1.25, rotate: -2 }}
      animate={run ? { opacity: 1, scale: 1, rotate: -9 } : undefined}
      transition={{ duration: 0.35, delay: reduce ? 0 : 1.2, ease: [0.5, 0, 0.2, 1] }}
    >
      <defs>
        <path id="stamp-ring" d="M 70 70 m -48 0 a 48 48 0 1 1 96 0 a 48 48 0 1 1 -96 0" />
      </defs>
      <circle cx="70" cy="70" r="66" fill="none" stroke="currentColor" strokeWidth="3" />
      <circle cx="70" cy="70" r="36" fill="none" stroke="currentColor" strokeWidth="1.5" />
      <text fontSize="14.5" fontWeight="700" fill="currentColor">
        <textPath href="#stamp-ring" startOffset="0" textLength="298" lengthAdjust="spacing">
          Checked today · Checked today ·
        </textPath>
      </text>
      <path d="M 55 71 L 66 82 L 86 59" fill="none" stroke="currentColor" strokeWidth="6" strokeLinecap="round" strokeLinejoin="round" />
    </motion.svg>
  )
}

const colophon = [
  ['Built for', 'The FalkorDB Hackathon 2026, Track 03'],
  ['Licence', 'Open source under Apache-2.0'],
  ['Set in', 'Funnel Display and Funnel Sans, code in JetBrains Mono'],
]

const columns: [string, [string, string][]][] = [
  [
    'On this page',
    [
      ['How it checks', '#check'],
      ['Product', '#product'],
      ['Demo company', '#company'],
    ],
  ],
  [
    'Elsewhere',
    [
      ['GitHub', REPO_URL],
      ['FalkorDB', 'https://www.falkordb.com'],
    ],
  ],
]

function Colophon() {
  const { ref, run, reduce } = useSeen<HTMLDivElement>(0.3)
  return (
    <div ref={ref} className="border-t border-line">
      <Container className="py-14 sm:py-16">
        <div className="grid gap-12 lg:grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)_auto] lg:gap-16">
          <div>
            <div className="flex items-end gap-5">
              <DrawnMark run={run} reduce={reduce} />
              <span className="pb-0.5 font-display text-[40px] leading-none font-semibold tracking-[-0.04em] sm:text-[52px]">Canon</span>
            </div>
            <dl className="mt-10 max-w-[30rem] divide-y divide-line border-y border-line">
              {colophon.map(([term, text]) => (
                <div key={term} className="grid grid-cols-[96px_minmax(0,1fr)] gap-4 py-3 text-[14.5px] sm:grid-cols-[110px_minmax(0,1fr)]">
                  <dt className="text-faint">{term}</dt>
                  <dd className="text-ink">{text}</dd>
                </div>
              ))}
            </dl>
          </div>

          <nav aria-label="Footer" className="grid grid-cols-2 gap-8 self-start lg:pt-4">
            {columns.map(([heading, links]) => (
              <div key={heading}>
                <p className="text-[14px] text-faint">{heading}</p>
                <ul className="mt-4 space-y-3">
                  {links.map(([label, href]) => (
                    <li key={label}>
                      <a href={href} className="text-[15.5px] font-medium text-ink decoration-line-strong underline-offset-4 transition-colors hover:text-cobalt hover:underline">
                        {label}
                      </a>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </nav>

          <div className="flex lg:justify-end lg:pt-2">
            <Stamp run={run} reduce={reduce} />
          </div>
        </div>
      </Container>
    </div>
  )
}

export function Closing() {
  return (
    <Slab tone="paper" className="ruled">
      <Container className="py-24 sm:py-32">
        <h2 className="display max-w-[1000px] text-[44px] text-balance sm:text-[72px] lg:text-[84px]">
          Stop answering from <Struck /> handbook.
        </h2>
        <div className="mt-10">
          <Button href={REPO_URL} variant="ink">
            View on GitHub <ArrowUpRight size={16} weight="bold" />
          </Button>
        </div>
      </Container>
      <div className="bg-paper">
        <Colophon />
      </div>
    </Slab>
  )
}
