import { useEffect, useRef, useState, type KeyboardEvent, type PointerEvent } from 'react'
import { Link } from 'react-router'
import { ensembles, scanDraft, scoresById, type ScanPage } from '../mock'
import { Screen, useViewport } from './layout'
import { useStore } from './store'
import { ICamera, ICheck, ILock, ITrash, IUndo, IWarning } from './icons'

const score = scoresById['s-faure']
const ensemble = ensembles.find(e => e.id === score.ensembleId)

const sourceLabel = (p: ScanPage) => (p.source === 'camera' ? `Photo ${p.index + 1}` : `PDF page ${p.index - 5}`)

/** A schematic of the captured page: systems of SATB and keyboard staves. Not the photo itself; the mock has none. */
function PageArt({ page }: { page: ScanPage }) {
  const systems = page.index === 0 ? 3 : 4
  const top = page.index === 0 ? 30 : 12
  const sysH = (130 - top) / systems
  const skew = page.source === 'camera' ? ((page.index % 3) - 1) * 0.6 : 0
  return (
    <svg viewBox="0 0 100 141" className={`art ${page.warning?.startsWith('Blurred') ? 'is-blurred' : ''} ${page.warning?.includes('edge') ? 'is-cropped' : ''}`} aria-hidden="true">
      <g transform={`rotate(${skew} 50 70)`}>
        <rect x="2" y="2" width="96" height="137" className="art-paper" />
        {page.index === 0 && <>
          <rect x="26" y="9" width="48" height="4" rx="1" className="art-title" />
          <rect x="62" y="17" width="26" height="2.2" rx="1" className="art-ink" />
        </>}
        {Array.from({ length: systems }, (_, s) => {
          const y0 = top + s * sysH
          const staves = [0, 1, 2, 3, 4.6, 5.6]
          return (
            <g key={s}>
              {staves.map((st, k) => (
                <g key={k}>
                  {[0, 1, 2, 3, 4].map(l => <line key={l} x1="9" x2="92" y1={y0 + st * (sysH / 7.2) + l * 0.9} y2={y0 + st * (sysH / 7.2) + l * 0.9} className="art-line" />)}
                </g>
              ))}
              <line x1="9" x2="9" y1={y0} y2={y0 + 5.6 * (sysH / 7.2) + 3.6} className="art-line" />
              {[30, 51, 72].map(x => <line key={x} x1={x} x2={x} y1={y0} y2={y0 + 3 * (sysH / 7.2) + 3.6} className="art-line" />)}
            </g>
          )
        })}
      </g>
    </svg>
  )
}

interface Drag { id: string; x: number; y: number; ox: number; oy: number; w: number; target: number }

export default function Scan() {
  const vp = useViewport()
  const { scan, setScan } = useStore()
  const { pages, retaking, committed } = scan
  const [drag, setDrag] = useState<Drag | null>(null)
  const [removed, setRemoved] = useState<{ page: ScanPage; at: number } | null>(null)
  const slots = useRef<DOMRect[]>([])
  const gridRef = useRef<HTMLOListElement>(null)
  const refocus = useRef<string | null>(null)

  const cols = vp.wide && vp.w / vp.h > 1.3 ? 8 : vp.w >= 780 ? 4 : 3
  const warned = pages.filter(p => p.warning)

  useEffect(() => {
    if (!refocus.current) return
    gridRef.current?.querySelector<HTMLElement>(`[data-id="${refocus.current}"]`)?.focus()
    refocus.current = null
  })

  const moveTo = (id: string, to: number) => setScan(s => {
    const list = s.pages.filter(p => p.id !== id)
    const page = s.pages.find(p => p.id === id)!
    list.splice(Math.max(0, Math.min(list.length, to)), 0, page)
    return { ...s, pages: list }
  })

  const remove = (id: string) => {
    const at = pages.findIndex(p => p.id === id)
    setRemoved({ page: pages[at], at })
    setScan(s => ({ ...s, pages: s.pages.filter(p => p.id !== id), retaking: s.retaking.filter(r => r !== id) }))
  }
  const undo = () => {
    if (!removed) return
    setScan(s => {
      const list = [...s.pages]
      list.splice(removed.at, 0, removed.page)
      return { ...s, pages: list }
    })
    setRemoved(null)
  }
  const toggleRetake = (id: string) => setScan(s => ({ ...s, retaking: s.retaking.includes(id) ? s.retaking.filter(r => r !== id) : [...s.retaking, id] }))

  const nearestSlot = (x: number, y: number) => {
    let best = 0
    let dist = Infinity
    slots.current.forEach((r, i) => {
      const d = Math.hypot(r.left + r.width / 2 - x, r.top + r.height / 2 - y)
      if (d < dist) { dist = d; best = i }
    })
    return best
  }

  const pagesRef = useRef(pages)
  useEffect(() => { pagesRef.current = pages })
  const dragRef = useRef<Drag | null>(null)

  // Pointer drag (mouse, touch, pencil). Listeners live on window because the dragged tile leaves the grid.
  const onPointerDown = (e: PointerEvent<HTMLLIElement>, id: string) => {
    if (committed || e.button > 0 || (e.target as HTMLElement).closest('button')) return
    const sx = e.clientX
    const sy = e.clientY
    const move = (ev: globalThis.PointerEvent) => {
      let d = dragRef.current
      if (!d) {
        if (Math.hypot(ev.clientX - sx, ev.clientY - sy) < 6) return
        const items = Array.from(gridRef.current?.children ?? []) as HTMLElement[]
        slots.current = items.map(el => el.getBoundingClientRect())
        const idx = pagesRef.current.findIndex(pg => pg.id === id)
        const r = slots.current[idx]
        if (!r) return
        d = { id, x: ev.clientX, y: ev.clientY, ox: sx - r.left, oy: sy - r.top, w: r.width, target: idx }
      } else {
        d = { ...d, x: ev.clientX, y: ev.clientY, target: nearestSlot(ev.clientX, ev.clientY) }
      }
      dragRef.current = d
      setDrag(d)
    }
    const end = (commit: boolean) => () => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', up)
      window.removeEventListener('pointercancel', cancel)
      const d = dragRef.current
      if (d && commit) moveTo(d.id, d.target)
      dragRef.current = null
      setDrag(null)
    }
    const up = end(true)
    const cancel = end(false)
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', up)
    window.addEventListener('pointercancel', cancel)
  }

  const onKeyDown = (e: KeyboardEvent<HTMLLIElement>, id: string, i: number) => {
    if (committed) return
    if (e.altKey && (e.key === 'ArrowLeft' || e.key === 'ArrowUp')) { e.preventDefault(); refocus.current = id; moveTo(id, i - 1) }
    if (e.altKey && (e.key === 'ArrowRight' || e.key === 'ArrowDown')) { e.preventDefault(); refocus.current = id; moveTo(id, i + 1) }
    if (e.key === 'Delete' || e.key === 'Backspace') { e.preventDefault(); remove(id) }
  }

  // While dragging, the grid shows the order the drop would produce, with a bracket where the page will land.
  const dragged = drag ? pages.find(p => p.id === drag.id) : undefined
  const preview: (ScanPage | 'slot')[] = drag ? (() => {
    const rest: (ScanPage | 'slot')[] = pages.filter(p => p.id !== drag.id)
    rest.splice(drag.target, 0, 'slot')
    return rest
  })() : pages

  const header = (
    <div className="ph">
      <div className="ph-title">
        <h1>{scanDraft.title}</h1>
        <p>{score.composer.split(' ').slice(-1)[0]} · {score.work} · {ensemble?.name}</p>
      </div>
    </div>
  )

  const dock = committed ? (
    <div className="scan-dock">
      <p className="dock-msg"><ICheck size={20} /><span>Sent in this order. Reading has started.</span></p>
      <div className="grow" />
      <Link to="/" className="dbtn is-primary">Back to the library</Link>
    </div>
  ) : (
    <div className="scan-dock">
      {removed ? (
        <p className="dock-msg" role="status">
          <span>{sourceLabel(removed.page)} removed.</span>
          <button type="button" className="dbtn" onClick={undo}><IUndo size={18} /><span>Undo</span></button>
        </p>
      ) : (
        <p className="dock-msg">
          <span className="num-ui">{pages.length} pages</span>
          {warned.length > 0 && <span className="dock-warn"><IWarning size={18} />{warned.length} with warnings</span>}
        </p>
      )}
      <div className="grow" />
      <button type="button" className="dbtn is-primary is-big" disabled={pages.length === 0} onClick={() => { setRemoved(null); setScan(s => ({ ...s, committed: true, retaking: [] })) }}>
        Read {pages.length} pages in this order
      </button>
    </div>
  )

  return (
    <Screen header={header} dock={dock} className="is-scan">
      <div className="scan">
        <div className="scan-inner">
          <div className="scan-lead">
            {committed ? (
              <p className="scan-instr"><ILock size={18} />Order confirmed. The parts appear in the library when reading finishes.</p>
            ) : (
              <p className="scan-instr">Drag pages into reading order, or focus a page and press Option with an arrow key. Nothing is read until you confirm the order.</p>
            )}
            {!committed && warned.length > 0 && (
              <ul className="warnings" aria-label="Warnings">
                {warned.map(p => {
                  const pos = pages.indexOf(p) + 1
                  return (
                    <li key={p.id}>
                      <IWarning size={18} />
                      <span><b>Position {pos}</b>, {sourceLabel(p).toLowerCase()}: {p.warning}</span>
                      <button type="button" className="btn btn-line is-small" onClick={() => toggleRetake(p.id)} aria-pressed={retaking.includes(p.id)}>
                        <ICamera size={16} />{retaking.includes(p.id) ? 'Cancel retake' : 'Retake'}
                      </button>
                    </li>
                  )
                })}
              </ul>
            )}
          </div>

          {pages.length === 0 ? (
            <div className="empty is-inline">
              <p>Every page has been removed. Undo, or go back to the library and scan again.</p>
            </div>
          ) : (
            <ol className={`pages ${committed ? 'is-locked' : ''}`} ref={gridRef} style={{ gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))` }} aria-label="Pages in reading order">
              {preview.map((p, i) => p === 'slot' ? (
                <li key="slot" className="page-slot" aria-hidden="true"><span className="slot-bracket" /></li>
              ) : (
                <li
                  key={p.id} data-id={p.id} className={`page ${p.warning ? 'has-warning' : ''}`} tabIndex={0}
                  aria-label={`Position ${i + 1}, ${sourceLabel(p)}${p.warning ? `, warning: ${p.warning}` : ''}${retaking.includes(p.id) ? ', retake requested' : ''}`}
                  onPointerDown={e => onPointerDown(e, p.id)}
                  onKeyDown={e => onKeyDown(e, p.id, i)}
                >
                  <div className="page-sheet">
                    <PageArt page={p} />
                    {retaking.includes(p.id) && <div className="page-retake"><ICamera size={22} /><span>Waiting for a new photo</span></div>}
                  </div>
                  {p.warning && <span className="page-heat" aria-hidden="true" />}
                  <div className="page-foot">
                    <span className="page-pos">{i + 1}</span>
                    <span className="grow" />
                    {!committed && <>
                      <button type="button" className="btn-icon is-small" onClick={() => toggleRetake(p.id)} aria-label={`Retake ${sourceLabel(p)}`} aria-pressed={retaking.includes(p.id)}><ICamera size={18} /></button>
                      <button type="button" className="btn-icon is-small" onClick={() => remove(p.id)} aria-label={`Delete ${sourceLabel(p)}`}><ITrash size={18} /></button>
                    </>}
                  </div>
                  <span className="page-src">{sourceLabel(p)}</span>
                  {p.warning && <p className="page-warning"><IWarning size={14} />{p.warning}</p>}
                </li>
              ))}
            </ol>
          )}
        </div>
      </div>
      {drag && dragged && (
        <div className="page-ghost" style={{ left: drag.x - drag.ox, top: drag.y - drag.oy, width: drag.w }} aria-hidden="true">
          <div className="page-sheet"><PageArt page={dragged} /></div>
        </div>
      )}
    </Screen>
  )
}
