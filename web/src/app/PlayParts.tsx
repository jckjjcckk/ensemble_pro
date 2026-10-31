/** Play the parts (014): the Stand's player. CK's musician's workflow: choose which parts sound (your own part off),
 *  set a pace, play; one bar is counted in, in the score's meter; a passage loops. The panel is the instrument's dark
 *  surface at the foot of the Stand (DESIGN.md: the dock "grows into the instrument's panel"), with the bar ruler on top:
 *  tap two bars on it to choose a passage (or use Loop from here on a bar), drag the bracket ends to adjust. The pace is
 *  the largest number. Everything here is this device's own state (localStorage), never a mark. */
import { useEffect, useMemo, useRef, useState, type ButtonHTMLAttributes, type ReactNode } from 'react'
import type { Score } from '../mock'
import { Ruler } from './Ruler'
import { barRange, type Span } from './store'
import { IClose, IMinus, IPlay, IPlus, IRepeat, IStop } from './icons'
import './play.css'
import { PartsPlayer, countIn, loadBook, preloadTone, tempoAt, type PlayBook, type PlayPosition } from './player'

// ---------------------------------------------------------------- this device's practice state

export interface PlayState {
  /** 0.25 .. 1.5 of the printed tempo */
  pace: number
  /** Part names that are off. Undefined until the reader chooses (then the device's own part starts off). */
  off?: string[]
  gain: Record<string, number>
  loop: boolean
  countIn: boolean
  range: Span | null
}

const DEFAULT: PlayState = { pace: 0.8, gain: {}, loop: true, countIn: true, range: null }
const key = (scoreId: string) => `folio.play:${scoreId}`

function readState(scoreId: string): PlayState {
  try {
    const raw = localStorage.getItem(key(scoreId))
    if (raw) return { ...DEFAULT, ...(JSON.parse(raw) as Partial<PlayState>) }
  } catch { /* private window, blocked storage */ }
  return DEFAULT
}

/** The player's per-device state for one book, kept across visits (pace, mix, loop, the passage). */
export function usePlayState(scoreId: string) {
  const [state, setState] = useState<PlayState>(() => readState(scoreId))
  useEffect(() => { setState(readState(scoreId)) }, [scoreId])
  useEffect(() => {
    try { localStorage.setItem(key(scoreId), JSON.stringify(state)) } catch { /* not kept */ }
  }, [scoreId, state])
  return [state, setState] as const
}

const PACE_MIN = 0.3
const PACE_MAX = 1.5
const clampPace = (p: number) => Math.round(Math.max(PACE_MIN, Math.min(PACE_MAX, p)) * 100) / 100

/** The printed beat as notation: "♩", "♩." and so on (Noto Music draws them). */
const BEAT_GLYPH: Record<string, string> = {
  quarter: '♩', 'dotted quarter': '♩.', half: '𝅗𝅥', 'dotted half': '𝅗𝅥.', eighth: '♪', 'dotted eighth': '♪.', whole: '𝅝',
}

function Repeat({ onStep, children, ...rest }: { onStep: () => void; children: ReactNode } & Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'onClick'>) {
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
        delay.current = window.setTimeout(() => { every.current = window.setInterval(() => step.current(), 140) }, 420)
      }}
      onPointerUp={stop} onPointerLeave={stop} onPointerCancel={stop}
      onClick={e => { if (e.detail === 0) step.current() }}
    >
      {children}
    </button>
  )
}

// ---------------------------------------------------------------- the panel

export interface PlayHead { bar: number; counting: boolean; beat: number; beats: number }

export function PlayParts({ score, state, setState, ownPart, fromBar, onHead, onClose }: {
  score: Score
  state: PlayState
  setState: (f: (s: PlayState) => PlayState) => void
  /** The device's own part, when the reader's seat names one: off until the reader turns it on. */
  ownPart: string | null
  /** Where playback starts without a chosen passage: the first bar on screen. */
  fromBar: number
  onHead: (h: PlayHead | null) => void
  onClose: () => void
}) {
  const pb = score.playback
  const [book, setBook] = useState<PlayBook | null>(null)
  const [error, setError] = useState<string | null>(null)
  const player = useRef<PartsPlayer | null>(null)
  const [pos, setPos] = useState<PlayPosition>({ status: 'idle', bar: null, beat: 0, beats: 0, countBeat: 0 })
  const [pick, setPick] = useState<number | null>(null)

  // The files, and Tone's code ahead of the first tap; the samples wait for Play.
  useEffect(() => {
    if (!pb) return
    let live = true
    setError(null)
    void preloadTone().catch(() => undefined)
    loadBook(pb).then(b => {
      if (!live) return
      setBook(b)
      const p = new PartsPlayer(b)
      player.current = p
      p.subscribe(setPos)
    }).catch(() => { if (live) setError('Could not load this book’s playback. Check the connection and open the player again.') })
    return () => {
      live = false
      player.current?.dispose()
      player.current = null
      setBook(null)
    }
  }, [pb?.midi, pb?.barMap])   // eslint-disable-line react-hooks/exhaustive-deps

  const parts = useMemo(() => book?.map.parts ?? pb?.parts ?? [], [book, pb?.parts])
  const off = useMemo(() => new Set(state.off ?? (ownPart && parts.includes(ownPart) ? [ownPart] : [])), [state.off, ownPart, parts])
  const gainOf = (name: string) => state.gain[name] ?? 0.8

  // The mix reaches the engine as it changes, playing or not.
  useEffect(() => {
    const p = player.current
    if (!p) return
    for (const name of parts) p.setLane(name, !off.has(name), gainOf(name))
  })
  useEffect(() => { player.current?.setPace(state.pace) }, [state.pace, book])
  useEffect(() => { player.current?.setLoop(state.loop) }, [state.loop])

  // The Stand draws the playing bar on the ruler's twin, the score.
  useEffect(() => {
    onHead(pos.status === 'idle' || pos.status === 'loading' || pos.bar == null ? null : { bar: pos.bar, counting: pos.status === 'counting', beat: pos.status === 'counting' ? pos.countBeat : pos.beat, beats: pos.beats })
  }, [pos, onHead])
  useEffect(() => () => onHead(null), [onHead])

  const map = book?.map
  const order = useMemo(() => map?.bars.map(b => b.bar) ?? [], [map])
  const indexOf = (bar: number) => Math.max(1, order.indexOf(bar) + 1)
  const range = state.range && order.includes(state.range.from) && order.includes(state.range.to) ? state.range : null
  const start = range?.from ?? (order.includes(fromBar) ? fromBar : order[0] ?? 1)
  const playing = pos.status === 'counting' || pos.status === 'playing'

  const play = () => {
    const p = player.current
    if (!p || !map) return
    setPick(null)
    p.play({ from: start, to: range?.to ?? null, loop: state.loop && !!range, countIn: state.countIn })
      .catch(() => setError('The sound could not start on this device. Tap Play again.'))
  }
  const stop = () => player.current?.stop()
  const toggle = () => (playing || pos.status === 'loading' ? stop() : play())

  // A new passage while playing starts again from its first bar.
  const rangeKey = range ? `${range.from}-${range.to}` : ''
  const lastKey = useRef(rangeKey)
  useEffect(() => {
    if (lastKey.current === rangeKey) return
    lastKey.current = rangeKey
    if (playing) play()
  })   // eslint-disable-line react-hooks/exhaustive-deps

  // Space plays and stops (the Mac); never the only way.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement
      if (e.key !== ' ' || e.metaKey || e.ctrlKey || e.altKey || t.closest('input, textarea, [contenteditable], button, a, [role="slider"]')) return
      e.preventDefault()
      toggle()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  const setRange = (r: Span | null) => setState(s => ({ ...s, range: r }))
  // Tap two bars: the first marks the start, the second the end (either order).
  const onRulerTap = (k: number) => {
    const bar = order[k - 1]
    if (bar == null) return
    if (pick == null) { setPick(bar); return }
    const a = order.indexOf(pick), b = k - 1
    setRange({ from: order[Math.min(a, b)], to: order[Math.max(a, b)] })
    setPick(null)
  }

  const tempo = map ? tempoAt(map, barOfStart(map, start)) : null
  const glyph = tempo ? BEAT_GLYPH[tempo.beat] ?? '♩' : '♩'
  const nowBpm = tempo ? Math.round(tempo.bpm * state.pace) : null
  const ci = map ? countIn(map, start) : null
  const pct = Math.round(state.pace * 100)

  if (!pb) {
    const scan = score.kinds ? !score.kinds.includes('digital') : score.book !== 'digital'
    return (
      <section className="pp is-empty" aria-label="Play the parts">
        <p className="pp-note">{scan ? 'Convert to Digital first: playing the parts needs the notes, written out from the scan.' : 'This book was imported before playback existed. Import its MusicXML again to play it.'}</p>
        <button type="button" className="pp-close" onClick={onClose} aria-label="Close the player"><IClose size={20} /></button>
      </section>
    )
  }

  const rulerSpan = pick != null ? { from: indexOf(pick), to: indexOf(pick) } : range ? { from: indexOf(range.from), to: indexOf(range.to) } : null
  const head = pos.bar != null && pos.status !== 'idle' ? indexOf(pos.bar) + (pos.status === 'playing' && pos.beats ? (pos.beat - 1) / pos.beats : 0) : null
  const hint = pick != null ? `From bar ${pick}. Tap the last bar.`
    : range ? null : 'Tap two bars on the ruler to choose a passage.'

  return (
    <section className="pp" aria-label="Play the parts">
      <div className="pp-head">
        <div className="pp-ruler">
        {map && (
          <Ruler
            total={order.length} span={rulerSpan} mode={pick != null || !range ? 'none' : 'range'} spanLabel="Passage"
            onSpan={s => setRange({ from: order[s.from - 1], to: order[s.to - 1] })}
            onSeek={onRulerTap} playhead={head} compact labelOf={k => order[k - 1] ?? k}
            label={`Bar ruler, bars ${order[0]} to ${order[order.length - 1]}. Tap two bars to choose a passage; drag its ends to change it.`}
          />
        )}
        <p className={`pp-hint ${error ? 'is-error' : ''}`} role={error ? 'alert' : undefined}>
          {error ?? hint ?? (range && <>Bars <span className="num">{barRange(range.from, range.to)}</span>{state.loop ? ', looping' : ', once'} · <button type="button" className="pp-link" onClick={() => setRange(null)}>Whole piece</button></>)}
        </p>
        </div>
        <button type="button" className="pp-close" onClick={() => { stop(); onClose() }} aria-label="Close the player"><IClose size={20} /></button>
      </div>

      <div className="pp-body">
        <div className="pp-transport">
          <button type="button" className={`pp-play ${playing ? 'is-on' : ''}`} onClick={toggle} disabled={!book}
            aria-label={playing ? 'Stop' : pos.status === 'loading' ? 'Loading the sounds' : 'Play'} aria-keyshortcuts="Space">
            {playing ? <IStop size={28} /> : <IPlay size={28} />}
            <span>{playing ? 'Stop' : pos.status === 'loading' ? 'Loading' : 'Play'}</span>
          </button>
          <div className="pp-pos" aria-live="off">
            {pos.status === 'counting' ? (
              <>
                <span className="pp-k">Count-in</span>
                <span className="pp-beats" aria-label={`Count-in, beat ${pos.countBeat} of ${pos.beats}`}>
                  {Array.from({ length: pos.beats }, (_, i) => <span key={i} className={`pp-beat ${i < pos.countBeat ? 'is-on' : ''}`} />)}
                </span>
              </>
            ) : (
              <>
                <span className="pp-k">{playing ? 'Bar' : range ? 'Passage' : 'From bar'}</span>
                <span className="pp-bar num">{playing && pos.bar != null ? pos.bar : range ? barRange(range.from, range.to) : start}</span>
              </>
            )}
          </div>
        </div>

        <div className="pp-pace" role="group" aria-label="Pace">
          <Repeat className="pp-step" onStep={() => setState(s => ({ ...s, pace: clampPace(s.pace - 0.05) }))} aria-label="Slower, 5 percent" disabled={state.pace <= PACE_MIN}>
            <IMinus size={22} />
          </Repeat>
          <div className="pp-pace-read">
            <output className="pp-pct num" aria-label={`Pace ${pct} percent`}>{pct}<small>%</small></output>
            <span className="pp-tempo">
              <span className="pp-glyph" aria-hidden="true">{glyph}</span> = <span className="num">{nowBpm ?? '–'}</span>
              <span className="pp-of"> of <span className="num">{tempo ? Math.round(tempo.bpm) : '–'}</span>{tempo && !tempo.marked ? ', none printed' : ''}</span>
            </span>
          </div>
          <Repeat className="pp-step" onStep={() => setState(s => ({ ...s, pace: clampPace(s.pace + 0.05) }))} aria-label="Faster, 5 percent" disabled={state.pace >= PACE_MAX}>
            <IPlus size={22} />
          </Repeat>
        </div>

        <div className="pp-opts">
          <button type="button" className={`pp-tog ${state.loop ? 'is-on' : ''}`} aria-pressed={state.loop} onClick={() => setState(s => ({ ...s, loop: !s.loop }))}
            title={range ? undefined : 'Choose a passage to loop it'}>
            <IRepeat size={20} /><span>Loop</span><small>{!range ? 'a passage' : state.loop ? 'On' : 'Off'}</small>
          </button>
          <button type="button" className={`pp-tog ${state.countIn ? 'is-on' : ''}`} aria-pressed={state.countIn} onClick={() => setState(s => ({ ...s, countIn: !s.countIn }))}>
            <span className="pp-tog-n num" aria-hidden="true">{ci ? ci.meter : '1'}</span><span>Count-in</span><small>{state.countIn ? 'One bar' : 'Off'}</small>
          </button>
        </div>

        <ul className="pp-lanes" aria-label="Parts">
          {parts.map(name => {
            const on = !off.has(name)
            const g = gainOf(name)
            return (
              <li key={name} className={`pp-lane ${on ? 'is-on' : ''}`}>
                <button type="button" className="pp-lane-name" aria-pressed={on}
                  onClick={() => setState(s => {
                    const was = new Set(s.off ?? [...off])
                    if (was.has(name)) was.delete(name); else was.add(name)
                    return { ...s, off: [...was] }
                  })}>
                  <span className="pp-dot" aria-hidden="true" />
                  <span className="pp-lane-t">{name}</span>
                  <small>{on ? (name === ownPart ? 'Yours, sounding' : 'Sounding') : name === ownPart ? 'Yours, silent' : 'Silent'}</small>
                </button>
                <input type="range" className="pp-gain" min={0} max={100} step={1} value={Math.round(g * 100)} disabled={!on}
                  aria-label={`${name} volume`} aria-valuetext={`${Math.round(g * 100)} percent`}
                  onChange={e => { const v = Number(e.target.value) / 100; setState(s => ({ ...s, gain: { ...s.gain, [name]: v } })) }} />
              </li>
            )
          })}
        </ul>

      </div>
    </section>
  )
}

const barOfStart = (map: PlayBook['map'], bar: number) => map.bars.find(b => b.bar === bar)?.at ?? 0
