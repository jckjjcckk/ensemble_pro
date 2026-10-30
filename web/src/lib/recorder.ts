/** Push-to-talk capture for voice notes (013). The microphone's raw samples, resampled here to 16 kHz mono and written
 *  as a 16-bit PCM WAV with a plain 44-byte header: the one shape Muse Voice Transcribe takes (the extensible header
 *  `afconvert` writes is refused, docs/features/013). Never MediaRecorder: on the iPad it records AAC in an m4a.
 *
 *  The microphone is open only between `startRecording` and `stop`/`cancel`; both stop the track, so the system's
 *  recording light goes out with the button. */

export const VOICE_RATE = 16000
/** A note is a sentence, not a rehearsal: the take stops itself here. */
export const MAX_SECONDS = 120

export type MicProblem = 'denied' | 'unavailable' | 'failed'
export class MicError extends Error {
  problem: MicProblem
  constructor(problem: MicProblem, message: string) {
    super(message)
    this.problem = problem
  }
}

export interface Recording { wav: Blob; seconds: number }

export interface Recorder {
  /** Seconds captured so far. */
  elapsed: () => number
  /** Stop, let the microphone go and return the take. */
  stop: () => Promise<Recording>
  /** Stop and let the microphone go; nothing is kept. */
  cancel: () => void
}

interface Options {
  /** The voice level, 0..1 (RMS in dBFS, -60 = 0, -10 = 1), fast attack and slow release like a meter; ~20 times a second. */
  onLevel?: (level: number) => void
  /** The take reached `MAX_SECONDS` and stopped capturing; the caller ends it with `stop`. */
  onLimit?: () => void
}

/** Collects the input in blocks of ~2048 frames and posts them to the page. */
const WORKLET = `
class Tap extends AudioWorkletProcessor {
  constructor() { super(); this.buf = new Float32Array(2048); this.n = 0 }
  process(inputs) {
    const ch = inputs[0] && inputs[0][0]
    if (ch) for (let i = 0; i < ch.length; i++) {
      this.buf[this.n++] = ch[i]
      if (this.n === this.buf.length) { this.port.postMessage(this.buf); this.buf = new Float32Array(2048); this.n = 0 }
    }
    return true
  }
}
registerProcessor('folio-tap', Tap)
`

type Ctx = typeof AudioContext
const AudioCtx: Ctx | undefined = typeof window === 'undefined' ? undefined
  : window.AudioContext ?? (window as unknown as { webkitAudioContext?: Ctx }).webkitAudioContext

/**
 * Open the microphone and start capturing. Call it straight from the pointer-down handler: the audio context is made
 * before the first await, inside the touch, which is what lets the iPad start it.
 */
export async function startRecording(opts: Options = {}): Promise<Recorder> {
  if (!AudioCtx || !navigator.mediaDevices?.getUserMedia) throw new MicError('unavailable', 'This device has no microphone Folio can use.')
  const ctx = new AudioCtx()
  void ctx.resume().catch(() => undefined)

  let stream: MediaStream
  try {
    stream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: false },
    })
  } catch (e) {
    void ctx.close().catch(() => undefined)
    const name = (e as DOMException)?.name
    if (name === 'NotAllowedError' || name === 'SecurityError') throw new MicError('denied', 'Folio is not allowed to use the microphone.')
    if (name === 'NotFoundError' || name === 'OverconstrainedError') throw new MicError('unavailable', 'No microphone was found.')
    throw new MicError('failed', 'The microphone could not be opened.')
  }

  const rate = ctx.sampleRate
  const limit = Math.round(MAX_SECONDS * rate)
  const blocks: Float32Array[] = []
  let frames = 0
  let level = 0
  let open = true

  const take = (block: Float32Array) => {
    if (!open || frames >= limit) return
    const room = limit - frames
    const b = block.length > room ? block.subarray(0, room) : block
    blocks.push(b)
    frames += b.length
    let sum = 0
    for (let i = 0; i < b.length; i++) sum += b[i] * b[i]
    const db = 20 * Math.log10(Math.sqrt(sum / (b.length || 1)) + 1e-9)
    const target = Math.min(1, Math.max(0, (db + 60) / 50))
    level += (target - level) * (target > level ? 0.35 : 0.06)
    opts.onLevel?.(level)
    if (frames >= limit) opts.onLimit?.()
  }

  let source: MediaStreamAudioSourceNode | null = null
  let node: AudioNode | null = null
  const release = () => {
    if (!open) return
    open = false
    try { source?.disconnect(); node?.disconnect() } catch { /* already gone */ }
    stream.getTracks().forEach(t => t.stop())
    void ctx.close().catch(() => undefined)
  }

  // From here on the microphone is open: anything that goes wrong lets it go before saying so.
  try {
    source = ctx.createMediaStreamSource(stream)
    // A silent sink keeps the graph pulling on every engine without playing the voice back.
    const mute = ctx.createGain()
    mute.gain.value = 0
    mute.connect(ctx.destination)
    let url: string | null = null
    try {
      if (!ctx.audioWorklet) throw new Error('no worklet')
      url = URL.createObjectURL(new Blob([WORKLET], { type: 'application/javascript' }))
      await ctx.audioWorklet.addModule(url)
      const w = new AudioWorkletNode(ctx, 'folio-tap', { numberOfInputs: 1, numberOfOutputs: 1, channelCount: 1, channelCountMode: 'explicit' })
      w.port.onmessage = e => take(e.data as Float32Array)
      node = w
    } catch {
      // Older engines: the deprecated ScriptProcessor does the same job on the main thread.
      const sp = ctx.createScriptProcessor(2048, 1, 1)
      sp.onaudioprocess = e => take(new Float32Array(e.inputBuffer.getChannelData(0)))
      node = sp
    } finally {
      if (url) URL.revokeObjectURL(url)
    }
    source.connect(node)
    node.connect(mute)
    // The context was made inside the touch; once the stream is live, ask again in case the engine held it suspended.
    if (ctx.state !== 'running') await ctx.resume().catch(() => undefined)
  } catch {
    release()
    throw new MicError('failed', 'The microphone could not be opened.')
  }
  // A context that will not run records silence: say so now rather than send an empty take.
  if ((ctx.state as string) !== 'running') {
    release()
    throw new MicError('failed', 'The microphone did not start.')
  }

  return {
    elapsed: () => frames / rate,
    cancel: release,
    stop: async () => {
      release()
      const all = new Float32Array(frames)
      let at = 0
      for (const b of blocks) { all.set(b, at); at += b.length }
      const pcm = resample(all, rate, VOICE_RATE)
      return { wav: encodeWav(pcm, VOICE_RATE), seconds: frames / rate }
    },
  }
}

/** Band-limited resampling (a Hann-windowed sinc, eight zero crossings of the low-pass each side), so a 48 kHz voice
 *  comes down to 16 kHz without folding its hiss into the speech band. The kernel is tabulated once per call at
 *  `PHASES` fractional offsets, so a two-minute take is multiply-adds only (no sin/cos per tap): about a tenth of a
 *  second on an iPad rather than a frozen second or two. */
const PHASES = 256
export function resample(x: Float32Array, from: number, to: number): Float32Array {
  if (from === to) return x
  const r = from / to
  const n = Math.floor(x.length / r)
  const out = new Float32Array(n)
  const fc = Math.min(1, to / from) * 0.94 // the cutoff, as a fraction of the source's Nyquist
  const half = Math.ceil(8 / fc)
  const taps = 2 * half
  // table[p * taps + j]: the weight of x[c - half + 1 + j] when the output falls p / PHASES past sample c.
  const table = new Float32Array((PHASES + 1) * taps)
  for (let p = 0; p <= PHASES; p++) {
    for (let j = 0; j < taps; j++) {
      const d = p / PHASES + half - 1 - j
      const a = Math.PI * fc * d
      table[p * taps + j] = Math.abs(d) >= half ? 0 : (d === 0 ? 1 : Math.sin(a) / a) * (0.5 + 0.5 * Math.cos((Math.PI * d) / half))
    }
  }
  for (let i = 0; i < n; i++) {
    const t = i * r
    const c = Math.floor(t)
    const row = Math.round((t - c) * PHASES) * taps
    const k0 = c - half + 1
    const j0 = Math.max(0, -k0), j1 = Math.min(taps - 1, x.length - 1 - k0)
    let acc = 0, wsum = 0
    for (let j = j0; j <= j1; j++) {
      const h = table[row + j]
      acc += x[k0 + j] * h
      wsum += h
    }
    out[i] = wsum ? acc / wsum : 0
  }
  return out
}

/** Mono 16-bit PCM in a RIFF/WAVE file with the plain 44-byte header (format 1, no extensible chunk, no FLLR). */
export function encodeWav(pcm: Float32Array, rate: number): Blob {
  const buf = new ArrayBuffer(44 + pcm.length * 2)
  const v = new DataView(buf)
  const str = (at: number, s: string) => { for (let i = 0; i < s.length; i++) v.setUint8(at + i, s.charCodeAt(i)) }
  str(0, 'RIFF'); v.setUint32(4, 36 + pcm.length * 2, true); str(8, 'WAVE')
  str(12, 'fmt '); v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true)
  v.setUint32(24, rate, true); v.setUint32(28, rate * 2, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true)
  str(36, 'data'); v.setUint32(40, pcm.length * 2, true)
  for (let i = 0; i < pcm.length; i++) {
    const s = Math.max(-1, Math.min(1, pcm[i]))
    v.setInt16(44 + i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true)
  }
  return new Blob([buf], { type: 'audio/wav' })
}
