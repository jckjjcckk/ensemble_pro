import type { OpenSheetMusicDisplay } from 'opensheetmusicdisplay'

export interface Rect { x: number; y: number; w: number; h: number }

export interface BarBox extends Rect {
  bar: number
  page: number
  /** Index of the system (line) the bar sits on, unique across the piece. */
  sys: number
}

/** Model-level facts that do not depend on the DOM: which page each bar is on. */
export interface Model {
  pageCount: number
  barPage: Map<number, number>
  /** [first, last] bar on each page */
  pageBars: [number, number][]
}

export interface Geo extends Model {
  /** Page sheets in stage coordinates; null when the page is not displayed. */
  pages: (Rect | null)[]
  /** Bars on displayed pages, in stage coordinates. */
  bars: Map<number, BarBox>
}

interface Raw { bar: number; page: number; sys: number; x: number; y: number; w: number; h: number }

function readRaw(osmd: OpenSheetMusicDisplay): { raw: Raw[]; pageCount: number; pageUnitW: number[] } {
  const gs = osmd.GraphicSheet
  const pages = gs?.MusicPages ?? []
  const sysIds = new Map<object, number>()
  const raw: Raw[] = []
  for (const column of gs?.MeasureList ?? []) {
    // A hidden instrument's measures keep the ParentMusicSystem of an earlier render (OSMD never resets it), and
    // that system's page is gone. Only measures on a current page count, whichever staff they sit on.
    const ms = (column ?? []).filter(m => m && !m.IsExtraGraphicalMeasure && m.ParentMusicSystem && pages.includes(m.ParentMusicSystem.Parent))
    if (!ms.length) continue
    const sysObj = ms[0].ParentMusicSystem
    const page = pages.indexOf(sysObj.Parent)
    if (!sysIds.has(sysObj)) sysIds.set(sysObj, sysIds.size)
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity
    for (const m of ms) {
      const ps = m.PositionAndShape
      const ax = ps.AbsolutePosition.x
      const ay = ps.AbsolutePosition.y
      x0 = Math.min(x0, ax + ps.BorderLeft)
      x1 = Math.max(x1, ax + ps.BorderRight)
      y0 = Math.min(y0, ay + ps.BorderTop)
      y1 = Math.max(y1, ay + Math.max(ps.BorderBottom, 4))
    }
    raw.push({ bar: ms[0].MeasureNumber, page, sys: sysIds.get(sysObj)!, x: x0, y: y0, w: x1 - x0, h: y1 - y0 })
  }
  const pageUnitW = pages.map(p => {
    const ps = p.PositionAndShape
    return (ps.BorderRight - ps.BorderLeft) || osmd.Sheet.pageWidth
  })
  return { raw, pageCount: pages.length, pageUnitW }
}

export function readModel(osmd: OpenSheetMusicDisplay): Model {
  const { raw, pageCount } = readRaw(osmd)
  const barPage = new Map<number, number>()
  const pageBars: [number, number][] = Array.from({ length: pageCount }, () => [Infinity, -Infinity])
  for (const r of raw) {
    if (!barPage.has(r.bar)) barPage.set(r.bar, r.page)
    const pb = pageBars[r.page]
    pb[0] = Math.min(pb[0], r.bar)
    pb[1] = Math.max(pb[1], r.bar)
  }
  return { pageCount, barPage, pageBars }
}

/** Measure displayed pages and bars relative to the stage element. */
export function measureGeo(osmd: OpenSheetMusicDisplay, stage: HTMLElement, pageEls: HTMLElement[]): Geo {
  const { raw, pageCount, pageUnitW } = readRaw(osmd)
  const model = readModel(osmd)
  const sr = stage.getBoundingClientRect()
  const pages: (Rect | null)[] = []
  const scale: number[] = []
  for (let i = 0; i < pageCount; i++) {
    const svg = pageEls[i]?.querySelector('svg')
    const r = svg?.getBoundingClientRect()
    if (!r || r.width === 0) { pages.push(null); scale.push(0); continue }
    pages.push({ x: r.left - sr.left + stage.scrollLeft, y: r.top - sr.top + stage.scrollTop, w: r.width, h: r.height })
    scale.push(r.width / pageUnitW[i]) // px per OSMD unit, whatever the zoom or CSS scale
  }
  const bars = new Map<number, BarBox>()
  for (const r of raw) {
    const p = pages[r.page]
    if (!p || bars.has(r.bar)) continue
    const s = scale[r.page]
    bars.set(r.bar, { bar: r.bar, page: r.page, sys: r.sys, x: p.x + r.x * s, y: p.y + r.y * s, w: r.w * s, h: r.h * s })
  }
  return { ...model, pages, bars }
}

/** Group consecutive bars of a span into one rectangle per system line. */
export function spanRects(geo: Geo, from: number, to: number): (Rect & { first: number; last: number })[] {
  const out: (Rect & { first: number; last: number; sys: number })[] = []
  for (let b = from; b <= to; b++) {
    const box = geo.bars.get(b)
    if (!box) continue
    const prev = out[out.length - 1]
    if (prev && prev.sys === box.sys && prev.last === b - 1) {
      const right = box.x + box.w
      prev.y = Math.min(prev.y, box.y)
      prev.h = Math.max(prev.y + prev.h, box.y + box.h) - prev.y
      prev.w = right - prev.x
      prev.last = b
    } else {
      out.push({ x: box.x, y: box.y, w: box.w, h: box.h, first: b, last: b, sys: box.sys })
    }
  }
  return out
}
