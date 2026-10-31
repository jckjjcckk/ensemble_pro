/** The reader's questions (011), as R3 dialogs over the dimmed shelf or stand. Only whoever may edit the book sees
 *  them; "Later" closes and leaves the yellow dot. Each answer goes through `POST /jobs/{id}/answer` and resumes the job.
 *
 *  - Which parts are on page N (004, `process_pages`; docs/design/r3/F_Parts): three choices: the parts of the earlier
 *    pages, what the reader found on this page, or something else (one name per staff, top to bottom). The page beside
 *    them carries the labels of the current choice on its systems' staves.
 *  - Choose the staves (008, `part_cut` `choose_staves`; F_Staves): the plain page with the line in question lit and the
 *    rest dimmed, the librarian's guess already chosen; tap the staves that are the part (tap again to let go), or say it
 *    is not on this line. A musician's words only (CK, 2026-10-31): no staff numbers, no blocks, no model; what refused
 *    the cut stays behind a small "Why am I asked?" for the admin who wants it. */
import { useEffect, useMemo, useState } from 'react'
import type { Score } from '../mock'
import { answerJob, apiFailure } from '../lib/api'
import { supabase } from '../lib/supabase'
import { useAuth } from './auth'
import type { AskJob, ChooseStaves, StaffBox } from './data'
import { Dialog } from './Surfaces'
import { MY_LIBRARY } from './data'
import { useStore } from './store'

const isStaves = (q: unknown): q is ChooseStaves => !!q && typeof q === 'object' && (q as ChooseStaves).kind === 'choose_staves'

/** The reader's question on a page (`process_pages`): the parts it read, the parts it knows so far. */
interface PageParts { page?: number; spark_parts?: string[]; known_parts?: string[]; system_staves?: number[]; interpretation_id?: string; header_parts?: string[] }
type Box = { x0: number; y0: number; x1: number; y1: number }
interface GeoSystem { index: number; box: Box; staves: number }

const IChev = () => <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M9 5l7 7-7 7" /></svg>
const ICheck = () => <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M5 12l5 5 9-10" /></svg>
const ORDINAL = ['first', 'second', 'third', 'fourth', 'fifth', 'sixth', 'seventh', 'eighth', 'ninth', 'tenth', 'eleventh', 'twelfth', 'thirteenth', 'fourteenth', 'fifteenth', 'sixteenth', 'seventeenth', 'eighteenth', 'nineteenth', 'twentieth']
const ordinal = (i: number) => ORDINAL[i] ?? `${i + 1}th`
const plural = (n: number, w: string) => `${n} ${w}${n === 1 ? '' : 's'}`
const KEYBOARD = /piano|organ|harp|cembalo|harpsichord|celest|keyboard/i

export function StaffQuestion({ job, open, onClose }: { job: AskJob | null; open: boolean; onClose: () => void }) {
  const { world } = useStore()
  const q = job?.questionPayload ?? null
  const staves = isStaves(q) ? q : null
  const score = world.scores.find(s => s.id === job?.scoreId) ?? null
  const label = staves ? `Which staves are the ${staves.instrument}'s on this line?` : `Which parts are on page ${(q as PageParts | null)?.page ?? ''}?`
  return (
    <Dialog open={open && !!job && !!q} onClose={onClose} label={label} className="ask">
      {job && staves && <StavesBody key={job.id} job={job} q={staves} score={score} onClose={onClose} />}
      {job && q && !staves && <PartsBody key={job.id} job={job} q={q as PageParts} score={score} onClose={onClose} />}
    </Dialog>
  )
}

function useSigned(path: string | null | undefined): string | null {
  const [url, setUrl] = useState<string | null>(null)
  useEffect(() => {
    if (!path) return
    let live = true
    supabase.storage.from('scores').createSignedUrl(path, 900).then(({ data }) => { if (live) setUrl(data?.signedUrl ?? null) })
    return () => { live = false }
  }, [path])
  return path ? url : null
}

/** A page image's path in reading order: the rendered PDF page, or the photograph in its committed order. */
function pagePath(s: Score | null, page: number | undefined): string | null {
  if (!s || !page) return null
  const src = s.pageSource
  if (src?.kind === 'images') {
    const i = src.order ? src.order[page - 1] : page
    return src.paths[(i ?? page) - 1] ?? null
  }
  return `${s.id}/pages/${page}.png`
}

/** The book's page count: the reading's, else the pages it was made from. */
const pagesOf = (s: Score | null) => s?.pages || s?.pageSource?.order?.length || (s?.pageSource?.kind === 'images' ? s.pageSource.paths.length : 0)

function AskHead({ where, onLater }: { where: string; onLater: () => void }) {
  return (
    <div className="ask-head">
      <span className="ask-where"><span className="card-dot is-ask is-inline" aria-hidden="true" />Needs you · {where}</span>
      <button type="button" className="r3-btn is-quiet" onClick={onLater}>Later</button>
    </div>
  )
}

/** One name per staff from a list of part names: a list one short of the staves gives a keyboard its two staves. */
function perStaff(names: string[], staves: number): { labels: string[]; matches: boolean } {
  if (names.length === staves) return { labels: names, matches: true }
  const k = names.findIndex(n => KEYBOARD.test(n))
  if (names.length === staves - 1 && k >= 0) return { labels: [...names.slice(0, k + 1), names[k], ...names.slice(k + 1)], matches: true }
  // Two pianos over four staves: each name takes an equal run, a keyboard's two staves each.
  if (names.length && staves % names.length === 0) {
    const per = staves / names.length
    return { labels: names.flatMap(n => Array<string>(per).fill(n)), matches: per === 2 && names.every(n => KEYBOARD.test(n)) }
  }
  const labels = Array.from({ length: staves }, (_, i) => names[i] ?? (names.length ? names[names.length - 1] : '?'))
  return { labels, matches: false }
}

function PartsBody({ job, q, score, onClose }: { job: AskJob; q: PageParts; score: Score | null; onClose: () => void }) {
  const { session } = useAuth()
  const { world, canEditBook } = useStore()
  const known = q.known_parts ?? []
  const found = q.spark_parts ?? []
  const stavesPer = q.system_staves?.length ? Math.max(...q.system_staves) : Math.max(known.length, found.length)
  const [pick, setPick] = useState<'known' | 'found' | 'other'>(known.length ? 'known' : found.length ? 'found' : 'other')
  const [typed, setTyped] = useState('')
  const [systems, setSystems] = useState<GeoSystem[] | null>(null)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)
  const url = useSigned(pagePath(score, q.page))

  // The page's systems as the reader found them (fractions of the page), so the labels sit on the real staves.
  useEffect(() => {
    if (!q.interpretation_id || !q.page) return
    let live = true
    supabase.from('interpretations').select('pages:params->state->pages').eq('id', q.interpretation_id).maybeSingle().then(({ data }) => {
      const geo = (data?.pages as Record<string, { geometry?: { systems?: GeoSystem[] } }> | null)?.[String(q.page)]?.geometry
      if (live) setSystems(geo?.systems ?? null)
    })
    return () => { live = false }
  }, [q.interpretation_id, q.page])

  const names = pick === 'known' ? known : pick === 'found' ? found : typed.split(/[,;\n]/).map(x => x.trim()).filter(Boolean)
  const knownFit = perStaff(known, stavesPer)
  const foundFit = perStaff(found, stavesPer)
  const fit = perStaff(names, stavesPer)
  const canAnswer = !!score && canEditBook(score)

  const send = async () => {
    if (!session || !names.length) return
    setBusy(true); setMsg(null)
    try {
      // The names as a list: one may hold a comma ("Timpani in Es, B"), and a joined string split it into two parts.
      await answerJob(job.id, { answer: names }, session.access_token)
      world.reload()
      onClose()
    } catch (e) {
      setMsg(apiFailure(e, 'Answering the librarian'))
    } finally {
      setBusy(false)
    }
  }

  const n = q.system_staves?.length ?? 0
  const layout = n ? `the page has ${n === 1 ? 'one system' : `${n} systems`} of ${stavesPer} staves` : ''
  const story = known.length && found.length && known.length !== found.length ? `Earlier pages had ${plural(known.length, 'part')}; the librarian read ${found.length} here.` : !known.length ? 'The librarian could not name the parts here.' : 'The librarian was unsure of the names here.'
  const where = [`page ${q.page}${pagesOf(score) ? ` of ${pagesOf(score)}` : ''}`, score?.answered ? `${score.answered} answered` : null].filter(Boolean).join(' · ')
  const mine = !score || score.ensembleId === MY_LIBRARY

  return (
    <>
      <AskHead where={where} onLater={onClose} />
      <div className="ask-title">
        <h2>Which parts are on page {q.page}?</h2>
        <span>{[score?.title, layout].filter(Boolean).join(' · ')}. {story}</span>
      </div>
      <div className="ask-body is-parts">
        <div className="ask-thumb" aria-label={`Page ${q.page}, with the chosen parts labelled`}>
          <div className="ask-thumb-page">
          {url ? <img src={url} alt="" draggable={false} decoding="async" onError={e => { e.currentTarget.style.visibility = 'hidden' }} /> : <span className="ask-thumb-wait">Page {q.page}</span>}
          {systems?.map(sys => {
            const lab = perStaff(names, sys.staves).labels
            const h = (sys.box.y1 - sys.box.y0) / sys.staves
            return lab.map((l, i) => (
              <span key={`${sys.index}-${i}`} className={`ask-staff-label ${fit.matches ? '' : 'is-doubt'}`} style={{ top: `${(sys.box.y0 + h * (i + 0.5)) * 100}%`, right: `${(1 - sys.box.x0) * 100}%` }}>{l}</span>
            ))
          })}
          <span className="ask-thumb-cap">page {q.page}</span>
          </div>
        </div>
        <div className="ask-choices" role="radiogroup" aria-label="Parts on this page">
          {known.length > 0 && (
            <button type="button" role="radio" aria-checked={pick === 'known'} className="ask-choice" onClick={() => setPick('known')}>
              <span className="ask-choice-h"><b>Same as earlier pages</b><span className={`ask-chip ${knownFit.matches ? 'is-ok' : 'is-doubt'}`}>{knownFit.matches ? `${stavesPer} staves · matches` : `${plural(known.length, 'name')} · ${stavesPer} staves`}</span></span>
              <span className="ask-choice-names">{known.join(' · ')}</span>
            </button>
          )}
          {found.length > 0 && found.join('|') !== known.join('|') && (
            <button type="button" role="radio" aria-checked={pick === 'found'} className="ask-choice" onClick={() => setPick('found')}>
              <span className="ask-choice-h"><b>What the librarian read here</b><span className={`ask-chip ${foundFit.matches ? 'is-ok' : 'is-doubt'}`}>{foundFit.matches ? `${stavesPer} staves · matches` : `${plural(found.length, 'name')} · ${stavesPer} staves`}</span></span>
              <span className="ask-choice-names is-muted">{found.join(' · ')}</span>
            </button>
          )}
          <div role="radio" aria-checked={pick === 'other'} tabIndex={-1} className="ask-choice is-other" onClick={() => setPick('other')}>
            <span className="ask-choice-h"><b>Something else</b>{pick !== 'other' && <span className="ask-choice-hint">name each staff, top to bottom</span>}</span>
            {pick === 'other' && (
              <input className="dt-input is-serif" autoFocus value={typed} onChange={e => setTyped(e.target.value)} placeholder="Violin, Viola, Cello, Piano" aria-label="Parts on this page, top to bottom" autoCapitalize="words" autoComplete="off" />
            )}
          </div>
          <span className="ask-note">The labels on the page follow your choice. Reading continues from page {q.page} once you confirm.</span>
          {msg && <p className="r3-msg" role="alert">{msg}</p>}
        </div>
      </div>
      <div className="ask-foot">
        <span className="ask-who">{mine ? 'Only you see this. The book is yours.' : 'Only the admins see this.'}</span>
        <button type="button" className="r3-btn is-solid is-big" disabled={!names.length || busy || !canAnswer} onClick={() => void send()}>
          {busy ? 'Sending' : 'Confirm and keep reading'} <IChev />
        </button>
      </div>
    </>
  )
}

function StavesBody({ job, q, score, onClose }: { job: AskJob; q: ChooseStaves; score: Score | null; onClose: () => void }) {
  const { session } = useAuth()
  const { world } = useStore()
  const boxes: StaffBox[] = useMemo(() => [...(q.staff_boxes ?? [])].sort((x, y) => x.index - y.index), [q])
  const proposed = useMemo(() => (Array.isArray(q.proposal) ? q.proposal : Array.isArray(q.last_attempt) ? q.last_attempt : []).map(Number), [q])
  const [sel, setSel] = useState<Set<number>>(() => new Set(proposed))
  const [size, setSize] = useState<{ w: number; h: number } | null>(null)
  const [busy, setBusy] = useState<'staves' | 'absent' | null>(null)
  const [msg, setMsg] = useState<string | null>(null)
  // The plain page when the question says what size its staff boxes are measured in; else the librarian's working
  // overlay (an older question), whose own pixels the boxes are in.
  const plain = !!q.page_key && Array.isArray(q.image_px) && q.image_px.length === 2
  const url = useSigned(plain ? q.page_key : q.image_key ?? pagePath(score, q.page))
  const frame = plain ? { w: q.image_px![0], h: q.image_px![1] } : size
  const instrument = q.instrument || 'the part'

  const send = async (answer: number[] | 'absent') => {
    if (!session) return
    setBusy(answer === 'absent' ? 'absent' : 'staves'); setMsg(null)
    try {
      await answerJob(job.id, { staves: answer }, session.access_token)
      world.reload()
      onClose()
    } catch (e) {
      setMsg(apiFailure(e, 'Answering the librarian'))
    } finally {
      setBusy(null)
    }
  }
  const toggle = (k: number) => setSel(s => { const n = new Set(s); if (n.has(k)) n.delete(k); else n.add(k); return n })
  const band = boxes.length && frame ? { top: boxes[0].y_top, bottom: boxes[boxes.length - 1].y_bottom } : null
  const pitch = boxes.length > 1 ? (boxes[boxes.length - 1].y_top - boxes[0].y_top) / (boxes.length - 1) : 60
  const chosen = [...sel].sort((a, b) => a - b)
  const line = ordinal(q.system - 1)

  return (
    <>
      <AskHead where={`splitting by instrument · page ${q.page}${pagesOf(score) ? ` of ${pagesOf(score)}` : ''}, ${line} line`} onLater={onClose} />
      <div className="ask-title">
        <h2>Which staves are the <i>{instrument}</i>’s on this line?</h2>
        <span>Tap them.{proposed.length ? ' The librarian’s guess is already chosen.' : ''}</span>
      </div>
      <div className="ask-body is-staves">
        <div className="ask-page" aria-label={`Page ${q.page}, the ${line} line lit`}>
          <div className="ask-page-in" style={size ? { width: `min(100%, calc(56vh * ${(size.w / size.h).toFixed(4)}))` } : undefined}>
          {url ? <img src={url} alt="" draggable={false} decoding="async" onLoad={e => setSize({ w: e.currentTarget.naturalWidth, h: e.currentTarget.naturalHeight })} /> : <span className="ask-thumb-wait">Loading page {q.page}</span>}
          {band && frame && size && (
            <>
              <span className="ask-dim" style={{ top: 0, height: `${Math.max(0, (band.top - pitch * 0.6) / frame.h) * 100}%` }} aria-hidden="true" />
              <span className="ask-dim" style={{ top: `${Math.min(1, (band.bottom + pitch * 0.6) / frame.h) * 100}%`, bottom: 0 }} aria-hidden="true" />
            </>
          )}
          {frame && size && boxes.map((b, i) => {
            const above = i > 0 ? (b.y_top + boxes[i - 1].y_bottom) / 2 : b.y_top - 10
            const below = i < boxes.length - 1 ? (b.y_bottom + boxes[i + 1].y_top) / 2 : b.y_bottom + 10
            const on = sel.has(b.index)
            return (
              <button key={b.index} type="button" aria-pressed={on} aria-label={`The ${ordinal(i)} staff of the line${on ? `, the ${instrument}` : ''}`} className="ask-staff"
                style={{ left: `${(b.x0 / frame.w) * 100}%`, width: `${((b.x1 - b.x0) / frame.w) * 100}%`, top: `${(above / frame.h) * 100}%`, height: `${((below - above) / frame.h) * 100}%` }}
                onClick={() => toggle(b.index)}>
                {on && <span className="ask-staff-tag">{instrument}</span>}
              </button>
            )
          })}
          </div>
          <span className="ask-thumb-cap">page {q.page} · {line} line</span>
        </div>
        <span className="ask-note">Tap a staff again to let it go. A piano or a harp takes two staves.</span>
        {q.feedback && (
          <details className="ask-why">
            <summary>Why am I asked?</summary>
            <p>The librarian tried this line three times and could not settle it. What it last noted, for whoever wants the detail:</p>
            <p className="ask-why-raw">{q.feedback}</p>
          </details>
        )}
        {msg && <p className="r3-msg" role="alert">{msg}</p>}
      </div>
      <div className="ask-foot">
        <button type="button" className="r3-btn is-line is-big" disabled={!!busy} onClick={() => void send('absent')}>{busy === 'absent' ? 'Sending' : `The ${instrument} isn’t on this line`}</button>
        <button type="button" className="r3-btn is-solid is-big" disabled={!chosen.length || !!busy} onClick={() => void send(chosen)}>
          {busy === 'staves' ? 'Sending' : chosen.length > 1 ? 'Use these staves' : 'Use this staff'} <ICheck />
        </button>
      </div>
    </>
  )
}
