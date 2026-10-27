import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode } from 'react'
import { ensembles, fmtDuration, membersById, partsById, practice, scoresById, type TroubleSpot } from '../shared'
import {
  Book,
  PartTabs,
  boxStyle,
  pct,
  segments,
  useEngraving,
  usePager,
  type BookLayout,
  type TabSpec,
} from './engraving'
import {
  IconClose,
  IconHistory,
  IconListen,
  IconLoop,
  IconMetronome,
  IconMinus,
  IconPause,
  IconPlay,
  IconPlus,
  KindIcon,
} from './icons'
import { KIND_LABEL, appliesTo, barRange, beatsPerBar, fmtDate, pinText } from './model'
import { useX4 } from './state'

type Accomp = 'solo' | 'with' | 'click'

const TEMPO_STEP = 2

export function Practice() {
  const { notes } = useX4()
  const score = scoresById[practice.scoreId]
  const part = partsById[practice.partId]
  const ens = ensembles.find(e => e.id === score.ensembleId)
  const partIndex = score.partIds.indexOf(part.id)
  const visible = useMemo(() => [Math.max(0, partIndex)], [partIndex])
  const { eng, offstage } = useEngraving(part.fixture, visible)
  const [layout, setLayout] = useState<BookLayout>({ perView: 2, bookW: 0 })
  const onLayout = useCallback(
    (l: BookLayout) => setLayout(prev => (prev.perView === l.perView && prev.bookW === l.bookW ? prev : l)),
    [],
  )
  const pager = usePager(eng.pages.length, layout.perView)

  const target = score.tempoBpm
  const beats = beatsPerBar(score.meter)
  const [tempo, setTempo] = useState(practice.tempoBpm)
  const [metronome, setMetronome] = useState(practice.metronome)
  const [accomp, setAccomp] = useState<Accomp>(practice.otherParts === 'off' ? 'solo' : 'with')
  const [listening, setListening] = useState(practice.listening)
  const [loop, setLoop] = useState(practice.loop ?? { barFrom: practice.bar, barTo: practice.bar })
  const [loopOn, setLoopOn] = useState(practice.loop !== null)
  const [pos, setPos] = useState({ bar: practice.bar, beat: practice.beat })
  const [playing, setPlaying] = useState(false)
  const [sheet, setSheet] = useState<string | null>(null)

  const pctOfTarget = Math.round((tempo / target) * 100)
  const scoreNotes = notes.filter(n => n.scoreId === score.id)
  const cuts = useMemo(() => notes.filter(n => n.scoreId === score.id && n.kind === 'cut'), [notes, score.id])
  const partNotes = scoreNotes.filter(n => n.kind !== 'cut' && appliesTo(n, part.id))
  const withLabel = ens?.kind === 'chamber' && score.partIds.length === 4 ? 'With quartet' : 'With orchestra'

  // Open on the loop.
  const placed = useRef(false)
  useEffect(() => {
    if (placed.current || eng.status !== 'ready') return
    const b = eng.bars.get(loop.barFrom)
    if (b) {
      pager.goToPage(b.page)
      placed.current = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [eng.version, eng.status])

  // Mock transport: the beat advances at the set tempo, wraps the loop and skips cuts.
  useEffect(() => {
    if (!playing) return
    const t = window.setInterval(() => {
      setPos(p => {
        let beat = p.beat + 1
        let bar = p.bar
        if (beat > beats) {
          beat = 1
          bar += 1
          if (loopOn && bar > loop.barTo) bar = loop.barFrom
          const cut = cuts.find(c => bar >= c.barFrom && bar <= c.barTo)
          if (cut) bar = cut.barTo + 1
          if (bar > score.bars) bar = loopOn ? loop.barFrom : 1
        }
        return { bar, beat }
      })
    }, 60000 / tempo)
    return () => window.clearInterval(t)
  }, [playing, tempo, beats, loopOn, loop, cuts, score.bars])

  // Turn the page when the playing bar leaves it.
  useEffect(() => {
    if (!playing) return
    const b = eng.bars.get(pos.bar)
    if (b && (b.page < pager.first || b.page > pager.last)) pager.goToPage(b.page)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pos.bar, playing])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null
      if (t?.closest('input, textarea, select, [role="tab"]')) return
      if (e.key === ' ' && !(t instanceof HTMLButtonElement)) {
        e.preventDefault()
        setPlaying(v => !v)
      } else if (e.key === 'ArrowRight' || e.key === 'PageDown') {
        e.preventDefault()
        pager.next()
      } else if (e.key === 'ArrowLeft' || e.key === 'PageUp') {
        e.preventDefault()
        pager.prev()
      } else if (e.key === '+' || e.key === '=') {
        setTempo(v => Math.min(target + 20, v + TEMPO_STEP))
      } else if (e.key === '-') {
        setTempo(v => Math.max(40, v - TEMPO_STEP))
      } else if (e.key === 'Escape') {
        setSheet(null)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [pager, target])

  const pickAccomp = (k: string) => {
    const a = k as Accomp
    setAccomp(a)
    if (a === 'click') setMetronome(true)
  }

  const loopSpot = (s: TroubleSpot) => {
    setLoop({ barFrom: s.barFrom, barTo: s.barTo })
    setLoopOn(true)
    setPos({ bar: s.barFrom, beat: 1 })
    const b = eng.bars.get(s.barFrom)
    if (b) pager.goToPage(b.page)
  }

  const nudgeLoop = (end: 'from' | 'to', d: number) => {
    setLoop(l => {
      if (end === 'from') return { ...l, barFrom: Math.min(l.barTo, Math.max(1, l.barFrom + d)) }
      return { ...l, barTo: Math.max(l.barFrom, Math.min(score.bars, l.barTo + d)) }
    })
    setLoopOn(true)
  }

  const overlay = (page: number) => {
    const out: ReactNode[] = []
    for (const c of cuts) {
      for (const s of segments(eng.bars, c.barFrom, c.barTo)) {
        if (s.page !== page) continue
        const isStart = s.fromBar === c.barFrom
        out.push(
          <div
            key={`c-${c.id}-${s.fromBar}`}
            className="x4-o-cut"
            data-start={isStart || undefined}
            data-end={s.toBar === c.barTo || undefined}
            style={boxStyle(s, 0.012)}
          >
            {isStart ? <span className="x4-o-cut-label">Cut {barRange(c.barFrom, c.barTo)}</span> : null}
          </div>,
        )
      }
    }
    for (const t of practice.troubleSpots) {
      for (const s of segments(eng.bars, t.barFrom, t.barTo)) {
        if (s.page !== page) continue
        out.push(
          <div
            key={`t-${t.barFrom}-${s.fromBar}`}
            className="x4-o-trouble"
            title={t.note}
            style={{
              left: pct(s.x),
              top: pct(s.y + s.h + 0.012),
              width: pct(s.w),
              '--sev': t.severity,
            } as CSSProperties}
          />,
        )
      }
    }
    if (loopOn) {
      for (const s of segments(eng.bars, loop.barFrom, loop.barTo)) {
        if (s.page !== page) continue
        out.push(
          <div
            key={`l-${s.fromBar}`}
            className="x4-o-loop"
            data-start={s.fromBar === loop.barFrom || undefined}
            data-end={s.toBar === loop.barTo || undefined}
            style={boxStyle(s, 0.016)}
          />,
        )
      }
    }
    const cur = eng.bars.get(pos.bar)
    if (cur && cur.page === page) out.push(<div key="cur" className="x4-o-now" style={boxStyle(cur, 0.016)} />)
    const stack = new Map<number, number>()
    for (const n of partNotes) {
      const b = eng.bars.get(n.barFrom)
      if (!b || b.page !== page) continue
      const k = stack.get(n.barFrom) ?? 0
      stack.set(n.barFrom, k + 1)
      out.push(
        <button
          key={`n-${n.id}`}
          type="button"
          className="x4-pin"
          data-kind={n.kind}
          style={{ left: pct(b.x), top: pct(b.y - 0.02), '--k': k } as CSSProperties}
          onClick={e => {
            e.stopPropagation()
            setSheet(n.id)
          }}
          aria-label={`${KIND_LABEL[n.kind]}, bars ${barRange(n.barFrom, n.barTo)}`}
        >
          <KindIcon kind={n.kind} size={14} />
          <span>{pinText(n)}</span>
        </button>,
      )
    }
    return out
  }

  const tabs: TabSpec[] = [
    { key: 'solo', label: 'Solo', meta: 'Only you', state: 'raised' },
    { key: 'with', label: withLabel, meta: 'The other parts play', state: 'raised' },
    { key: 'click', label: 'Click', meta: 'Metronome only', state: 'raised' },
  ]

  const spotsFit = layout.bookW >= 760
  const spots = (
    <div className="x4-spots" role="group" aria-label="Trouble spots">
      {practice.troubleSpots.map(s => {
        const active = loopOn && loop.barFrom === s.barFrom && loop.barTo === s.barTo
        return (
          <button
            key={s.barFrom}
            type="button"
            className="x4-spot"
            aria-pressed={active}
            onClick={() => loopSpot(s)}
            title={s.note}
            aria-label={`Trouble spot, bars ${barRange(s.barFrom, s.barTo)}: ${s.note}. Loop it.`}
          >
            <span className="x4-spot-bars">{barRange(s.barFrom, s.barTo)}</span>
            <Severity v={s.severity} />
          </button>
        )
      })}
    </div>
  )

  const noteOpen = sheet && sheet !== 'history' ? scoreNotes.find(n => n.id === sheet) : undefined
  const listenWord = listening === 'off' ? 'Off' : listening === 'lost' ? 'Lost' : 'Following'

  return (
    <main className="x4-work">
      {offstage}
      <div className="x4-bar2">
        <div className="x4-bar2-title">
          <h1>{part.name}</h1>
          <p>
            {score.title} · {score.work.split(', ').slice(1).join(', ') || score.work}
          </p>
        </div>
        <p className="x4-listening" data-state={listening} aria-live="polite">
          <IconListen />
          Listening · {listenWord.toLowerCase()}
        </p>
        <button
          type="button"
          className="x4-btn"
          data-variant="quiet"
          aria-expanded={sheet === 'history'}
          onClick={() => setSheet(s => (s === 'history' ? null : 'history'))}
        >
          <IconHistory />
          History<span className="x4-count">{practice.history.length}</span>
        </button>
      </div>

      <div className="x4-stagewrap">
        <Book
          eng={eng}
          first={pager.first}
          tabs={<PartTabs tabs={tabs} active={accomp} onPick={pickAccomp} label="What plays with you" />}
          aside={spotsFit ? spots : undefined}
          overlay={overlay}
          onLayout={onLayout}
          onPrev={pager.prev}
          onNext={pager.next}
          canPrev={pager.canPrev}
          canNext={pager.canNext}
          waitLabel={`Engraving the ${part.name} part`}
        />
        {sheet === 'history' ? (
          <section className="x4-sheet" aria-label="Practice history">
            <header className="x4-sheet-head">
              <h2>
                History · {part.name}
              </h2>
              <button type="button" className="x4-iconbtn" aria-label="Close" onClick={() => setSheet(null)}>
                <IconClose />
              </button>
            </header>
            <div className="x4-sheet-body">
              <History target={target} />
            </div>
          </section>
        ) : noteOpen ? (
          <section className="x4-sheet" aria-label="Marking">
            <header className="x4-sheet-head">
              <h2>
                {KIND_LABEL[noteOpen.kind]} · bars {barRange(noteOpen.barFrom, noteOpen.barTo)}
              </h2>
              <button type="button" className="x4-iconbtn" aria-label="Close" onClick={() => setSheet(null)}>
                <IconClose />
              </button>
            </header>
            <div className="x4-sheet-body">
              {noteOpen.transcript ? (
                <blockquote className="x4-transcript">“{noteOpen.transcript}”</blockquote>
              ) : (
                <p className="x4-note-text">{noteOpen.text ?? KIND_LABEL[noteOpen.kind]}</p>
              )}
              <p className="x4-note-by">
                {membersById[noteOpen.authorId]?.name ?? 'Unknown member'} · {fmtDate(noteOpen.createdAt, true)}
                {noteOpen.durationSec ? ` · ${fmtDuration(noteOpen.durationSec)}` : ''}
              </p>
            </div>
          </section>
        ) : null}
      </div>

      <div className="x4-controls" role="group" aria-label="Practice controls">
        {!spotsFit ? <div className="x4-ctl x4-ctl-spots">{spots}</div> : null}

        <div className="x4-ctl x4-ctl-loop">
          <button
            type="button"
            className="x4-toggle"
            aria-pressed={loopOn}
            onClick={() => setLoopOn(v => !v)}
            aria-label={loopOn ? 'Loop on' : 'Loop off'}
          >
            <IconLoop />
            <span>Loop</span>
          </button>
          <div className="x4-loop-ends" data-off={!loopOn || undefined}>
            <LoopEnd value={loop.barFrom} label="Loop start" onDown={() => nudgeLoop('from', -1)} onUp={() => nudgeLoop('from', 1)} />
            <span className="x4-loop-dash" aria-hidden="true">
              –
            </span>
            <LoopEnd value={loop.barTo} label="Loop end" onDown={() => nudgeLoop('to', -1)} onUp={() => nudgeLoop('to', 1)} />
          </div>
        </div>

        <div className="x4-ctl x4-ctl-tempo">
          <button
            type="button"
            className="x4-step"
            onClick={() => setTempo(v => Math.max(40, v - TEMPO_STEP))}
            aria-label={`Slower by ${TEMPO_STEP}`}
          >
            <IconMinus size={24} />
          </button>
          <div className="x4-tempo" aria-live="polite">
            <span className="x4-big">{tempo}</span>
            <span className="x4-tempo-sub">
              of {target} · {pctOfTarget}%
            </span>
          </div>
          <button
            type="button"
            className="x4-step"
            onClick={() => setTempo(v => Math.min(target + 20, v + TEMPO_STEP))}
            aria-label={`Faster by ${TEMPO_STEP}`}
          >
            <IconPlus size={24} />
          </button>
        </div>

        <div className="x4-ctl x4-ctl-toggles">
          <button
            type="button"
            className="x4-toggle"
            aria-pressed={metronome}
            onClick={() => setMetronome(v => !v)}
            disabled={accomp === 'click'}
          >
            <IconMetronome />
            <span>Click</span>
          </button>
          <button
            type="button"
            className="x4-toggle"
            aria-pressed={listening !== 'off'}
            data-lost={listening === 'lost' || undefined}
            onClick={() => setListening(v => (v === 'off' ? 'following' : 'off'))}
          >
            <IconListen />
            <span>{listenWord}</span>
          </button>
        </div>

        <div className="x4-ctl x4-ctl-play">
          <div className="x4-now" aria-live="off">
            <span className="x4-now-label">Bar</span>
            <span className="x4-big">{pos.bar}</span>
            <span className="x4-beats" aria-label={`Beat ${pos.beat} of ${beats}`}>
              {Array.from({ length: beats }, (_, i) => (
                <i key={i} data-on={i + 1 === pos.beat || undefined} />
              ))}
            </span>
          </div>
          <button
            type="button"
            className="x4-play"
            onClick={() => setPlaying(v => !v)}
            aria-label={playing ? 'Pause' : 'Play'}
            aria-pressed={playing}
          >
            {playing ? <IconPause size={34} /> : <IconPlay size={34} />}
          </button>
        </div>
      </div>
    </main>
  )
}

function LoopEnd({ value, label, onDown, onUp }: { value: number; label: string; onDown: () => void; onUp: () => void }) {
  return (
    <span className="x4-loop-end">
      <button type="button" className="x4-step" data-size="sm" onClick={onDown} aria-label={`${label} earlier`}>
        <IconMinus />
      </button>
      <span className="x4-loop-num" aria-label={`${label}, bar ${value}`}>
        {value}
      </span>
      <button type="button" className="x4-step" data-size="sm" onClick={onUp} aria-label={`${label} later`}>
        <IconPlus />
      </button>
    </span>
  )
}

function Severity({ v }: { v: number }) {
  const on = Math.round(v * 5)
  return (
    <span className="x4-sev" aria-hidden="true">
      {[1, 2, 3, 4, 5].map(i => (
        <i key={i} data-on={i <= on || undefined} />
      ))}
    </span>
  )
}

function History({ target }: { target: number }) {
  const h = practice.history
  const first = h[0]
  const last = h[h.length - 1]
  return (
    <div className="x4-history">
      {first && last ? (
        <p className="x4-history-lede">
          <span className="x4-big">{first.reachedBpm}</span>
          <span className="x4-history-arrow" aria-hidden="true">
            to
          </span>
          <span className="x4-big">{last.reachedBpm}</span>
          <span className="x4-history-sub">
            bpm over {h.length} sessions, toward {target}. Today’s loop is {barRange(practice.loop?.barFrom ?? 0, practice.loop?.barTo ?? 0)}.
          </span>
        </p>
      ) : null}
      <div className="x4-trouble-list">
        {practice.troubleSpots.map(s => (
          <p key={s.barFrom} className="x4-trouble-item">
            <span className="x4-trouble-bars">{barRange(s.barFrom, s.barTo)}</span>
            <Severity v={s.severity} />
            <span>{s.note}</span>
          </p>
        ))}
      </div>
      <table className="x4-table">
        <thead>
          <tr>
            <th scope="col">Date</th>
            <th scope="col">Length</th>
            <th scope="col">Tempo reached</th>
            <th scope="col">Accuracy</th>
            <th scope="col">Loops</th>
          </tr>
        </thead>
        <tbody>
          {h.map(s => (
            <tr key={s.id}>
              <td>{fmtDate(s.date)}</td>
              <td>{s.durationMin} min</td>
              <td>
                <span className="x4-ladder" aria-hidden="true">
                  <i style={{ width: `${(s.reachedBpm / s.targetBpm) * 100}%` }} />
                </span>
                {s.reachedBpm} of {s.targetBpm}
              </td>
              <td>{Math.round(s.accuracy * 100)}%</td>
              <td>{s.loops.map(l => `${barRange(l.barFrom, l.barTo)} × ${l.reps}`).join(', ')}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
