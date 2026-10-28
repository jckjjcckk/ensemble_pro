import { useCallback, useEffect, useLayoutEffect, useRef, useState, type FormEvent } from 'react'
import { Pop } from './Sheet'
import { KindIcon } from './marks'
import { IRepeat } from './icons'
import { kindLabel } from './store'
import type { Geo } from './geometry'
import type { BarMark } from './ink'
import { IHighlight, INote, IScribble } from './MarkIcons'
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

const GAP = 12

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
  /** Practice only: loop from this bar. */
  onLoop?: () => void
  onRemove: (id: string) => void
  onClose: () => void
}) {
  const ref = useRef<HTMLDivElement>(null)
  const [host, setHost] = useState<HTMLElement | null>(null)
  const [size, setSize] = useState({ w: 340, h: 92 })
  const [text, setText] = useState('')
  const box = state ? geo.bars.get(state.bar) : undefined
  const note = !!state?.note
  const kb = useKeyboardOverlap(host, note)

  useEffect(() => { setText('') }, [state?.bar])

  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    setHost(h => h ?? el.closest<HTMLElement>('.stage'))
    const w = el.offsetWidth, h = el.offsetHeight
    setSize(s => (s.w === w && s.h === h ? s : { w, h }))
  }, [state?.bar, note, marks.length])

  if (!state || !box) return <Pop open={false} />

  // Below the bar when it fits above the keyboard and the page foot; otherwise above it.
  const stageW = host?.clientWidth ?? 1024
  const stageH = (host?.clientHeight ?? 768) - kb
  const below = box.y + box.h + GAP + size.h <= stageH - 34 || box.y - GAP - size.h < 8
  const top = below ? box.y + box.h + GAP : box.y - GAP - size.h
  const left = Math.max(8, Math.min(box.x + box.w / 2 - size.w / 2, stageW - size.w - 8))
  const originX = Math.max(16, Math.min(size.w - 16, box.x + box.w / 2 - left))

  const submit = (e: FormEvent) => {
    e.preventDefault()
    const t = text.trim()
    if (!t) return
    onSaveNote(t)
    setText('')
  }

  return (
    <Pop
      open id={String(state.bar)} className="qm" role="dialog" aria-label={`Bar ${state.bar}`}
      style={{ left, top: Math.max(8, top) }} origin={`${originX}px ${below ? '0px' : '100%'}`}
      // Keys typed in the note never reach the stage (arrows turn pages there).
      onKeyDown={e => { e.stopPropagation(); if (e.key === 'Escape') onClose() }}
    >
      <div ref={ref} className="qm-in">
        {marks.length > 0 && (
          <ul className="qm-marks" aria-label={`Marks on bar ${state.bar}`}>
            {marks.map(m => (
              <li key={m.id} className="qm-mark">
                <span className={`qm-kind is-${m.kind}`}>{m.kind === 'highlight' ? <IHighlight size={18} on /> : <KindIcon kind={m.kind} size={16} />}</span>
                <span className="qm-mark-body">
                  <span className="qm-mark-text">{m.kind === 'highlight' ? 'Highlight' : m.text || m.transcript || kindLabel[m.kind]}</span>
                  <span className="qm-mark-by">{m.mine ? 'You' : nameOf(m)}{m.kind === 'text' && m.partId === null && m.mine ? ' · only you see it' : ''}</span>
                </span>
                {m.removable && (
                  <button type="button" className="btn btn-line is-small qm-remove" onClick={() => onRemove(m.id)}>Remove</button>
                )}
              </li>
            ))}
          </ul>
        )}
        <div className="qm-acts" role="group" aria-label={`Mark bar ${state.bar}`}>
          <span className="qm-bar"><span className="qm-bar-k">bar</span><span className="num">{state.bar}</span></span>
          <button type="button" className="qm-act" aria-pressed={highlighted} onClick={onHighlight}>
            <IHighlight size={22} on={highlighted} /><span>Highlight</span>
          </button>
          <button type="button" className="qm-act" aria-expanded={note} onClick={onNote}>
            <INote size={22} /><span>Note</span>
          </button>
          <button type="button" className="qm-act" onClick={onScribble}>
            <IScribble size={22} /><span>Scribble</span>
          </button>
          {onLoop && (
            <button type="button" className="qm-act" onClick={onLoop}>
              <IRepeat size={22} /><span>Loop from here</span>
            </button>
          )}
        </div>
        {note && (
          <form className="qm-note" onSubmit={submit}>
            <input
              className="qm-input" value={text} onChange={e => setText(e.target.value)} autoFocus maxLength={140}
              enterKeyHint="done" placeholder={`Note on bar ${state.bar}`} aria-label={`Note on bar ${state.bar}`}
            />
            <button type="submit" className="btn btn-solid is-small" disabled={!text.trim()}>Save</button>
          </form>
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
