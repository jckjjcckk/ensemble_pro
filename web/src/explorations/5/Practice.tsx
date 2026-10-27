import { useCallback, useEffect, useMemo, useRef, useState, type ButtonHTMLAttributes, type ReactNode } from 'react'
import { partsById, practice, scoresById, type TroubleSpot } from '../shared'
import { Screen, useReducedMotion, useViewport } from './layout'
import { ScoreStage } from './ScoreStage'
import { Ruler } from './Ruler'
import { spanRects, type Geo } from './geometry'
import { CutLayer, PinLayer } from './marks'
import { TODAY, barRange, fmtDay, useStore, type Span } from './store'
import { IClose, IEar, IHistory, IMetronome, IMinus, IParts, IPause, IPlay, IPlus, IRepeat } from './icons'

const score = scoresById[practice.scoreId]
const part = partsById[practice.partId]
const BEATS = Number.parseInt(score.meter, 10) || 4
const TEMPO_MIN = 30
const TEMPO_MAX = 200
const clamp = (v: number, a: number, b: number) => Math.max(a, Math.min(b, v))

function RepeatButton({ onStep, children, ...rest }: { onStep: () => void; children: ReactNode } & Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'onClick'>) {
  const delay = useRef<number | undefined>(undefined)
  const every = useRef<number | undefined>(undefined)
  const step = useRef(onStep)
  useEffect(() => { step.current = onStep })
  const stop = () => { window.clearTimeout(delay.current); window.clearInterval(every.current) }
  useEffect(() => stop, [])
  return (
    <button
      type="button" {...rest}
      onPointerDown={e => {
        if (e.button > 0) return
        step.current()
        stop()
        delay.current = window.setTimeout(() => { every.current = window.setInterval(() => step.current(), 85) }, 380)
      }}
      onPointerUp={stop} onPointerLeave={stop} onPointerCancel={stop}
      onClick={e => { if (e.detail === 0) step.current() }}
    >
      {children}
    </button>
  )
}

function Toggle({ icon, label, value, on, onClick, keys, children }: {
  icon: ReactNode; label: string; value: string; on: boolean; onClick: () => void; keys: string; children?: ReactNode
}) {
  return (
    <button type="button" className={`tog ${on ? 'is-on' : ''}`} aria-pressed={on} onClick={onClick} aria-keyshortcuts={keys} title={`${label} (${keys})`}>
      <span className="tog-icon">{icon}{children}</span>
      <span className="tog-label">{label}</span>
      <span className="tog-value">{value}</span>
    </button>
  )
}

const cuts = (anns: { kind: string; barFrom: number; barTo: number; scoreId: string }[]) =>
  anns.filter(a => a.kind === 'cut' && a.scoreId === score.id).map(a => ({ from: a.barFrom, to: a.barTo }))

export default function Practice() {
  const vp = useViewport()
  const reduced = useReducedMotion()
  const { practiceUI: p, setPracticeUI: setP, annotations } = useStore()
  const [historyOpen, setHistoryOpen] = useState(vp.w >= 1360)
  const [focus, setFocus] = useState({ bar: p.loop?.from ?? p.bar, key: 0 })
  const [lost, setLost] = useState(false)
  const [pin, setPin] = useState<string | null>(null)
  const [spot, setSpot] = useState<TroubleSpot | null>(null)
  const tall = vp.wide
  const cutSpans = useMemo(() => cuts(annotations), [annotations])
  const lostTimer = useRef<number | undefined>(undefined)

  // Playback: the beat clock. Wraps at the loop end and skips the cut.
  useEffect(() => {
    if (!p.playing) return
    const id = window.setInterval(() => setP(s => {
      let { bar, beat } = s
      beat += 1
      if (beat > BEATS) {
        beat = 1
        bar += 1
        if (s.loop && bar === s.loop.to + 1) bar = s.loop.from
        const cut = cutSpans.find(c => bar >= c.from && bar <= c.to)
        if (cut) bar = cut.to + 1
        if (bar > score.bars) return { ...s, bar: s.loop?.from ?? 1, beat: 1, playing: false }
      }
      return { ...s, bar, beat }
    }), 60000 / p.tempo)
    return () => window.clearInterval(id)
  }, [p.playing, p.tempo, setP, cutSpans])

  // After the loop start moves, bring its page into view.
  const loopFrom = p.loop?.from
  useEffect(() => {
    if (loopFrom == null) return
    const id = window.setTimeout(() => setFocus(f => (f.bar === loopFrom ? f : { bar: loopFrom, key: f.key + 1 })), 260)
    return () => window.clearTimeout(id)
  }, [loopFrom])

  const seek = useCallback((bar: number) => {
    setP(s => ({ ...s, bar, beat: 1 }))
    if (p.playing && p.listenOn) {
      setLost(true)
      window.clearTimeout(lostTimer.current)
      lostTimer.current = window.setTimeout(() => setLost(false), 1800)
    }
  }, [p.playing, p.listenOn, setP])

  const tempoBy = useCallback((d: number) => setP(s => ({ ...s, tempo: clamp(s.tempo + d, TEMPO_MIN, TEMPO_MAX) })), [setP])
  const togglePlay = useCallback(() => setP(s => ({ ...s, playing: !s.playing })), [setP])
  const setLoop = useCallback((loop: Span) => setP(s => ({ ...s, loop })), [setP])

  // One-hand keyboard: Space, minus/plus, M, O, L, H.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement
      if (e.metaKey || e.ctrlKey || e.altKey) return
      if (t.closest('input, textarea, select, [contenteditable], [role="slider"]')) return
      const k = e.key.toLowerCase()
      if (k === ' ' && !t.closest('button, a')) { e.preventDefault(); togglePlay() }
      else if (k === '-' || k === '_') tempoBy(-1)
      else if (k === '=' || k === '+') tempoBy(1)
      else if (k === 'm') setP(s => ({ ...s, metronome: !s.metronome }))
      else if (k === 'o') setP(s => ({ ...s, others: s.others === 'off' ? 'all' : 'off' }))
      else if (k === 'l') setP(s => ({ ...s, listenOn: !s.listenOn }))
      else if (k === 'h') setHistoryOpen(v => !v)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [togglePlay, tempoBy, setP])

  const pct = Math.round((p.tempo / score.tempoBpm) * 100)
  const listenWord = !p.listenOn ? 'not listening' : lost ? 'lost' : 'following'
  const listenTone = !p.listenOn ? 'off' : lost ? 'lost' : 'following'
  const playhead = p.bar + (p.beat - 1) / BEATS
  const pins = annotations.filter(a => a.scoreId === score.id && (a.partId === null || a.partId === part.id))

  const underlay = (g: Geo) => (
    <>
      {p.loop && spanRects(g, p.loop.from, p.loop.to).map(r => (
        <div key={`l${r.first}`} className="u-loop" style={{ left: r.x - 6, top: r.y - 16, width: r.w + 12, height: r.h + 32 }} />
      ))}
      {practice.troubleSpots.map(t => spanRects(g, t.barFrom, t.barTo).map(r => (
        <div key={`h${t.barFrom}-${r.first}`} className="u-heat" style={{ left: r.x, top: r.y + r.h + 9, width: r.w, opacity: 0.35 + t.severity * 0.65 }} />
      )))}
      <CutLayer geo={g} cuts={cutSpans} />
    </>
  )

  const overlay = (g: Geo) => {
    const cur = g.bars.get(p.bar)
    const loopRects = p.loop ? spanRects(g, p.loop.from, p.loop.to) : []
    const first = loopRects[0]
    const last = loopRects[loopRects.length - 1]
    return (
      <>
        {first && first.first === p.loop?.from && (
          <span className="o-bracket is-start" style={{ left: first.x - 10, top: first.y - 16, height: first.h + 32 }} aria-hidden="true" />
        )}
        {last && last.last === p.loop?.to && (
          <span className="o-bracket is-end" style={{ left: last.x + last.w + 4, top: last.y - 16, height: last.h + 32 }} aria-hidden="true" />
        )}
        {practice.troubleSpots.map(t => {
          const r = spanRects(g, t.barFrom, t.barTo)[0]
          return r && r.first === t.barFrom
            ? <span key={`n${t.barFrom}`} className="o-heat-note" style={{ left: r.x, top: r.y + r.h + 16 }}>{t.note}</span>
            : null
        })}
        {cur && (
          <span
            className={`o-cursor is-${listenTone}`} aria-hidden="true"
            style={{ left: cur.x + ((p.beat - 1) / BEATS) * cur.w, top: cur.y - 12, height: cur.h + 24, width: Math.max(4, cur.w / BEATS) }}
          />
        )}
        <PinLayer geo={g} items={pins} selected={pin} onSelect={setPin} />
      </>
    )
  }

  const header = (
    <div className="ph">
      <div className="ph-title">
        <h1>{score.title}</h1>
        <p>{score.composer.split(' ').slice(-1)[0]} · {score.work}</p>
      </div>
      <span className="part-tag">{part.name}</span>
      <div className="grow" />
      <button type="button" className="btn btn-quiet" aria-pressed={historyOpen} onClick={() => setHistoryOpen(v => !v)} aria-keyshortcuts="H">
        <IHistory size={20} /><span>History</span>
      </button>
    </div>
  )

  const ruler = (
    <div className="ruler-wrap">
      <Ruler
        total={score.bars} span={p.loop} mode="loop" onSpan={setLoop} spanLabel="Loop"
        heat={practice.troubleSpots} onHeat={t => setSpot(s => (s === t ? null : t))}
        cuts={cutSpans} playhead={playhead} playTone={listenTone} onSeek={seek} compact={!tall}
        label={`Bar ruler, bars 1 to ${score.bars}. Drag the bracket ends to set the loop.`}
      />
      {spot && (
        <div className="spot-card" role="dialog" aria-label={`Trouble spot, bars ${barRange(spot.barFrom, spot.barTo)}`}>
          <span className="spot-heat" style={{ opacity: 0.35 + spot.severity * 0.65 }} aria-hidden="true" />
          <div>
            <p className="spot-bars num">bars {barRange(spot.barFrom, spot.barTo)}</p>
            <p className="spot-note">{spot.note}</p>
          </div>
          <button type="button" className="dbtn" onClick={() => { setLoop({ from: spot.barFrom, to: spot.barTo }); setSpot(null) }}>
            <IRepeat size={18} /><span>Loop these bars</span>
          </button>
          <button type="button" className="dbtn is-icon" onClick={() => setSpot(null)} aria-label="Close"><IClose size={18} /></button>
        </div>
      )}
    </div>
  )

  const beatDots = (
    <span className="beats" aria-label={`Beat ${p.beat} of ${BEATS}`}>
      {Array.from({ length: BEATS }, (_, i) => (
        <span key={i} className={`beat ${i + 1 === p.beat ? 'is-on' : ''}`}>
          {i + 1 === p.beat && p.playing && p.metronome && !reduced && <span key={`${p.bar}-${p.beat}`} className="beat-pulse" />}
        </span>
      ))}
    </span>
  )

  const dock = (
    <div className={`pd ${tall ? 'is-tall' : 'is-row'}`}>
      <div className="pd-pos" aria-live="off">
        <span className="pd-k">Bar</span>
        <span className="pd-bar-line">
          <output className="pd-bar num" aria-label={`Bar ${p.bar}`}>{p.bar}</output>
          <span className={`listen is-${listenTone}`} role="status"><i aria-hidden="true" />{listenWord}</span>
        </span>
        <span className="pd-sub">
          {beatDots}
          {p.loop && tall && <span className="pd-loop num">loop {barRange(p.loop.from, p.loop.to)}</span>}
        </span>
      </div>

      <div className="pd-tempo" role="group" aria-label="Tempo">
        <RepeatButton className="step" onStep={() => tempoBy(-1)} aria-label="Slower, 1 bpm" aria-keyshortcuts="-"><IMinus size={tall ? 28 : 22} /></RepeatButton>
        <div className="pd-tempo-read">
          <span className="pd-tempo-line">
            <output className="pd-tempo-num num" aria-label={`Tempo ${p.tempo} bpm`}>{p.tempo}</output>
            <span className="pd-tempo-unit">bpm</span>
          </span>
          <span className="pd-tempo-of">
            {tall ? <>of <span className="num">{score.tempoBpm}</span> · </> : null}<b>{pct}%</b>
          </span>
        </div>
        <RepeatButton className="step" onStep={() => tempoBy(1)} aria-label="Faster, 1 bpm" aria-keyshortcuts="+"><IPlus size={tall ? 28 : 22} /></RepeatButton>
      </div>

      <div className="pd-toggles">
        <Toggle icon={<IMetronome size={tall ? 26 : 22} />} label="Metronome" value={p.metronome ? 'On' : 'Off'} on={p.metronome} keys="M"
          onClick={() => setP(s => ({ ...s, metronome: !s.metronome }))}>
          {p.metronome && p.playing && !reduced && <span key={`${p.bar}-${p.beat}`} className="tog-pulse" />}
        </Toggle>
        <Toggle icon={<IParts size={tall ? 26 : 22} />} label="Other parts" value={p.others === 'off' ? 'Off' : 'All'} on={p.others !== 'off'} keys="O"
          onClick={() => setP(s => ({ ...s, others: s.others === 'off' ? 'all' : 'off' }))} />
        <Toggle icon={<IEar size={tall ? 26 : 22} />} label="Listening" value={p.listenOn ? 'On' : 'Off'} on={p.listenOn} keys="L"
          onClick={() => setP(s => ({ ...s, listenOn: !s.listenOn }))} />
      </div>

      <button type="button" className={`pd-play ${p.playing ? 'is-playing' : ''}`} onClick={togglePlay} aria-label={p.playing ? 'Pause' : 'Play'} aria-keyshortcuts="Space">
        {p.playing ? <IPause size={tall ? 34 : 28} /> : <IPlay size={tall ? 34 : 28} />}
        {tall && <span>{p.playing ? 'Pause' : 'Play'}</span>}
      </button>
    </div>
  )

  return (
    <Screen header={header} ruler={ruler} dock={dock} tall={tall} className="is-practice">
      <div className={`work ${historyOpen ? 'has-side' : ''} ${historyOpen && vp.w >= 1360 ? 'side-docked' : ''}`}>
        <ScoreStage
          src={part.fixture}
          instruments={[score.partIds.indexOf(part.id)]}
          scale={tall ? 0.8 : 0.86}
          focus={focus}
          follow={p.playing ? p.bar : undefined}
          underlay={underlay}
          overlay={overlay}
          onBarTap={seek}
          label={`${part.name} part, ${score.title}`}
        />
        {historyOpen && <HistoryPanel onClose={() => setHistoryOpen(false)} onLoop={s => { setLoop(s) }} loop={p.loop} />}
      </div>
    </Screen>
  )
}

function HistoryPanel({ onClose, onLoop, loop }: { onClose: () => void; onLoop: (s: Span) => void; loop: Span | null }) {
  const sessions = practice.history
  const lo = 96
  const hi = score.tempoBpm
  const W = 300
  const Hh = 132
  const px = (i: number) => 26 + (i / (sessions.length - 1)) * (W - 52)
  const py = (bpm: number) => 14 + (1 - (bpm - lo) / (hi - lo)) * (Hh - 40)
  const path = sessions.map((s, i) => `${i ? 'L' : 'M'}${px(i)} ${py(s.reachedBpm)}`).join(' ')
  return (
    <aside className="side" aria-label="Practice history">
      <div className="side-head">
        <h2>Practice history</h2>
        <button type="button" className="btn-icon" onClick={onClose} aria-label="Close history"><IClose size={20} /></button>
      </div>
      <div className="side-scroll">
        <figure className="tempo-chart">
          <figcaption>Tempo reached, toward <span className="num">{hi}</span> bpm</figcaption>
          <svg viewBox={`0 0 ${W} ${Hh}`} width="100%" role="img" aria-label={`Tempo reached per session: ${sessions.map(s => `${fmtDay(s.date)} ${s.reachedBpm}`).join(', ')}. Target ${hi}.`}>
            <line x1={14} x2={W - 14} y1={py(hi)} y2={py(hi)} className="c-target" />
            <text x={W - 14} y={py(hi) - 5} textAnchor="end" className="c-label">target {hi}</text>
            {[100, 110, 120].map(v => <line key={v} x1={14} x2={W - 14} y1={py(v)} y2={py(v)} className="c-grid" />)}
            <path d={path} className="c-line" />
            {sessions.map((s, i) => (
              <g key={s.id}>
                <circle cx={px(i)} cy={py(s.reachedBpm)} r={i === sessions.length - 1 ? 4.5 : 3.5} className={i === sessions.length - 1 ? 'c-dot is-last' : 'c-dot'} />
                <text x={px(i)} y={py(s.reachedBpm) - 9} textAnchor="middle" className="c-val">{s.reachedBpm}</text>
                <text x={px(i)} y={Hh - 6} textAnchor="middle" className="c-day">{fmtDay(s.date).replace(/^\w+ /, '')}</text>
              </g>
            ))}
          </svg>
        </figure>

        <h3 className="side-h">Sessions</h3>
        <ol className="sessions">
          {[...sessions].reverse().map(s => (
            <li key={s.id} className="session">
              <div className="session-top">
                <strong>{s.date === TODAY ? 'Today' : fmtDay(s.date)}</strong>
                <span>{s.durationMin} min</span>
              </div>
              <dl className="session-facts">
                <div><dt>Reached</dt><dd><span className="num">{s.reachedBpm}</span> of <span className="num">{s.targetBpm}</span></dd></div>
                <div><dt>Accuracy</dt><dd>{Math.round(s.accuracy * 100)}%</dd></div>
              </dl>
              <p className="session-loops">
                {s.loops.map(l => <span key={`${l.barFrom}`}><span className="num">{barRange(l.barFrom, l.barTo)}</span> × {l.reps}</span>)}
              </p>
            </li>
          ))}
        </ol>

        <h3 className="side-h">Trouble spots</h3>
        <ul className="spots">
          {[...practice.troubleSpots].sort((a, b) => b.severity - a.severity).map(t => {
            const isLoop = loop?.from === t.barFrom && loop?.to === t.barTo
            return (
              <li key={t.barFrom} className="spot">
                <span className="spot-heat" style={{ opacity: 0.35 + t.severity * 0.65 }} aria-hidden="true" />
                <div className="spot-text">
                  <p className="num">bars {barRange(t.barFrom, t.barTo)}</p>
                  <p>{t.note}</p>
                </div>
                <button type="button" className="btn btn-line" disabled={isLoop} onClick={() => onLoop({ from: t.barFrom, to: t.barTo })}>
                  {isLoop ? 'Looping' : 'Loop'}
                </button>
              </li>
            )
          })}
        </ul>
        <p className="side-foot">Keys: Space play · − + tempo · M metronome · O other parts · L listening · H history</p>
      </div>
    </aside>
  )
}
