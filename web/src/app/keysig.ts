/** Reading a book's key and meter as music21 writes them (`scores.key_sig`, `scores.meter`). Pure; Identity.tsx draws them. */

const LETTER_FIFTHS: Record<string, number> = { F: -1, C: 0, G: 1, D: 2, A: 3, E: 4, B: 5 }
const MODE_SHIFT: Record<string, number> = { major: 0, ionian: 0, minor: -3, aeolian: -3, dorian: -2, phrygian: -4, lydian: 1, mixolydian: -1, locrian: -5 }

export interface KeySig { tonic: string; mode: string; fifths: number }

/** music21's key name ("E- major", "F# minor", "c minor") to its place on the circle of fifths. Null when it cannot be read. */
export function parseKey(raw: string | null | undefined): KeySig | null {
  const m = (raw ?? '').trim().match(/^([A-Ga-g])([#-]*|b*)(?:\s+([A-Za-z]+))?$/)
  if (!m) return null
  const [, letter, acc, modeRaw] = m
  const mode = (modeRaw || (letter === letter.toLowerCase() ? 'minor' : 'major')).toLowerCase()
  if (!(mode in MODE_SHIFT)) return null
  const sharps = [...acc].filter(c => c === '#').length
  const flats = [...acc].filter(c => c === '-' || c === 'b').length
  const fifths = LETTER_FIFTHS[letter.toUpperCase()] + 7 * (sharps - flats) + MODE_SHIFT[mode]
  if (Math.abs(fifths) > 7) return null   // a theoretical key: no signature exists, so none is drawn
  return { tonic: letter.toUpperCase() + '♯'.repeat(sharps) + '♭'.repeat(flats), mode, fifths }
}

export interface Meter { top: string; bottom: string }

/** "3/4" to its two numerals. Null for anything a time signature cannot carry as stacked digits. */
export function parseMeter(raw: string | null | undefined): Meter | null {
  const m = (raw ?? '').trim().match(/^(\d{1,2})\s*\/\s*(\d{1,2})$/)
  return m && Number(m[1]) > 0 && Number(m[2]) > 0 ? { top: m[1], bottom: m[2] } : null
}

/** The key as a musician names it: "E♭ major", "F♯ minor". */
export const keyName = (k: KeySig) => `${k.tonic} ${k.mode}`

/** "c. 6 min" from seconds, or null when the file gave no tempo to time it by. */
export function durationWords(sec: number): string | null {
  if (!sec || sec < 1) return null
  if (sec < 60) return `c. ${Math.round(sec)} s`
  return `c. ${Math.round(sec / 60)} min`
}
