/** R3's two raised surfaces (docs/design/r3, "Sheets"): the bottom sheet over the dimmed shelf (the Book sheet) and the
 *  centred dialog (the Groups sheet). Both are rendered at the app root, dim what is under them, close on a tap on the
 *  dim, on Escape and on their own button, take focus when they open and give it back when they close. The sheet springs
 *  up from the bottom edge and follows a downward drag from its handle or head; the dialog scales in from just below
 *  its place. Reduced motion: both fade. */
import { useEffect, useRef, type PointerEvent as ReactPointerEvent, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { AnimatePresence, motion, useDragControls, type PanInfo } from 'motion/react'
import { useReducedMotion } from './layout'
import { EASE_OUT, FADE_IN, FADE_OUT, SPRING_SHEET } from './Sheet'

/** Escape closes the topmost surface only: open surfaces stack, and one listener closes the last one opened. Menus
 *  inside a surface close themselves first (they listen in the capture phase and stop the event). */
const stack: { current: () => void }[] = []
function onEscape(e: KeyboardEvent) {
  if (e.key !== 'Escape' || !stack.length) return
  stack[stack.length - 1].current()
}
function useEscape(open: boolean, onClose: () => void) {
  const ref = useRef(onClose)
  useEffect(() => { ref.current = onClose })
  useEffect(() => {
    if (!open) return
    if (!stack.length) window.addEventListener('keydown', onEscape)
    stack.push(ref)
    return () => {
      stack.splice(stack.indexOf(ref), 1)
      if (!stack.length) window.removeEventListener('keydown', onEscape)
    }
  }, [open])
}

/** Focus moves into the surface when it opens and back to what had it when it closes. */
function useFocusTrap(open: boolean) {
  const panel = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const before = document.activeElement as HTMLElement | null
    const id = window.requestAnimationFrame(() => {
      const el = panel.current
      if (!el || el.contains(document.activeElement)) return
      const first = el.querySelector<HTMLElement>('[data-autofocus], button:not([disabled]), [href], input')
      ;(first ?? el).focus({ preventScroll: true })
    })
    return () => { window.cancelAnimationFrame(id); before?.focus?.({ preventScroll: true }) }
  }, [open])
  return panel
}

function host(): Element {
  return document.querySelector('.fo') ?? document.body
}

function Dim({ onClose }: { onClose: () => void }) {
  return (
    <motion.div
      className="r3-scrim" aria-hidden="true" onClick={onClose}
      initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0, transition: FADE_OUT }} transition={FADE_IN}
    />
  )
}

export function BottomSheet({ open, onClose, label, className = '', children }: {
  open: boolean; onClose: () => void; label: string; className?: string; children: ReactNode
}) {
  const reduced = useReducedMotion()
  const controls = useDragControls()
  const panel = useFocusTrap(open)
  useEscape(open, onClose)

  const startDrag = (e: ReactPointerEvent<HTMLDivElement>) => {
    if (e.button > 0) return
    const t = e.target as HTMLElement
    if (t.closest('button, a, input, textarea, select, [role="menu"], .r3-scroll')) return
    controls.start(e)
  }
  const onDragEnd = (_: unknown, info: PanInfo) => {
    const h = panel.current?.offsetHeight ?? 600
    if (info.offset.y > h * 0.3 || (info.velocity.y > 500 && info.offset.y > 24)) onClose()
  }

  return createPortal(
    <AnimatePresence>
      {open && <Dim key="dim" onClose={onClose} />}
      {open && (
        <motion.div
          key="sheet" ref={panel} role="dialog" aria-modal="true" aria-label={label} tabIndex={-1}
          className={`r3-sheet ${className}`}
          initial={reduced ? { opacity: 0 } : { y: '100%' }}
          animate={reduced ? { opacity: 1 } : { y: 0 }}
          exit={reduced ? { opacity: 0, transition: FADE_OUT } : { y: '100%', transition: { duration: 0.24, ease: EASE_OUT } }}
          transition={reduced ? FADE_IN : SPRING_SHEET}
          drag={reduced ? false : 'y'} dragListener={false} dragControls={controls} dragMomentum={false}
          dragConstraints={{ top: 0, bottom: 0 }} dragElastic={{ top: 0.04, bottom: 1 }}
          onDragEnd={onDragEnd} onPointerDown={startDrag}
        >
          <span className="r3-handle" aria-hidden="true" />
          {children}
        </motion.div>
      )}
    </AnimatePresence>,
    host(),
  )
}

export function Dialog({ open, onClose, label, className = '', children }: {
  open: boolean; onClose: () => void; label: string; className?: string; children: ReactNode
}) {
  const reduced = useReducedMotion()
  const panel = useFocusTrap(open)
  useEscape(open, onClose)
  return createPortal(
    <AnimatePresence>
      {open && <Dim key="dim" onClose={onClose} />}
      {open && (
        // The place is a motion element too, so the dialog's own exit plays before both leave.
        <motion.div key="place" className="r3-dialog-place" exit={{ opacity: 1, transition: { duration: 0.14 } }}>
          <motion.div
            ref={panel} role="dialog" aria-modal="true" aria-label={label} tabIndex={-1}
            className={`r3-dialog ${className}`}
            initial={reduced ? { opacity: 0 } : { opacity: 0, y: 24, scale: 0.97 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={reduced ? { opacity: 0, transition: FADE_OUT } : { opacity: 0, y: 12, scale: 0.98, transition: FADE_OUT }}
            transition={reduced ? FADE_IN : { type: 'spring', stiffness: 380, damping: 32, mass: 0.8 }}
          >
            {children}
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>,
    host(),
  )
}

/** One message box (CK's rule for anything that cannot be undone): the question, why, Cancel and the act. */
export function Confirm({ question, why, act, busyWord, busy, msg, onCancel, onAct, danger = true }: {
  question: string; why: string; act: string; busyWord: string; busy: boolean; msg?: string | null; onCancel: () => void; onAct: () => void; danger?: boolean
}) {
  return (
    <motion.div
      className="r3-confirm" role="alertdialog" aria-label={question}
      initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.18, ease: EASE_OUT }}
    >
      <p className="r3-confirm-q">{question}</p>
      <p className="r3-confirm-why">{why}</p>
      {msg && <p className="r3-msg" role="alert">{msg}</p>}
      <div className="r3-confirm-acts">
        <button type="button" className="r3-btn is-line" disabled={busy} onClick={onCancel}>Cancel</button>
        <button type="button" className={`r3-btn ${danger ? 'is-danger' : 'is-solid'}`} disabled={busy} onClick={onAct} data-autofocus>{busy ? busyWord : act}</button>
      </div>
    </motion.div>
  )
}
