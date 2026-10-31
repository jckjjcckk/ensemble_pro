/** The sampled instruments of Play the parts (014): which files, where they are, and when a fetch of one has arrived.
 *  No Tone and no app imports here, so the node tests load it as it is. */

export type Voice = 'piano' | 'strings'

/** Note -> file stem in `public/sounds/<voice>/` (MIT, from the tonejs-instrument-*-mp3 packages). */
export const SAMPLES: Record<Voice, Record<string, string>> = {
  piano: { A1: 'A1', C2: 'C2', 'F#2': 'Fs2', C3: 'C3', 'F#3': 'Fs3', C4: 'C4', 'F#4': 'Fs4', C5: 'C5', 'F#5': 'Fs5', C6: 'C6', 'F#6': 'Fs6', C7: 'C7' },
  strings: { C2: 'cello-C2', G2: 'cello-G2', D3: 'cello-D3', G3: 'violin-G3', E4: 'violin-E4', C5: 'violin-C5', G5: 'violin-G5', E6: 'violin-E6' },
}

/** Keyboards (and anything unnamed) sound as piano; bowed strings, voices, winds and brass as sustained strings. */
export function voiceFor(name: string): Voice {
  if (/piano|klavier|keyboard|harpsichord|cembalo|organ|celesta|harp|guitar|^part\b/i.test(name)) return 'piano'
  if (/violin|viola|cello|violoncello|bass|string|soprano|alto|tenor|baritone|voice|choir|flute|oboe|clarinet|bassoon|horn|trumpet|trombone|tuba|sax/i.test(name)) return 'strings'
  return 'piano'
}

/** The sample's path inside the app, as the panel names it. */
export const samplePath = (voice: Voice, stem: string) => `sounds/${voice}/${stem}.mp3`

/** The sample's absolute URL: the build's base (`import.meta.env.BASE_URL`) resolved against the page. The iPad shell's
 *  page is capacitor://localhost/, the hosted app's its https origin; any route depth gives the same file. */
export function sampleUrl(voice: Voice, stem: string, base: string, page: string): string {
  const root = base.endsWith('/') ? base : `${base}/`
  return new URL(`${root}${samplePath(voice, stem)}`, page).href
}

/** Whether a fetched sample arrived. Capacitor's iOS asset handler answers a media file (.mp3, .m4a, .wav ...) with a
 *  plain URLResponse, not an HTTP one (WebViewAssetHandler.swift, isMediaExtension), so WKWebView's fetch reports
 *  status 0, ok false and no headers, with the whole file as the body. Tone's own loader throws on `!response.ok`, which
 *  is why the instruments never loaded in the app; here status 0 with bytes counts, and the decoder judges the bytes. */
export function sampleArrived(status: number, bytes: number): boolean {
  return bytes > 0 && (status === 0 || (status >= 200 && status < 300))
}

/** One sample that did not load, named for the panel: the file and what happened to it. */
export class SampleError extends Error {
  voice: Voice
  path: string
  detail: string
  constructor(voice: Voice, path: string, detail: string) {
    super(`The ${voice} sound did not load: ${path}, ${detail}. Tap Play to try again.`)
    this.name = 'SampleError'
    this.voice = voice
    this.path = path
    this.detail = detail
  }
}

/** What went wrong with a fetch that answered, in a few words. */
export function fetchFault(status: number, bytes: number): string {
  if (status >= 200 && status < 300 && bytes === 0) return 'an empty file'
  return status ? `HTTP ${status}` : 'no data'
}
