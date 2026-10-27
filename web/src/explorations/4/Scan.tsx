import { useMemo, useRef, useState, type KeyboardEvent, type PointerEvent } from 'react'
import { Link } from 'react-router'
import { ensembles, scanDraft, scoresById, type ScanPage } from '../shared'
import { IconCamera, IconCheck, IconTrash, IconUndo, IconWarn } from './icons'

interface PageItem extends ScanPage {
  retaken?: boolean
}

interface DragState {
  id: string
  dx: number
  dy: number
  to: number
}

export function Scan() {
  const score = scoresById['s-faure']
  const ens = ensembles.find(e => e.id === score?.ensembleId)
  const [pages, setPages] = useState<PageItem[]>(() => scanDraft.pages.map(p => ({ ...p })))
  const [removed, setRemoved] = useState<{ page: PageItem; at: number } | null>(null)
  const [committed, setCommitted] = useState(false)
  const [drag, setDrag] = useState<DragState | null>(null)
  const [said, setSaid] = useState('')
  const tiles = useRef(new Map<string, HTMLElement>())
  const start = useRef<{ id: string; x: number; y: number; rects: DOMRect[]; moved: boolean } | null>(null)

  const warnings = pages.filter(p => p.warning)
  const fromIndex = drag ? pages.findIndex(p => p.id === drag.id) : -1
  const dropAt = drag && drag.to !== fromIndex && drag.to !== fromIndex + 1 ? drag.to : -1

  const move = (from: number, to: number) => {
    if (from === to || to < 0 || to >= pages.length) return
    setPages(ps => {
      const next = ps.slice()
      const [it] = next.splice(from, 1)
      next.splice(to, 0, it)
      return next
    })
    setSaid(`${label(pages[from])} moved to position ${to + 1}.`)
  }

  const onDown = (e: PointerEvent<HTMLDivElement>, id: string) => {
    if (committed || e.button !== 0) return
    const rects = pages.map(p => tiles.current.get(p.id)?.getBoundingClientRect() ?? new DOMRect())
    start.current = { id, x: e.clientX, y: e.clientY, rects, moved: false }
    e.currentTarget.setPointerCapture(e.pointerId)
  }

  const onMove = (e: PointerEvent<HTMLDivElement>) => {
    const s = start.current
    if (!s) return
    const dx = e.clientX - s.x
    const dy = e.clientY - s.y
    if (!s.moved && Math.hypot(dx, dy) < 6) return
    s.moved = true
    let to = s.rects.length
    for (let i = 0; i < s.rects.length; i++) {
      const r = s.rects[i]
      if (e.clientY < r.top - 16) {
        to = i
        break
      }
      const sameRow = e.clientY <= r.bottom + 16
      if (sameRow && e.clientX < r.left + r.width / 2) {
        to = i
        break
      }
    }
    setDrag({ id: s.id, dx, dy, to })
  }

  const onUp = () => {
    const s = start.current
    start.current = null
    if (s?.moved && drag) {
      const from = pages.findIndex(p => p.id === drag.id)
      let to = drag.to
      if (to > from) to -= 1
      move(from, to)
    }
    setDrag(null)
  }

  const onCancel = () => {
    start.current = null
    setDrag(null)
  }

  const onKey = (e: KeyboardEvent<HTMLDivElement>, i: number) => {
    if (committed) return
    if (e.altKey && (e.key === 'ArrowLeft' || e.key === 'ArrowUp')) {
      e.preventDefault()
      move(i, i - 1)
      requestAnimationFrame(() => tiles.current.get(pages[i].id)?.focus())
    } else if (e.altKey && (e.key === 'ArrowRight' || e.key === 'ArrowDown')) {
      e.preventDefault()
      move(i, i + 1)
      requestAnimationFrame(() => tiles.current.get(pages[i].id)?.focus())
    } else if (e.key === 'Delete' || e.key === 'Backspace') {
      e.preventDefault()
      remove(i)
    }
  }

  const remove = (i: number) => {
    const page = pages[i]
    if (!page) return
    setPages(ps => ps.filter(p => p.id !== page.id))
    setRemoved({ page, at: i })
    setSaid(`${label(page)} removed. Undo is available.`)
  }

  const undo = () => {
    if (!removed) return
    setPages(ps => {
      const next = ps.slice()
      next.splice(Math.min(removed.at, next.length), 0, removed.page)
      return next
    })
    setSaid(`${label(removed.page)} restored.`)
    setRemoved(null)
  }

  const retake = (id: string) => {
    setPages(ps => ps.map(p => (p.id === id ? { ...p, retaken: true, warning: undefined } : p)))
    const p = pages.find(x => x.id === id)
    if (p) setSaid(`${label(p)} retaken.`)
  }

  const commit = () => {
    setCommitted(true)
    setRemoved(null)
    setSaid(`Order committed. Processing ${pages.length} pages.`)
  }

  return (
    <main className="x4-main">
      <div className="x4-scan">
        <header className="x4-scan-head">
          <div className="x4-scan-title">
            <h1 className="x4-h1">{scanDraft.title}</h1>
            <p className="x4-lede">
              {score ? `${score.composer} · ${score.work}` : 'Scan draft'}
              {ens ? ` · ${ens.name}` : ''}
            </p>
          </div>
          <div className="x4-scan-commit">
            <p className="x4-scan-state" data-committed={committed || undefined}>
              {committed ? (
                <>
                  <IconCheck size={18} /> Order committed · processing started
                </>
              ) : (
                <>
                  {pages.length} {pages.length === 1 ? 'page' : 'pages'} · order not committed
                </>
              )}
            </p>
            {committed ? (
              <Link className="x4-btn" to="/4">
                Back to library
              </Link>
            ) : (
              <button type="button" className="x4-btn" data-variant="solid" onClick={commit} disabled={!pages.length}>
                Commit order and process
              </button>
            )}
          </div>
        </header>

        {!committed && warnings.length > 0 ? (
          <div className="x4-notice" role="note">
            <IconWarn />
            <div>
              <p className="x4-notice-title">
                {warnings.length === 1 ? 'One page needs a look' : `${warnings.length} pages need a look`} before you
                commit
              </p>
              <ul className="x4-notice-list">
                {warnings.map(w => (
                  <li key={w.id}>
                    Position {pages.indexOf(w) + 1}, {label(w).toLowerCase()}: {w.warning}.{' '}
                    <button type="button" className="x4-link" onClick={() => retake(w.id)}>
                      Retake
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        ) : null}

        {removed && !committed ? (
          <div className="x4-notice" data-quiet="" role="status">
            <IconTrash />
            <p className="x4-notice-title">{label(removed.page)} removed from the draft.</p>
            <button type="button" className="x4-btn" data-variant="quiet" onClick={undo}>
              <IconUndo /> Undo
            </button>
          </div>
        ) : null}

        {committed ? (
          <div className="x4-notice" data-quiet="" role="status">
            <IconCheck />
            <p className="x4-notice-title">
              Reading has started on these {pages.length} pages in this order. Progress and any failure will show in
              the library.
            </p>
          </div>
        ) : (
          <p className="x4-help">
            The pages are bound in the order shown, two to a spread. Drag a page to move it. With a page focused,
            Option and an arrow key move it; Delete removes it. Nothing is read until you commit the order.
          </p>
        )}

        <ol className="x4-pages" data-committed={committed || undefined} aria-label="Pages in order">
          {pages.map((p, i) => {
            const dragging = drag?.id === p.id
            return (
              <li
                key={p.id}
                className="x4-ptile"
                data-drop={dropAt === i ? 'before' : dropAt === pages.length && i === pages.length - 1 ? 'after' : undefined}
                data-warn={p.warning ? '' : undefined}
              >
                <div
                  ref={el => {
                    if (el) tiles.current.set(p.id, el)
                    else tiles.current.delete(p.id)
                  }}
                  className="x4-thumb"
                  data-dragging={dragging || undefined}
                  style={drag && dragging ? { transform: `translate(${drag.dx}px, ${drag.dy}px)` } : undefined}
                  tabIndex={0}
                  role="button"
                  aria-roledescription="Draggable page"
                  aria-label={`Position ${i + 1}: ${label(p)}${p.warning ? `. Warning: ${p.warning}` : ''}`}
                  onPointerDown={e => onDown(e, p.id)}
                  onPointerMove={onMove}
                  onPointerUp={onUp}
                  onPointerCancel={onCancel}
                  onKeyDown={e => onKey(e, i)}
                >
                  <PageArt page={p} />
                </div>
                <div className="x4-pmeta">
                  <span className="x4-pnum">{i + 1}</span>
                  <span className="x4-psrc">{p.retaken ? 'Retaken' : label(p)}</span>
                </div>
                {p.warning ? (
                  <p className="x4-pwarn">
                    <IconWarn size={16} />
                    {p.warning}
                  </p>
                ) : (
                  <p className="x4-pwarn" data-ok="">
                    {p.retaken ? 'New photo' : 'Clear'}
                  </p>
                )}
                <div className="x4-pacts">
                  <button
                    type="button"
                    className="x4-iconbtn"
                    onClick={() => retake(p.id)}
                    disabled={committed || p.source === 'pdf'}
                    aria-label={`Retake ${label(p)}`}
                    title={p.source === 'pdf' ? 'Imported from PDF' : 'Retake with the camera'}
                  >
                    <IconCamera />
                  </button>
                  <button
                    type="button"
                    className="x4-iconbtn"
                    onClick={() => remove(i)}
                    disabled={committed}
                    aria-label={`Delete ${label(p)}`}
                    title="Delete page"
                  >
                    <IconTrash />
                  </button>
                </div>
              </li>
            )
          })}
        </ol>
        <p className="sr-only" aria-live="polite">
          {said}
        </p>
      </div>
    </main>
  )
}

const label = (p: PageItem) => (p.source === 'pdf' ? `PDF page ${p.index + 1}` : `Photo ${p.index + 1}`)

// ------------------------------------------------------------------ page drawings

function rng(seed: number) {
  let a = seed * 2654435761
  return () => {
    a |= 0
    a = (a + 0x6d2b79f5) | 0
    let t = Math.imul(a ^ (a >>> 15), 1 | a)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

/** A schematic of the captured page: staves, bar lines, note heads. Photos sit askew on the desk. */
function PageArt({ page }: { page: PageItem }) {
  const blurred = !!page.warning?.toLowerCase().includes('blur')
  const cropped = !!page.warning?.toLowerCase().includes('edge')
  const photo = page.source === 'camera' && !page.retaken
  const first = page.index === 0
  const art = useMemo(() => {
    const r = rng(page.index + 7)
    const systems: { y: number; bars: number[]; notes: { x: number; y: number }[] }[] = []
    let y = first ? 74 : 30
    const count = first ? 4 : 5
    for (let s = 0; s < count; s++) {
      const nb = 3 + Math.floor(r() * 2)
      const bars: number[] = []
      for (let b = 1; b < nb; b++) bars.push(22 + ((188 - 22) * b) / nb + (r() - 0.5) * 8)
      const notes: { x: number; y: number }[] = []
      for (let n = 0; n < 22; n++) {
        const staff = Math.floor(r() * 3)
        notes.push({ x: 30 + r() * 154, y: y + staff * 15 + Math.round(r() * 8) * 1 })
      }
      systems.push({ y, bars, notes })
      y += 52
    }
    return systems
  }, [page.index, first])
  const tilt = photo ? ((page.index % 3) - 1) * 1.1 : 0
  const fid = `x4blur-${page.id}`
  return (
    <svg viewBox="0 0 210 297" className="x4-art" aria-hidden="true" focusable="false">
      <defs>
        <filter id={fid} x="-5%" y="-5%" width="110%" height="110%">
          <feGaussianBlur stdDeviation="1.6" />
        </filter>
      </defs>
      {photo || cropped ? <rect className="x4-art-desk" x="0" y="0" width="210" height="297" /> : null}
      <g
        transform={
          cropped
            ? 'translate(34 6) scale(0.96)'
            : photo
              ? `rotate(${tilt} 105 148) translate(8 10) scale(0.925)`
              : undefined
        }
      >
        <rect className="x4-art-paper" x="0" y="0" width="210" height="297" />
        <g filter={blurred ? `url(#${fid})` : undefined}>
          {first ? (
            <g className="x4-art-fill">
              <rect x="62" y="26" width="86" height="7" rx="1" />
              <rect x="80" y="40" width="50" height="4" rx="1" />
              <rect x="150" y="54" width="36" height="3" rx="1" />
            </g>
          ) : null}
          {art.map((s, i) => (
            <g key={i}>
              {[0, 1, 2].map(st => (
                <g key={st} className="x4-art-line">
                  {[0, 2, 4, 6, 8].map(l => (
                    <line key={l} x1="22" x2="188" y1={s.y + st * 15 + l} y2={s.y + st * 15 + l} />
                  ))}
                </g>
              ))}
              <line className="x4-art-line" x1="22" x2="22" y1={s.y} y2={s.y + 38} />
              {s.bars.map((bx, k) => (
                <line key={k} className="x4-art-line" x1={bx} x2={bx} y1={s.y} y2={s.y + 38} />
              ))}
              <line className="x4-art-line" x1="188" x2="188" y1={s.y} y2={s.y + 38} />
              <g className="x4-art-fill">
                {s.notes.map((n, k) => (
                  <ellipse key={k} cx={n.x} cy={n.y} rx="2.1" ry="1.5" transform={`rotate(-20 ${n.x} ${n.y})`} />
                ))}
              </g>
            </g>
          ))}
        </g>
      </g>
    </svg>
  )
}
