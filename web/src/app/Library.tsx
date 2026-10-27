import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router'
import { members, partsById, practice, scores, type Part, type Score } from '../mock'
import { Screen, useViewport } from './layout'
import { DisplayButton } from './Display'
import { barRange, contexts, difficultyWord, fmtDateTime, partShort, useStore } from './store'
import { ICamera, IClose, IRepeat, IWarning } from './icons'

const roleWord = { owner: 'your own library', admin: 'you are the admin', player: 'you play' } as const

export default function Library() {
  const vp = useViewport()
  const navigate = useNavigate()
  const { context, setContext, scan, practiceUI } = useStore()
  const [selected, setSelected] = useState<string | null>(null)
  const docked = vp.w >= 1100

  // The Fauré moves to processing once its page order is committed on the scan screen.
  const live = useMemo(() => scores.map(s => (s.id === 's-faure' && scan.committed ? { ...s, status: 'processing' as const, progress: 0 } : s)), [scan.committed])
  const mine = live.filter(s => s.ensembleId === context.ensemble.id)
  const folders = [...new Set(mine.map(s => s.folder))].map(name => ({ name, scores: mine.filter(s => s.folder === name) }))
  // A selection from another library simply finds nothing here; no reset effect needed.
  const open = selected ? mine.find(s => s.id === selected) ?? null : null

  const { persona, membership } = context
  const partName = persona.partId ? partsById[persona.partId]?.name : persona.instrument
  const practiceHere = practice.scoreId && live.find(s => s.id === practice.scoreId)?.ensembleId === context.ensemble.id ? live.find(s => s.id === practice.scoreId)! : null

  const header = (
    <div className="ph">
      <div className="ph-title">
        <h1>{context.ensemble.name}</h1>
        <p>
          {mine.length} {mine.length === 1 ? 'score' : 'scores'} · {membership.role === 'player' ? `you play ${partName}` : roleWord[membership.role]}
        </p>
      </div>
      <div className="grow" />
      <DisplayButton />
    </div>
  )

  const dock = (
    <div className="lib-dock">
      {practiceHere && (
        <button type="button" className="dbtn" onClick={() => navigate('/practice')}>
          <IRepeat size={20} />
          <span>Resume · {partsById[practice.partId]?.name}{practiceUI.loop ? `, ${barRange(practiceUI.loop.from, practiceUI.loop.to)}` : ''}</span>
        </button>
      )}
      <div className="grow" />
      <Link to="/scan" className="dbtn is-primary"><ICamera size={20} /><span>Scan pages</span></Link>
    </div>
  )

  return (
    <Screen header={header} dock={dock} className="is-library">
      <div className={`lib-work ${open ? 'has-side' : ''} ${open && docked ? 'side-docked' : ''}`}>
        <div className="lib">
          <div className="lib-inner">
            <div className="ctx">
              {vp.narrow ? (
                <select className="ctx-select" value={context.ensemble.id} onChange={e => setContext(e.target.value)} aria-label="Library">
                  {contexts.map(c => <option key={c.ensemble.id} value={c.ensemble.id}>{c.ensemble.name}</option>)}
                </select>
              ) : (
                <div className="seg" role="radiogroup" aria-label="Library">
                  {contexts.map(c => (
                    <button key={c.ensemble.id} type="button" role="radio" aria-checked={context.ensemble.id === c.ensemble.id} onClick={() => setContext(c.ensemble.id)}>
                      {c.ensemble.name}
                    </button>
                  ))}
                </div>
              )}
            </div>

            {folders.length === 0 && (
              <div className="empty is-inline">
                <p>Nothing here yet. Scan pages, or import a MusicXML file, and the score appears as a cover.</p>
                <Link className="btn btn-line" to="/scan"><ICamera size={18} />Scan pages</Link>
              </div>
            )}

            {folders.map(f => (
              <section key={f.name} className="folder" aria-label={f.name}>
                <div className="folder-h">
                  <h2>{f.name}</h2>
                  <span>{f.scores.length}</span>
                </div>
                <ul className="covers">
                  {f.scores.map(s => (
                    <li key={s.id}>
                      <Cover score={s} selected={selected === s.id} onSelect={() => setSelected(v => (v === s.id ? null : s.id))} />
                    </li>
                  ))}
                </ul>
              </section>
            ))}
          </div>
        </div>
        {open && <InfoBox score={open} onClose={() => setSelected(null)} />}
      </div>
    </Screen>
  )
}

function StatusBadge({ score: s, partName }: { score: Score; partName?: string }) {
  if (s.status === 'processing') {
    const pct = Math.round((s.progress ?? 0) * 100)
    return (
      <span className="badge is-processing">
        <span className="meter" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100} aria-label="Reading"><span style={{ width: `${pct}%` }} /></span>
        <span>{pct ? `${pct}% read` : 'Queued'}</span>
      </span>
    )
  }
  if (s.status === 'failed') return <span className="badge is-failed"><IWarning size={14} /><span>Needs pages</span></span>
  if (s.status === 'ordering') return <span className="badge">Order pages</span>
  if (s.status === 'uploaded') return <span className="badge">Uploaded</span>
  if (partName) return <span className="badge is-mine">{partName}</span>
  return null
}

function Cover({ score: s, selected, onSelect }: { score: Score; selected: boolean; onSelect: () => void }) {
  const { context } = useStore()
  const myPart = context.membership.role === 'player' && context.persona.partId && s.partIds.includes(context.persona.partId)
    ? partShort[partsById[context.persona.partId].name] ?? partsById[context.persona.partId].name
    : undefined
  return (
    <button
      type="button" className={`cover ${s.status === 'ready' ? '' : 'is-unavailable'}`} aria-pressed={selected} onClick={onSelect}
      aria-label={`${s.title}, ${s.composer}${s.status === 'ready' ? '' : `, ${s.status}`}`}
    >
      <span className="cover-composer">{s.composer}</span>
      <span className="cover-title">{s.title}</span>
      <span className="cover-work">{s.work}</span>
      <span className="cover-foot"><StatusBadge score={s} partName={myPart} /></span>
    </button>
  )
}

const holderOf = (p: Part) => members.find(m => m.partId === p.id)

function InfoBox({ score: s, onClose }: { score: Score; onClose: () => void }) {
  const { context, practiceUI } = useStore()
  const { membership, persona } = context
  const parts = s.partIds.map(id => partsById[id])
  const myPart = persona.partId ? parts.find(p => p.id === persona.partId) : undefined
  const ready = s.status === 'ready'
  const flags = s.flags
  const flagText = flags && (flags.pagesUnreadable || flags.barsDoubtful)
    ? [flags.pagesUnreadable ? `${flags.pagesUnreadable} ${flags.pagesUnreadable === 1 ? 'page' : 'pages'} unreadable` : null,
       flags.barsDoubtful ? `${flags.barsDoubtful} ${flags.barsDoubtful === 1 ? 'bar' : 'bars'} doubtful` : null].filter(Boolean).join(', ')
    : null
  const isPractice = practice.scoreId === s.id

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <aside className="side info" aria-label={`${s.title}, information`}>
      <div className="side-head">
        <h2 className="sr-only">Information</h2>
        <span />
        <button type="button" className="btn-icon" onClick={onClose} aria-label="Close"><IClose size={20} /></button>
      </div>
      <div className="side-scroll">
        <div>
          <h2 className="info-title">{s.title}</h2>
          <p className="info-sub">{s.composer} · {s.work}</p>
        </div>

        {s.status === 'failed' && (
          <div className="info-state is-failed">
            <span className="reason">Reading stopped</span>
            <span>{s.failureReason}</span>
            {flagText && <span className="flags">{flagText}</span>}
          </div>
        )}
        {s.status === 'processing' && (
          <div className="info-state">
            <StatusBadge score={s} />
            <span>{s.pages} pages · parts appear when reading finishes</span>
          </div>
        )}
        {s.status === 'ordering' && (
          <div className="info-state">
            <span>{s.pages} pages waiting for their order. Nothing is read until you commit it.</span>
          </div>
        )}
        {ready && (
          <dl className="facts">
            <dt>Key</dt><dd>{s.key}</dd>
            <dt>Meter</dt><dd>{s.meter}</dd>
            <dt>Length</dt><dd><span className="num">{s.bars}</span> bars · {Math.round(s.durationSec / 60)} min · <span className="num">{s.tempoBpm}</span> bpm</dd>
            <dt>Pages</dt><dd>{s.pages}</dd>
            <dt>Read</dt><dd>{flagText ?? (flags ? 'Every page and bar resolved' : 'Imported from MusicXML')}</dd>
            <dt>Changed</dt><dd>{fmtDateTime(s.updatedAt)}</dd>
          </dl>
        )}

        {parts.length > 0 && (
          <div>
            <h3>{myPart ? 'Your part, and the others' : 'Parts'}</h3>
            <ul className="parts-list">
              {[...parts].sort((a, b) => (a.id === myPart?.id ? -1 : b.id === myPart?.id ? 1 : 0)).map(p => {
                const who = holderOf(p)
                const isMine = p.id === myPart?.id
                return (
                  <li key={p.id}>
                    <span className="pname">{p.name}{isMine && <span className="badge is-mine">You</span>}</span>
                    <span className={`pwho ${who || isMine ? '' : 'is-unassigned'}`}>{isMine ? persona.name : who ? who.name : 'Unassigned'}</span>
                    <span className="pdiff">{difficultyWord[p.difficulty]}</span>
                  </li>
                )
              })}
            </ul>
          </div>
        )}

        {ready && s.brief && membership.role !== 'player' && (
          <div>
            <h3>Brief</h3>
            <blockquote className="info-brief">{s.brief}</blockquote>
          </div>
        )}

        <div className="info-actions">
          {ready && <Link to={`/score/${s.id}`} className="btn btn-solid">Open score</Link>}
          {ready && isPractice && (
            <Link to="/practice" className="btn btn-line">
              Practise {partsById[practice.partId]?.name}{practiceUI.loop ? `, loop ${barRange(practiceUI.loop.from, practiceUI.loop.to)}` : ''}
            </Link>
          )}
          {s.status === 'ordering' && <Link to="/scan" className="btn btn-solid">Order pages</Link>}
          {s.status === 'failed' && <Link to="/scan" className="btn btn-solid"><ICamera size={18} />Retake pages</Link>}
        </div>

        {s.status === 'processing' && <p className="info-log">The librarian is reading the pages. It will say what it did, and ask if a page cannot be placed.</p>}
      </div>
    </aside>
  )
}
