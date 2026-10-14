import { motion, useReducedMotion } from 'motion/react'
import { Container, Slab } from '../ui'

const ease = [0.22, 1, 0.36, 1] as const

// PostHog's public record, counted from its repositories and site on 15 October 2026.
const stats = [
  { value: '58', label: 'teams, each with members, a lead and the areas it owns', tone: 'bg-marker text-ink' },
  { value: '44', label: 'dated design docs (RFCs), with their review threads', tone: 'bg-paper text-ink' },
  { value: '11,479', label: 'issues, with assignees, labels and linked pull requests', tone: 'bg-night-2 text-paper ring-1 ring-night-line' },
  { value: '6,830', label: 'community forum threads: what people actually ask', tone: 'bg-cobalt text-paper' },
]

export function Company() {
  const reduce = useReducedMotion()
  return (
    <Slab id="company" tone="night" className="ruled-night py-24 sm:py-32">
      <Container className="grid gap-14 lg:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)] lg:items-center">
        <div>
          <div className="flex items-center gap-3">
            <img src="https://cdn.simpleicons.org/posthog/ffffff" alt="" className="size-7" loading="lazy" />
            <span className="font-mono text-[12.5px] text-[#a3a8b3]">The demo company</span>
          </div>
          <h2 className="display mt-6 text-[40px] text-balance sm:text-[56px]">Shown on a company that works in public.</h2>
          <p className="mt-6 max-w-[30rem] text-[18px] leading-relaxed text-pretty text-[#a3a8b3]">
            PostHog publishes its handbook, its design docs, its issues and its team pages. Canon reads all of it, so every answer in the demo can be checked
            against a real source.
          </p>
          <p className="mt-6 max-w-[30rem] text-[14px] leading-relaxed text-[#7d828e]">
            Public data only. People appear by the GitHub handles and roles PostHog already publishes.
          </p>
        </div>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {stats.map((s, i) => (
            <motion.div
              key={s.value}
              className={`flex min-h-[190px] flex-col justify-between rounded-[22px] p-7 ${s.tone} ${i % 2 === 1 ? 'sm:translate-y-8' : ''}`}
              initial={reduce ? false : { opacity: 0, y: 20 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true, amount: 0.3 }}
              transition={{ duration: 0.6, delay: i * 0.07, ease }}
            >
              <span className="font-display text-[60px] leading-none font-semibold tracking-[-0.05em]">{s.value}</span>
              <span className="mt-6 max-w-[24ch] text-[14.5px] leading-snug opacity-80">{s.label}</span>
            </motion.div>
          ))}
        </div>
      </Container>
    </Slab>
  )
}
