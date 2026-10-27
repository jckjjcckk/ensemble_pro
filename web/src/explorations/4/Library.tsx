import { Link } from 'react-router'
import {
  ensembles,
  fmtDuration,
  members,
  membersById,
  partsById,
  practice,
  scores,
  type Annotation,
  type Member,
  type Part,
  type Role,
  type Score,
  type ScoreStatus,
} from '../shared'
import { IconCamera, IconCheck, IconWarn } from './icons'
import { ENSEMBLE_KIND, KIND_LABEL, barRange, ensemblesOf, firstName, fmtDate, memberForRole } from './model'
import { useX4 } from './state'

const INTRO: Record<Role, (m: Member) => string> = {
  player: m => `${m.name}, ${m.instrument}. Your part is raised on every score; the others lie flat.`,
  leader: m => `${m.name}, conducting. Every part of every score you lead, with what the group has marked.`,
  pianist: m => `${m.name}, piano. Your own scores are raised; practice opens from any ready score.`,
  librarian: m => `${m.name}, librarian. Processing results, failures and who holds which part.`,
}

export function Library() {
  const { role, notes } = useX4()
  const me = memberForRole(role)
  const mine = new Set(ensemblesOf(me.id).map(e => e.id))
  const groups = ensembles
    .map(e => ({ e, list: scores.filter(s => s.ensembleId === e.id) }))
    .filter(g => g.list.length > 0)

  return (
    <main className="x4-main">
      <div className="x4-lib">
        <header className="x4-lib-head">
          <div>
            <h1 className="x4-h1">Library</h1>
            <p className="x4-lede">{INTRO[role](me)}</p>
          </div>
          <Link className="x4-btn" data-variant={role === 'librarian' ? 'solid' : undefined} to="/4/scan">
            <IconCamera />
            Scan a score
          </Link>
        </header>

        {groups.map(({ e, list }) => {
          const online = e.members.filter(m => m.online).length
          return (
            <section className="x4-group" key={e.id} aria-labelledby={`x4-g-${e.id}`}>
              <header className="x4-group-head">
                <h2 className="x4-group-name" id={`x4-g-${e.id}`}>
                  {e.name}
                </h2>
                <span className="x4-group-meta">
                  {ENSEMBLE_KIND[e.kind]} · {online} of {e.members.length} online
                </span>
              </header>
              <div className="x4-rows" role="list">
                {list.map(s => (
                  <ScoreRow key={s.id} s={s} role={role} me={me} responsible={mine.has(s.ensembleId)} notes={notes} />
                ))}
              </div>
            </section>
          )
        })}
      </div>
    </main>
  )
}

function ScoreRow({
  s,
  role,
  me,
  responsible,
  notes,
}: {
  s: Score
  role: Role
  me: Member
  responsible: boolean
  notes: Annotation[]
}) {
  const sParts = s.partIds.map(id => partsById[id]).filter(Boolean)
  const sNotes = notes.filter(n => n.scoreId === s.id)
  const myPart = sParts.find(p => p.id === me.partId)
  const myNotes = myPart ? sNotes.filter(n => n.partId === null || n.partId === myPart.id) : sNotes
  const latest = [...myNotes].sort((a, b) => b.createdAt.localeCompare(a.createdAt))[0]
  const ready = s.status === 'ready'
  const canPractise = ready && s.id === practice.scoreId

  return (
    <article className="x4-row" role="listitem" data-status={s.status}>
      <div className="x4-row-t">
        {ready ? (
          <Link to={`/4/score/${s.id}`} className="x4-row-title">
            {s.title}
          </Link>
        ) : (
          <span className="x4-row-title">{s.title}</span>
        )}
        <p className="x4-row-work">
          {s.composer} · {s.work}
        </p>
        {role === 'leader' && s.brief ? <p className="x4-row-brief">{s.brief}</p> : null}
        {role === 'librarian' ? (
          <p className="x4-row-facts">
            {s.pages} pages scanned{s.bars ? ` · ${s.bars} bars` : ''}
            {s.key ? ` · ${s.key}` : ''}
            {s.durationSec ? ` · ${fmtDuration(s.durationSec)}` : ''}
          </p>
        ) : null}
      </div>

      <div className="x4-row-p">
        {sParts.length ? (
          <div className="x4-minitabs" aria-label={`Parts of ${s.title}`}>
            {sParts.map(p => (
              <MiniTab key={p.id} p={p} role={role} me={me} responsible={responsible} />
            ))}
          </div>
        ) : (
          <p className="x4-row-muted">{NO_PARTS[s.status]}</p>
        )}
      </div>

      <div className="x4-row-s">
        <Status s={s} role={role} />
      </div>

      <div className="x4-row-a">
        {latest ? (
          <>
            <p className="x4-act">
              <span className="x4-act-who">{membersById[latest.authorId]?.name ?? 'Someone'}</span> added a{' '}
              {KIND_LABEL[latest.kind].toLowerCase()}, bars {barRange(latest.barFrom, latest.barTo)}
            </p>
            <p className="x4-act-when">
              {fmtDate(latest.createdAt, true)} · {myNotes.length} {myNotes.length === 1 ? 'marking' : 'markings'}
              {myPart ? ` on ${myPart.name}` : ''}
            </p>
          </>
        ) : (
          <p className="x4-act-when">Updated {fmtDate(s.updatedAt, true)}</p>
        )}
      </div>

      <div className="x4-row-x">
        {ready ? (
          <>
            <Link className="x4-btn" to={`/4/score/${s.id}`}>
              {myPart ? `Open ${myPart.name}` : 'Open'}
            </Link>
            {canPractise ? (
              <Link className="x4-btn" data-variant="quiet" to="/4/practice">
                Practise
              </Link>
            ) : null}
          </>
        ) : s.status === 'ordering' || s.status === 'uploaded' ? (
          <Link className="x4-btn" data-variant={role === 'librarian' ? 'solid' : undefined} to="/4/scan">
            Order pages
          </Link>
        ) : s.status === 'failed' ? (
          <Link className="x4-btn" to="/4/scan">
            Retake pages
          </Link>
        ) : null}
      </div>
    </article>
  )
}

const NO_PARTS: Record<ScoreStatus, string> = {
  uploaded: 'Parts are split after the pages are ordered and read.',
  ordering: 'Parts are split after the pages are ordered and read.',
  processing: 'Parts appear when reading finishes.',
  failed: 'No parts: reading stopped.',
  ready: 'No parts',
}

function MiniTab({ p, role, me, responsible }: { p: Part; role: Role; me: Member; responsible: boolean }) {
  const holder = members.find(m => m.partId === p.id)
  const own = p.id === me.partId
  const raised = role === 'player' ? own : responsible
  return (
    <span className="x4-minitab" data-state={raised ? 'raised' : 'flat'}>
      <span className="x4-minitab-name">{p.name}</span>
      <span className="x4-minitab-sub">
        <Difficulty n={p.difficulty} />
        {role === 'librarian' ? (
          <span className={holder ? undefined : 'x4-unassigned'}>{holder ? firstName(holder.name) : 'Unassigned'}</span>
        ) : own ? (
          <span>Yours</span>
        ) : null}
      </span>
    </span>
  )
}

function Difficulty({ n }: { n: number }) {
  return (
    <span className="x4-diff" role="img" aria-label={`Difficulty ${n} of 5`}>
      {[1, 2, 3, 4, 5].map(i => (
        <i key={i} data-on={i <= n || undefined} />
      ))}
    </span>
  )
}

const STAGES = ['Uploaded', 'Pages ordered', 'Read and split', 'Ready'] as const
const STAGE_OF: Record<ScoreStatus, number> = { uploaded: 0, ordering: 1, processing: 2, failed: 2, ready: 3 }

function Stages({ status }: { status: ScoreStatus }) {
  const at = STAGE_OF[status]
  const label =
    status === 'failed'
      ? `Stopped at stage 3 of 4, ${STAGES[2].toLowerCase()}`
      : `Stage ${at + 1} of 4, ${STAGES[at].toLowerCase()}`
  return (
    <span className="x4-stages" role="img" aria-label={label}>
      {STAGES.map((st, i) => (
        <i
          key={st}
          title={st}
          data-done={i < at || undefined}
          data-current={(i === at && status !== 'failed') || undefined}
          data-failed={(i === at && status === 'failed') || undefined}
        />
      ))}
    </span>
  )
}

function Status({ s, role }: { s: Score; role: Role }) {
  switch (s.status) {
    case 'ready':
      return (
        <div className="x4-status">
          <span className="x4-status-label">
            <IconCheck size={18} />
            Ready
          </span>
          <span className="x4-status-sub">
            {role === 'librarian' && s.confidence
              ? `Read with ${Math.round(s.confidence * 100)}% confidence`
              : `${s.bars} bars · ${s.meter} · ${s.tempoBpm} bpm`}
          </span>
        </div>
      )
    case 'processing': {
      const p = Math.round((s.progress ?? 0) * 100)
      return (
        <div className="x4-status">
          <span className="x4-status-label">Reading · {p}%</span>
          <span
            className="x4-progress"
            role="progressbar"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={p}
            aria-label="Reading progress"
          >
            <span style={{ width: `${p}%` }} />
          </span>
          <span className="x4-status-sub">
            <Stages status={s.status} /> {s.pages} pages
          </span>
        </div>
      )
    }
    case 'failed':
      return (
        <div className="x4-status" data-failed="">
          <span className="x4-status-label">
            <IconWarn size={18} />
            Reading failed
          </span>
          <span className="x4-status-reason">{s.failureReason}</span>
          <span className="x4-status-sub">
            <Stages status={s.status} />
          </span>
        </div>
      )
    case 'ordering':
      return (
        <div className="x4-status">
          <span className="x4-status-label">Pages not ordered</span>
          <span className="x4-status-sub">
            <Stages status={s.status} /> {s.pages} pages waiting for a committed order
          </span>
        </div>
      )
    case 'uploaded':
      return (
        <div className="x4-status">
          <span className="x4-status-label">Uploaded</span>
          <span className="x4-status-sub">
            <Stages status={s.status} /> {s.pages} pages
          </span>
        </div>
      )
  }
}
