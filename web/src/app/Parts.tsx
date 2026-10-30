/** Split by instrument (feature 008) on the iPad. A PDF book: choose instruments, start the cut, watch it, answer its
 *  question (011), open the finished strip (010); the librarian runs `part_cut` on Muse Spark. A digital book: choose
 *  among its parts, and the API writes a MusicXML file holding only them (no model call); the split opens in the
 *  reader with only those instruments and exports as MusicXML. This file only asks for the work and shows what it says. */
import { useState, type FormEvent } from 'react'
import { Link } from 'react-router'
import type { Score } from '../mock'
import { ApiError, apiFailure, cutParts } from '../lib/api'
import { useAuth } from './auth'
import { exportName, exportStored, partLabel, type PartJob, type PartStrip } from './data'
import { fmtDateTime, useStore } from './store'
import { Sheet } from './Sheet'
import { StaffQuestion } from './StaffQuestion'
import { ICheck, IChevronRight, IClose, IExport, IParts, IWarning } from './icons'
import { Rope, type RopeState } from './Rope'
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

/** The instrument picker. A PDF book offers the instruments its first page names, in score order, or names typed by
 *  hand when that has not been read; a digital book offers its own parts. A split is one instrument, or several that
 *  read together (CK's contract). */
export function PartPicker({ score, open, onClose }: { score: Score; open: boolean; onClose: () => void }) {
  return (
    <Sheet open={open} onClose={onClose} label="Split by instrument" portal>
      <SheetHead title="Split by instrument" sub={score.title} onClose={onClose} />
      <PickerForm score={score} onClose={onClose} />
    </Sheet>
  )
}

function PickerForm({ score, onClose }: { score: Score; onClose: () => void }) {
  const { world, partsById } = useStore()
  const { session } = useAuth()
  const digital = score.book === 'digital'
  const header = digital ? score.partIds.map(id => partsById[id]?.name).filter((n): n is string => !!n) : world.headers[score.id] ?? []
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
  // Keep score order for the payload: the handler takes the chosen staves as one block, top to bottom.
  const ordered = names.filter(n => chosen.includes(n))

  const start = async () => {
    if (!session || !ordered.length) return
    setBusy(true); setMsg(null)
    try {
      await cutParts(score.id, { instruments: ordered }, session.access_token)
      world.reload()
      onClose()
    } catch (e) {
      // The same split is already under way (409 names it): show that one instead of a second.
      if (e instanceof ApiError && e.status === 409 && e.live) { world.reload(); onClose(); return }
      setMsg(apiFailure(e, 'Splitting by instrument'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <div className="sheet-body">
        <p className="pick-sub">
          {digital
            ? 'Choose one instrument, or several to read together. The split keeps only them, in score order, ready to read or export.'
            : header.length
              ? 'The first page names these instruments, top to bottom. Choose one, or several that read together on one strip.'
              : 'The instrument names on the first page have not been read yet. Type the instrument as the score prints it, for example "Violino I" or "Soprano".'}
        </p>
        {names.length > 0 && (
          <div className="pick" role="group" aria-label="Instruments">
            {names.map((n, i) => (
              <button key={n} type="button" role="checkbox" aria-checked={chosen.includes(n)} aria-label={n} className="pick-row" onClick={() => toggle(n)}>
                <span className="pick-mark"><ICheck size={15} strokeWidth={2.5} /></span>
                <span className="pick-name">{n}</span>
                {i < header.length && <span className="pick-pos num">{i + 1}</span>}
              </button>
            ))}
          </div>
        )}
        {!digital && (
          <form className="pick-add" onSubmit={addTyped}>
            <label className="field">
              <span>{header.length ? 'Another instrument, as printed' : 'Instrument, as printed'}</span>
              <input value={typed} onChange={e => setTyped(e.target.value)} placeholder="e.g. Violino I" autoCapitalize="words" autoComplete="off" />
            </label>
            <button type="submit" className="btn btn-line" disabled={!typed.trim()}>Add</button>
          </form>
        )}
      </div>
      <div className="sheet-foot">
        {msg && <p className="sheet-msg" role="alert">{msg}</p>}
        <button type="button" className="btn btn-line" onClick={onClose}>Cancel</button>
        <button type="button" className="btn btn-solid" disabled={!ordered.length || busy} onClick={start}>
          <IParts size={18} />{busy ? 'Starting' : ordered.length ? `Split out ${partLabel(ordered.length > 3 ? [`${ordered.length} instruments`] : ordered)}` : 'Choose instruments'}
        </button>
      </div>
    </>
  )
}

const jobRope: Partial<Record<PartJob['status'], RopeState>> = { queued: 'working', running: 'working', needs_review: 'asking', failed: 'failed' }
const stateWord: Record<PartJob['status'], string> = { queued: 'Queued', running: 'Working', needs_review: 'Waiting for you', done: 'Done', failed: 'Stopped' }

/** A finished split. PDF: its strip of systems. Digital: read it with only these instruments, or export it. */
function SplitRow({ score, split, twins }: { score: Score; split: PartStrip; twins: boolean }) {
  const [exporting, setExporting] = useState(false)
  const name = (
    <span className="pt-name">
      {split.label}
      {twins && <span className="pt-when"> · {fmtDateTime(split.createdAt)}</span>}
    </span>
  )
  if (split.kind === 'images') {
    return (
      <li className="pt-row">
        {name}
        <Link className="pt-open" to={`/score/${score.id}?view=strips&strip=${split.id}`}>
          <span className="num">{split.paths.length}</span> {split.paths.length === 1 ? 'system' : 'systems'} <IChevronRight size={18} />
        </Link>
      </li>
    )
  }
  const exportSplit = async () => {
    if (!split.path) return
    setExporting(true)
    try {
      await exportStored(split.path, exportName(score.title, split.path, undefined, split.label))
    } catch (e) {
      window.alert((e as Error).message)
    } finally {
      setExporting(false)
    }
  }
  return (
    <li className="pt-row is-digital">
      {name}
      <span className="pt-acts">
        {split.path && (
          <button type="button" className="btn-icon" disabled={exporting} onClick={exportSplit} aria-label={`Export ${split.label} as MusicXML`}>
            <IExport size={20} />
          </button>
        )}
        <Link className="pt-open" to={`/score/${score.id}?split=${split.id}`}>Read <IChevronRight size={18} /></Link>
      </span>
    </li>
  )
}

/** What the information box shows under "Split by instrument": finished splits, running jobs, the question, the action. */
export function PartsPanel({ score }: { score: Score }) {
  const { contextFor, jobsFor, stripsFor } = useStore()
  const strips = stripsFor(score.id)
  const jobs = jobsFor(score.id).filter(j => j.status !== 'done' || !strips.some(s => s.id === j.sourceId))
  const canEdit = (contextFor(score.ensembleId)?.membership.role ?? 'player') !== 'player'
  const digital = score.book === 'digital'
  const [picking, setPicking] = useState(false)
  const [answering, setAnswering] = useState<string | null>(null)
  const asked = jobs.find(j => j.id === answering && j.status === 'needs_review') ?? null
  // A digital book can be split once it is read and has more than one instrument; a PDF book's cut works from the pages.
  const canSplit = canEdit && (!digital || (score.status === 'ready' && score.partIds.length > 1))
  // One split at a time (CK, 2026-10-31): while one works or waits on a question, it stands in place of the action.
  const working = jobs.find(j => j.status === 'queued' || j.status === 'running' || j.status === 'needs_review')
  if (!canSplit && !strips.length && !jobs.length) return null

  return (
    <div>
      <h3>Split by instrument</h3>
      {strips.length + jobs.length === 0 && (
        <p className="info-log">
          {digital
            ? 'Nothing split out yet. A split keeps only the instruments you choose, to read on its own or export.'
            : 'Nothing split out yet. A split lifts the chosen staves out of every page and stacks them as one strip.'}
        </p>
      )}
      {(strips.length > 0 || jobs.length > 0) && (
        <ul className="pt-list">
          {strips.map(s => <SplitRow key={s.id} score={score} split={s} twins={strips.filter(x => x.label === s.label).length > 1} />)}
          {jobs.map(j => (
            <li key={j.id} className={`pt-row ${jobRope[j.status] ? 'has-rope' : ''}`} aria-live={j.status === 'running' ? 'polite' : undefined}>
              {jobRope[j.status] && <Rope state={jobRope[j.status]!} />}
              <span className="pt-name">{partLabel(j.instruments)}</span>
              <span className="pt-state">
                {j.status === 'failed' && <IWarning size={15} />}
                {j.status === 'queued' && j.resumed ? 'Resuming' : stateWord[j.status]}
              </span>
              {j.status === 'running' && j.phase && (
                <span className="pt-note num">Page {j.phase.page} of {j.phase.pages} · {j.phase.systemsCut} {j.phase.systemsCut === 1 ? 'system' : 'systems'} cut</span>
              )}
              {j.status === 'running' && (j.log.length > 0 || j.note) && (
                <ul className="pt-log" aria-label="What the librarian did">
                  {(j.log.length ? j.log.slice(-3) : [j.note!]).map((line, i) => <li key={i}>{line}</li>)}
                </ul>
              )}
              {j.status === 'queued' && <span className="pt-note">{j.resumed ? 'Your answer is in. Picking up from it.' : `Starting${j.pages ? `, ${j.pages.length} pages` : ''}.`}</span>}
              {j.status === 'failed' && <span className="pt-fail">{j.error ?? 'The split stopped.'}</span>}
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
      {canSplit && (
        <div className="pt-actions">
          <button type="button" className="btn btn-line" disabled={!!working} onClick={() => setPicking(true)}><IParts size={18} />Split by instrument</button>
          {working && <span className="pt-note">One split at a time. {partLabel(working.instruments)} {working.status === 'needs_review' ? 'waits for your answer' : 'is under way'}.</span>}
        </div>
      )}
      {canEdit && <PartPicker score={score} open={picking} onClose={() => setPicking(false)} />}
      {canEdit && <StaffQuestion job={asked} open={!!asked} onClose={() => setAnswering(null)} />}
    </div>
  )
}
