/** Feature 011, kind `choose_staves`: the librarian could not decide which staves of one system are the part's.
 *  The admin sees the numbered overlay of that system, taps the staves (a run of adjacent ones), or says the part
 *  is not printed there. The answer resumes the job without a recheck. */
import { useEffect, useMemo, useState } from 'react'
import { answerJob, apiFailure } from '../lib/api'
import { supabase } from '../lib/supabase'
import { useAuth } from './auth'
import type { ChooseStaves, PartJob, StaffBox } from './data'
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

export function StaffQuestion({ job, open, onClose }: { job: PartJob | null; open: boolean; onClose: () => void }) {
  const q = job?.questionPayload ?? null
  const instrument = q?.instrument ?? 'the part'
  return (
    <Sheet open={open && !!job && !!q} onClose={onClose} label="The librarian's question" portal>
      <SheetHead title={q ? `Page ${q.page}, system ${q.system}` : 'Question'} sub={`Which staves are ${instrument}'s?`} onClose={onClose} />
      {job && q && <QuestionBody job={job} q={q} onClose={onClose} />}
    </Sheet>
  )
}

function QuestionBody({ job, q, onClose }: { job: PartJob; q: ChooseStaves; onClose: () => void }) {
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
          ) : <span>{q.image_key ? 'Loading the page' : 'No overlay for this page'}</span>}
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
          <ICheck size={18} />{busy === 'staves' ? 'Sending' : sel ? `${stavesWord(sel)} are ${instrument}'s` : 'Tap the staves'}
        </button>
      </div>
    </>
  )
}
