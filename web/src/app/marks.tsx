import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { fmtDuration, membersById, type Annotation } from '../mock'
import { barRange, firstName, fmtDateTime, kindLabel } from './store'
import { IClose, IMic, IPause, IPencil, IPlay, IScissors } from './icons'
import { spanRects, type Geo } from './geometry'

export function pinText(a: Annotation): string {
  const author = membersById[a.authorId]
  switch (a.kind) {
    case 'voice': return `${firstName(author?.name ?? '')} · ${fmtDuration(a.durationSec ?? 0)}`
    case 'dynamic': return (a.text ?? '').split(' — ')[0]
    case 'marking': return (a.text ?? 'Pencil').replace(/^Pencil:\s*/, '')
    case 'cut': return `Cut ${barRange(a.barFrom, a.barTo)}`
    case 'breath': return 'Breath'
    default: return (a.text ?? '').length > 30 ? `${(a.text ?? '').slice(0, 29)}…` : a.text ?? ''
  }
}

export function KindIcon({ kind, size = 16 }: { kind: Annotation['kind']; size?: number }) {
  if (kind === 'voice') return <IMic size={size} />
  if (kind === 'cut') return <IScissors size={size} />
  if (kind === 'dynamic') return <span className="glyph-dyn" aria-hidden="true">p</span>
  return <IPencil size={size} />
}

/** Simulated playback of a voice note: progress over its real duration. Audio files are not part of the mock. */
export function VoicePlayer({ a }: { a: Annotation }) {
  const [t, setT] = useState(0)
  const [on, setOn] = useState(false)
  const dur = a.durationSec ?? 0
  useEffect(() => {
    if (!on) return
    const id = window.setInterval(() => setT(v => {
      if (v + 0.1 >= dur) { setOn(false); return dur }
      return v + 0.1
    }), 100)
    return () => window.clearInterval(id)
  }, [on, dur])
  const toggle = () => { if (!on && t >= dur) setT(0); setOn(v => !v) }
  return (
    <div className="voice">
      <button type="button" className="btn-round" onClick={toggle} aria-label={on ? 'Pause voice note' : 'Play voice note'}>
        {on ? <IPause size={18} /> : <IPlay size={18} />}
      </button>
      <div className="voice-track" aria-hidden="true"><span style={{ width: `${dur ? (t / dur) * 100 : 0}%` }} /></div>
      <span className="voice-time">{fmtDuration(Math.floor(t))} / {fmtDuration(dur)}</span>
    </div>
  )
}

export function NoteBody({ a }: { a: Annotation }) {
  const author = membersById[a.authorId]
  return (
    <>
      <p className="note-meta">
        <span className="note-kind"><KindIcon kind={a.kind} size={15} />{kindLabel[a.kind]}</span>
        <span className="num">{a.kind === 'cut' ? 'bars ' : 'bar '}{barRange(a.barFrom, a.barTo)}</span>
      </p>
      {a.kind === 'voice'
        ? (a.transcript
          ? <blockquote className="note-quote">{a.transcript}</blockquote>
          : <p className="note-pending">Transcript arrives when the recording has been processed.</p>)
        : a.text && <p className="note-text">{a.text}</p>}
      {a.kind === 'voice' && <VoicePlayer a={a} />}
      <p className="note-by">{author?.name ?? 'Unknown'} · {a.partId ? 'one part' : 'everyone'} · {fmtDateTime(a.createdAt)}</p>
    </>
  )
}

/** Annotation pins in the score, grouped above the bar they belong to, with one open card at a time. */
export function PinLayer({ geo, items, selected, onSelect }: {
  geo: Geo
  items: Annotation[]
  selected: string | null
  onSelect: (id: string | null) => void
}) {
  const byBar = new Map<number, Annotation[]>()
  for (const a of items) {
    if (a.kind === 'cut' || !geo.bars.has(a.barFrom)) continue
    byBar.set(a.barFrom, [...(byBar.get(a.barFrom) ?? []), a])
  }
  const open = items.find(a => a.id === selected)
  const openBox = open ? geo.bars.get(open.barFrom) : undefined
  const right = Math.max(0, ...geo.pages.map(p => (p ? p.x + p.w : 0)))

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onSelect(null) }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onSelect])

  return (
    <>
      {[...byBar.entries()].map(([bar, list]) => {
        const b = geo.bars.get(bar)!
        return (
          <div key={bar} className="pins" style={{ left: b.x, top: b.y - 34 }}>
            {list.map(a => (
              <button
                key={a.id} type="button" className={`pin is-${a.kind}`} aria-expanded={selected === a.id}
                onClick={e => { e.stopPropagation(); onSelect(selected === a.id ? null : a.id) }}
              >
                <KindIcon kind={a.kind} size={14} />
                <span>{pinText(a)}</span>
              </button>
            ))}
          </div>
        )
      })}
      {open && openBox && (
        <div
          className="pop" role="dialog" aria-label={`${kindLabel[open.kind]}, bar ${open.barFrom}`}
          style={{ left: Math.max(8, Math.min(openBox.x, right - 328)), top: openBox.y + openBox.h + 18 }}
          onClick={e => e.stopPropagation()}
        >
          <button type="button" className="pop-close" onClick={() => onSelect(null)} aria-label="Close"><IClose size={18} /></button>
          <NoteBody a={open} />
        </div>
      )}
    </>
  )
}

/** The cut, drawn on the score as hatching over the skipped bars. */
export function CutLayer({ geo, cuts }: { geo: Geo; cuts: { from: number; to: number; label?: string }[] }) {
  return (
    <>
      {cuts.map(c => spanRects(geo, c.from, c.to).map((r, i) => (
        <div key={`${c.from}-${r.first}`} className="u-cut" style={{ left: r.x, top: r.y - 10, width: r.w, height: r.h + 20 }}>
          {i === 0 && <span className="u-cut-label">{c.label ?? `Cut ${barRange(c.from, c.to)}`}</span>}
        </div>
      )))}
    </>
  )
}

/** Words go to the margin, pencil stays on the staff: which annotations the margin carries. */
export const inMargin = (a: Annotation) => a.kind === 'voice' || a.kind === 'text'

interface Placed { a: Annotation; side: 'left' | 'right'; y: number; top: number }

/**
 * Margin notes: each note level with the system that holds its bar, in the outer margin of its page
 * (left page's notes on the left, right page's on the right). Collisions step down and a tick stays
 * at the bar's true height, so a reader finds a note by looking across, never by scanning a list.
 */
export function MarginLayer({ geo, items, width, selected, onSelect }: {
  geo: Geo
  items: Annotation[]
  /** Horizontal room beside the pages, from the stage edge to the page edge. */
  width: number
  selected: string | null
  onSelect: (id: string | null) => void
}) {
  const ref = useRef<HTMLDivElement>(null)
  const [heights, setHeights] = useState<Record<string, number>>({})
  const shown = geo.pages.map((p, i) => (p ? i : -1)).filter(i => i >= 0)
  const leftPage = shown.length === 2 ? shown[0] : -1
  const noteW = Math.max(110, width - 62) // leaves the page-turn target at the stage edge clear

  const placed = useMemo<Placed[]>(() => {
    const raw: Placed[] = []
    for (const a of items) {
      const b = geo.bars.get(a.barFrom)
      if (!b) continue
      raw.push({ a, side: b.page === leftPage ? 'left' : 'right', y: b.y, top: b.y })
    }
    for (const side of ['left', 'right'] as const) {
      const col = raw.filter(p => p.side === side).sort((p, q) => p.y - q.y)
      let floor = 0
      for (const p of col) {
        p.top = Math.max(p.y, floor)
        floor = p.top + (heights[p.a.id] ?? 72) + 10
      }
    }
    return raw
  }, [items, geo, leftPage, heights])

  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    const next: Record<string, number> = {}
    el.querySelectorAll<HTMLElement>('[data-mnote]').forEach(n => { next[n.dataset.mnote!] = n.offsetHeight })
    setHeights(h => (Object.keys(next).some(k => h[k] !== next[k]) ? next : h))
  }, [placed, items])

  const pageOf = (p: Placed) => geo.pages[geo.bars.get(p.a.barFrom)!.page]!

  return (
    <div className="margin-layer" ref={ref}>
      {placed.map(p => {
        const pg = pageOf(p)
        const left = p.side === 'left' ? pg.x - width + 8 : pg.x + pg.w + 18
        const author = membersById[p.a.authorId]
        const sel = selected === p.a.id
        return (
          <div key={p.a.id} className={`m-note is-${p.side} ${sel ? 'is-sel' : ''}`} style={{ left, top: p.top, width: noteW }} data-mnote={p.a.id}>
            <span className="m-tick" aria-hidden="true" style={{ top: p.y - p.top + 6 }} />
            <button type="button" className="m-body" aria-pressed={sel} onClick={e => { e.stopPropagation(); onSelect(sel ? null : p.a.id) }}>
              <span className="m-meta"><KindIcon kind={p.a.kind} size={13} />{firstName(author?.name ?? '')} · <span className="num">bar {barRange(p.a.barFrom, p.a.barTo)}</span></span>
              {p.a.kind === 'voice'
                ? (p.a.transcript ? <span className="m-text m-quote">{p.a.transcript}</span> : <span className="m-text m-pending">Transcript arrives after processing.</span>)
                : <span className="m-text">{p.a.text}</span>}
            </button>
            {sel && p.a.kind === 'voice' && <VoicePlayer a={p.a} />}
          </div>
        )
      })}
    </div>
  )
}
