// A sheet of its own beside the screen on a wide window, or a bottom sheet on a narrow one. Esc and the scrim
// close it; the handle drags it down. The same shape as Ask's sources.

import { AnimatePresence, motion, useDragControls, useReducedMotion } from 'motion/react'
import { useEffect, useState, type ReactNode } from 'react'
import { ease } from './Answer'

export function useWide() {
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

export function Sheet({ open, onClose, labelledBy, children, width = 'w-[min(470px,42vw)]' }: {
  open: boolean
  onClose: () => void
  labelledBy: string
  children: ReactNode
  width?: string
}) {
  const wide = useWide()
  const reduce = useReducedMotion()
  const drag = useDragControls()

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (wide) {
    return (
      <AnimatePresence>
        {open && (
          <motion.aside
            key="panel"
            aria-labelledby={labelledBy}
            className={`slab sticky top-3 h-[calc(100dvh-24px)] ${width} shrink-0 overflow-y-auto bg-paper px-7 pt-7 pb-10`}
            initial={reduce ? false : { opacity: 0, x: 28 }}
            animate={{ opacity: 1, x: 0 }}
            exit={reduce ? { opacity: 0 } : { opacity: 0, x: 28 }}
            transition={{ duration: 0.4, ease }}
          >
            {children}
          </motion.aside>
        )}
      </AnimatePresence>
    )
  }
  return (
    <AnimatePresence>
      {open && (
        <>
          <motion.div
            key="scrim"
            className="fixed inset-0 z-40 bg-night/30"
            onClick={onClose}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.25 }}
          />
          <motion.div
            key="sheet"
            role="dialog"
            aria-modal="true"
            aria-labelledby={labelledBy}
            className="fixed inset-x-0 bottom-0 z-50 flex max-h-[86dvh] flex-col rounded-t-[26px] bg-paper shadow-[0_-20px_60px_-20px_rgb(13_14_18/0.35)]"
            initial={reduce ? false : { y: '100%' }}
            animate={{ y: 0 }}
            exit={reduce ? { opacity: 0 } : { y: '100%' }}
            transition={{ duration: 0.45, ease }}
            drag={reduce ? false : 'y'}
            dragListener={false}
            dragControls={drag}
            dragConstraints={{ top: 0, bottom: 0 }}
            dragElastic={{ top: 0, bottom: 0.6 }}
            onDragEnd={(_, info) => (info.offset.y > 120 || info.velocity.y > 600) && onClose()}
          >
            <div className="flex touch-none justify-center pt-3 pb-2" aria-hidden="true" onPointerDown={(e) => drag.start(e)}>
              <span className="h-1 w-10 rounded-full bg-line-strong" />
            </div>
            <div className="sheet-scroll overflow-y-auto px-5 pt-2 pb-10">{children}</div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  )
}
