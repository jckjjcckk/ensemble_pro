import { useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router'
import { ensembles, members, partsById, practice, scores, scoresById, type Role, type Score, type ScoreStatus } from '../shared'
import { Screen, useViewport } from './layout'
import { Ruler } from './Ruler'
import { BASE, TODAY, barRange, fmtDateTime, initials, kindLabel, partShort, personaFor, useStore } from './store'
import { ICamera, IWarning } from './icons'

const roles: { id: Role; label: string }[] = [
  { id: 'player', label: 'Player' },
  { id: 'leader', label: 'Leader' },
  { id: 'pianist', label: 'Pianist' },
  { id: 'librarian', label: 'Librarian' },
]

const stateOrder: ScoreStatus[] = ['ready', 'processing', 'failed', 'ordering', 'uploaded']
const stateName: Record<ScoreStatus, string> = { ready: 'Ready', processing: 'Processing', failed: 'Failed', ordering: 'Ordering', uploaded: 'Uploaded' }
const emptyCopy: Record<ScoreStatus, string> = {
  ready: 'Nothing is ready yet. Processed scores land here with their parts.',
  processing: 'Nothing is being read right now.',
  failed: 'No failures. When a page cannot be read, it shows here with the reason.',
  ordering: 'No page sets are waiting for their order.',
  uploaded: 'No uploads waiting. Photos and PDFs you add stay here until you put their pages in order.',
}

const librarianOf = (s: Score) => ensembles.find(e => e.id === s.ensembleId)?.members.find(m => m.role === 'librarian')

export default function Library() {
  const vp = useViewport()
  const navigate = useNavigate()
  const { role, setRole, persona, annotations, scan, practiceUI } = useStore()
  const [filter, setFilter] = useState<ScoreStatus | 'all'>('all')

  // The Fauré moves to processing once its page order is committed on the scan screen.
  const live = useMemo(() => scores.map(s => (s.id === 's-faure' && scan.committed ? { ...s, status: 'processing' as const, progress: 0 } : s)), [scan.committed])
  const counts = Object.fromEntries(stateOrder.map(st => [st, live.filter(s => s.status === st).length])) as Record<ScoreStatus, number>
  const shown = filter === 'all' ? live : live.filter(s => s.status === filter)

  const lastBy = (s: Score) => {
    const anns = annotations.filter(a => a.scoreId === s.id).sort((a, b) => b.createdAt.localeCompare(a.createdAt))
    if (anns[0] && anns[0].createdAt > s.updatedAt) {
      const a = anns[0]
      const who = members.find(m => m.id === a.authorId)
      return { who: who?.name ?? '', what: `${kindLabel[a.kind].toLowerCase()}, ${a.kind === 'cut' ? 'bars' : 'bar'} ${barRange(a.barFrom, a.barTo)}`, when: a.createdAt }
    }
    const ens = ensembles.find(e => e.id === s.ensembleId)
    const who = ens?.kind === 'solo' ? ens.members[0] : librarianOf(s)
    const what = s.status === 'ready' ? `processed ${s.pages} pages`
      : s.status === 'processing' ? `sent ${s.pages} pages to be read`
      : s.status === 'failed' ? `sent ${s.pages} pages to be read`
      : `uploaded ${s.pages} pages`
    return { who: who?.name ?? '', what, when: s.updatedAt }
  }

  const header = (
    <div className="ph">
      <div className="ph-title">
        <h1>Library</h1>
        <p>{scores.length} scores · {ensembles.length} libraries</p>
      </div>
    </div>
  )

  const dock = (
    <div className="lib-dock">
      <div className="grow" />
      <Link to={`${BASE}/scan`} className="dbtn is-primary"><ICamera size={20} /><span>Scan pages</span></Link>
    </div>
  )

  const beet = scoresById['s-beethoven']
  const vn1 = partsById[practice.partId]
  const lastSession = practice.history[practice.history.length - 1]
  const quartet = ensembles.find(e => e.id === beet.ensembleId)!
  const online = quartet.members.filter(m => (m.role === 'player' || m.role === 'leader') && m.online)
  const beetCuts = annotations.filter(a => a.scoreId === beet.id && a.kind === 'cut').map(a => ({ from: a.barFrom, to: a.barTo }))
  const beats = Number.parseInt(beet.meter, 10) || 4

  const strip = (() => {
    if (role === 'player' || role === 'pianist') {
      return (
        <section className="strip" aria-label="Resume practice">
          <div className="strip-text">
            <h2>Resume practice</h2>
            <p className="strip-title">{beet.title}, <span className="muted">{vn1.name}</span></p>
            <p className="strip-facts">
              <span>loop <span className="num">{practiceUI.loop ? barRange(practiceUI.loop.from, practiceUI.loop.to) : 'off'}</span></span>
              <span><span className="num">{practiceUI.tempo}</span> of <span className="num">{beet.tempoBpm}</span> bpm</span>
              <span>{lastSession.date === TODAY ? 'today' : lastSession.date}, {lastSession.durationMin} min</span>
            </p>
          </div>
          <div className="strip-ruler">
            <Ruler total={beet.bars} span={practiceUI.loop} mode="loop" heat={practice.troubleSpots} playhead={practiceUI.bar + (practiceUI.beat - 1) / beats}
              cuts={beetCuts} compact readOnly label="Where you are in the piece" />
          </div>
          <button type="button" className="btn btn-solid" onClick={() => navigate(`${BASE}/practice`)}>Resume</button>
        </section>
      )
    }
    if (role === 'leader') {
      const latest = annotations.filter(a => a.scoreId === beet.id).sort((a, b) => b.createdAt.localeCompare(a.createdAt))[0]
      return (
        <section className="strip" aria-label="Rehearsal">
          <div className="strip-text">
            <h2>Rehearsal score</h2>
            <p className="strip-title">{beet.title}</p>
            <p className="strip-facts">
              <span>{online.length} online</span>
              {[...new Set(online.map(m => m.atBar))].map(b => <span key={b}>{online.filter(m => m.atBar === b).length} at bar <span className="num">{b}</span></span>)}
              {latest && <span>last: {kindLabel[latest.kind].toLowerCase()} at <span className="num">{latest.barFrom}</span></span>}
            </p>
          </div>
          <div className="strip-ruler">
            <Ruler total={beet.bars} cuts={beetCuts} compact readOnly label="Where the group is"
              presence={online.map(m => ({ bar: m.atBar ?? 1, label: m.name }))}
              marks={annotations.filter(a => a.scoreId === beet.id && a.kind !== 'cut').map(a => ({ id: a.id, bar: a.barFrom, kind: a.kind === 'voice' ? 'voice' : 'mark', label: a.kind }))} />
          </div>
          <button type="button" className="btn btn-solid" onClick={() => navigate(`${BASE}/score/${beet.id}`)}>Open score</button>
        </section>
      )
    }
    const todo = live.filter(s => s.status === 'failed' || s.status === 'ordering' || s.status === 'processing' || s.status === 'uploaded')
    return (
      <section className="strip is-list" aria-label="Needs you">
        <div className="strip-text">
          <h2>Intake</h2>
          <p className="strip-title">{todo.length} scores between upload and ready</p>
        </div>
        <ul className="intake">
          {todo.map(s => (
            <li key={s.id}>
              <StateMark score={s} />
              <span className="intake-title">{s.title}</span>
              <span className="intake-what">
                {s.status === 'failed' ? s.failureReason
                  : s.status === 'ordering' ? `${s.pages} pages waiting for their order`
                  : s.status === 'processing' ? (s.progress ? `${Math.round(s.progress * 100)}% read` : 'Queued')
                  : 'Uploaded'}
              </span>
              {s.status === 'ordering' && <Link className="btn btn-solid is-small" to={`${BASE}/scan`}>Order pages</Link>}
            </li>
          ))}
        </ul>
      </section>
    )
  })()

  return (
    <Screen header={header} dock={dock} className="is-library">
      <div className="lib">
        <div className="lib-inner">
          <div className="lib-top">
            <div className="seg" role="radiogroup" aria-label="View as">
              {roles.map(r => (
                <button key={r.id} type="button" role="radio" aria-checked={role === r.id} onClick={() => setRole(r.id)}>{r.label}</button>
              ))}
            </div>
            <p className="persona">{persona.name}, <span className="muted">{persona.instrument}</span></p>
          </div>

          {strip}

          <div className="filters" role="radiogroup" aria-label="Filter by state">
            <button type="button" role="radio" aria-checked={filter === 'all'} onClick={() => setFilter('all')}>All <span className="num">{live.length}</span></button>
            {stateOrder.map(st => (
              <button key={st} type="button" role="radio" aria-checked={filter === st} onClick={() => setFilter(st)} className={counts[st] ? '' : 'is-zero'}>
                {stateName[st]} <span className="num">{counts[st]}</span>
              </button>
            ))}
          </div>

          {shown.length === 0 && filter !== 'all' && (
            <div className="empty is-inline">
              <p>{emptyCopy[filter]}</p>
              {filter === 'uploaded' && <Link className="btn btn-line" to={`${BASE}/scan`}><ICamera size={18} />Scan pages</Link>}
            </div>
          )}

          {ensembles.map(ens => {
            const rows = shown.filter(s => s.ensembleId === ens.id)
            if (!rows.length) return null
            return (
              <section key={ens.id} className="group" aria-label={ens.name}>
                <h2 className="group-h">{ens.name}</h2>
                {!vp.narrow && (
                  <div className="row is-head" aria-hidden="true">
                    <span>State</span><span>Score</span><span>Parts</span><span>Difficulty</span><span>Last change</span><span />
                  </div>
                )}
                <ul className="rows">
                  {rows.map(s => <Row key={s.id} score={s} role={role} last={lastBy(s)} />)}
                </ul>
              </section>
            )
          })}
        </div>
      </div>
    </Screen>
  )
}

function StateMark({ score: s }: { score: Score }) {
  if (s.status === 'processing') {
    const pct = Math.round((s.progress ?? 0) * 100)
    return (
      <span className="state is-processing">
        <span className="meter" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100} aria-label="Processing"><span style={{ width: `${pct}%` }} /></span>
        <span>{pct ? `${pct}%` : 'Queued'}</span>
      </span>
    )
  }
  if (s.status === 'failed') return <span className="state is-failed"><IWarning size={16} /><span>Failed</span></span>
  return <span className={`state is-${s.status}`}><i aria-hidden="true" /><span>{s.status === 'ordering' ? 'Ordering' : stateName[s.status]}</span></span>
}

function Row({ score: s, role, last }: { score: Score; role: Role; last: { who: string; what: string; when: string } }) {
  const persona = personaFor[role]
  const parts = s.partIds.map(id => partsById[id])
  const mine = role === 'player' ? parts.find(p => p.id === persona.partId) : undefined
  const difficulty = mine ? mine.difficulty : parts.length ? Math.max(...parts.map(p => p.difficulty)) : null
  const assignee = (partId: string) => members.find(m => m.partId === partId)
  const ready = s.status === 'ready'

  let action: { label: string; to: string } | null = null
  if (ready) {
    if ((role === 'player' || role === 'pianist') && s.id === practice.scoreId) action = { label: 'Practise', to: `${BASE}/practice` }
    else action = { label: role === 'leader' ? 'Open score' : 'Open', to: `${BASE}/score/${s.id}` }
  } else if (s.status === 'ordering') action = { label: 'Order pages', to: `${BASE}/scan` }

  return (
    <li className={`row is-${s.status}`}>
      <span className="c-state"><StateMark score={s} />{ready && s.confidence != null && <span className="conf">{Math.round(s.confidence * 100)}% read</span>}</span>
      <span className="c-title">
        {ready ? <Link to={`${BASE}/score/${s.id}`} className="title-link">{s.title}</Link> : <span className="title-link">{s.title}</span>}
        <span className="sub">{s.composer} · {s.work}</span>
        {ready && <span className="meta">{s.key} · {s.meter} · <span className="num">{s.bars}</span> bars · {Math.round(s.durationSec / 60)} min</span>}
        {s.status === 'failed' && <span className="reason">{s.failureReason}</span>}
        {s.status === 'ordering' && <span className="meta">{s.pages} pages, not yet in order</span>}
        {s.status === 'processing' && <span className="meta">{s.pages} pages · parts appear when reading finishes</span>}
      </span>
      <span className="c-parts">
        {parts.length === 0 && <span className="muted">Parts after processing</span>}
        {parts.map(p => {
          const who = assignee(p.id)
          return (
            <span key={p.id} className={`ptag ${mine && mine.id === p.id ? 'is-mine' : ''} ${mine && mine.id !== p.id ? 'is-dim' : ''}`}>
              {parts.length > 2 ? partShort[p.name] ?? p.name : p.name}
              {role === 'librarian' && who && <span className="ptag-who">{initials(who.name)}</span>}
            </span>
          )
        })}
        {mine && <span className="sr-only">Your part: {mine.name}</span>}
      </span>
      <span className="c-diff">
        {difficulty == null ? <span className="muted">–</span> : (
          <span className="diff" aria-label={`Difficulty ${difficulty} of 5`}>
            {[1, 2, 3, 4, 5].map(i => <i key={i} className={i <= difficulty ? 'is-on' : ''} />)}
            <span className="diff-n">{difficulty}</span>
          </span>
        )}
      </span>
      <span className="c-upd">
        <span>{last.who}</span>
        <span className="muted">{last.what} · {fmtDateTime(last.when)}</span>
      </span>
      <span className="c-act">
        {action && <Link to={action.to} className={`btn ${action.label === 'Practise' || action.label === 'Order pages' ? 'btn-solid' : 'btn-line'} is-small`}>{action.label}</Link>}
      </span>
    </li>
  )
}
