/** A book's identity, engraved: a short treble staff with the key signature and the time signature, then its length.
 *  The signature is drawn only when it is known and valid. A PDF book whose read has not landed shows the bare staff
 *  with the signature's place left empty, never a guess. Glyphs are VexFlow's Gonville outlines (engraving.ts), the
 *  same face OpenSheetMusicDisplay uses on the stage; every stroke and fill is `currentColor`, so the theme's ink draws it. */
import { useId } from 'react'
import type { Score } from '../mock'
import { GLYPHS, type Glyph } from './engraving'
import { durationWords, keyName, parseKey, parseMeter, type KeySig, type Meter } from './keysig'

// ---------------------------------------------------------------- the staff

/** Treble-clef lines of each accidental, top line 0, half a space per step (VexFlow's own order and placement). */
const SHARP_LINES = [0, 1.5, -0.5, 1, 2.5, 0.5, 2]
const FLAT_LINES = [2, 0.5, 2.5, 1, 3, 1.5, 3.5]

const SP = 10          // one staff space in glyph units
const CLEF_X = 4
const AFTER_CLEF = 9
const ACC_GAP = 2.4
const AFTER_KEY = 9
const TAIL = 60        // staff run after the signature; it fades out, the music continues off the plate
const TOP = -17        // room above the top line for the clef's head
const BOTTOM = 4 * SP + 17

function digitsWidth(s: string) {
  return [...s].reduce((w, d) => w + (GLYPHS[`digit${d}` as keyof typeof GLYPHS] as Glyph).w, 0)
}

function Digits({ text, x, y, width }: { text: string; x: number; y: number; width: number }) {
  const glyphs = [...text].map(d => GLYPHS[`digit${d}` as keyof typeof GLYPHS] as Glyph)
  const starts: number[] = []
  for (let i = 0, cx = x + (width - digitsWidth(text)) / 2; i < glyphs.length; cx += glyphs[i].w, i++) starts.push(cx)
  return <>{glyphs.map((g, i) => <path key={i} d={g.d} transform={`translate(${starts[i] - g.x0} ${y})`} />)}</>
}

/** The plate itself. `unit` is CSS px per glyph unit (1.1 draws an 11 px staff space). */
export function IdentityStaff({ keySig, meter, unit = 1.1, label }: { keySig: KeySig | null; meter: Meter | null; unit?: number; label: string }) {
  const fadeId = useId().replace(/:/g, '')
  const accs = keySig ? (keySig.fifths > 0 ? SHARP_LINES.slice(0, keySig.fifths).map(line => ({ line, g: GLYPHS.sharp })) : FLAT_LINES.slice(0, -keySig.fifths).map(line => ({ line, g: GLYPHS.flat }))) : []

  const keyX = CLEF_X + GLYPHS.gClef.w + AFTER_CLEF
  // One accidental glyph per signature, so each sits a fixed advance from the last.
  const placed = accs.map((a, i) => ({ ...a, x: keyX + i * (a.g.w + ACC_GAP) }))
  const tsX = placed.length ? keyX + placed.length * (placed[0].g.w + ACC_GAP) - ACC_GAP + AFTER_KEY : keyX
  const tsW = meter ? Math.max(digitsWidth(meter.top), digitsWidth(meter.bottom)) : 0
  // With no signature yet the plate keeps a signature's room, so the box does not jump when the read lands.
  const sigEnd = keySig || meter ? tsX + tsW : tsX + 30
  const W = sigEnd + TAIL
  const H = BOTTOM - TOP

  return (
    <svg
      className="id-staff" viewBox={`0 ${TOP} ${W} ${H}`} width={Math.round(W * unit)} height={Math.round(H * unit)}
      role="img" aria-label={label} fill="currentColor"
    >
      <defs>
        <linearGradient id={`${fadeId}-g`} x1="0" x2="1" y1="0" y2="0">
          <stop offset={(W - 32) / W} stopColor="#fff" />
          <stop offset="1" stopColor="#fff" stopOpacity="0" />
        </linearGradient>
        <mask id={`${fadeId}-m`} maskUnits="userSpaceOnUse" x="0" y={TOP} width={W} height={H}>
          <rect x="0" y={TOP} width={W} height={H} fill={`url(#${fadeId}-g)`} />
        </mask>
      </defs>
      <g mask={`url(#${fadeId}-m)`} stroke="currentColor" strokeWidth={0.85} shapeRendering="geometricPrecision">
        {[0, 1, 2, 3, 4].map(i => <line key={i} x1={0} x2={W} y1={i * SP} y2={i * SP} />)}
      </g>
      <path d={GLYPHS.gClef.d} transform={`translate(${CLEF_X - GLYPHS.gClef.x0} ${3 * SP})`} />
      {placed.map((a, i) => <path key={i} d={a.g.d} transform={`translate(${a.x - a.g.x0} ${a.line * SP})`} />)}
      {meter && (
        <>
          <Digits text={meter.top} x={tsX} y={2 * SP} width={tsW} />
          <Digits text={meter.bottom} x={tsX} y={4 * SP} width={tsW} />
        </>
      )}
    </svg>
  )
}

// ---------------------------------------------------------------- the block in the information box

/** Key, meter and length, leading the information box. Length is bars; a digital book also gives its duration. */
export function Identity({ score: s, digital }: { score: Score; digital: boolean }) {
  const keySig = parseKey(s.key)
  const meter = parseMeter(s.meter)
  const duration = digital ? durationWords(s.durationSec) : null
  const label = [keySig ? keyName(keySig) : null, meter ? `${meter.top}/${meter.bottom} time` : null].filter(Boolean).join(', ')
  return (
    <div className="identity">
      <figure className="id-plate">
        <IdentityStaff keySig={keySig} meter={meter} label={label || 'Staff, signature not read yet'} />
        {keySig && <figcaption className="id-key">{keyName(keySig)}</figcaption>}
      </figure>
      {s.bars > 0 && (
        <p className="id-length">
          <span className="id-bars num">{s.bars}</span>
          <span className="id-unit">{s.bars === 1 ? 'bar' : 'bars'}</span>
          {duration && <span className="id-dur">{duration}</span>}
        </p>
      )}
    </div>
  )
}
