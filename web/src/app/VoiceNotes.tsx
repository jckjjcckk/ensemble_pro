/** Voice notes on the Stand (013): the push-to-talk button, the tray of proposed marks, and their ghosts on the page.
 *  Only the admin who leads the layer on screen sees any of it (players never receive proposed rows). Muse blue
 *  (`--muse`) appears here and nowhere else: it means Muse is listening or proposing. Glass values from
 *  docs/design liquid_glass M5_GlassSurface (frost, rim, the lit-from-inside glow driven by `--level`, the wash). */
import { useEffect, useRef, useState, type KeyboardEvent as ReactKeyboardEvent, type PointerEvent as ReactPointerEvent } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { startRecording, MicError, type Recorder } from '../lib/recorder'
import { tap } from '../lib/native'
import { spanRects, type Geo } from './geometry'
import { KindIcon } from './marks'
import { barRange, kindLabel } from './store'
import { IClose, IMic } from './icons'
import { Sheet } from './Sheet'
import { sameWho, type MarkInsert, type MarkPatch, type Who } from './ink'
import { acceptWrites, cutText, type Card, type Draft, type Group, type Roster, type useVoice } from './voice'
import './voice.css'

type Voice = ReturnType<typeof useVoice>
/** Writes a card's rows in one transaction; resolves to why it did not, or null. */
type Commit = (w: { remove?: string[]; update?: MarkPatch[]; insert?: MarkInsert[] }) => Promise<string | null>

/** A hold shorter than this is a tap: nothing is sent. */
const HOLD_MS = 400
const stamp = () => Date.now()
const clock = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`
const timeOf = (ms: number) => new Date(ms).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
const placeOf = (from: number | null, to: number | null) => (from == null ? 'no bar yet' : `${to != null && to !== from ? 'bars' : 'bar'} ${barRange(from, to ?? from)}`)

/** The glass layers every Muse surface shares: tint, the Muse glow, the wash, a glint and the rim. */
function GlassLayers() {
  return (
    <>
      <span className="v-glow" aria-hidden="true" />
      <span className="v-wash" aria-hidden="true" />
      <span className="v-glint" aria-hidden="true" />
      <span className="v-rim" aria-hidden="true" />
    </>
  )
}

// ---------------------------------------------------------------- the button

type Mode = 'idle' | 'listening' | 'hint' | 'mic'

const micWords = (e: unknown) => {
  const p = e instanceof MicError ? e.problem : 'failed'
  return p === 'denied' ? 'The microphone is off for Folio. Turn it on in Settings.'
    : p === 'unavailable' ? 'This device has no microphone Folio can use.'
      : 'The microphone could not be opened.'
}

/**
 * Hold to speak: the microphone opens on pointer-down and the take is sent on release. A hold shorter than 400 ms is
 * a tap and only says how it works. While listening the glass lights up in Muse blue with the voice; while the
 * librarian places the note a wash drifts through it. Errors say what happened in one line, with a retry.
 */
export function VoiceButton({ voice, reduced, lifted, under, onListening, onOpen }: {
  voice: Voice; reduced: boolean; lifted: boolean
  /** The tray is open over it: kept mounted (a take in progress goes on), out of sight. */
  under: boolean
  onListening?: (on: boolean) => void
  onOpen: () => void
}) {
  const [mode, setMode] = useState<Mode>('idle')
  const [sec, setSec] = useState(0)
  const [micMsg, setMicMsg] = useState<string | null>(null)
  /** The finished take whose words have left the button. */
  const [spent, setSpent] = useState<string | null>(null)
  const pill = useRef<HTMLButtonElement>(null)
  const take = useRef<{ t0: number; rec: Recorder | null; ended: boolean } | null>(null)
  const reducedRef = useRef(reduced)
  useEffect(() => { reducedRef.current = reduced })

  const setLevel = (v: number) => pill.current?.style.setProperty('--level', reducedRef.current ? '0.4' : v.toFixed(3))

  const begin = () => {
    if (take.current) return
    const t = { t0: stamp(), rec: null as Recorder | null, ended: false }
    take.current = t
    setMode('listening'); setSec(0); setMicMsg(null); setSpent(voice.latest?.key ?? null); setLevel(0)
    void tap()
    startRecording({ onLevel: setLevel, onLimit: () => { if (take.current === t) void end() } }).then(
      rec => { if (t.ended) rec.cancel(); else t.rec = rec },
      e => {
        if (take.current === t) take.current = null
        t.ended = true
        setMicMsg(micWords(e)); setMode('mic')
      },
    )
  }

  const end = async () => {
    const t = take.current
    if (!t) return
    take.current = null
    t.ended = true
    const held = stamp() - t.t0
    // Released before the microphone opened (the permission prompt, or a quick tap): nothing to send.
    if (!t.rec) { setMode(held < HOLD_MS ? 'hint' : 'idle'); return }
    if (held < HOLD_MS) { t.rec.cancel(); setMode('hint'); return }
    const r = await t.rec.stop()
    setMode('idle')
    if (r.seconds < 0.3) { setMode('hint'); return }
    voice.send(r)
  }

  // Leaving the Stand mid-take lets the microphone go, also when it is still opening (`begin` cancels it on arrival).
  useEffect(() => () => {
    const t = take.current
    take.current = null
    if (t) { t.ended = true; t.rec?.cancel() }
  }, [])

  useEffect(() => {
    if (mode !== 'listening') return
    const id = window.setInterval(() => setSec(take.current?.rec?.elapsed() ?? 0), 250)
    return () => window.clearInterval(id)
  }, [mode])
  useEffect(() => {
    if (mode !== 'hint') return
    const id = window.setTimeout(() => setMode('idle'), 1800)
    return () => window.clearTimeout(id)
  }, [mode])

  // A take that comes back with nothing to mark says so on the button for a moment.
  const latest = voice.latest
  const doneKey = latest?.phase === 'done' ? latest.key : null
  const count = (latest?.result?.proposed ?? 0) + (latest?.result?.unplaced.length ?? 0)
  const flash = doneKey && spent !== doneKey ? (count ? `${count} ${count === 1 ? 'mark' : 'marks'} to check` : 'Nothing to mark') : null
  useEffect(() => {
    if (!doneKey) return
    const id = window.setTimeout(() => setSpent(doneKey), 2600)
    return () => window.clearTimeout(id)
  }, [doneKey])

  const listenRef = useRef(onListening)
  useEffect(() => { listenRef.current = onListening })
  useEffect(() => { listenRef.current?.(mode === 'listening') }, [mode])

  const working = mode !== 'listening' && !!latest && (latest.phase === 'sending' || latest.phase === 'queued' || latest.phase === 'running')
  const failed = mode !== 'listening' && latest?.phase === 'failed' && !latest.closed ? latest : null
  const state = mode === 'listening' ? 'listening' : working ? 'working' : 'idle'

  const onDown = (e: ReactPointerEvent<HTMLButtonElement>) => {
    if (e.button > 0) return
    e.preventDefault()
    e.currentTarget.setPointerCapture?.(e.pointerId)
    begin()
  }
  const onKeyDown = (e: ReactKeyboardEvent) => { if ((e.key === ' ' || e.key === 'Enter') && !e.repeat) { e.preventDefault(); begin() } }
  const onKeyUp = (e: ReactKeyboardEvent) => { if (e.key === ' ' || e.key === 'Enter') { e.preventDefault(); void end() } }

  const line = mode === 'mic' ? micMsg : failed?.problem?.message ?? null

  return (
    <div className={`v-dock ${lifted ? 'is-lifted' : ''} ${under ? 'is-under' : ''}`} aria-hidden={under || undefined}>
      <AnimatePresence>
        {mode === 'hint' && (
          <motion.p key="hint" className="v-say" role="status"
            initial={{ opacity: 0, y: reduced ? 0 : 4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} transition={{ duration: 0.16 }}>
            Hold to speak
          </motion.p>
        )}
        {line && mode !== 'hint' && (
          <motion.div key="err" className="v-say is-problem" role="alert"
            initial={{ opacity: 0, y: reduced ? 0 : 4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} transition={{ duration: 0.16 }}>
            <span>{line}</span>
            {failed?.wav && <button type="button" className="v-say-btn" onClick={() => void voice.retry(failed.key)}>Send again</button>}
            {mode === 'mic' && <button type="button" className="v-say-btn" onClick={() => { setMicMsg(null); setMode('idle') }}>Try again</button>}
            {failed && <button type="button" className="v-say-x" aria-label="Put it away" onClick={() => voice.close(failed.key)}><IClose size={16} /></button>}
          </motion.div>
        )}
      </AnimatePresence>
      <div className="v-row">
        {voice.waiting > 0 && state !== 'listening' && (
          <button type="button" className="vglass v-count" onClick={onOpen} aria-label={`${voice.waiting} proposed ${voice.waiting === 1 ? 'mark' : 'marks'} to check`}>
            <GlassLayers /><span className="v-count-n num">{voice.waiting}</span><span>to check</span>
          </button>
        )}
        <button
          ref={pill} type="button" className="vglass v-pill" data-state={state}
          aria-label={state === 'listening' ? `Listening, ${clock(sec)}. Let go to send` : 'Voice note: hold to speak, let go to send'}
          onPointerDown={onDown} onPointerUp={() => void end()} onPointerCancel={() => void end()} onLostPointerCapture={() => void end()}
          onKeyDown={onKeyDown} onKeyUp={onKeyUp} onContextMenu={e => e.preventDefault()}
        >
          <GlassLayers />
          {/* The clock is in the label; announcing it would read every tick. */}
          <span className="v-pill-in" aria-live={state === 'listening' ? 'off' : 'polite'}>
            {state === 'listening' ? <><span className="v-dot" aria-hidden="true" /><span className="v-time num">{clock(sec)}</span></>
              : state === 'working' ? <span>{latest?.retrying ? 'Trying again…' : 'Placing your note…'}</span>
                : flash ? <span>{flash}</span>
                  : <><IMic size={20} />Hold to speak</>}
          </span>
        </button>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------- ghosts on the page

/** A proposed mark on the page: a small glass lens over its bars (one per system line), lit in Muse blue, labelled
 *  "proposed · 42". A tap opens its card in the tray. Accepted, it becomes the ordinary mark; dismissed, it fades. */
export function VoiceGhosts({ geo, cards, focus, onOpen }: { geo: Geo; cards: Card[]; focus: string | null; onOpen: (key: string) => void }) {
  const lenses = cards.flatMap(c => (c.barFrom == null ? [] : spanRects(geo, c.barFrom, c.barTo ?? c.barFrom).map((r, i) => ({ c, r, i }))))
  // A ghost lets the pointer through to the spread's drag; only a press that stays put (a tap) opens its card.
  const down = useRef<{ x: number; y: number } | null>(null)
  return (
    <AnimatePresence>
      {lenses.map(({ c, r, i }) => (
        <motion.button
          key={`${c.key}:${r.first}`} type="button" className={`vglass v-ghost ${focus === c.key ? 'is-focus' : ''}`}
          style={{ left: r.x - 3, top: r.y - 12, width: r.w + 6, height: r.h + 24 }}
          initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0, transition: { duration: 0.18 } }} transition={{ duration: 0.16 }}
          onPointerDown={e => { down.current = { x: e.clientX, y: e.clientY } }}
          onClick={e => {
            e.stopPropagation()
            const d = down.current
            down.current = null
            if (!d || Math.hypot(e.clientX - d.x, e.clientY - d.y) < 10) onOpen(c.key)
          }}
          aria-label={`Proposed ${kindLabel[c.kind].toLowerCase()}, ${placeOf(c.barFrom, c.barTo)}: ${c.body}. Open it in voice notes`}
        >
          <GlassLayers />
          {i === 0 && <span className="v-ghost-label">proposed · <span className="num">{barRange(c.barFrom!, c.barTo ?? c.barFrom!)}</span></span>}
        </motion.button>
      ))}
    </AnimatePresence>
  )
}

// ---------------------------------------------------------------- the tray

const whoLabel = (w: Who, roster: Roster) =>
  w.audience === 'ensemble' ? 'Everyone' : w.audience === 'part' ? w.part : roster.members.find(m => m.id === w.member)?.name ?? 'One player'

/**
 * The queue of what Muse proposed on this score in this visit, newest first. A group is one take: what was heard (in
 * quotes) and its time; under it one card per mark with its kind, place, the stand text, who it is for and the words
 * it came from. Accept sends it to the stands, Edit changes text, bars and audience first, Dismiss drops it.
 */
export function VoiceTray({ open, onClose, voice, commit, roster, lastBar, focus, onShow, onPick }: {
  open: boolean; onClose: () => void; voice: Voice; commit: Commit; roster: Roster
  /** The book's last bar: the bar steppers stop there. */
  lastBar?: number
  focus: string | null
  onShow: (c: Card) => void; onPick: (c: Card) => void
}) {
  // Each edited card's draft, with the bar it was drafted on: an unplaced item given another bar takes the new one.
  const [drafts, setDrafts] = useState<Record<string, Draft & { at: number | null }>>({})
  const [busy, setBusy] = useState<Set<string>>(() => new Set())
  // Read and written at once (Accept all runs cards in a row): state alone would let a second tap through.
  const busyNow = useRef(new Set<string>())
  /** Why a card's last write did not go through. */
  const [failed, setFailed] = useState<Record<string, string>>({})
  const scroller = useRef<HTMLDivElement>(null)

  // Opened at a ghost: its card comes into view.
  useEffect(() => {
    if (!open || !focus) return
    const id = window.setTimeout(() => scroller.current?.querySelector(`[data-card="${CSS.escape(focus)}"]`)?.scrollIntoView({ block: 'nearest', behavior: 'smooth' }), 240)
    return () => window.clearTimeout(id)
  }, [open, focus])

  const draftOf = (c: Card): Draft => {
    const own = drafts[c.key]
    const bars = { barFrom: c.barFrom ?? 0, barTo: c.barTo ?? c.barFrom ?? 0 }
    if (!own) return { body: c.body, ...bars, who: c.who.length ? c.who : [{ audience: 'ensemble' }] }
    return own.at === c.barFrom ? own : { ...own, ...bars }
  }
  const setDraft = (c: Card, d: Partial<Draft>) => setDrafts(x => ({ ...x, [c.key]: { ...draftOf(c), ...d, at: c.barFrom } }))
  const setBusyOn = (key: string, on: boolean) => {
    if (on) busyNow.current.add(key); else busyNow.current.delete(key)
    setBusy(new Set(busyNow.current))
  }
  const setReason = (key: string, why: string | null) => setFailed(x => {
    const { [key]: _, ...rest } = x
    return why ? { ...rest, [key]: why } : rest
  })

  const settled = (g: Group, c: Card) => {
    if (c.unplaced) voice.dropUnplaced(c.unplaced.takeKey, c.unplaced.id)
    if (g.take) voice.settle(g.take.key)
    setDrafts(x => Object.fromEntries(Object.entries(x).filter(([k]) => k !== c.key)))
  }
  const accept = async (g: Group, c: Card) => {
    if (c.barFrom == null || busyNow.current.has(c.key)) return
    setBusyOn(c.key, true); setReason(c.key, null)
    const why = await commit(acceptWrites(c, draftOf(c), g.take?.utteranceId ?? (c.rows[0]?.payload?.utterance_id as string | undefined) ?? null))
    setBusyOn(c.key, false)
    if (why == null) settled(g, c); else setReason(c.key, why)
  }
  const dismiss = async (g: Group, c: Card) => {
    if (busyNow.current.has(c.key)) return
    if (!c.rows.length) { settled(g, c); return }
    setBusyOn(c.key, true); setReason(c.key, null)
    const why = await commit({ remove: c.rows.map(r => r.id) })
    setBusyOn(c.key, false)
    if (why == null) settled(g, c); else setReason(c.key, why)
  }
  const acceptAll = async (g: Group) => { for (const c of g.cards) if (c.barFrom != null) await accept(g, c) }

  // Not raised over the header (unlike Markings): in portrait it rises half-way, so the bar a card shows stays in view.
  return (
    <Sheet open={open} onClose={onClose} label="Voice notes" className="v-tray">
      <div className="side-head">
        <h2>Voice notes {voice.waiting > 0 && <span className="count">{voice.waiting}</span>}</h2>
        <button type="button" className="btn-icon" onClick={onClose} aria-label="Close voice notes"><IClose size={20} /></button>
      </div>
      <div className="side-scroll" ref={scroller}>
        {voice.groups.length === 0 && <p className="side-sub">Hold the voice button and say what the stands should mark: “Second violins, from 42 to 48 we’re cutting that.” Nothing reaches anyone until you accept it.</p>}
        <ol className="v-groups">
          {voice.groups.map(g => {
            const t = g.take
            const pending = t && (t.phase === 'sending' || t.phase === 'queued' || t.phase === 'running')
            const placing = pending || (t?.phase === 'done' && !g.cards.length && (t.result?.proposed ?? 0) > 0 && t.settled === 0)
            const nothing = t?.phase === 'done' && !g.cards.length && !placing
            const ready = g.cards.filter(c => c.barFrom != null)
            return (
              <li key={g.key} className="v-group">
                <div className="v-group-head">
                  <p className="v-heard">{g.transcript ? `“${g.transcript}”` : placing ? (t?.retrying ? 'Trying again…' : 'Placing your note…') : t?.phase === 'failed' ? 'Not heard' : 'Earlier'}</p>
                  <span className="v-muse">Muse · {timeOf(g.at)}</span>
                </div>
                {placing && g.transcript && <p className="v-group-msg">{t?.retrying ? 'Trying again…' : 'Placing your note…'}</p>}
                {t?.phase === 'failed' && (
                  <div className="v-group-msg is-problem">
                    <span>{t.problem?.message ?? 'Couldn’t use that recording.'}</span>
                    {t.wav && <button type="button" className="btn btn-line is-small" onClick={() => void voice.retry(t.key)}>Send again</button>}
                    <button type="button" className="btn btn-quiet is-small" onClick={() => voice.close(t.key)}>Dismiss</button>
                  </div>
                )}
                {nothing && (
                  <div className="v-group-msg">
                    <span>Nothing to mark</span>
                    <button type="button" className="btn btn-quiet is-small" onClick={() => voice.close(t!.key)}>Dismiss</button>
                  </div>
                )}
                {g.refused.length > 0 && <p className="v-refused">Left out: {g.refused.join('; ')}</p>}
                {g.cards.map(c => (
                  <VoiceCard
                    key={c.key} card={c} draft={draftOf(c)} roster={roster} lastBar={lastBar} focused={focus === c.key} busy={busy.has(c.key)} failed={failed[c.key] ?? null}
                    onDraft={d => setDraft(c, d)} onShow={() => onShow(c)} onPick={() => onPick(c)}
                    onAccept={() => void accept(g, c)} onDismiss={() => void dismiss(g, c)}
                  />
                ))}
                {ready.length > 1 && (
                  <button type="button" className="btn btn-line v-all" onClick={() => void acceptAll(g)} disabled={ready.some(c => busy.has(c.key))}>
                    Accept all {ready.length}
                  </button>
                )}
              </li>
            )
          })}
        </ol>
      </div>
    </Sheet>
  )
}

function VoiceCard({ card: c, draft: d, roster, lastBar, focused, busy, failed, onDraft, onShow, onPick, onAccept, onDismiss }: {
  card: Card; draft: Draft; roster: Roster; lastBar?: number; focused: boolean; busy: boolean; failed: string | null
  onDraft: (d: Partial<Draft>) => void; onShow: () => void; onPick: () => void; onAccept: () => void; onDismiss: () => void
}) {
  const [editing, setEditing] = useState(false)
  const [picking, setPicking] = useState(false)
  const placed = c.barFrom != null
  const from = placed ? d.barFrom : null
  const to = placed ? d.barTo : null
  const canAddress = roster.parts.length > 0 || roster.members.length > 0

  const toggle = (w: Who) => {
    if (w.audience === 'ensemble') { onDraft({ who: [w] }); return }
    const cur = d.who.filter(x => x.audience !== 'ensemble')
    const next = cur.some(x => sameWho(x, w)) ? cur.filter(x => !sameWho(x, w)) : [...cur, w]
    onDraft({ who: next.length ? next : [{ audience: 'ensemble' }] })
  }
  const has = (w: Who) => d.who.some(x => sameWho(x, w))
  const top = lastBar && lastBar > 0 ? lastBar : Infinity
  const step = (which: 'barFrom' | 'barTo', by: number) => {
    const f = which === 'barFrom' ? Math.min(top, Math.max(1, d.barFrom + by)) : d.barFrom
    const t = Math.min(top, which === 'barTo' ? Math.max(f, d.barTo + by) : Math.max(f, d.barTo))
    // A cut's text that only names its bars ("Cut 42–48") moves with them.
    onDraft({ barFrom: f, barTo: t, body: cutText(c.kind, d.body, f, t) })
  }

  return (
    <article
      className={`vglass v-card ${focused ? 'is-focus' : ''} ${busy ? 'is-busy' : ''}`} data-card={c.key} aria-busy={busy}
      onClick={e => { if (placed && !(e.target as HTMLElement).closest('button, input, label')) onShow() }}
    >
      <GlassLayers />
      <div className="v-card-head">
        <span className="v-kind"><KindIcon kind={c.kind} size={15} />{c.unplaced ? 'Heard this, couldn’t place it' : kindLabel[c.kind]}</span>
        {placed
          ? <button type="button" className="v-place num" onClick={c.unplaced ? onPick : onShow} aria-label={c.unplaced ? `${placeOf(from, to)}. Tap another bar` : `Show ${placeOf(from, to)}`}>{placeOf(from, to)}</button>
          : <span className="v-place is-none">{c.unplaced?.item.position || 'no bar yet'}</span>}
      </div>

      {editing
        ? <input className="v-input" value={d.body} onChange={e => onDraft({ body: e.target.value })} aria-label="Mark text" autoFocus />
        : <p className="v-text">{d.body || kindLabel[c.kind]}</p>}

      {editing && placed && (
        <div className="v-bars" role="group" aria-label="Bars">
          {(['barFrom', 'barTo'] as const).map(k => (
            <div key={k} className="v-step">
              <span className="r3-label">{k === 'barFrom' ? 'From' : 'To'}</span>
              <button type="button" className="v-step-btn" onClick={() => step(k, -1)} disabled={d[k] <= (k === 'barTo' ? d.barFrom : 1)} aria-label={`${k === 'barFrom' ? 'First' : 'Last'} bar earlier`}>−</button>
              <span className="num v-step-val">{d[k]}</span>
              <button type="button" className="v-step-btn" onClick={() => step(k, 1)} disabled={d[k] >= top} aria-label={`${k === 'barFrom' ? 'First' : 'Last'} bar later`}>+</button>
            </div>
          ))}
        </div>
      )}

      <div className="v-who" role="group" aria-label="Who it is for">
        {d.who.map(w => <button key={w.audience === 'part' ? w.part : w.audience === 'member' ? w.member : 'all'} type="button" className="v-chip is-on" onClick={() => setPicking(p => !p)} disabled={!canAddress}>{whoLabel(w, roster)}</button>)}
        {canAddress && <button type="button" className="v-chip" aria-expanded={picking} onClick={() => setPicking(p => !p)}>{picking ? 'Done' : 'Change…'}</button>}
      </div>
      {picking && (
        <div className="v-pick-list" role="group" aria-label="Send to">
          <button type="button" className="v-chip" aria-pressed={has({ audience: 'ensemble' })} onClick={() => toggle({ audience: 'ensemble' })}>Everyone</button>
          {roster.parts.map(p => <button key={p} type="button" className="v-chip" aria-pressed={has({ audience: 'part', part: p })} onClick={() => toggle({ audience: 'part', part: p })}>{p}</button>)}
          {roster.members.map(m => <button key={m.id} type="button" className="v-chip is-person" aria-pressed={has({ audience: 'member', member: m.id })} onClick={() => toggle({ audience: 'member', member: m.id })}>{m.name}</button>)}
        </div>
      )}

      {c.quote && <blockquote className="v-quote">“{c.quote}”</blockquote>}
      {failed && <p className="r3-msg" role="alert">Not saved. {failed.replace(/\.?$/, '.')} Try again.</p>}

      <div className="v-acts">
        {placed ? <>
          <button type="button" className="v-btn is-accept" onClick={onAccept} disabled={busy}>Accept</button>
          <button type="button" className="v-btn" aria-pressed={editing} onClick={() => setEditing(v => !v)}>{editing ? 'Done' : 'Edit'}</button>
        </> : <button type="button" className="v-btn is-accept" onClick={onPick}>Tap a bar</button>}
        <button type="button" className="v-btn is-quiet" onClick={onDismiss} disabled={busy}>Dismiss</button>
      </div>
    </article>
  )
}

/** Choosing the bar for something Muse heard but could not place: the stage takes the next bar tap. */
export function PickHint({ card, reduced, onCancel }: { card: Card | null; reduced: boolean; onCancel: () => void }) {
  const y = reduced ? 0 : 8
  return (
    <AnimatePresence>
      {card && (
        <motion.div key="pick" className="vglass v-pickhint is-lit" role="status" initial={{ opacity: 0, y, x: '-50%' }} animate={{ opacity: 1, y: 0, x: '-50%' }} exit={{ opacity: 0, y, x: '-50%' }} transition={{ duration: 0.16 }}>
          <GlassLayers />
          <span className="v-pickhint-text">Tap the bar for “{card.quote || card.body}”</span>
          <button type="button" className="v-btn is-quiet" onClick={onCancel}>Cancel</button>
        </motion.div>
      )}
    </AnimatePresence>
  )
}
