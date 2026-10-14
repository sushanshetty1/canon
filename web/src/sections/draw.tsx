import { animate, useInView, useReducedMotion } from 'motion/react'
import { useEffect, useRef } from 'react'

export const ease = [0.22, 1, 0.36, 1] as const

/** Starts an illustration once, the first time it scrolls into view. With reduced motion it is shown finished. */
export function useSeen<T extends Element>(amount = 0.35) {
  const ref = useRef<T>(null)
  const seen = useInView(ref, { once: true, amount })
  const reduce = !!useReducedMotion()
  return { ref, run: seen || reduce, reduce }
}

/**
 * A dot that travels along an SVG path once. The path is measured in the browser, so the dot follows
 * any curve exactly at any size. It is hidden before it sets off and after it arrives.
 */
export function Traveller({
  d,
  run,
  delay = 0,
  duration = 1,
  r = 4,
  fill = 'currentColor',
  stay = false,
  className,
}: {
  d: string
  run: boolean
  delay?: number
  duration?: number
  r?: number
  fill?: string
  /** Keep the dot at the end of the path instead of hiding it. */
  stay?: boolean
  className?: string
}) {
  const pathRef = useRef<SVGPathElement>(null)
  const dotRef = useRef<SVGCircleElement>(null)
  useEffect(() => {
    const path = pathRef.current
    const dot = dotRef.current
    if (!run || !path || !dot) return
    const length = path.getTotalLength()
    const place = (v: number) => {
      const p = path.getPointAtLength(v * length)
      dot.setAttribute('cx', String(p.x))
      dot.setAttribute('cy', String(p.y))
    }
    const controls = animate(0, 1, {
      duration,
      delay,
      ease: [0.45, 0, 0.25, 1],
      onUpdate: (v) => {
        place(v)
        dot.style.opacity = '1'
      },
      onComplete: () => {
        place(1)
        if (!stay) dot.style.opacity = '0'
      },
    })
    return () => controls.stop()
  }, [run, delay, duration, stay])
  return (
    <g aria-hidden="true">
      <path ref={pathRef} d={d} fill="none" stroke="none" />
      <circle ref={dotRef} r={r} fill={fill} className={className} style={{ opacity: 0 }} />
    </g>
  )
}
