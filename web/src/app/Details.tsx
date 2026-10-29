/** Details (R3, docs/design/r3/F_Details): a centred dialog for the book's identity. Title, composer, the key (the
 *  reader's guess outlined in amber), one time signature, the cover's clef, one speed with its marking, and where bar
 *  numbering starts. Save sends `PATCH /scores/{id}`; saving the key or meter confirms them, so a later reading never
 *  overwrites the owner. A book with a Digital copy keeps the bar numbers of its notation. */
import { useMemo, useState } from 'react'
import type { CoverClef, Score } from '../mock'
import { apiFailure, saveDetails, type DetailsBody } from '../lib/api'
import { useAuth } from './auth'
import { Dialog } from './Surfaces'
import { IdentityStaff } from './Identity'
import { keyName, parseKey, parseMeter } from './keysig'
import { keyInDoubt } from './r3bits'
import { useStore } from './store'

type Mode = 'major' | 'minor'
/** Around the circle of fifths, seven flats to seven sharps; spelled as the API stores them ("E-" is E flat). */
const TONICS: Record<Mode, string[]> = {
  major: ['C-', 'G-', 'D-', 'A-', 'E-', 'B-', 'F', 'C', 'G', 'D', 'A', 'E', 'B', 'F#', 'C#'],
  minor: ['A-', 'E-', 'B-', 'F', 'C', 'G', 'D', 'A', 'E', 'B', 'F#', 'C#', 'G#', 'D#', 'A#'],
}
const ACCS = ['7♭', '6♭', '5♭', '4♭', '3♭', '2♭', '1♭', '—', '1♯', '2♯', '3♯', '4♯', '5♯', '6♯', '7♯']
const TIMES = ['2/4', '3/4', '4/4', '6/8', '2/2', '3/8', '9/8', '12/8', '5/4', '7/8']
const CLEFS: { id: CoverClef; label: string; glyph: string }[] = [
  { id: 'treble', label: 'Treble', glyph: '\u{1D11E}' }, { id: 'bass', label: 'Bass', glyph: '\u{1D122}' },
  { id: 'alto', label: 'Alto', glyph: '\u{1D121}' }, { id: 'grand', label: 'Grand staff', glyph: '\u{1D11E}\u{1D122}' },
]
const shown = (t: string) => t.replace('-', '♭').replace('#', '♯')
const canon = (raw: string | undefined): string | null => {
  const k = parseKey(raw)
  if (!k) return null
  return `${k.tonic.replace('♭', '-').replace('♯', '#')} ${k.mode}`
}

export function DetailsDialog({ score, open, onClose }: { score: Score | null; open: boolean; onClose: () => void }) {
  return (
    <Dialog open={open && !!score} onClose={onClose} label="Details" className="details">
      {score && <Body key={score.id} s={score} onClose={onClose} />}
    </Dialog>
  )
}

function Body({ s, onClose }: { s: Score; onClose: () => void }) {
  const { session } = useAuth()
  const { world } = useStore()
  const doubt = keyInDoubt(s)
  const guess = canon(s.keyGuess)
  const initialKey = canon(s.key) ?? guess
  const [title, setTitle] = useState(s.title)
  const [composer, setComposer] = useState(s.composer)
  const [key, setKey] = useState<string | null>(initialKey)
  const [mode, setMode] = useState<Mode>((initialKey?.endsWith('minor') ? 'minor' : 'major'))
  const [meter, setMeter] = useState<string | null>(s.meter || s.meterGuess || null)
  const [clef, setClef] = useState<CoverClef>(s.coverClef ?? 'treble')
  const [bpm, setBpm] = useState(s.tempoBpm ? String(s.tempoBpm) : '')
  const [marking, setMarking] = useState(s.tempoText ?? '')
  const [firstBar, setFirstBar] = useState(String(s.firstBar ?? 1))
  const [firstPage, setFirstPage] = useState(String(s.firstBarPage ?? 1))
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)
  const digital = s.book === 'digital' || !!s.transcriptionPath || !!s.engravings?.length
  const times = useMemo(() => (meter && !TIMES.includes(meter) ? [...TIMES, meter] : TIMES), [meter])
  const keySig = parseKey(key)
  const met = parseMeter(meter)
  const keyUnconfirmed = doubt && key === guess

  const save = async () => {
    if (!session || !title.trim()) return
    const body: DetailsBody = {}
    if (title.trim() !== s.title) body.title = title.trim()
    if (composer.trim() !== s.composer) body.composer = composer.trim()
    // Saving confirms the signature: send it whenever it changed or was only a guess.
    if (key !== canon(s.key) || doubt) body.key_sig = key
    if (meter !== (s.meter || null) || (!s.meter && s.meterGuess && !s.sigConfirmed)) body.meter = meter
    if (clef !== (s.coverClef ?? 'treble')) body.cover_clef = clef
    const n = bpm.trim() ? Number(bpm) : null
    if (n !== (s.tempoBpm || null)) body.tempo_bpm = n
    if (marking.trim() !== (s.tempoText ?? '')) body.tempo_text = marking.trim()
    if (!digital && (Number(firstBar) !== (s.firstBar ?? 1) || Number(firstPage) !== (s.firstBarPage ?? 1))) {
      body.first_bar = Number(firstBar); body.first_bar_page = Number(firstPage)
    }
    if (!Object.keys(body).length) { onClose(); return }
    setBusy(true); setMsg(null)
    try {
      await saveDetails(s.id, body, session.access_token)
      world.reload()
      onClose()
    } catch (e) {
      setMsg(apiFailure(e, 'Saving the details'))
    } finally {
      setBusy(false)
    }
  }

  const summary = [keySig ? keyName(keySig) : 'Key not set', met ? `${met.top}/${met.bottom}` : null, bpm ? `♩ = ${bpm}` : null].filter(Boolean).join(' · ')
  const made = s.createdAt ? new Date(s.createdAt).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' }) : null
  const madeLine = [made ? `${s.book === 'pdf' ? 'Read from the scan' : 'Imported'} on ${made}` : null, s.pages && s.book === 'pdf' ? `${s.pages} ${s.pages === 1 ? 'page' : 'pages'}` : null, s.bars ? `${s.bars} bars` : null].filter(Boolean).join(' · ')

  return (
    <>
      <div className="dt-head">
        <button type="button" className="r3-btn is-quiet" onClick={onClose}>Cancel</button>
        <h2>Details</h2>
        <button type="button" className="r3-btn is-solid" disabled={busy || !title.trim()} onClick={() => void save()}>{busy ? 'Saving' : 'Save'}</button>
      </div>
      <div className="dt-body r3-scroll">
        <div className="dt-preview">
          <span className="dt-preview-staff"><IdentityStaff keySig={keySig} meter={met} unit={1.2} minWidth={262} clef={clef} label={summary} /></span>
          <span className="dt-preview-text">
            <b>{summary}</b>
            <span>This is what the cover will show.</span>
            {keyUnconfirmed && <span className="is-doubt">Key is the reader's best guess. Confirm or change it below.</span>}
          </span>
        </div>
        {msg && <p className="r3-msg" role="alert">{msg}</p>}

        <div className="dt-grid2">
          <label className="dt-field"><span className="r3-label">Title</span><input className="dt-input is-serif" value={title} onChange={e => setTitle(e.target.value)} maxLength={200} /></label>
          <label className="dt-field"><span className="r3-label">Composer</span><input className="dt-input is-serif" value={composer} onChange={e => setComposer(e.target.value)} maxLength={200} /></label>
        </div>

        <div className="dt-field">
          <div className="dt-row">
            <span className="r3-label">Key</span>
            <div className="r3-seg dt-mini-seg" role="tablist" aria-label="Mode">
              {(['major', 'minor'] as Mode[]).map(m => (
                <button key={m} type="button" role="tab" aria-selected={mode === m} onClick={() => { setMode(m); if (key) { const i = TONICS[mode].indexOf(key.split(' ')[0]); setKey(i >= 0 ? `${TONICS[m][i]} ${m}` : null) } }}>{m === 'major' ? 'Major' : 'Minor'}</button>
              ))}
            </div>
          </div>
          <div className="dt-keys" role="radiogroup" aria-label="Key">
            {TONICS[mode].map((t, i) => {
              const v = `${t} ${mode}`
              const on = key === v
              return (
                <button key={v} type="button" role="radio" aria-checked={on} className={`dt-key ${v === guess && doubt ? 'is-guess' : ''}`} onClick={() => setKey(v)} aria-label={`${shown(t)} ${mode}${v === guess && doubt ? ', the reader’s guess' : ''}`}>
                  <b>{shown(t)}</b><span>{ACCS[i]}</span>
                </button>
              )
            })}
          </div>
          {doubt && guess && <span className="dt-hint">Outlined in amber: the reader's guess. Tap it to confirm, or pick another.</span>}
        </div>

        <div className="dt-grid2">
          <div className="dt-field">
            <span className="r3-label">Time signature</span>
            <div className="dt-times" role="radiogroup" aria-label="Time signature">
              {times.map(t => {
                const [n, d] = t.split('/')
                return <button key={t} type="button" role="radio" aria-checked={meter === t} className={`dt-time ${t === s.meterGuess && !s.meter && !s.sigConfirmed ? 'is-guess' : ''}`} onClick={() => setMeter(t)} aria-label={`${n} ${d}`}><b>{n}</b><b>{d}</b></button>
              })}
            </div>
            <span className="dt-hint">One time signature for the whole book.</span>
          </div>
          <div className="dt-field">
            <span className="r3-label">Clef on the cover</span>
            <div className="dt-clefs" role="radiogroup" aria-label="Clef">
              {CLEFS.map(c => <button key={c.id} type="button" role="radio" aria-checked={clef === c.id} aria-label={c.label} className={`dt-clef is-${c.id}`} onClick={() => setClef(c.id)}>{c.glyph}</button>)}
            </div>
            <span className="dt-hint">Only the cover uses this; the pages keep their own clefs.</span>
          </div>
        </div>

        <div className="dt-grid2">
          <div className="dt-field">
            <span className="r3-label">Speed</span>
            <div className="dt-inline">
              <span className="dt-note" aria-hidden="true">♩</span><span className="dt-eq">=</span>
              <input className="dt-input is-serif is-num" aria-label="Beats per minute" inputMode="numeric" value={bpm} onChange={e => setBpm(e.target.value.replace(/\D/g, '').slice(0, 3))} placeholder="—" />
              <input className="dt-input is-serif is-italic" aria-label="Tempo marking" value={marking} onChange={e => setMarking(e.target.value)} placeholder="Andante" maxLength={60} />
            </div>
            <span className="dt-hint">One speed for the whole book. Practise uses it for the metronome.</span>
          </div>
          <div className="dt-field">
            <span className="r3-label">Bar numbering</span>
            <div className="dt-inline">
              <span>Bar</span>
              <input className="dt-input is-serif is-num" aria-label="First bar number" inputMode="numeric" value={firstBar} disabled={digital} onChange={e => setFirstBar(e.target.value.replace(/[^\d]/g, '').slice(0, 4))} />
              <span>starts on page</span>
              <input className="dt-input is-serif is-num" aria-label="Page of the first bar" inputMode="numeric" value={firstPage} disabled={digital} onChange={e => setFirstPage(e.target.value.replace(/\D/g, '').slice(0, 3))} />
            </div>
            <span className="dt-hint">{digital ? 'The Digital copy keeps the bar numbers of its notation.' : "Later pages continue from the previous page's last bar."}</span>
          </div>
        </div>

        <span className="dt-foot">{madeLine ? `${madeLine}. ` : ''}Anything here can be changed later from the book.</span>
      </div>
    </>
  )
}
