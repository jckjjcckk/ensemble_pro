import { useCallback, useEffect, useLayoutEffect, useRef, useState, type FormEvent } from 'react'
import { Pop } from './Sheet'
import { KindIcon } from './marks'
import { kindLabel } from './store'
import type { Geo } from './geometry'
import type { BarMark } from './ink'
import { IHighlight } from './MarkIcons'
import './Ink.css'

// ---------------------------------------------------------------- the menu's state and its dismissal

export interface BarMenuState { bar: number; note: boolean }

/**
 * One quick menu at a time, anchored on a bar. A press anywhere outside it closes it, and that same tap does
 * nothing else on the stage (it does not open a menu on the bar under it): the dismissing tap is spent.
 */
export function useBarMenu() {
  const [menu, setMenu] = useState<BarMenuState | null>(null)
  const dismissedAt = useRef(0)
  const open = !!menu
  useEffect(() => {
    if (!open) return
    const onDown = (e: PointerEvent) => {
      if ((e.target as Element | null)?.closest?.('.qm')) return
      dismissedAt.current = performance.now()
      setMenu(null)
    }
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setMenu(null) }
    window.addEventListener('pointerdown', onDown, true)
    window.addEventListener('keydown', onKey)
    return () => { window.removeEventListener('pointerdown', onDown, true); window.removeEventListener('keydown', onKey) }
  }, [open])
  /** A tap on a bar: opens the menu there, unless this tap was the one that closed the last menu. */
  const tap = useCallback((bar: number) => {
    if (performance.now() - dismissedAt.current < 600) return
    setMenu({ bar, note: false })
  }, [])
  const close = useCallback(() => setMenu(null), [])
  return { menu, setMenu, tap, close }
}

// ---------------------------------------------------------------- the on-screen keyboard's overlap with an element

function useKeyboardOverlap(el: HTMLElement | null, on: boolean) {
  const [overlap, setOverlap] = useState(0)
  useEffect(() => {
    const vv = window.visualViewport
    if (!on || !vv || !el) { setOverlap(0); return }
    const read = () => {
      const r = el.getBoundingClientRect()
      setOverlap(Math.max(0, Math.round(r.bottom - (vv.offsetTop + vv.height))))
    }
    read()
    vv.addEventListener('resize', read)
    vv.addEventListener('scroll', read)
    return () => { vv.removeEventListener('resize', read); vv.removeEventListener('scroll', read) }
  }, [el, on])
  return overlap
}

// ---------------------------------------------------------------- the menu

const GAP = 14
const ARROW = 22

/** R3's icons for the four acts (docs/design/r3, the vertical quick menu). */
const IHl = () => <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M4 20h16M6 16l9-9 3 3-9 9H6z" /></svg>
const INoteR3 = () => <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M5 5h14v10H9l-4 4z" /></svg>
const IScr = () => <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M4 17c3-6 6 2 9-4s4-5 7-9" /></svg>
const ILoop = () => <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M17 4l3 3-3 3M4 7h16M7 20l-3-3 3-3M20 17H4" /></svg>

/** The quick menu on a tapped bar (R3): a vertical card beside the bar, its arrow at the bar's middle, on the side with
 *  room. "Bar N", the marks already on the bar (each removable by its author), then Highlight, Note (opens a line to
 *  write in), Scribble and Loop from here. It pops from the arrow and leaves faster. */
export function MarkMenu({ geo, state, marks, highlighted, nameOf, onHighlight, onNote, onSaveNote, onScribble, onLoop, onRemove, onClose }: {
  geo: Geo
  state: BarMenuState | null
  /** Marks on this bar, in the order they were made. */
  marks: BarMark[]
  /** The reader's own highlight is on this bar. */
  highlighted: boolean
  nameOf: (m: BarMark) => string
  onHighlight: () => void
  onNote: () => void
  onSaveNote: (text: string) => void
  onScribble: () => void
  /** Loop from this bar (practice, or the stand's way into it). */
  onLoop?: () => void
  onRemove: (id: string) => void
  onClose: () => void
}) {
  const ref = useRef<HTMLDivElement>(null)
  const [host, setHost] = useState<HTMLElement | null>(null)
  const [size, setSize] = useState({ w: 200, h: 236 })
  const [text, setText] = useState('')
  const box = state ? geo.bars.get(state.bar) : undefined
  const note = !!state?.note
  const kb = useKeyboardOverlap(host, note)

  useEffect(() => { setText('') }, [state?.bar])

  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    setHost(h => h ?? el.closest<HTMLElement>('.stage-content') ?? el.closest<HTMLElement>('.stage'))
    const w = el.offsetWidth, h = el.offsetHeight
    setSize(s => (s.w === w && s.h === h ? s : { w, h }))
  }, [state?.bar, note, marks.length])

  if (!state || !box) return <Pop open={false} />

  // Beside the bar on the side with room (right first), the arrow level with the bar's middle.
  const hostW = host?.clientWidth ?? 1024
  const hostH = (host?.clientHeight ?? 768) - kb
  const right = box.x + box.w + GAP + size.w <= hostW - 8 || box.x - GAP - size.w < 8
  const left = right ? box.x + box.w + GAP : box.x - GAP - size.w
  const mid = box.y + box.h / 2
  const top = Math.max(8, Math.min(mid - ARROW - 6, hostH - size.h - 8))
  const arrowY = Math.max(12, Math.min(size.h - 24, mid - top - 6))

  const submit = (e: FormEvent) => {
    e.preventDefault()
    const t = text.trim()
    if (!t) return
    onSaveNote(t)
    setText('')
  }

  return (
    <Pop
      open id={String(state.bar)} className={`qm ${right ? 'is-right' : 'is-left'}`} role="menu" aria-label={`Bar ${state.bar}`}
      style={{ left: Math.max(8, left), top }} origin={`${right ? '0px' : '100%'} ${arrowY + 6}px`}
      transition={{ type: 'spring', stiffness: 520, damping: 34, mass: 0.7 }}
      // Keys typed in the note never reach the stage (arrows turn pages there).
      onKeyDown={e => { e.stopPropagation(); if (e.key === 'Escape') onClose() }}
    >
      <span className="qm-arrow" aria-hidden="true" style={{ top: arrowY }} />
      <div ref={ref} className="qm-in">
        <span className="qm-head">Bar {state.bar}</span>
        {marks.length > 0 && (
          <ul className="qm-marks" aria-label={`Marks on bar ${state.bar}`}>
            {marks.map(m => (
              <li key={m.id} className="qm-mark">
                <span className={`qm-kind is-${m.kind}`}>{m.kind === 'highlight' ? <IHighlight size={16} on /> : <KindIcon kind={m.kind} size={15} />}</span>
                <span className="qm-mark-body">
                  <span className="qm-mark-text">{m.kind === 'highlight' ? 'Highlight' : m.text || m.transcript || kindLabel[m.kind]}</span>
                  <span className="qm-mark-by">{m.mine ? 'You' : nameOf(m)}{m.kind === 'text' && m.partId === null && m.mine && m.audience === 'member' ? ' · only you' : ''}</span>
                </span>
                {m.removable && <button type="button" className="qm-remove" onClick={() => onRemove(m.id)} aria-label={`Remove ${m.kind === 'highlight' ? 'highlight' : 'note'}`}>Remove</button>}
              </li>
            ))}
          </ul>
        )}
        <button type="button" role="menuitemcheckbox" className="qm-act" aria-checked={highlighted} onClick={onHighlight}>
          <IHl /><span>{highlighted ? 'Highlighted' : 'Highlight'}</span>
        </button>
        <button type="button" role="menuitem" className="qm-act" aria-expanded={note} onClick={onNote}>
          <INoteR3 /><span>Note</span>
        </button>
        {note && (
          <form className="qm-note" onSubmit={submit}>
            <input
              className="qm-input" value={text} onChange={e => setText(e.target.value)} autoFocus maxLength={140}
              enterKeyHint="done" placeholder={`Note on bar ${state.bar}`} aria-label={`Note on bar ${state.bar}`}
            />
            <button type="submit" className="qm-save" disabled={!text.trim()}>Save</button>
          </form>
        )}
        <button type="button" role="menuitem" className="qm-act" onClick={onScribble}>
          <IScr /><span>Scribble</span>
        </button>
        {onLoop && (
          <button type="button" role="menuitem" className="qm-act" onClick={onLoop}>
            <ILoop /><span>Loop from here</span>
          </button>
        )}
      </div>
    </Pop>
  )
}

/** Highlights on the score: one wash per marked bar, under the notes like a highlighter on paper. */
export function HighlightLayer({ geo, bars, arriving }: { geo: Geo; bars: Iterable<number>; /** Bars whose highlight just arrived from another stand. */ arriving?: ReadonlySet<number> }) {
  return (
    <>
      {[...new Set(bars)].map(bar => {
        const b = geo.bars.get(bar)
        return b ? <div key={`hl${bar}`} className={`u-mark${arriving?.has(bar) ? ' is-arriving' : ''}`} style={{ left: b.x - 2, top: b.y - 8, width: b.w + 4, height: b.h + 16 }} /> : null
      })}
    </>
  )
}

/** The bar the menu is about, washed in ink so the reader sees which one they tapped. */
export function BarSelection({ geo, bar }: { geo: Geo; bar: number | null }) {
  const b = bar != null ? geo.bars.get(bar) : undefined
  return b ? <div className="u-sel" style={{ left: b.x - 4, top: b.y - 12, width: b.w + 8, height: b.h + 24 }} /> : null
}
