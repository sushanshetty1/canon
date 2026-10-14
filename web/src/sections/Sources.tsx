import { motion, useReducedMotion } from 'motion/react'
import { Slab } from '../ui'

// What Canon reads, and the one thing it takes from each.
const sources = [
  ['Handbook', 'what the company says'],
  ['Design docs', 'what was decided'],
  ['Issues', 'what is broken'],
  ['Pull requests', 'what actually changed'],
  ['Reviews', 'who knows the code'],
  ['Forum threads', 'what people keep asking'],
  ['Ownership map', 'who owns what'],
  ['Team pages', 'who works where'],
]

export function Sources() {
  const reduce = useReducedMotion()
  const row = [...sources, ...sources]
  return (
    <Slab tone="night" className="py-7">
      <div className="relative overflow-hidden [mask-image:linear-gradient(to_right,transparent,black_8%,black_92%,transparent)]">
        <motion.div
          className="flex w-max items-center gap-12 pr-12"
          animate={reduce ? undefined : { x: ['0%', '-50%'] }}
          transition={{ duration: 46, ease: 'linear', repeat: Infinity }}
        >
          {row.map(([name, what], i) => (
            <span key={i} className="flex items-baseline gap-3 whitespace-nowrap">
              <span className="font-display text-[26px] font-semibold tracking-[-0.03em] text-paper">{name}</span>
              <span className="text-[15px] text-[#7d828e]">{what}</span>
            </span>
          ))}
        </motion.div>
      </div>
    </Slab>
  )
}
