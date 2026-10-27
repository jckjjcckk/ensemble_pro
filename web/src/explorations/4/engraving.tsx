import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent,
  type MouseEvent,
  type ReactNode,
} from 'react'
import type { IOSMDOptions, OpenSheetMusicDisplay } from 'opensheetmusicdisplay'
import { ScoreView } from '../shared'
import { IconChevronLeft, IconChevronRight } from './icons'

/** OSMD A4 portrait: width / height. Every leaf is drawn at exactly this ratio. */
export const PAGE_ASPECT = 210 / 297
const TABS_H = 52
/** Engraving widths in CSS px at zoom 1. A part gets larger notation per page than the full score. */
const PART_WIDTH = 680
const FULL_WIDTH = 900
const OSMD_OPTIONS: IOSMDOptions = { autoResize: false }

/** A bar's box on its page, as fractions of the page width and height. */
export interface BarBox {
  bar: number
  page: number
  sys: number
  x: number
  y: number
  w: number
  h: number
}

export interface Engraving {
  status: 'loading' | 'engraving' | 'ready' | 'error'
  error?: string
  pages: SVGSVGElement[]
  version: number
  bars: Map<number, BarBox>
}

const NO_BARS: Map<number, BarBox> = new Map()

function applyVisibility(osmd: OpenSheetMusicDisplay, want: number[] | null): boolean {
  let changed = false
  osmd.Sheet.Instruments.forEach((inst, i) => {
    const v = !want || want.includes(i)
    if (inst.Visible !== v) {
      inst.Visible = v
      changed = true
    }
  })
  return changed
}

function measureBars(osmd: OpenSheetMusicDisplay, svgs: SVGSVGElement[]): Map<number, BarBox> {
  const gs = osmd.GraphicSheet
  const pages = gs.MusicPages
  const out = new Map<number, BarBox>()
  const systems = new Map<unknown, number>()
  const fallbackW = osmd.Sheet.pageWidth * 10
  const fallbackH = osmd.EngravingRules.PageHeight * 10
  for (const staffMeasures of gs.MeasureList) {
    if (!staffMeasures) continue
    const vis = staffMeasures.filter(m => m && m.isVisible() && m.ParentMusicSystem)
    if (!vis.length) continue
    const top = vis[0]
    const bottom = vis[vis.length - 1]
    const sys = top.ParentMusicSystem
    const page = pages.indexOf(sys.Parent)
    const svg = svgs[page]
    if (page < 0 || !svg) continue
    const vb = svg.viewBox?.baseVal
    const W = vb && vb.width ? vb.width : fallbackW
    const H = vb && vb.height ? vb.height : fallbackH
    if (!W || !H) continue
    if (!systems.has(sys)) systems.set(sys, systems.size)
    const bar = top.MeasureNumber
    if (out.has(bar)) continue
    const p = top.PositionAndShape.AbsolutePosition
    const q = bottom.PositionAndShape.AbsolutePosition
    out.set(bar, {
      bar,
      page,
      sys: systems.get(sys) ?? 0,
      x: (p.x * 10) / W,
      y: (p.y * 10) / H,
      w: (top.PositionAndShape.Size.width * 10) / W,
      h: ((q.y + 4 - p.y) * 10) / H,
    })
  }
  return out
}

/**
 * Renders the score off screen through the shared ScoreView (A4 pages), then hands back
 * the page SVGs and every bar's position. The visible leaves are clones, so the layout
 * of the book never feeds back into OSMD's own layout.
 */
export function useEngraving(src: string, visible: number[] | null) {
  const key = visible ? visible.join(',') : 'all'
  const width = visible && visible.length === 1 ? PART_WIDTH : FULL_WIDTH
  const wrapRef = useRef<HTMLDivElement>(null)
  const osmdRef = useRef<OpenSheetMusicDisplay | null>(null)
  const wantRef = useRef<number[] | null>(visible)
  const keyRef = useRef(key)
  const renderedRef = useRef<string | null>(null)
  const skipRef = useRef(0)
  const [eng, setEng] = useState<Engraving>({ status: 'loading', pages: [], version: 0, bars: NO_BARS })

  const collect = useCallback(() => {
    const wrap = wrapRef.current
    if (!wrap) return
    const host = wrap.querySelector('[data-score-state]')
    if (host?.getAttribute('data-score-state') === 'error') {
      const msg = host.querySelector('[role="alert"]')?.textContent || 'The score could not be engraved.'
      setEng(e => ({ ...e, status: 'error', error: msg }))
      return
    }
    const osmd = osmdRef.current
    if (!osmd) return
    let svgs = Array.from(wrap.querySelectorAll<SVGSVGElement>('div[id^="osmdCanvasPage"] > svg'))
    if (!svgs.length) svgs = Array.from(wrap.querySelectorAll<SVGSVGElement>('svg')).filter(s => !s.parentElement?.closest('svg'))
    if (!svgs.length) return
    let bars = NO_BARS
    try {
      bars = measureBars(osmd, svgs)
    } catch {
      bars = NO_BARS
    }
    setEng(e => ({ status: 'ready', pages: svgs, version: e.version + 1, bars }))
  }, [])

  useEffect(() => {
    const wrap = wrapRef.current
    if (!wrap) return
    let t = 0
    const mo = new MutationObserver(records => {
      if (skipRef.current > 0) {
        skipRef.current--
        return
      }
      const attrOnly = records.every(r => r.type === 'attributes')
      if (attrOnly && !wrap.querySelector('[data-score-state="error"]')) return
      window.clearTimeout(t)
      t = window.setTimeout(collect, 40)
    })
    mo.observe(wrap, { childList: true, subtree: true, attributes: true, attributeFilter: ['data-score-state'] })
    return () => {
      mo.disconnect()
      window.clearTimeout(t)
    }
  }, [collect])

  const onReady = useCallback((osmd: OpenSheetMusicDisplay) => {
    osmdRef.current = osmd
    try {
      if (applyVisibility(osmd, wantRef.current)) osmd.updateGraphic()
    } catch {
      /* the full score still renders */
    }
    renderedRef.current = keyRef.current
    // ScoreView renders once more after it marks itself ready; ignore this first pass.
    skipRef.current = 1
  }, [])

  useEffect(() => {
    wantRef.current = visible
    keyRef.current = key
    const osmd = osmdRef.current
    if (!osmd) return
    if (renderedRef.current === key) {
      setEng(e => (e.status === 'engraving' ? { ...e, status: 'ready' } : e))
      return
    }
    setEng(e => ({ ...e, status: 'engraving' }))
    let raf2 = 0
    const raf1 = requestAnimationFrame(() => {
      raf2 = requestAnimationFrame(() => {
        try {
          applyVisibility(osmd, wantRef.current)
          osmd.updateGraphic()
          osmd.render()
          renderedRef.current = keyRef.current
        } catch (err) {
          setEng(e => ({ ...e, status: 'error', error: err instanceof Error ? err.message : String(err) }))
        }
      })
    })
    return () => {
      cancelAnimationFrame(raf1)
      cancelAnimationFrame(raf2)
    }
    // visible is represented by key
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key])

  const offstage = (
    <div ref={wrapRef} className="x4-offstage" style={{ width }} aria-hidden="true">
      <ScoreView src={src} zoom={1} pageFormat="A4_P" onReady={onReady} options={OSMD_OPTIONS} />
    </div>
  )

  return { eng, offstage }
}

// ------------------------------------------------------------------ geometry helpers

export interface Segment {
  page: number
  sys: number
  x: number
  y: number
  w: number
  h: number
  fromBar: number
  toBar: number
}

/** A bar range broken into one rectangle per system. */
export function segments(bars: Map<number, BarBox>, from: number, to: number): Segment[] {
  const out: Segment[] = []
  for (let b = from; b <= to; b++) {
    const box = bars.get(b)
    if (!box) continue
    const last = out[out.length - 1]
    if (last && last.page === box.page && last.sys === box.sys) {
      last.w = box.x + box.w - last.x
      last.toBar = b
      last.y = Math.min(last.y, box.y)
      last.h = Math.max(last.h, box.h)
    } else {
      out.push({ page: box.page, sys: box.sys, x: box.x, y: box.y, w: box.w, h: box.h, fromBar: b, toBar: b })
    }
  }
  return out
}

export const pct = (n: number) => `${(n * 100).toFixed(3)}%`

export function boxStyle(b: { x: number; y: number; w: number; h: number }, padY = 0.01): CSSProperties {
  return { left: pct(b.x), top: pct(b.y - padY), width: pct(b.w), height: pct(b.h + padY * 2) }
}

function hitBar(bars: Map<number, BarBox>, page: number, fx: number, fy: number): BarBox | undefined {
  let best: BarBox | undefined
  let bestD = Infinity
  for (const b of bars.values()) {
    if (b.page !== page) continue
    const top = b.y - 0.02
    const bottom = b.y + b.h + 0.02
    const dy = fy < top ? top - fy : fy > bottom ? fy - bottom : 0
    const dx = fx < b.x ? b.x - fx : fx > b.x + b.w ? fx - b.x - b.w : 0
    const d = dx * 2 + dy
    if (d < bestD) {
      bestD = d
      best = b
    }
  }
  return bestD < 0.05 ? best : undefined
}

// ------------------------------------------------------------------ pager

export function usePager(count: number, perView: 1 | 2) {
  const [raw, setRaw] = useState(0)
  const norm = useCallback(
    (i: number) => {
      const max = Math.max(0, count - 1)
      let n = Math.min(Math.max(0, i), max)
      if (perView === 2) n -= n % 2
      return n
    },
    [count, perView],
  )
  const first = norm(raw)
  const goToPage = useCallback((i: number) => setRaw(norm(i)), [norm])
  const next = useCallback(() => setRaw(r => norm(norm(r) + perView)), [norm, perView])
  const prev = useCallback(() => setRaw(r => norm(norm(r) - perView)), [norm, perView])
  const last = Math.max(first, Math.min(first + perView - 1, count - 1))
  return { first, last, count, goToPage, next, prev, canPrev: first > 0, canNext: first + perView < count }
}

export function pagesLabel(first: number, last: number, count: number) {
  if (!count) return 'Engraving'
  return first === last ? `Page ${first + 1} of ${count}` : `Pages ${first + 1}–${last + 1} of ${count}`
}

// ------------------------------------------------------------------ the book

export interface BookLayout {
  perView: 1 | 2
  bookW: number
}

interface BookProps {
  eng: Engraving
  first: number
  tabs: ReactNode
  aside?: ReactNode
  overlay?: (page: number) => ReactNode
  onBarTap?: (bar: number) => void
  onLayout: (l: BookLayout) => void
  onPrev: () => void
  onNext: () => void
  canPrev: boolean
  canNext: boolean
  waitLabel: string
}

/** Part tabs on the top edge, then one leaf or two facing leaves sized to the space left. */
export function Book(p: BookProps) {
  const stageRef = useRef<HTMLDivElement>(null)
  const [size, setSize] = useState({ w: 0, h: 0 })

  useLayoutEffect(() => {
    const el = stageRef.current
    if (!el) return
    const ro = new ResizeObserver(entries => {
      const r = entries[0]?.contentRect
      if (r) setSize({ w: Math.floor(r.width), h: Math.floor(r.height) })
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  let pageW = Math.max(0, (size.h - TABS_H) * PAGE_ASPECT)
  const perView: 1 | 2 = pageW > 120 && size.w >= pageW * 2 ? 2 : 1
  if (perView === 1) pageW = Math.min(pageW, size.w)
  pageW = Math.floor(pageW)
  const pageH = Math.floor(pageW / PAGE_ASPECT)
  const bookW = pageW * perView
  const showTurns = size.w - bookW >= 128

  const { onLayout } = p
  useEffect(() => {
    if (size.w > 0) onLayout({ perView, bookW })
  }, [perView, bookW, size.w, onLayout])

  const { eng } = p
  const count = eng.pages.length
  const indices = perView === 2 ? [p.first, p.first + 1] : [p.first]
  let msg: string | null = null
  if (eng.status === 'error') msg = eng.error || 'The score could not be engraved.'
  else if (eng.status === 'loading' || (eng.status === 'engraving' && count === 0)) msg = p.waitLabel
  else if (eng.status === 'engraving') msg = p.waitLabel

  const tap = (page: number) => (e: MouseEvent<HTMLDivElement>) => {
    if (!p.onBarTap || eng.status !== 'ready') return
    const r = e.currentTarget.getBoundingClientRect()
    const hit = hitBar(eng.bars, page, (e.clientX - r.left) / r.width, (e.clientY - r.top) / r.height)
    if (hit) p.onBarTap(hit.bar)
  }

  return (
    <div className="x4-stage" ref={stageRef}>
      {showTurns && (
        <>
          <button type="button" className="x4-turn" data-side="left" onClick={p.onPrev} disabled={!p.canPrev} aria-label="Previous pages">
            <IconChevronLeft size={28} />
          </button>
          <button type="button" className="x4-turn" data-side="right" onClick={p.onNext} disabled={!p.canNext} aria-label="Next pages">
            <IconChevronRight size={28} />
          </button>
        </>
      )}
      {size.w > 0 && pageW > 0 && (
        <div className="x4-book" style={{ width: bookW }}>
          <div className="x4-tabs-row">
            {p.tabs}
            {p.aside ? <div className="x4-tabs-aside">{p.aside}</div> : null}
          </div>
          <div className="x4-spread" style={{ height: pageH }}>
            {indices.map((i, k) => {
              const exists = i < count
              const side = perView === 1 ? 'single' : k === 0 ? 'left' : 'right'
              return (
                <Leaf
                  key={k}
                  svg={exists ? eng.pages[i] : null}
                  version={eng.version}
                  w={pageW}
                  h={pageH}
                  side={side}
                  folio={exists ? i + 1 : null}
                  msg={k === 0 || !count ? msg : null}
                  error={eng.status === 'error'}
                  dim={eng.status === 'engraving' && count > 0}
                  onClick={exists ? tap(i) : undefined}
                >
                  {exists && eng.status === 'ready' && p.overlay ? p.overlay(i) : null}
                </Leaf>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}

interface LeafProps {
  svg: SVGSVGElement | null
  version: number
  w: number
  h: number
  side: 'left' | 'right' | 'single'
  folio: number | null
  msg: string | null
  error: boolean
  dim: boolean
  onClick?: (e: MouseEvent<HTMLDivElement>) => void
  children?: ReactNode
}

function Leaf({ svg, version, w, h, side, folio, msg, error, dim, onClick, children }: LeafProps) {
  const hostRef = useRef<HTMLDivElement>(null)

  useLayoutEffect(() => {
    const host = hostRef.current
    if (!host) return
    if (!svg) {
      host.replaceChildren()
      return
    }
    const clone = svg.cloneNode(true) as SVGSVGElement
    if (!clone.getAttribute('viewBox')) {
      const sw = parseFloat(svg.getAttribute('width') || '0')
      const sh = parseFloat(svg.getAttribute('height') || '0')
      if (sw && sh) clone.setAttribute('viewBox', `0 0 ${sw} ${sh}`)
    }
    clone.removeAttribute('id')
    clone.removeAttribute('width')
    clone.removeAttribute('height')
    clone.removeAttribute('style')
    clone.setAttribute('preserveAspectRatio', 'xMidYMin meet')
    clone.setAttribute('aria-hidden', 'true')
    host.replaceChildren(clone)
  }, [svg, version])

  return (
    <div className="x4-leaf" data-side={side} data-dim={dim || undefined} style={{ width: w, height: h }} onClick={onClick}>
      <div className="x4-leaf-svg" ref={hostRef} />
      {!svg && !msg ? <div className="x4-leaf-blank" aria-hidden="true" /> : null}
      <div className="x4-ov">{children}</div>
      {folio ? <span className="x4-folio">{folio}</span> : null}
      {msg ? (
        <div className="x4-leaf-msg" data-error={error || undefined} role={error ? 'alert' : 'status'}>
          {!svg && !error ? <span className="x4-skeleton" aria-hidden="true" /> : null}
          <span>{msg}</span>
        </div>
      ) : null}
    </div>
  )
}

/** Part tabs: the signature move. Active is lifted and joined to the page; flat tabs sit low. */
export interface TabSpec {
  key: string
  label: string
  meta?: ReactNode
  count?: number
  countLabel?: string
  state: 'raised' | 'flat'
}

export function PartTabs({
  tabs,
  active,
  onPick,
  label,
}: {
  tabs: TabSpec[]
  active: string
  onPick: (key: string) => void
  label: string
}) {
  const refs = useRef<(HTMLButtonElement | null)[]>([])
  const onKey = (e: KeyboardEvent<HTMLButtonElement>, i: number) => {
    let n = -1
    if (e.key === 'ArrowRight') n = (i + 1) % tabs.length
    else if (e.key === 'ArrowLeft') n = (i - 1 + tabs.length) % tabs.length
    else if (e.key === 'Home') n = 0
    else if (e.key === 'End') n = tabs.length - 1
    if (n < 0) return
    e.preventDefault()
    e.stopPropagation()
    refs.current[n]?.focus()
    onPick(tabs[n].key)
  }
  return (
    <div className="x4-tabs" role="tablist" aria-label={label}>
      {tabs.map((t, i) => {
        const selected = t.key === active
        return (
          <button
            key={t.key}
            ref={el => {
              refs.current[i] = el
            }}
            type="button"
            role="tab"
            aria-selected={selected}
            tabIndex={selected ? 0 : -1}
            className="x4-tab"
            data-state={t.state}
            onClick={() => onPick(t.key)}
            onKeyDown={e => onKey(e, i)}
          >
            <span className="x4-tab-name">
              {t.label}
              {t.count ? (
                <span className="x4-tab-count" aria-label={t.countLabel}>
                  {t.count}
                </span>
              ) : null}
            </span>
            {t.meta ? <span className="x4-tab-meta">{t.meta}</span> : null}
          </button>
        )
      })}
    </div>
  )
}
