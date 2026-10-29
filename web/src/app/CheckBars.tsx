/** Checking the Digital copy (R3, docs/design/r3/F_CheckBar), `/score/:id/check`, for whoever may edit the book. The
 *  doubtful bars the conversion flagged (`flagged_bars` in the transcription's meta, 005) are listed with their reasons;
 *  for the chosen bar the scan's crop sits above the engraved copy's crop. "Wrong, use the scan here" and "Looks right"
 *  write a per-bar decision (`bar_decisions`); the reader never rewrites music, so a rejected bar is drawn on the stand
 *  with the scan's bar over the engraved one (`ScanPatches`). Also here: the stand's placeholder for a page the reader
 *  could not read (F_Unreadable). */
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router'
import type { FlaggedBar, Score } from '../mock'
import { supabase } from '../lib/supabase'
import type { Geo } from './geometry'
import { useStore } from './store'

export type Decision = 'scan' | 'digital'
type Box = { x0: number; y0: number; x1: number; y1: number }

/** The book's decisions, live (Realtime), and a writer that upserts one. */
export function useBarDecisions(scoreId: string | undefined): { decisions: Map<number, Decision>; decide: (bar: number, d: Decision) => Promise<void>; loaded: boolean } {
  const [rows, setRows] = useState<Map<number, Decision>>(new Map())
  const [loaded, setLoaded] = useState(false)
  useEffect(() => {
    if (!scoreId) return
    let live = true
    const load = () => supabase.from('bar_decisions').select('bar,decision').eq('score_id', scoreId).then(({ data }) => {
      if (!live) return
      setRows(new Map((data ?? []).map(r => [r.bar as number, r.decision as Decision])))
      setLoaded(true)
    })
    void load()
    const ch = supabase.channel(`bar_decisions:${scoreId}`)
      .on('postgres_changes', { event: '*', schema: 'public', table: 'bar_decisions', filter: `score_id=eq.${scoreId}` }, () => void load())
      .subscribe()
    return () => { live = false; void supabase.removeChannel(ch) }
  }, [scoreId])
  const decide = useCallback(async (bar: number, d: Decision) => {
    if (!scoreId) return
    setRows(m => new Map(m).set(bar, d))
    const { data: u } = await supabase.auth.getUser()
    const { error } = await supabase.from('bar_decisions').upsert({ score_id: scoreId, bar, decision: d, decided_by: u.user?.id, decided_at: new Date().toISOString() }, { onConflict: 'score_id,bar' })
    if (error) throw new Error(error.message)
  }, [scoreId])
  return { decisions: rows, decide, loaded }
}

/** The page image a PDF book shows for page `n` (1-based): the rendered page, or the photograph in reading order. */
export function scanPath(s: Score, n: number): string {
  const src = s.pageSource
  if (src?.kind === 'images') return src.paths[(src.order?.[n - 1] ?? n) - 1] ?? ''
  return `${s.id}/pages/${n}.png`
}

function useSignedMany(paths: string[]): Map<string, string> {
  const [urls, setUrls] = useState<Map<string, string>>(new Map())
  const key = [...new Set(paths.filter(Boolean))].sort().join('|')
  useEffect(() => {
    const ps = key ? key.split('|') : []
    if (!ps.length) return
    let live = true
    supabase.storage.from('scores').createSignedUrls(ps, 3600).then(({ data }) => {
      if (live) setUrls(new Map((data ?? []).filter(d => d.path && d.signedUrl).map(d => [d.path!, d.signedUrl as string])))
    })
    return () => { live = false }
  }, [key])
  return urls
}

/** On the engraved stand: each bar the owner rejected shows the scan's bar instead, stretched over the engraved one,
 *  unmarked. A bar that is only flagged is drawn as read; doubt lives on the check screen alone (CK, 2026-10-28). */
export function ScanPatches({ geo, score, decisions }: { geo: Geo; score: Score; decisions: Map<number, Decision> }) {
  const patches = (score.flaggedBars ?? []).filter(f => f.box && decisions.get(f.number) === 'scan')
  const urls = useSignedMany(patches.map(f => scanPath(score, f.page)))
  return (
    <>
      {patches.map(f => {
        const r = geo.bars.get(f.number)
        const url = urls.get(scanPath(score, f.page))
        if (!r || !url || !f.box) return null
        const bw = r.w / (f.box.x1 - f.box.x0), bh = r.h / (f.box.y1 - f.box.y0)
        return (
          <div key={f.number} className="scan-patch" role="img" aria-label={`Bar ${f.number}, shown from the scan`}
            style={{ left: r.x, top: r.y, width: r.w, height: r.h, backgroundImage: `url("${url}")`, backgroundSize: `${bw}px ${bh}px`, backgroundPosition: `${-f.box.x0 * bw}px ${-f.box.y0 * bh}px` }} />
        )
      })}
    </>
  )
}

/** "Page 3 could not be read" over a page the reader found no staves on, until the reader asks for the scan as is. */
export function UnreadablePages({ geo, score, shown, onShow, onRescan, rescanMsg }: {
  geo: Geo; score: Score; shown: Set<number>; onShow: (page: number) => void; onRescan: (page: number) => void; rescanMsg: number | null
}) {
  return (
    <>
      {(score.unreadable ?? []).filter(u => !shown.has(u.page)).map(u => {
        const r = geo.pages[u.page - 1]
        if (!r) return null
        return (
          <div key={u.page} className="unread" role="region" aria-label={`Page ${u.page} could not be read`} style={{ left: r.x, top: r.y, width: r.w, height: r.h }}
            onPointerDown={e => e.stopPropagation()} onPointerUp={e => e.stopPropagation()} onClick={e => e.stopPropagation()}>
            <span className="unread-lines" aria-hidden="true" />
            <div className="unread-card">
              <span className="card-dot is-fail is-inline unread-dot" aria-hidden="true" />
              <b>Page {u.page} could not be read</b>
              <span>{unreadWhy(u.reason)} The other pages are fine; this page's bars are missing until it is rescanned.</span>
              <div className="unread-acts">
                <button type="button" className="r3-btn is-solid" onClick={() => onRescan(u.page)}>
                  <svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M4 8V5a1 1 0 0 1 1-1h3M16 4h3a1 1 0 0 1 1 1v3M20 16v3a1 1 0 0 1-1 1h-3M8 20H5a1 1 0 0 1-1-1v-3M4 12h16" /></svg>
                  Rescan page {u.page}
                </button>
                <button type="button" className="r3-btn is-line" onClick={() => onShow(u.page)}>Show the scan as is</button>
              </div>
              {rescanMsg === u.page && <span className="unread-msg" role="status">Rescanning a single page is not built yet. Show the scan as is for now, or scan the book again from the shelf.</span>}
            </div>
          </div>
        )
      })}
    </>
  )
}

const unreadWhy = (reason: string) => /no staff lines/i.test(reason) ? 'No staff lines could be found on the scan.' : 'The staves could not be told apart on the scan.'

/** A flag's reasons in the product's words: "Adds up to 3½ beats in 3/4, half a beat too many", "Cello bar missing
 *  from the copy". Audiveris gives bar lengths in whole notes ("7/8 vs expected 3/4"); the rhythm checks in beats. */
const num = (x: string) => { const m = x.match(/^(-?\d+)\/(\d+)$/); return m ? Number(m[1]) / Number(m[2]) : Number(x) }
function beats(v: number): string {
  const whole = Math.floor(v + 1e-9), rest = v - whole
  const f = Math.abs(rest - 0.5) < 1e-6 ? '½' : Math.abs(rest - 0.25) < 1e-6 ? '¼' : Math.abs(rest - 0.75) < 1e-6 ? '¾' : rest > 1e-6 ? `.${String(Math.round(rest * 100)).padStart(2, '0')}` : ''
  return `${whole || !f ? whole : ''}${f}`
}
const diffWords = (d: number) => (Math.abs(d - 0.5) < 1e-6 ? 'half a beat' : Math.abs(d - 1) < 1e-6 ? 'a beat' : `${beats(d)} beats`)
export function reasonWords(r: string, parts: string[] = [], meter = ''): string {
  const staffName = (n: string) => parts[Number(n) - 1] ?? `Staff ${n}`
  const ab = r.match(/abnormal: duration (\S+) vs expected (\S+)/i)
  if (ab) {
    const d = num(ab[1]) * 4, e = num(ab[2]) * 4
    if (!Number.isFinite(d) || !Number.isFinite(e) || Math.abs(d - e) < 1e-6) return 'The reader marked this bar as odd'
    return `Adds up to ${beats(d)} beats${meter ? ` in ${meter}` : ''}, ${diffWords(Math.abs(d - e))} too ${d > e ? 'many' : 'few'}`
  }
  const fills = r.match(/staff (\d+) fills only (\S+) of (\S+)/i)
  if (fills) return `${staffName(fills[1])} fills only ${beats(num(fills[2]))} of ${beats(num(fills[3]))} beats`
  const sums = r.match(/staff (\d+) voice sums to (\S+) > (\S+)/i)
  if (sums) return `${staffName(sums[1])} adds up to ${beats(num(sums[2]))} beats, more than ${beats(num(sums[3]))}`
  const miss = r.match(/staff (\d+): bar missing from the export/i)
  if (miss) return `${staffName(miss[1])} bar missing from the copy`
  const sym = r.match(/^symbol: (.*)$/i)
  if (sym) return `Unsure symbol: ${sym[1]}`
  return (r.charAt(0).toUpperCase() + r.slice(1)).replace(/^Rhythm: /, '')
}

/** A page crop: the page image placed so `box` (fractions, with a margin) fills the frame, centred, never stretched. */
function Crop({ url, box, outline, label }: { url: string | null; box: Box; outline?: boolean; label: string }) {
  const frame = useRef<HTMLDivElement>(null)
  const [size, setSize] = useState<{ w: number; h: number } | null>(null)
  const [aspect, setAspect] = useState<number | null>(null)
  useLayoutEffect(() => {
    const el = frame.current
    if (!el) return
    const ro = new ResizeObserver(() => setSize({ w: el.clientWidth, h: el.clientHeight }))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])
  const mx = (box.x1 - box.x0) * 0.35 + 0.02, my = (box.y1 - box.y0) * 0.12 + 0.01
  const c = { x0: Math.max(0, box.x0 - mx), x1: Math.min(1, box.x1 + mx), y0: Math.max(0, box.y0 - my), y1: Math.min(1, box.y1 + my) }
  let style: React.CSSProperties | undefined
  let ring: React.CSSProperties | undefined
  if (size && aspect) {
    const W = Math.min(size.w / (c.x1 - c.x0), size.h / ((c.y1 - c.y0) * aspect))
    const H = W * aspect
    const left = size.w / 2 - ((c.x0 + c.x1) / 2) * W, top = size.h / 2 - ((c.y0 + c.y1) / 2) * H
    style = { width: W, height: H, left, top }
    ring = { left: left + box.x0 * W - 4, top: top + box.y0 * H - 4, width: (box.x1 - box.x0) * W + 8, height: (box.y1 - box.y0) * H + 8 }
  }
  return (
    <div className="cb-crop-frame" ref={frame}>
      {url && <img src={url} alt={label} draggable={false} decoding="async" style={style ?? { visibility: 'hidden' }} onLoad={e => setAspect(e.currentTarget.naturalHeight / e.currentTarget.naturalWidth || 1.414)} />}
      {outline && ring && <span className="cb-ring" style={ring} aria-hidden="true" />}
    </div>
  )
}

export function CheckBars() {
  const { scoreId } = useParams()
  const navigate = useNavigate()
  const { world, canEditBook } = useStore()
  const score = world.scores.find(s => s.id === scoreId)
  const { decisions, decide, loaded } = useBarDecisions(score?.id)
  const flags = useMemo(() => [...(score?.flaggedBars ?? [])].sort((a, b) => a.number - b.number), [score?.flaggedBars])
  const [current, setCurrent] = useState<number | null>(null)
  const [msg, setMsg] = useState<string | null>(null)
  const parts = useMemo(() => (score ? world.parts.filter(p => score.partIds.includes(p.id)).map(p => p.name) : []), [score, world.parts])
  const engraving = score?.engravings?.find(e => e.layout === (score.digitalLayout ?? 'display')) ?? score?.engravings?.[0]

  // Start on the first bar nobody has decided yet.
  useEffect(() => {
    if (current != null || !loaded || !flags.length) return
    setCurrent((flags.find(f => !decisions.has(f.number)) ?? flags[0]).number)
  }, [current, loaded, flags, decisions])

  const f = flags.find(x => x.number === current) ?? null
  const eb = f && engraving ? engraving.bars.find(b => b[0] === f.number) : undefined
  const urls = useSignedMany([f && score ? scanPath(score, f.page) : '', eb && engraving ? engraving.paths[eb[1] - 1] ?? '' : ''])
  const scanUrl = f && score ? urls.get(scanPath(score, f.page)) ?? null : null
  const digitalUrl = eb && engraving ? urls.get(engraving.paths[eb[1] - 1] ?? '') ?? null : null

  if (!world.loaded) return <div className="cb is-empty"><p>Opening the book</p></div>
  if (!score || !canEditBook(score)) return <div className="cb is-empty"><p>Only the book's owner checks its Digital copy.</p><button type="button" className="r3-btn is-line" onClick={() => navigate('/')}>Back to the shelf</button></div>

  const checked = flags.filter(x => decisions.has(x.number)).length
  const next = (after: number) => flags.find(x => x.number > after && !decisions.has(x.number)) ?? flags.find(x => !decisions.has(x.number) && x.number !== after)
  const act = async (d: Decision) => {
    if (!f) return
    setMsg(null)
    try {
      await decide(f.number, d)
      const n = next(f.number)
      if (n) setCurrent(n.number)
    } catch (e) {
      setMsg((e as Error).message)
    }
  }
  const words = (x: FlaggedBar) => x.reasons.map(r => reasonWords(r, parts, score.meter))
  const status = (x: FlaggedBar) => decisions.get(x.number)

  return (
    <div className="cb">
      <header className="cb-head">
        <button type="button" className="stand-back" onClick={() => (window.history.length > 1 ? navigate(-1) : navigate('/'))} aria-label="Back to the book">
          <svg aria-hidden="true" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M15 5l-7 7 7 7" /></svg>Book
        </button>
        <div className="cb-title">
          <span className="cb-title-t">{score.title} <span className="cb-title-p">— checking the Digital copy</span></span>
          <span className="cb-title-s">{[score.bars ? `${score.bars} bars` : null, `${flags.length} ${flags.length === 1 ? 'bar' : 'bars'} the reader is unsure about`].filter(Boolean).join(' · ')}</span>
        </div>
        <span className="cb-count" aria-live="polite">{checked} of {flags.length} checked</span>
      </header>
      {!flags.length ? (
        <div className="cb is-empty"><p>The reader is sure of every bar in this copy.</p></div>
      ) : (
        <div className="cb-main">
          <nav className="cb-list" aria-label="Doubtful bars">
            <span className="cb-list-h">Doubtful bars</span>
            <div className="cb-list-rows r3-scroll">
              {flags.map(x => {
                const st = status(x)
                return (
                  <button key={x.number} type="button" aria-current={x.number === current} className={`cb-row ${st ? 'is-done' : ''}`} onClick={() => setCurrent(x.number)}>
                    <span className={`cb-dot ${st ? 'is-done' : ''}`} aria-hidden="true" />
                    <span className="cb-row-text"><b>Bar {x.number} <span>· p. {x.page}</span></b><span>{words(x)[0] ?? 'Unsure'}</span></span>
                    {st && <span className={`cb-row-st ${st === 'scan' ? 'is-scan' : ''}`}>{st === 'scan' ? 'Scan used' : 'Looks right'}</span>}
                  </button>
                )
              })}
            </div>
          </nav>
          {f && (
            <section className="cb-pane" aria-label={`Bar ${f.number}`}>
              <div className="cb-pane-h">
                <h2>Bar {f.number} · page {f.page}</h2>
                <span className="cb-why"><span className="card-dot is-ask is-inline" aria-hidden="true" />{words(f).join('; ') || 'The reader is unsure of this bar'}</span>
              </div>
              <div className="cb-crops">
                <div className="cb-crop is-scan">
                  <span className="cb-crop-label">Your scan</span>
                  {f.box ? <Crop url={scanUrl} box={f.box} outline label={`Bar ${f.number} on the scan`} /> : <span className="cb-crop-none">The scan's bar box is missing</span>}
                </div>
                <div className="cb-crop is-digital">
                  <span className="cb-crop-label">Digital copy</span>
                  {eb ? <Crop url={digitalUrl} box={{ x0: eb[2], y0: eb[3], x1: eb[2] + eb[4], y1: eb[3] + eb[5] }} outline label={`Bar ${f.number} in the Digital copy`} /> : <span className="cb-crop-none">{engraving ? 'This bar is not on the engraved pages' : 'The engraved pages are not ready yet'}</span>}
                </div>
              </div>
              <div className="cb-acts">
                <span className="cb-note">Compare the two. The reader never rewrites the music: if the copy is wrong, this bar shows your scan instead.</span>
                {msg && <p className="r3-msg" role="alert">{msg}</p>}
                <div className="cb-btns">
                  <button type="button" className={`r3-btn is-line is-big ${status(f) === 'scan' ? 'is-chosen' : ''}`} aria-pressed={status(f) === 'scan'} onClick={() => void act('scan')}>Wrong, use the scan here</button>
                  <button type="button" className={`r3-btn is-solid is-big ${status(f) === 'digital' ? 'is-chosen' : ''}`} aria-pressed={status(f) === 'digital'} onClick={() => void act('digital')}>
                    Looks right
                    <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M5 12l5 5 9-10" /></svg>
                  </button>
                </div>
              </div>
            </section>
          )}
        </div>
      )}
    </div>
  )
}
