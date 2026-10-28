/** The sheet every librarian question and picker opens in. No modals anywhere (DESIGN.md): it closes with the
 *  cross, Escape, or a tap outside. Children render the body (`.sheet-body`) and, when they have one, the foot
 *  (`.sheet-foot`); they mount when the sheet opens and unmount when it closes, so their state starts fresh. */
import { useEffect, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { AnimatePresence, motion } from 'motion/react'
import { useReducedMotion, useViewport } from './layout'
import { IClose } from './icons'
import './parts.css'

/** The sheet's one authored moment: it rises on a spring. A bottom sheet in portrait, a right panel in landscape. */
const spring = { type: 'spring' as const, stiffness: 320, damping: 20, mass: 0.8 }
const leave = { duration: 0.18, ease: [0.22, 1, 0.36, 1] as const }

export function Sheet({ open, onClose, title, sub, children, label }: {
  open: boolean; onClose: () => void; title: string; sub?: string; children: ReactNode; label?: string
}) {
  const vp = useViewport()
  const reduced = useReducedMotion()
  const bottom = vp.h > vp.w
  useEffect(() => {
    if (!open) return
    // Capture phase, and stop there: Escape closes the sheet alone, not the panel that opened it.
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') { e.stopImmediatePropagation(); onClose() } }
    window.addEventListener('keydown', onKey, true)
    return () => window.removeEventListener('keydown', onKey, true)
  }, [open, onClose])
  const off = bottom ? { y: '100%' } : { x: '100%' }
  const on = bottom ? { y: 0 } : { x: 0 }
  // Rendered at the app root: a sheet opened from a sliding panel must not be positioned inside that panel's transform.
  const host = document.querySelector('.fo') ?? document.body
  return createPortal(
    <AnimatePresence>
      {open && (
        <>
          <motion.div key="scrim" className="sheet-scrim" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: reduced ? 0 : 0.16 }} onClick={onClose} aria-hidden="true" />
          <motion.section
            key="sheet" role="dialog" aria-modal="true" aria-label={label ?? title} className={`sheet ${bottom ? 'is-bottom' : 'is-side'}`}
            initial={reduced ? { opacity: 0 } : off} animate={reduced ? { opacity: 1 } : on} exit={reduced ? { opacity: 0, transition: { duration: 0 } } : { ...off, transition: leave }}
            transition={reduced ? { duration: 0 } : spring}
          >
            {bottom && <div className="sheet-grab" aria-hidden="true" />}
            <div className="sheet-head">
              <div className="grow">
                <h2>{title}</h2>
                {sub && <p>{sub}</p>}
              </div>
              <button type="button" className="btn-icon" onClick={onClose} aria-label="Close"><IClose size={20} /></button>
            </div>
            {children}
          </motion.section>
        </>
      )}
    </AnimatePresence>,
    host,
  )
}
