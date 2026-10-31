/** Play the parts (014): the browser plays a digital book's MIDI, part by part, with Web Audio (Tone.js).
 *
 *  The API wrote two files at import or Convert to Digital (`api/app/librarian/playback.py`): `score.mid` (one track per
 *  part, named with the book's part names) and `bars.json` (where each bar starts in quarter notes, the tempo and meter
 *  changes). Nothing here talks to the API; both files come from Storage through the score's own policies.
 *
 *  The engine schedules one pass on Tone's transport, counted in quarter notes: a one-bar count-in in the meter of the
 *  start bar (clicks, the first one higher), then the chosen bars shifted to follow it. The transport's tempo is the
 *  printed tempo times the pace, so a pace change lands within a beat and tempo changes in the score still apply. A loop
 *  jumps back to the range start, after the count-in, so the count-in sounds once. A part that is off skips its notes;
 *  each part has its own gain. Tone and the samples (web/public/sounds, ~4.4 MB, two instruments) load on the first play,
 *  fetched and decoded here rather than by Tone's loader (see `sampleArrived`), and kept for the session. */
import type * as ToneNS from 'tone'
import { supabase } from '../lib/supabase'
import type { Playback } from '../mock'
import { SAMPLES, SampleError, fetchFault, sampleArrived, samplePath, sampleUrl, voiceFor, type Voice } from './sounds'

type Tone = typeof ToneNS

export interface BarMap {
  version: number
  ppq: number
  parts: string[]
  quarters: number
  bars: { bar: number; at: number; quarters: number }[]
  tempos: { bar: number; at: number; qpm: number; bpm: number; beat: string; text: string | null; marked: boolean }[]
  meters: { bar: number; at: number; meter: string; beats: number; beat_quarters: number }[]
}

export interface PlayNote { q: number; dur: number; midi: number; vel: number }
export interface PlayTrack { name: string; notes: PlayNote[] }
export interface PlayBook { map: BarMap; tracks: PlayTrack[] }

/** The bar's entry, by number (a number printed twice keeps its first place, as the API wrote it). */
export const barOf = (map: BarMap, bar: number) => map.bars.find(b => b.bar === bar)

/** The entry in force at quarter offset `q` of a list sorted by `at`. */
function inForce<T extends { at: number }>(list: T[], q: number): T {
  let hit = list[0]
  for (const x of list) { if (x.at <= q + 1e-6) hit = x; else break }
  return hit
}

/** The one-bar count-in before `bar`: the meter in force there, as clicks (mirrors `playback.count_in`). */
export function countIn(map: BarMap, bar: number) {
  const b = barOf(map, bar) ?? map.bars[0]
  const m = inForce(map.meters, b.at)
  return { meter: m.meter, beats: m.beats, beatQ: m.beat_quarters, quarters: m.beats * m.beat_quarters }
}

export const tempoAt = (map: BarMap, q: number) => inForce(map.tempos, q)

/** Bars in time order, for the lookup from a position to the bar holding it. */
function sortedBars(map: BarMap) {
  return [...map.bars].sort((a, b) => a.at - b.at)
}

function barAtQ(sorted: BarMap['bars'], q: number) {
  let lo = 0, hi = sorted.length - 1, hit = 0
  while (lo <= hi) {
    const mid = (lo + hi) >> 1
    if (sorted[mid].at <= q + 1e-6) { hit = mid; lo = mid + 1 } else hi = mid - 1
  }
  return sorted[hit]
}

async function download(path: string): Promise<ArrayBuffer> {
  const { data, error } = await supabase.storage.from('scores').download(path)
  if (error || !data) throw new Error(error?.message || 'not found')
  return data.arrayBuffer()
}

/** The book's MIDI and bar map, from the bucket. Tracks are matched to the bar map's parts by name, else by order. */
export async function loadBook(pb: Playback): Promise<PlayBook> {
  const [{ Midi }, midiBytes, mapBytes] = await Promise.all([import('@tonejs/midi'), download(pb.midi), download(pb.barMap)])
  const map = JSON.parse(new TextDecoder().decode(mapBytes)) as BarMap
  const midi = new Midi(midiBytes)
  const ppq = midi.header.ppq || map.ppq
  const sounding = midi.tracks.filter(t => t.notes.length)
  const tracks = map.parts.map((name, i) => {
    const t = sounding.find(x => x.name === name) ?? sounding[i]
    return {
      name,
      notes: (t?.notes ?? []).map(n => ({ q: n.ticks / ppq, dur: n.durationTicks / ppq, midi: n.midi, vel: n.velocity })).sort((a, b) => a.q - b.q),
    }
  })
  return { map, tracks }
}

// ---------------------------------------------------------------- sounds

const errText = (e: unknown) => (e instanceof Error ? e.message || e.name : String(e))

/** One sample, fetched and decoded. Not Tone's loader: in the iPad shell a bundled .mp3 answers with status 0 (see
 *  `sampleArrived`), which Tone takes for a failed download. A failure names the file. */
async function fetchSample(T: Tone, voice: Voice, stem: string): Promise<AudioBuffer> {
  const path = samplePath(voice, stem)
  let res: Response
  let bytes: ArrayBuffer
  try {
    res = await fetch(sampleUrl(voice, stem, import.meta.env.BASE_URL, location.href))
    bytes = await res.arrayBuffer()
  } catch (e) {
    throw new SampleError(voice, path, `not reachable (${errText(e)})`)
  }
  if (!sampleArrived(res.status, bytes.byteLength)) throw new SampleError(voice, path, fetchFault(res.status, bytes.byteLength))
  try {
    return await T.getContext().decodeAudioData(bytes)
  } catch (e) {
    throw new SampleError(voice, path, `not decodable here (${errText(e)})`)
  }
}

/** A voice's samples by note, decoded once per session. A failed load is forgotten, so the next Play fetches again. */
const voices = new Map<Voice, Promise<Record<string, AudioBuffer>>>()
function loadVoice(T: Tone, voice: Voice) {
  let p = voices.get(voice)
  if (!p) {
    const loading = Promise.all(Object.entries(SAMPLES[voice]).map(async ([note, stem]) => [note, await fetchSample(T, voice, stem)] as const))
      .then(pairs => Object.fromEntries(pairs))
    loading.catch(() => { if (voices.get(voice) === loading) voices.delete(voice) })
    voices.set(voice, loading)
    p = loading
  }
  return p
}

// ---------------------------------------------------------------- the engine

export type PlayStatus = 'idle' | 'loading' | 'counting' | 'playing'
export interface PlayPosition { status: PlayStatus; bar: number | null; beat: number; beats: number; countBeat: number }
export interface PlayRequest { from: number; to: number | null; loop: boolean; countIn: boolean }

let toneModule: Promise<Tone> | null = null
/** Tone's code, fetched ahead (when the panel opens) so the Play tap can resume audio inside the gesture. */
export function preloadTone(): Promise<Tone> {
  toneModule ??= import('tone')
  return toneModule
}

interface Lane { name: string; voice: Voice; gain: ToneNS.Gain; sampler: ToneNS.Sampler | null; on: boolean; level: number }

export class PartsPlayer {
  private T: Tone | null = null
  private book: PlayBook
  private sorted: BarMap['bars']
  private lanes: Lane[] = []
  private master: ToneNS.Gain | null = null
  private click: ToneNS.Synth | null = null
  /** Bumped by every play and stop: a play whose samples arrive after a Stop (or after the panel closed) does not start. */
  private gen = 0
  private pace = 0.8
  private marked = 120
  private pass: { startQ: number; endQ: number; ciTicks: number; ci: ReturnType<typeof countIn>; loop: boolean } | null = null
  private raf = 0
  private pos: PlayPosition = { status: 'idle', bar: null, beat: 0, beats: 0, countBeat: 0 }
  private listeners = new Set<(p: PlayPosition) => void>()
  private noteNames = new Map<number, string>()
  private wanted: { on: Record<string, boolean>; level: Record<string, number> } = { on: {}, level: {} }
  /** Notes sounded and skipped per part since the player opened (for checking a mix; the dev build exposes the player
   *  as `window.__folioPlayer`). */
  readonly stats: { played: Record<string, number>; skipped: Record<string, number> } = { played: {}, skipped: {} }

  constructor(book: PlayBook) {
    this.book = book
    this.sorted = sortedBars(book.map)
    if (import.meta.env.DEV) (window as unknown as { __folioPlayer?: PartsPlayer }).__folioPlayer = this
  }

  /** The audio clock and the transport, for checking timing in the dev build. */
  debug() {
    const T = this.T
    if (!T) return null
    const tr = T.getTransport()
    return {
      context: T.getContext().state, bpm: tr.bpm.value, loop: tr.loop, ticks: tr.ticks, state: tr.state,
      lanes: this.lanes.map(l => ({ name: l.name, voice: l.voice, on: l.on, gain: l.gain.gain.value, loaded: l.sampler?.loaded ?? false })),
    }
  }

  get map() { return this.book.map }

  subscribe(fn: (p: PlayPosition) => void) {
    this.listeners.add(fn)
    fn(this.pos)
    return () => { this.listeners.delete(fn) }
  }

  private emit(p: Partial<PlayPosition>) {
    const next = { ...this.pos, ...p }
    if (next.status === this.pos.status && next.bar === this.pos.bar && next.beat === this.pos.beat && next.countBeat === this.pos.countBeat) return
    this.pos = next
    for (const fn of this.listeners) fn(next)
  }

  /** A part's state, applied now when sounding and kept for the first play. */
  setLane(name: string, on: boolean, level: number) {
    this.wanted.on[name] = on
    this.wanted.level[name] = level
    const lane = this.lanes.find(l => l.name === name)
    if (!lane) return
    lane.on = on
    lane.level = level
    lane.gain.gain.rampTo(on ? level : 0, 0.04)
  }

  setPace(p: number) {
    this.pace = p
    const T = this.T
    if (T && this.pos.status !== 'idle') T.getTransport().bpm.value = this.marked * p
  }

  setLoop(loop: boolean) {
    const T = this.T
    if (!T || !this.pass) return
    this.pass.loop = loop
    T.getTransport().loop = loop
  }

  /** Audio must start inside the tap (iOS); everything else may wait. */
  private async ensure(): Promise<Tone> {
    const T = await preloadTone()
    if (!this.T) {
      this.T = T
      this.master = new T.Gain(0.9).toDestination()
      this.click = new T.Synth({ oscillator: { type: 'triangle' }, envelope: { attack: 0.001, decay: 0.06, sustain: 0, release: 0.03 }, volume: -6 }).connect(this.master)
      for (const t of this.book.tracks) {
        const voice = voiceFor(t.name)
        const on = this.wanted.on[t.name] ?? true
        const level = this.wanted.level[t.name] ?? 0.8
        const gain = new T.Gain(on ? level : 0).connect(this.master)
        this.lanes.push({ name: t.name, voice, gain, sampler: null, on, level })
      }
    }
    // A lane gets its sampler only from decoded buffers; until every voice has loaded nothing is scheduled, and a failure
    // leaves the player idle with no half-loaded sampler behind (the clicks used to play over silent parts).
    const need = [...new Set(this.lanes.filter(l => !l.sampler).map(l => l.voice))]
    if (need.length) {
      this.emit({ status: 'loading' })
      let loaded: Record<string, AudioBuffer>[]
      try {
        loaded = await Promise.all(need.map(v => loadVoice(T, v)))
      } catch (e) {
        this.emit({ status: 'idle' })
        throw e
      }
      need.forEach((voice, i) => {
        for (const lane of this.lanes) {
          if (lane.voice !== voice || lane.sampler) continue
          lane.sampler = new T.Sampler({ urls: loaded[i], attack: voice === 'strings' ? 0.03 : 0, release: voice === 'strings' ? 0.25 : 0.9 }).connect(lane.gain)
        }
      })
    }
    return T
  }

  private name(midi: number) {
    let n = this.noteNames.get(midi)
    if (!n && this.T) { n = this.T.Frequency(midi, 'midi').toNote(); this.noteNames.set(midi, n) }
    return n ?? 'C4'
  }

  /** Call from the tap: resumes audio at once, then loads what the first play needs and starts. */
  play(req: PlayRequest): Promise<void> {
    const started = this.T ? this.T.start() : preloadTone().then(T => T.start())
    try {
      const nav = navigator as Navigator & { audioSession?: { type: string } }
      if (nav.audioSession) nav.audioSession.type = 'playback'   // iOS: sound with the silent switch on
    } catch { /* not there */ }
    const gen = ++this.gen
    return started.then(() => this.ensure()).then(T => { if (gen === this.gen) this.schedule(T, req) })
  }

  private schedule(T: Tone, req: PlayRequest) {
    const tr = T.getTransport()
    tr.stop()
    tr.cancel(0)
    tr.loop = false
    tr.position = 0
    for (const l of this.lanes) l.sampler?.releaseAll()

    const map = this.book.map
    const first = barOf(map, req.from) ?? map.bars[0]
    const last = req.to != null ? barOf(map, req.to) : undefined
    const startQ = first.at
    const endQ = last ? Math.max(last.at + last.quarters, startQ + 0.25) : map.quarters
    const ci = countIn(map, first.bar)
    const PPQ = tr.PPQ
    const ciQ = req.countIn ? ci.quarters : 0
    const ciTicks = Math.round(ciQ * PPQ)
    const tick = (q: number) => Math.round(ciTicks + (q - startQ) * PPQ)
    const t0 = tempoAt(map, startQ)
    this.marked = t0.qpm
    tr.bpm.value = t0.qpm * this.pace
    this.pass = { startQ, endQ, ciTicks, ci, loop: req.loop }

    // The count-in: one bar of clicks in the start bar's meter, the first one higher.
    if (req.countIn) {
      const beatTicks = ci.beatQ * PPQ
      for (let i = 0; i < ci.beats; i++) {
        tr.schedule(time => { this.click?.triggerAttackRelease(i === 0 ? 1760 : 1320, 0.05, time) }, `${Math.round(i * beatTicks)}i`)
      }
    }
    // The tempo at the range start, again on every pass of a loop; then each change inside the range.
    tr.schedule(time => { this.marked = t0.qpm; tr.bpm.setValueAtTime(t0.qpm * this.pace, time) }, `${ciTicks}i`)
    for (const tq of map.tempos) {
      if (tq.at <= startQ + 1e-6 || tq.at >= endQ - 1e-6) continue
      tr.schedule(time => { this.marked = tq.qpm; tr.bpm.setValueAtTime(tq.qpm * this.pace, time) }, `${tick(tq.at)}i`)
    }
    // The notes. A part that is off when its note comes skips it.
    for (const lane of this.lanes) {
      const notes = this.book.tracks.find(t => t.name === lane.name)?.notes ?? []
      for (const n of notes) {
        if (n.q < startQ - 1e-6 || n.q >= endQ - 1e-6) continue
        const durQ = Math.min(n.dur, endQ - n.q)
        const note = this.name(n.midi)
        const vel = Math.max(0.15, Math.min(1, n.vel || 0.7))
        tr.schedule(time => {
          if (!lane.on || !lane.sampler) { this.stats.skipped[lane.name] = (this.stats.skipped[lane.name] ?? 0) + 1; return }
          this.stats.played[lane.name] = (this.stats.played[lane.name] ?? 0) + 1
          const sec = Math.max(0.05, (durQ * 60) / tr.bpm.getValueAtTime(time))
          lane.sampler.triggerAttackRelease(note, sec, time, vel)
        }, `${tick(n.q)}i`)
      }
    }
    const endTick = tick(endQ)
    tr.loopStart = `${ciTicks}i`
    tr.loopEnd = `${endTick}i`
    tr.loop = req.loop
    // Without a loop the pass ends at the range end (or the last bar).
    // (A timer, not Tone's Draw: Draw drops a callback that comes late, as it does in a throttled tab.)
    tr.schedule(time => {
      if (tr.loop) return
      window.setTimeout(() => { if (this.pass && !tr.loop) this.stop() }, Math.max(0, (time - T.immediate()) * 1000))
    }, `${endTick}i`)
    tr.start('+0.05')
    this.emit({ status: req.countIn ? 'counting' : 'playing', bar: first.bar, beat: 1, beats: ci.beats, countBeat: req.countIn ? 1 : 0 })
    this.watch()
  }

  /** Where the transport is, every frame, as a bar and a beat (or a count-in beat). */
  private watch() {
    cancelAnimationFrame(this.raf)
    const T = this.T
    if (!T || !this.pass) return
    const tr = T.getTransport()
    const PPQ = tr.PPQ
    const frame = () => {
      const p = this.pass
      if (!p || tr.state !== 'started') { this.raf = requestAnimationFrame(frame); return }
      const ticks = tr.getTicksAtTime(T.immediate())
      if (ticks < p.ciTicks) {
        const b = Math.min(p.ci.beats, Math.floor(ticks / (p.ci.beatQ * PPQ)) + 1)
        const firstBar = barAtQ(this.sorted, p.startQ)
        this.emit({ status: 'counting', countBeat: Math.max(1, b), bar: firstBar.bar, beat: 1, beats: p.ci.beats })
      } else {
        const q = p.startQ + (ticks - p.ciTicks) / PPQ
        const b = barAtQ(this.sorted, Math.min(q, p.endQ - 1e-3))
        const m = inForce(this.book.map.meters, b.at)
        const beat = Math.min(m.beats, Math.floor((q - b.at) / m.beat_quarters + 1e-6) + 1)
        this.emit({ status: 'playing', bar: b.bar, beat: Math.max(1, beat), beats: m.beats, countBeat: 0 })
      }
      this.raf = requestAnimationFrame(frame)
    }
    this.raf = requestAnimationFrame(frame)
  }

  stop() {
    this.gen++
    cancelAnimationFrame(this.raf)
    const T = this.T
    if (T) {
      const tr = T.getTransport()
      tr.stop()
      tr.cancel(0)
      tr.loop = false
      for (const l of this.lanes) l.sampler?.releaseAll()
    }
    this.pass = null
    this.emit({ status: 'idle', bar: null, beat: 0, countBeat: 0 })
  }

  dispose() {
    this.stop()
    for (const l of this.lanes) { l.sampler?.dispose(); l.gain.dispose() }
    this.lanes = []
    this.click?.dispose()
    this.master?.dispose()
    this.listeners.clear()
  }
}
