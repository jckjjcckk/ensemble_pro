import { useEffect, useRef, type CSSProperties, type PointerEvent as ReactPointerEvent, type ReactNode } from 'react'
import { AnimatePresence, motion, useDragControls, useIsPresent, type HTMLMotionProps, type PanInfo, type Transition } from 'motion/react'
import { useReducedMotion, useViewport } from './layout'
import './sheet.css'

/** The sheet's own spring: arrives from the edge with a touch of give. */
export const SPRING_SHEET: Transition = { type: 'spring', stiffness: 320, damping: 20, mass: 0.8 }
/** Reflow of what stays on screen (covers, a title moving into the box): no overshoot, so text never swings. */
export const SPRING_LAYOUT: Transition = { type: 'spring', stiffness: 320, damping: 30, mass: 0.8 }
/** The app's exponential ease-out (`--ease` in styles.css). */
export const EASE_OUT = [0.22, 1, 0.36, 1] as const
export const FADE_IN: Transition = { duration: 0.2, ease: EASE_OUT }
export const FADE_OUT: Transition = { duration: 0.12, ease: EASE_OUT }
const REDUCED: Transition = { duration: 0.15, ease: EASE_OUT }

/** How far past the viewport edge a sheet rests while closed: its own extent plus room for the shadow. */
const SIDE_W = 380
const BOTTOM_FRACTION = 0.56
const SHADOW = 48

interface SheetProps {
  open: boolean
  onClose: () => void
  label: string
  /** Laid out as a column beside the work by the parent's grid instead of over it: no scrim, no drag. */
  docked?: boolean
  className?: string
  children: ReactNode
}

/**
 * A side panel as a sprung sheet. Landscape: slides in from the right, swipe right to dismiss.
 * Portrait: a half-height bottom sheet with a handle, swipe down to dismiss. Both: a scrim that
 * swallows the dismissing tap, Escape, and the panel's own close button (the children carry it).
 * Docked (a grid column the parent owns) it only slides; the scrim and the drag go away.
 * Keep it mounted with `open` false so the exit can play.
 */
export function Sheet({ open, onClose, label, docked = false, className = '', children }: SheetProps) {
  const vp = useViewport()
  const reduced = useReducedMotion()
  const bottom = !docked && vp.h > vp.w

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  return (
    <AnimatePresence initial={false}>
      {open && !docked && <Scrim key="scrim" onClose={onClose} />}
      {open && (
        <Panel
          key="panel" label={label} className={className} docked={docked} bottom={bottom} reduced={reduced} onClose={onClose}
          off={bottom ? Math.round(vp.h * BOTTOM_FRACTION) + SHADOW : Math.min(SIDE_W, vp.w) + SHADOW}
        >
          {children}
        </Panel>
      )}
    </AnimatePresence>
  )
}

function Panel({ label, className, docked, bottom, reduced, off, onClose, children }: {
  label: string; className: string; docked: boolean; bottom: boolean; reduced: boolean; off: number; onClose: () => void; children: ReactNode
}) {
  const ref = useRef<HTMLElement>(null)
  const present = useIsPresent()
  const controls = useDragControls()
  const axis = bottom ? 'y' : 'x'
  const hidden = reduced ? { opacity: 0 } : { [axis]: off }
  const shown = reduced ? { opacity: 1 } : { [axis]: 0 }

  const startDrag = (e: ReactPointerEvent<HTMLElement>) => {
    if (docked || e.button > 0) return
    const t = e.target as HTMLElement
    if (t.closest('button, a, input, select, textarea, [role="slider"]')) return
    // The bottom sheet's list scrolls; its handle and head drag. The side sheet drags from anywhere (vertical scroll stays native).
    if (bottom && t.closest('.side-scroll')) return
    controls.start(e)
  }

  const onDragEnd = (_: unknown, info: PanInfo) => {
    const el = ref.current
    const size = el ? (bottom ? el.offsetHeight : el.offsetWidth) : SIDE_W
    const d = bottom ? info.offset.y : info.offset.x
    const v = bottom ? info.velocity.y : info.velocity.x
    if (d > size * 0.35 || (v > 400 && d > 24)) onClose()
  }

  return (
    <motion.aside
      ref={ref}
      className={`side ${className} ${bottom ? 'is-bottom' : 'is-side'} ${present ? '' : 'is-leaving'}`}
      aria-label={label} role={docked ? undefined : 'dialog'} aria-modal={docked ? undefined : true}
      initial={hidden} animate={shown} exit={hidden}
      transition={reduced ? REDUCED : SPRING_SHEET}
      drag={docked ? false : axis}
      dragListener={false} dragControls={controls} dragMomentum={false}
      dragConstraints={bottom ? { top: 0, bottom: 0 } : { left: 0, right: 0 }}
      dragElastic={bottom ? { top: 0.04, bottom: 1 } : { left: 0.04, right: 1 }}
      dragTransition={{ bounceStiffness: 320, bounceDamping: 30 }}
      onDragEnd={onDragEnd}
      onPointerDown={startDrag}
    >
      {!docked && <span className="sheet-handle" aria-hidden="true" />}
      {children}
    </motion.aside>
  )
}

/** Dims the work under a sheet and swallows the tap that dismisses it. `clear` keeps the dim off (a small popover). */
export function Scrim({ onClose, clear = false, fixed = false }: { onClose: () => void; clear?: boolean; fixed?: boolean }) {
  return (
    <motion.div
      className={`sheet-scrim ${clear ? 'is-clear' : ''} ${fixed ? 'is-fixed' : ''}`} aria-hidden="true"
      initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0, transition: FADE_OUT }} transition={FADE_IN}
      onClick={onClose}
    />
  )
}

interface PopProps extends Omit<HTMLMotionProps<'div'>, 'style' | 'children'> {
  open: boolean
  /** A new id animates the open pop out and the next one in (a different pin, another trouble spot). */
  id?: string
  /** Where the pop grows from, as a CSS transform-origin: the tapped element's side. */
  origin?: string
  style?: CSSProperties
  children?: ReactNode
}

/** A popover or card that scales in from its source point (180 ms) and leaves faster (120 ms). */
export function Pop({ open, id, origin = 'top left', style, children, transition, ...rest }: PopProps) {
  const reduced = useReducedMotion()
  return (
    <AnimatePresence>
      {open && (
        <motion.div
          key={id ?? 'pop'}
          style={{ ...style, transformOrigin: origin }}
          initial={reduced ? { opacity: 0 } : { opacity: 0, scale: 0.96 }}
          animate={{ opacity: 1, scale: 1 }}
          exit={reduced ? { opacity: 0, transition: FADE_OUT } : { opacity: 0, scale: 0.98, transition: FADE_OUT }}
          transition={transition ?? { duration: 0.18, ease: EASE_OUT }}
          {...rest}
        >
          {children}
        </motion.div>
      )}
    </AnimatePresence>
  )
}

interface FadeProps extends Omit<HTMLMotionProps<'div'>, 'children'> {
  show: boolean
  children?: ReactNode
}

/** Mounts its content with a 200 ms fade and unmounts it with a 120 ms one, in place of a cut (a skeleton, a status line). */
export function Fade({ show, children, ...rest }: FadeProps) {
  return (
    <AnimatePresence initial={false}>
      {show && (
        <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0, transition: FADE_OUT }} transition={FADE_IN} {...rest}>
          {children}
        </motion.div>
      )}
    </AnimatePresence>
  )
}
