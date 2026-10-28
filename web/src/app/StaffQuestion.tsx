/** The librarian's confirmation screen (011): one sheet for every parked question, answered through
 *  `POST /jobs/{id}/answer`. Kind `choose_staves` (a split, 008): the librarian could not decide which staves of one
 *  system are the part's; the admin sees the numbered overlay of that system, taps the staves (a run of adjacent ones),
 *  or says the part is not printed there. The answer resumes the job without a recheck. The reader's page question
 *  (`process_pages`, 004): which parts are on page N, top to bottom; the admin picks one of the readings offered or
 *  types the names, and the reading resumes from that page. */
import { useEffect, useMemo, useState, type FormEvent } from 'react'
import { answerJob, apiFailure } from '../lib/api'
import { supabase } from '../lib/supabase'
import { useAuth } from './auth'
import type { AskJob, ChooseStaves, StaffBox } from './data'
import { Sheet } from './Sheet'
import { SheetHead } from './Parts'
import { useStore } from './store'
import { ICheck } from './icons'

type Range = [number, number] | null

/** A tap keeps the selection one run of adjacent staves: extend at an end, shrink from an end, or start over. */
function tapStaff(sel: Range, k: number): Range {
  if (!sel) return [k, k]
  const [a, b] = sel
  if (k === a - 1) return [k, b]
  if (k === b + 1) return [a, k]
  if (a === b && k === a) return null
  if (k === a) return [a + 1, b]
  if (k === b) return [a, b - 1]
  return [k, k]
}

const stavesWord = (r: Range) => (!r ? '' : r[0] === r[1] ? `staff ${r[0]}` : `staves ${r[0]}–${r[1]}`)
const rangeOf = (xs: unknown): Range => (Array.isArray(xs) && xs.length ? [Math.min(...xs), Math.max(...xs)] : null)

const isStaves = (q: unknown): q is ChooseStaves => !!q && typeof q === 'object' && (q as ChooseStaves).kind === 'choose_staves'

/** The reader's question on a page (`process_pages`): the parts it read, the parts it knows so far, the answer's shape. */
interface PageParts { page?: number; spark_parts?: string[]; known_parts?: string[]; options?: string[][]; answer_format?: string }

export function StaffQuestion({ job, open, onClose }: { job: AskJob | null; open: boolean; onClose: () => void }) {
  const q = job?.questionPayload ?? null
  const staves = isStaves(q) ? q : null
  const page = !staves && q ? (q as PageParts) : null
  const title = staves ? `Page ${staves.page}, system ${staves.system}` : page?.page ? `Page ${page.page}` : 'The librarian has a question'
  const sub = staves ? `Which staves are ${staves.instrument ?? 'the part'}'s?` : 'Which parts are on this page, top to bottom?'
  return (
    <Sheet open={open && !!job && !!q} onClose={onClose} label="The librarian's question" portal>
      <SheetHead title={title} sub={sub} onClose={onClose} />
      {job && staves && <QuestionBody job={job} q={staves} onClose={onClose} />}
      {job && page && <PageQuestionBody job={job} q={page} onClose={onClose} />}
    </Sheet>
  )
}

/** Which parts are on page N: one of the readings the librarian offers, or the names typed top to bottom. */
function PageQuestionBody({ job, q, onClose }: { job: AskJob; q: PageParts; onClose: () => void }) {
  const { session } = useAuth()
  const { world } = useStore()
  const options = useMemo(() => {
    const seen = new Set<string>()
    return [...(q.options ?? []), q.spark_parts ?? [], q.known_parts ?? []]
      .filter(o => Array.isArray(o) && o.length)
      .filter(o => { const k = o.join('|'); if (seen.has(k)) return false; seen.add(k); return true })
  }, [q])
  const [typed, setTyped] = useState(() => (options[0] ?? []).join(', '))
  const [url, setUrl] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)
  const names = typed.split(/[,;\n]/).map(x => x.trim()).filter(Boolean)

  // The page as the librarian saw it, when its rendered page is in the bucket.
  useEffect(() => {
    if (!q.page) return
    let live = true
    supabase.storage.from('scores').createSignedUrl(`${job.scoreId}/pages/${q.page}.png`, 900).then(({ data }) => { if (live) setUrl(data?.signedUrl ?? null) })
    return () => { live = false }
  }, [job.scoreId, q.page])

  const send = async (e?: FormEvent) => {
    e?.preventDefault()
    if (!session || !names.length) return
    setBusy(true); setMsg(null)
    try {
      await answerJob(job.id, { answer: names.join(', ') }, session.access_token)
      world.reload()
      onClose()
    } catch (err) {
      setMsg(apiFailure(err, 'Answering the librarian'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <form className="sheet-body" onSubmit={send}>
        {job.question && <p className="sq-ctx">{job.question}</p>}
        {url && (
          <div className="sq-page">
            <img src={url} alt={`Page ${q.page}`} draggable={false} decoding="async" onError={() => setUrl(null)} />
          </div>
        )}
        {options.length > 0 && (
          <div className="sq-rows" role="radiogroup" aria-label="What the librarian read">
            {options.map(o => {
              const v = o.join(', ')
              return (
                <button key={v} type="button" role="radio" aria-checked={typed === v} className="sq-row" onClick={() => setTyped(v)}>
                  <span className="pick-mark"><ICheck size={15} strokeWidth={2.5} /></span>
                  <span>{v}</span>
                </button>
              )
            })}
          </div>
        )}
        <label className="field">
          <span>Parts on this page, top to bottom</span>
          <input value={typed} onChange={e => setTyped(e.target.value)} placeholder={q.answer_format ? 'e.g. Piano I, Piano II' : 'Part names, separated by commas'} autoCapitalize="words" autoComplete="off" />
        </label>
      </form>
      <div className="sheet-foot">
        {msg && <p className="sheet-msg" role="alert">{msg}</p>}
        <button type="button" className="btn btn-line" onClick={onClose}>Later</button>
        <button type="button" className="btn btn-solid" disabled={!names.length || busy} onClick={() => send()}>
          <ICheck size={18} />{busy ? 'Sending' : 'These are the parts'}
        </button>
      </div>
    </>
  )
}

function QuestionBody({ job, q, onClose }: { job: AskJob; q: ChooseStaves; onClose: () => void }) {
  const { session } = useAuth()
  const { world } = useStore()
  const boxes: StaffBox[] = useMemo(() => [...(q.staff_boxes ?? [])].sort((x, y) => x.index - y.index), [q])
  const proposed = useMemo(() => rangeOf(q.proposal) ?? rangeOf(q.last_attempt), [q])
  const [sel, setSel] = useState<Range>(proposed)
  const [url, setUrl] = useState<string | null>(null)
  const [size, setSize] = useState<{ w: number; h: number } | null>(null)
  const [busy, setBusy] = useState<'staves' | 'absent' | null>(null)
  const [msg, setMsg] = useState<string | null>(null)
  const instrument = q.instrument || 'the part'

  // The overlay lives in the private `scores` bucket: a short signed URL, made when the sheet opens.
  useEffect(() => {
    if (!q.image_key) return
    let live = true
    supabase.storage.from('scores').createSignedUrl(q.image_key, 900).then(({ data }) => { if (live) setUrl(data?.signedUrl ?? null) })
    return () => { live = false }
  }, [q.image_key])

  // Show only the system in question: from a little above its first staff to a little below its last.
  const crop = useMemo(() => {
    if (!boxes.length || !size) return null
    const pitch = boxes.length > 1 ? (boxes[boxes.length - 1].y_top - boxes[0].y_top) / (boxes.length - 1) : 80
    const top = Math.max(0, boxes[0].y_top - pitch * 0.7)
    const bottom = Math.min(size.h, boxes[boxes.length - 1].y_bottom + pitch * 0.7)
    return { top, h: bottom - top }
  }, [boxes, size])

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

  const inSel = (k: number) => !!sel && k >= sel[0] && k <= sel[1]
  const chosen = sel ? Array.from({ length: sel[1] - sel[0] + 1 }, (_, i) => sel[0] + i) : []

  return (
    <>
      <div className="sheet-body">
        {q.feedback && <p className="sq-why">{q.feedback}</p>}
        <p className="sq-ctx">
          {proposed ? <>The librarian's guess, {stavesWord(proposed)}, is marked. </> : null}
          Tap a staff to choose it; a part's staves are next to each other.
        </p>

        {/* Height from the width (padding-bottom), so the crop keeps its shape as a flex child in the scrolling body. */}
        <div className={`sq-image ${url && size && crop ? 'is-ready' : 'is-loading'}`} style={crop && size ? { paddingBottom: `${(crop.h / size.w) * 100}%` } : undefined}>
          {url ? (
            <img src={url} alt="" draggable={false} decoding="async"
              onLoad={e => setSize({ w: e.currentTarget.naturalWidth, h: e.currentTarget.naturalHeight })}
              style={crop ? { top: `${(-crop.top / crop.h) * 100}%` } : { position: 'static', visibility: 'hidden' }} />
          ) : <span>{q.image_key ? 'Loading the page' : 'No picture of this page to choose from'}</span>}
          {crop && size && boxes.map((b, i) => {
            // Each box's hit area reaches halfway to its neighbours, so a finger lands on a staff, not between two.
            const above = i > 0 ? (b.y_top + boxes[i - 1].y_bottom) / 2 : b.y_top - 12
            const below = i < boxes.length - 1 ? (b.y_bottom + boxes[i + 1].y_top) / 2 : b.y_bottom + 12
            return (
              <button key={b.index} type="button" role="checkbox" aria-checked={inSel(b.index)} aria-label={`Staff ${b.index}`} className="sq-box"
                style={{ left: `${(b.x0 / size.w) * 100}%`, width: `${((b.x1 - b.x0) / size.w) * 100}%`, top: `${((above - crop.top) / crop.h) * 100}%`, height: `${((below - above) / crop.h) * 100}%` }}
                onClick={() => setSel(s => tapStaff(s, b.index))} />
            )
          })}
        </div>

        <div className="sq-rows" role="group" aria-label="Staves of this system">
          {boxes.map(b => (
            <button key={b.index} type="button" role="checkbox" aria-checked={inSel(b.index)} aria-label={`Staff ${b.index}`} className="sq-row" onClick={() => setSel(s => tapStaff(s, b.index))}>
              <span className="pick-mark"><ICheck size={15} strokeWidth={2.5} /></span>
              <span className="num">{b.index}</span>
              <span>Staff {b.index}</span>
              {proposed && b.index >= proposed[0] && b.index <= proposed[1] && <span className="sq-tag">librarian's guess</span>}
            </button>
          ))}
        </div>
        {sel && <p className="sq-pick">Chosen: {stavesWord(sel)}.</p>}
      </div>
      <div className="sheet-foot">
        {msg && <p className="sheet-msg" role="alert">{msg}</p>}
        <button type="button" className="btn btn-line" disabled={!!busy} onClick={() => send('absent')}>
          {busy === 'absent' ? 'Sending' : `${instrument} is not printed here`}
        </button>
        <button type="button" className="btn btn-solid" disabled={!sel || !!busy} onClick={() => send(chosen)}>
          <ICheck size={18} />{busy === 'staves' ? 'Sending' : sel ? `${stavesWord(sel).replace(/^s/, 'S')} ${sel[0] === sel[1] ? 'is' : 'are'} ${instrument}` : 'Tap the staves'}
        </button>
      </div>
    </>
  )
}
