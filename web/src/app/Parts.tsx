/** Feature 008 on the iPad: choose the parts to cut out of a scanned score, start the job, watch it, answer its
 *  question (011), open the finished strip (010). The librarian runs `part_cut` on Muse Spark; this file only
 *  asks for it and shows what it says. */
import { useState, type FormEvent } from 'react'
import { Link } from 'react-router'
import type { Score } from '../mock'
import { apiFailure, cutParts } from '../lib/api'
import { useAuth } from './auth'
import { partLabel, type PartJob } from './data'
import { fmtDateTime, useStore } from './store'
import { Sheet } from './Sheet'
import { StaffQuestion } from './StaffQuestion'
import { ICheck, IChevronRight, IClose, IScissors, IWarning } from './icons'
import './parts.css'

/** The head of a librarian sheet: title, a line under it, the close button. Children carry `.sheet-body` and `.sheet-foot`. */
export function SheetHead({ title, sub, onClose }: { title: string; sub?: string; onClose: () => void }) {
  return (
    <div className="side-head">
      <div className="sheet-title">
        <h2>{title}</h2>
        {sub && <p>{sub}</p>}
      </div>
      <button type="button" className="btn-icon" onClick={onClose} aria-label="Close"><IClose size={20} /></button>
    </div>
  )
}

/** The part picker: the instruments the header names, in score order, or names typed by hand when there is no header.
 *  An export is a selection of parts (CK's contract): one, or several that read together. */
export function PartPicker({ score, open, onClose }: { score: Score; open: boolean; onClose: () => void }) {
  return (
    <Sheet open={open} onClose={onClose} label="Cut parts" portal>
      <SheetHead title="Cut parts" sub={score.title} onClose={onClose} />
      <PickerForm score={score} onClose={onClose} />
    </Sheet>
  )
}

function PickerForm({ score, onClose }: { score: Score; onClose: () => void }) {
  const { world } = useStore()
  const { session } = useAuth()
  const header = world.headers[score.id] ?? []
  const [chosen, setChosen] = useState<string[]>([])
  const [extra, setExtra] = useState<string[]>([])
  const [typed, setTyped] = useState('')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)

  const names = [...header, ...extra.filter(x => !header.includes(x))]
  const toggle = (n: string) => setChosen(xs => (xs.includes(n) ? xs.filter(x => x !== n) : [...xs, n]))
  const addTyped = (e: FormEvent) => {
    e.preventDefault()
    const n = typed.trim()
    if (!n) return
    if (!names.includes(n)) setExtra(xs => [...xs, n])
    if (!chosen.includes(n)) setChosen(xs => [...xs, n])
    setTyped('')
  }
  // Keep score order for the payload: the handler cuts the chosen staves as one block, top to bottom.
  const ordered = names.filter(n => chosen.includes(n))

  const start = async () => {
    if (!session || !ordered.length) return
    setBusy(true); setMsg(null)
    try {
      await cutParts(score.id, { instruments: ordered }, session.access_token)
      world.reload()
      onClose()
    } catch (e) {
      setMsg(apiFailure(e, 'Cutting parts'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <div className="sheet-body">
        <p className="pick-sub">
          {header.length
            ? 'The header names these parts, top to bottom. Choose one, or several that read together on one strip.'
            : 'No header has been read for this score yet. Name the part as the score prints it, for example "Violino I" or "Soprano".'}
        </p>
        {names.length > 0 && (
          <div className="pick" role="group" aria-label="Parts">
            {names.map((n, i) => (
              <button key={n} type="button" role="checkbox" aria-checked={chosen.includes(n)} aria-label={n} className="pick-row" onClick={() => toggle(n)}>
                <span className="pick-mark"><ICheck size={15} strokeWidth={2.5} /></span>
                <span className="pick-name">{n}</span>
                {i < header.length && <span className="pick-pos num">{i + 1}</span>}
              </button>
            ))}
          </div>
        )}
        <form className="pick-add" onSubmit={addTyped}>
          <label className="field">
            <span>{header.length ? 'Another part, as printed' : 'Part name, as printed'}</span>
            <input value={typed} onChange={e => setTyped(e.target.value)} placeholder="e.g. Violino I" autoCapitalize="words" autoComplete="off" />
          </label>
          <button type="submit" className="btn btn-line" disabled={!typed.trim()}>Add</button>
        </form>
      </div>
      <div className="sheet-foot">
        {msg && <p className="sheet-msg" role="alert">{msg}</p>}
        <button type="button" className="btn btn-line" onClick={onClose}>Cancel</button>
        <button type="button" className="btn btn-solid" disabled={!ordered.length || busy} onClick={start}>
          <IScissors size={18} />{busy ? 'Starting' : ordered.length <= 1 ? `Cut ${ordered[0] ?? 'parts'}` : `Cut ${ordered.length} parts together`}
        </button>
      </div>
    </>
  )
}

const stateWord: Record<PartJob['status'], string> = { queued: 'Queued', running: 'Cutting', needs_review: 'Needs you', done: 'Cut', failed: 'Stopped' }

/** What the information box shows under "Cut parts": finished strips, running jobs, the question, and the action. */
export function PartsPanel({ score }: { score: Score }) {
  const { contextFor, jobsFor, stripsFor } = useStore()
  const strips = stripsFor(score.id)
  const jobs = jobsFor(score.id).filter(j => j.status !== 'done' || !strips.some(s => s.id === j.sourceId))
  const canEdit = (contextFor(score.ensembleId)?.membership.role ?? 'player') !== 'player'
  const [picking, setPicking] = useState(false)
  const [answering, setAnswering] = useState<string | null>(null)
  const asked = jobs.find(j => j.id === answering && j.status === 'needs_review') ?? null
  if (!canEdit && !strips.length && !jobs.length) return null

  return (
    <div>
      <h3>Cut parts</h3>
      {strips.length + jobs.length === 0 && <p className="info-log">Nothing cut yet. A part is a selection of staves lifted out of every page and stacked as one strip.</p>}
      {(strips.length > 0 || jobs.length > 0) && (
        <ul className="pt-list">
          {strips.map(s => (
            <li key={s.id} className="pt-row">
              <span className="pt-name">
                {s.label}
                {strips.filter(x => x.label === s.label).length > 1 && <span className="pt-when"> · {fmtDateTime(s.createdAt)}</span>}
              </span>
              <Link className="pt-open" to={`/score/${score.id}?view=strips&strip=${s.id}`}>
                <span className="num">{s.paths.length}</span> systems <IChevronRight size={18} />
              </Link>
            </li>
          ))}
          {jobs.map(j => (
            <li key={j.id} className="pt-row" aria-live={j.status === 'running' ? 'polite' : undefined}>
              <span className="pt-name">{partLabel(j.instruments)}</span>
              <span className="pt-state">
                {(j.status === 'queued' || j.status === 'running') && (
                  <span className="meter" role="progressbar" aria-valuenow={Math.round(j.progress * 100)} aria-valuemin={0} aria-valuemax={100} aria-label="Cutting">
                    <span style={{ width: `${Math.round(j.progress * 100)}%` }} />
                  </span>
                )}
                {j.status === 'failed' && <IWarning size={15} />}
                {stateWord[j.status]}
              </span>
              {j.status === 'running' && (j.log.length > 0 || j.note) && (
                <ul className="pt-log" aria-label="What the librarian did">
                  {(j.log.length ? j.log.slice(-3) : [j.note!]).map((line, i) => <li key={i}>{line}</li>)}
                </ul>
              )}
              {j.status === 'queued' && <span className="pt-note">Waiting for the librarian{j.pages ? `, ${j.pages.length} pages` : ''}.</span>}
              {j.status === 'failed' && <span className="pt-fail">{j.error ?? 'The run stopped.'}</span>}
              {j.status === 'needs_review' && (
                <div className="pt-q">
                  <p>{j.question?.split('?')[0]}?</p>
                  {canEdit && <button type="button" className="btn btn-solid is-small" onClick={() => setAnswering(j.id)}>Choose the staves</button>}
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
      {canEdit && (
        <div className="pt-actions">
          <button type="button" className="btn btn-line" onClick={() => setPicking(true)}><IScissors size={18} />Cut parts</button>
        </div>
      )}
      {canEdit && <PartPicker score={score} open={picking} onClose={() => setPicking(false)} />}
      {canEdit && <StaffQuestion job={asked} open={!!asked} onClose={() => setAnswering(null)} />}
    </div>
  )
}
