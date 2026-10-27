import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type FormEvent,
  type ReactNode,
} from 'react'
import { Link, useParams } from 'react-router'
import {
  fmtDuration,
  membersById,
  partsById,
  scoresById,
  type Annotation,
  type Member,
  type Part,
  type Role,
  type Score,
} from '../shared'
import {
  Book,
  PartTabs,
  boxStyle,
  pagesLabel,
  pct,
  segments,
  useEngraving,
  usePager,
  type BookLayout,
  type TabSpec,
} from './engraving'
import {
  IconChevronLeft,
  IconChevronRight,
  IconClose,
  IconCut,
  IconList,
  IconMic,
  IconPause,
  IconPencil,
  IconPlay,
  IconText,
  KindIcon,
} from './icons'
import {
  KIND_LABEL,
  appliesTo,
  barRange,
  ensembleOfScore,
  firstName,
  fmtDate,
  initials,
  memberForRole,
  pinText,
} from './model'
import { useX4 } from './state'

type Tool = 'marking' | 'cut' | 'voice' | 'text'

interface Draft {
  kind: Tool
  from: number
  to: number
  awaitingEnd: boolean
  scope: string | null
  text: string
  seconds: number
  recording: boolean
}

const TOOLS: { key: Tool; label: string; hint: string; Icon: typeof IconPencil }[] = [
  { key: 'marking', label: 'Pencil', hint: 'Pencil a marking on a bar', Icon: IconPencil },
  { key: 'cut', label: 'Cut', hint: 'Cut a range of bars for every part', Icon: IconCut },
  { key: 'voice', label: 'Voice note', hint: 'Record a spoken note on a bar', Icon: IconMic },
  { key: 'text', label: 'Note', hint: 'Write a note on a bar', Icon: IconText },
]

const TOOL_NOUN: Record<Tool, string> = { marking: 'pencil marking', cut: 'cut', voice: 'voice note', text: 'note' }
const COMPOSER_TITLE: Record<Tool, string> = {
  marking: 'New pencil marking',
  cut: 'New cut',
  voice: 'New voice note',
  text: 'New note',
}
const SAVE_LABEL: Record<Tool, string> = {
  marking: 'Add marking',
  cut: 'Cut these bars',
  voice: 'Send voice note',
  text: 'Add note',
}
const PLACEHOLDER: Record<Tool, string> = {
  marking: 'For example: breathe before the upbeat',
  cut: 'For example: agreed at Saturday’s rehearsal',
  voice: '',
  text: 'What should the part know?',
}

export function ScoreRoute() {
  const { id = '' } = useParams()
  const score = scoresById[id]
  if (!score) return <Unavailable title="Not in the library" body={`No score with the id “${id}” is in this library.`} />
  if (score.status !== 'ready' || !score.fixture) return <NotReady score={score} />
  return <DocumentMode key={score.id} score={score} />
}

function DocumentMode({ score }: { score: Score }) {
  const { role, notes, addNote } = useX4()
  const me = memberForRole(role)
  const ens = ensembleOfScore(score.id)
  const parts = useMemo(() => score.partIds.map(id => partsById[id]).filter(Boolean), [score])
  const ownTab = (r: Role) => {
    const m = memberForRole(r)
    return r === 'player' && m.partId && score.partIds.includes(m.partId) ? m.partId : 'full'
  }

  const [tab, setTab] = useState(() => ownTab(role))
  const [seenRole, setSeenRole] = useState(role)
  const [tool, setTool] = useState<Tool | null>(null)
  const [draft, setDraft] = useState<Draft | null>(null)
  if (seenRole !== role) {
    setSeenRole(role)
    setTab(ownTab(role))
    setTool(null)
    setDraft(null)
  }

  const partIndex = tab === 'full' ? -1 : score.partIds.indexOf(tab)
  const visible = useMemo(() => (partIndex < 0 ? null : [partIndex]), [partIndex])
  const { eng, offstage } = useEngraving(score.fixture, visible)
  const [layout, setLayout] = useState<BookLayout>({ perView: 2, bookW: 0 })
  const onLayout = useCallback(
    (l: BookLayout) => setLayout(prev => (prev.perView === l.perView && prev.bookW === l.bookW ? prev : l)),
    [],
  )
  const pager = usePager(eng.pages.length, layout.perView)

  const [sheet, setSheet] = useState(false)
  const [focusId, setFocusId] = useState<string | null>(null)
  const [mark, setMark] = useState<number | null>(null)
  const [gotoVal, setGotoVal] = useState('')
  const [gotoErr, setGotoErr] = useState('')

  const viewPart = tab === 'full' ? null : tab
  const viewName = viewPart ? (partsById[viewPart]?.name ?? 'Part') : 'Full score'
  const scoreNotes = notes.filter(n => n.scoreId === score.id)
  const shown = scoreNotes
    .filter(n => appliesTo(n, viewPart))
    .sort((a, b) => a.barFrom - b.barFrom || a.createdAt.localeCompare(b.createdAt))
  const cuts = scoreNotes.filter(n => n.kind === 'cut')
  const people = (ens?.members ?? []).filter(m => m.role !== 'librarian')
  const online = people.filter(m => m.online)
  const leader = people.find(m => m.role === 'leader')
  const canCut = role === 'leader'
  const playerPart = role === 'player' && me.partId && score.partIds.includes(me.partId) ? me.partId : null

  // Keep the reader's place when the part changes.
  const anchor = useRef<number | null>(null)
  const pickTab = (k: string) => {
    if (k === tab) return
    let firstBar = Infinity
    for (const b of eng.bars.values()) if (b.page === pager.first && b.bar < firstBar) firstBar = b.bar
    anchor.current = mark ?? (Number.isFinite(firstBar) ? firstBar : null)
    setTab(k)
  }
  useEffect(() => {
    if (eng.status !== 'ready' || anchor.current == null) return
    const b = eng.bars.get(anchor.current)
    anchor.current = null
    if (b) pager.goToPage(b.page)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [eng.version, eng.status])

  const goToBar = (bar: number) => {
    const b = eng.bars.get(bar)
    if (b) pager.goToPage(b.page)
    setMark(bar)
  }

  const defaultScope = (kind: Tool): string | null => playerPart ?? (kind === 'cut' || kind === 'voice' ? null : viewPart)
  const newDraft = (kind: Tool, bar: number, awaitingEnd: boolean): Draft => ({
    kind,
    from: bar,
    to: bar,
    awaitingEnd,
    scope: defaultScope(kind),
    text: '',
    seconds: 0,
    recording: false,
  })

  const pickTool = (k: Tool) => {
    if (tool === k) {
      setTool(null)
      setDraft(null)
      return
    }
    setTool(k)
    setDraft(mark != null ? newDraft(k, mark, k === 'cut') : null)
  }

  const onBarTap = (bar: number) => {
    if (tool) {
      if (tool === 'cut' && draft?.awaitingEnd) {
        setDraft({ ...draft, from: Math.min(draft.from, bar), to: Math.max(draft.from, bar), awaitingEnd: false })
      } else {
        setDraft(newDraft(tool, bar, tool === 'cut'))
      }
      return
    }
    setMark(m => (m === bar ? null : bar))
  }

  const cancelDraft = () => {
    setDraft(null)
    setTool(null)
  }

  const save = () => {
    if (!draft) return
    const n: Annotation = {
      id: `local-${Date.now()}`,
      scoreId: score.id,
      partId: draft.scope,
      authorId: me.id,
      kind: draft.kind,
      barFrom: draft.from,
      barTo: draft.to,
      text: draft.kind === 'voice' ? undefined : draft.text.trim() || undefined,
      durationSec: draft.kind === 'voice' ? draft.seconds : undefined,
      createdAt: new Date().toISOString(),
    }
    addNote(n)
    setDraft(null)
    setTool(null)
    setSheet(true)
    setFocusId(n.id)
  }

  const openNote = (id: string) => {
    setSheet(true)
    setFocusId(id)
  }

  const recording = draft?.recording ?? false
  useEffect(() => {
    if (!recording) return
    const t = window.setInterval(() => setDraft(d => (d ? { ...d, seconds: d.seconds + 1 } : d)), 1000)
    return () => window.clearInterval(t)
  }, [recording])

  const composing = !!draft && !draft.awaitingEnd
  const sheetOpen = composing || sheet

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null
      if (t?.closest('input, textarea, select, [role="tab"]')) return
      if (e.key === 'ArrowRight' || e.key === 'PageDown') {
        e.preventDefault()
        pager.next()
      } else if (e.key === 'ArrowLeft' || e.key === 'PageUp') {
        e.preventDefault()
        pager.prev()
      } else if (e.key === 'Escape') {
        if (draft || tool) {
          setDraft(null)
          setTool(null)
        } else if (sheet) setSheet(false)
        else setMark(null)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [pager, draft, tool, sheet])

  const submitGoto = (e: FormEvent) => {
    e.preventDefault()
    const n = parseInt(gotoVal, 10)
    if (!Number.isFinite(n) || n < 1 || n > score.bars) {
      setGotoErr(`Bars run 1–${score.bars}`)
      return
    }
    if (!eng.bars.has(n)) {
      setGotoErr('Still engraving')
      return
    }
    setGotoErr('')
    goToBar(n)
  }

  const present = new Map<number, Member[]>()
  for (const m of people) if (m.online && m.atBar) present.set(m.atBar, [...(present.get(m.atBar) ?? []), m])

  const overlay = (page: number) => {
    const out: ReactNode[] = []
    for (const c of cuts) {
      for (const s of segments(eng.bars, c.barFrom, c.barTo)) {
        if (s.page !== page) continue
        const isStart = s.fromBar === c.barFrom
        const isEnd = s.toBar === c.barTo
        out.push(
          <div
            key={`c-${c.id}-${s.fromBar}`}
            className="x4-o-cut"
            data-start={isStart || undefined}
            data-end={isEnd || undefined}
            style={boxStyle(s, 0.012)}
          >
            {isStart ? <span className="x4-o-cut-label">Cut {barRange(c.barFrom, c.barTo)}</span> : null}
          </div>,
        )
      }
    }
    if (draft) {
      for (const s of segments(eng.bars, draft.from, draft.to)) {
        if (s.page === page) out.push(<div key={`d-${s.fromBar}`} className="x4-o-draft" data-kind={draft.kind} style={boxStyle(s, 0.012)} />)
      }
    }
    if (mark != null) {
      const b = eng.bars.get(mark)
      if (b && b.page === page) out.push(<div key="mark" className="x4-o-mark" style={boxStyle(b, 0.012)} />)
    }
    present.forEach((who, bar) => {
      const b = eng.bars.get(bar)
      if (!b || b.page !== page) return
      out.push(
        <div
          key={`p-${bar}`}
          className="x4-o-here"
          role="img"
          aria-label={`${who.map(w => w.name).join(', ')} at bar ${bar}`}
          style={{ left: pct(b.x + b.w), top: pct(b.y - 0.014) }}
        >
          {who.map(w => (
            <span key={w.id}>{initials(w.name)}</span>
          ))}
        </div>,
      )
    })
    const stack = new Map<number, number>()
    for (const n of shown) {
      if (n.kind === 'cut') continue
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
          data-focus={focusId === n.id || undefined}
          style={{ left: pct(b.x), top: pct(b.y - 0.014), '--k': k } as CSSProperties}
          onClick={e => {
            e.stopPropagation()
            openNote(n.id)
          }}
          aria-label={`${KIND_LABEL[n.kind]}, bars ${barRange(n.barFrom, n.barTo)}. Open in markings.`}
        >
          <KindIcon kind={n.kind} size={14} />
          <span>{pinText(n)}</span>
        </button>,
      )
    }
    return out
  }

  const whoMeta = (m: Member | undefined) =>
    m ? `${firstName(m.name)} · ${m.online ? (m.atBar ? `bar ${m.atBar}` : 'online') : 'offline'}` : 'Unassigned'

  const tabs: TabSpec[] = [
    {
      key: 'full',
      label: 'Full score',
      meta: whoMeta(leader),
      count: scoreNotes.filter(n => n.partId === null).length,
      countLabel: 'markings for everyone',
      state: role === 'player' ? 'flat' : 'raised',
    },
    ...parts.map((p: Part): TabSpec => {
      const holder = people.find(m => m.partId === p.id)
      return {
        key: p.id,
        label: p.name,
        meta: whoMeta(holder),
        count: scoreNotes.filter(n => n.partId === p.id).length,
        countLabel: `markings for ${p.name} only`,
        state: role === 'player' ? (p.id === me.partId ? 'raised' : 'flat') : 'raised',
      }
    }),
  ]

  let hint: string | null = null
  if (draft?.awaitingEnd) hint = `Cut from bar ${draft.from}. Now tap its last bar.`
  else if (tool && !draft) hint = tool === 'cut' ? 'Tap the first bar of the cut.' : `Tap the bar for the ${TOOL_NOUN[tool]}.`

  const waitLabel =
    eng.status === 'engraving'
      ? `Engraving ${viewPart ? `the ${viewName} part` : 'the full score'}`
      : `Engraving ${viewPart ? `the ${viewName} part` : 'the full score'}. A large score takes a few seconds.`

  return (
    <main className="x4-work">
      {offstage}
      <div className="x4-bar2">
        <div className="x4-bar2-title">
          <h1>{score.title}</h1>
          <p>
            {score.composer} · {score.work}
          </p>
        </div>
        <div className="x4-presence" role="group" aria-label="Who is reading">
          <span className="x4-presence-sum">{online.length} online</span>
          {people.map(m =>
            m.online && m.atBar ? (
              <button
                key={m.id}
                type="button"
                className="x4-face"
                onClick={() => goToBar(m.atBar as number)}
                title={`${m.name}, ${m.instrument}, at bar ${m.atBar}`}
                aria-label={`${m.name}, ${m.instrument}, at bar ${m.atBar}. Go there.`}
              >
                <span className="x4-face-i">{initials(m.name)}</span>
                <span className="x4-face-bar">{m.atBar}</span>
              </button>
            ) : (
              <span
                key={m.id}
                className="x4-face"
                data-off={!m.online || undefined}
                title={`${m.name}, ${m.instrument}, ${m.online ? 'online' : 'offline'}`}
              >
                <span className="x4-face-i">{initials(m.name)}</span>
                <span className="x4-face-bar">{m.online ? 'here' : 'offline'}</span>
              </span>
            ),
          )}
        </div>
        <div className="x4-tools" role="group" aria-label="Add to the score">
          {TOOLS.map(t => {
            const disabled = t.key === 'cut' && !canCut
            return (
              <button
                key={t.key}
                type="button"
                className="x4-tool"
                aria-pressed={tool === t.key}
                disabled={disabled}
                title={disabled ? 'Cuts come from the leader' : t.hint}
                aria-label={t.label}
                onClick={() => pickTool(t.key)}
              >
                <t.Icon />
                <span className="x4-tool-label">{t.label}</span>
              </button>
            )
          })}
        </div>
      </div>

      <div className="x4-stagewrap">
        <Book
          eng={eng}
          first={pager.first}
          tabs={<PartTabs tabs={tabs} active={tab} onPick={pickTab} label="Parts" />}
          overlay={overlay}
          onBarTap={onBarTap}
          onLayout={onLayout}
          onPrev={pager.prev}
          onNext={pager.next}
          canPrev={pager.canPrev}
          canNext={pager.canNext}
          waitLabel={waitLabel}
        />
        {hint && !sheetOpen ? (
          <p className="x4-hintbar" role="status">
            {hint}
            <button type="button" className="x4-link" onClick={cancelDraft}>
              Cancel
            </button>
          </p>
        ) : null}
        {sheetOpen ? (
          <section className="x4-sheet" aria-label={draft && composing ? COMPOSER_TITLE[draft.kind] : `Markings, ${viewName}`}>
            <header className="x4-sheet-head">
              <h2>{draft && composing ? COMPOSER_TITLE[draft.kind] : `Markings · ${viewName}`}</h2>
              <button
                type="button"
                className="x4-iconbtn"
                aria-label="Close"
                onClick={() => (composing ? cancelDraft() : setSheet(false))}
              >
                <IconClose />
              </button>
            </header>
            <div className="x4-sheet-body">
              {draft && composing ? (
                <Composer
                  draft={draft}
                  setDraft={setDraft}
                  parts={parts}
                  lockedPart={playerPart}
                  maxBar={score.bars}
                  onSave={save}
                  onCancel={cancelDraft}
                />
              ) : shown.length ? (
                <ol className="x4-notes">
                  {shown.map(n => (
                    <NoteItem
                      key={n.id}
                      n={n}
                      focused={focusId === n.id}
                      onShow={b => goToBar(b)}
                    />
                  ))}
                </ol>
              ) : (
                <p className="x4-empty-line">
                  Nothing is marked on this part yet. Choose Pencil, Note or Voice note above, then tap a bar.
                </p>
              )}
            </div>
          </section>
        ) : null}
      </div>

      <footer className="x4-foot">
        <div className="x4-foot-l">
          <button
            type="button"
            className="x4-btn"
            data-variant="quiet"
            aria-expanded={sheet && !composing}
            onClick={() => {
              if (composing) cancelDraft()
              setSheet(s => !s)
            }}
          >
            <IconList />
            <span className="x4-hide-sm">Markings</span>
            <span className="x4-count">{shown.length}</span>
          </button>
        </div>
        <div className="x4-pager">
          <button type="button" className="x4-iconbtn" onClick={pager.prev} disabled={!pager.canPrev} aria-label="Previous pages">
            <IconChevronLeft />
          </button>
          <span className="x4-pager-label" aria-live="polite">
            {pagesLabel(pager.first, pager.last, pager.count)}
          </span>
          <button type="button" className="x4-iconbtn" onClick={pager.next} disabled={!pager.canNext} aria-label="Next pages">
            <IconChevronRight />
          </button>
        </div>
        <form className="x4-goto" onSubmit={submitGoto}>
          <label className="x4-goto-field">
            <span className="x4-hide-sm">Bar</span>
            <input
              inputMode="numeric"
              value={gotoVal}
              onChange={e => {
                setGotoVal(e.target.value.replace(/\D/g, ''))
                setGotoErr('')
              }}
              aria-label="Go to bar"
              aria-invalid={!!gotoErr || undefined}
              placeholder={`1–${score.bars}`}
            />
          </label>
          <button type="submit" className="x4-btn">
            Go
          </button>
          {gotoErr ? (
            <span className="x4-goto-err" role="alert">
              {gotoErr}
            </span>
          ) : null}
        </form>
      </footer>
    </main>
  )
}

function NoteItem({ n, focused, onShow }: { n: Annotation; focused: boolean; onShow: (bar: number) => void }) {
  const ref = useRef<HTMLLIElement>(null)
  useEffect(() => {
    if (focused) ref.current?.scrollIntoView({ block: 'nearest' })
  }, [focused])
  const author = membersById[n.authorId]
  const scope = n.partId ? (partsById[n.partId]?.name ?? 'One part') : 'Everyone'
  return (
    <li ref={ref} className="x4-note" data-kind={n.kind} data-focus={focused || undefined}>
      <button
        type="button"
        className="x4-note-bars"
        onClick={() => onShow(n.barFrom)}
        aria-label={`Show bar ${n.barFrom} on the score`}
        title="Show on the score"
      >
        {barRange(n.barFrom, n.barTo)}
      </button>
      <div className="x4-note-body">
        <p className="x4-note-kind">
          <KindIcon kind={n.kind} size={16} />
          {KIND_LABEL[n.kind]} · {scope}
          {n.kind === 'voice' && n.durationSec ? ` · ${fmtDuration(n.durationSec)}` : ''}
        </p>
        {n.kind === 'voice' ? (
          <>
            <VoicePlayer seconds={n.durationSec ?? 0} />
            {n.transcript ? (
              <blockquote className="x4-transcript">“{n.transcript}”</blockquote>
            ) : (
              <p className="x4-note-pending">Transcribing. The text appears here once Muse Voice Transcribe has listened.</p>
            )}
          </>
        ) : n.kind === 'cut' ? (
          <p className="x4-note-text">
            Bars {barRange(n.barFrom, n.barTo)} are skipped in every part{n.text ? `. ${n.text}.` : '.'}
          </p>
        ) : (
          <p className="x4-note-text">{n.text ?? KIND_LABEL[n.kind]}</p>
        )}
        <p className="x4-note-by">
          {author?.name ?? 'Unknown member'} · {fmtDate(n.createdAt, true)}
        </p>
      </div>
    </li>
  )
}

function VoicePlayer({ seconds }: { seconds: number }) {
  const [t, setT] = useState(0)
  const [on, setOn] = useState(false)
  useEffect(() => {
    if (!on) return
    const id = window.setInterval(() => setT(x => x + 1), 1000)
    return () => window.clearInterval(id)
  }, [on])
  useEffect(() => {
    if (on && t >= seconds) {
      setOn(false)
      setT(0)
    }
  }, [t, seconds, on])
  const frac = seconds ? Math.min(1, t / seconds) : 0
  return (
    <div className="x4-voice">
      <button
        type="button"
        className="x4-btn"
        data-variant={on ? 'solid' : undefined}
        onClick={() => setOn(v => !v)}
        disabled={!seconds}
      >
        {on ? <IconPause /> : <IconPlay />}
        {on ? 'Pause' : t ? 'Resume' : 'Play'}
      </button>
      <span className="x4-voice-track" aria-hidden="true">
        <span style={{ width: `${frac * 100}%` }} />
      </span>
      <span className="x4-voice-time">
        {fmtDuration(t)} / {fmtDuration(seconds)}
      </span>
    </div>
  )
}

function Composer({
  draft,
  setDraft,
  parts,
  lockedPart,
  maxBar,
  onSave,
  onCancel,
}: {
  draft: Draft
  setDraft: (d: Draft) => void
  parts: Part[]
  lockedPart: string | null
  maxBar: number
  onSave: () => void
  onCancel: () => void
}) {
  const rangeOk = draft.from >= 1 && draft.to >= draft.from && draft.to <= maxBar
  const valid =
    rangeOk &&
    (draft.kind === 'voice'
      ? draft.seconds > 0 && !draft.recording
      : draft.kind === 'cut'
        ? draft.scope === null
        : draft.text.trim().length > 0)
  return (
    <form
      className="x4-composer"
      onSubmit={e => {
        e.preventDefault()
        if (valid) onSave()
      }}
    >
      <div className="x4-field-row">
        <label className="x4-field">
          <span>From bar</span>
          <input
            type="number"
            inputMode="numeric"
            min={1}
            max={maxBar}
            value={draft.from || ''}
            onChange={e => setDraft({ ...draft, from: Number(e.target.value) || 0 })}
          />
        </label>
        <label className="x4-field">
          <span>To bar</span>
          <input
            type="number"
            inputMode="numeric"
            min={1}
            max={maxBar}
            value={draft.to || ''}
            onChange={e => setDraft({ ...draft, to: Number(e.target.value) || 0 })}
          />
        </label>
        <label className="x4-field">
          <span>For</span>
          <span className="x4-select">
            <select
              value={draft.scope ?? ''}
              disabled={!!lockedPart || draft.kind === 'cut'}
              onChange={e => setDraft({ ...draft, scope: e.target.value || null })}
            >
              <option value="">Everyone</option>
              {parts.map(p => (
                <option key={p.id} value={p.id}>
                  {p.name} only
                </option>
              ))}
            </select>
          </span>
        </label>
      </div>
      {!rangeOk ? (
        <p className="x4-field-err" role="alert">
          Bars run 1–{maxBar}, and the last bar cannot come before the first.
        </p>
      ) : null}
      {draft.kind === 'voice' ? (
        <div className="x4-rec">
          <button
            type="button"
            className="x4-btn"
            data-variant={draft.recording ? 'solid' : undefined}
            onClick={() =>
              setDraft({ ...draft, recording: !draft.recording, seconds: draft.recording ? draft.seconds : 0 })
            }
          >
            <IconMic />
            {draft.recording ? 'Stop' : draft.seconds ? 'Record again' : 'Record'}
          </button>
          <span className="x4-rec-time" aria-live="polite">
            {fmtDuration(draft.seconds)}
          </span>
          <p className="x4-rec-note">
            Muse Voice Transcribe writes the text and anchors it to bars {barRange(draft.from, draft.to)}.
          </p>
        </div>
      ) : (
        <label className="x4-field x4-field-wide">
          <span>{draft.kind === 'cut' ? 'Reason, optional' : draft.kind === 'text' ? 'Note' : 'Marking'}</span>
          <input
            type="text"
            value={draft.text}
            onChange={e => setDraft({ ...draft, text: e.target.value })}
            placeholder={PLACEHOLDER[draft.kind]}
            autoFocus
          />
        </label>
      )}
      {draft.kind === 'cut' ? (
        <p className="x4-composer-cut">
          Bars {barRange(draft.from, draft.to)} will be skipped in every member’s part, live.
        </p>
      ) : null}
      <div className="x4-composer-acts">
        <button type="button" className="x4-btn" data-variant="quiet" onClick={onCancel}>
          Cancel
        </button>
        <button type="submit" className="x4-btn" data-variant="solid" disabled={!valid}>
          {SAVE_LABEL[draft.kind]}
        </button>
      </div>
    </form>
  )
}

function NotReady({ score }: { score: Score }) {
  const pctDone = Math.round((score.progress ?? 0) * 100)
  return (
    <main className="x4-main">
      <div className="x4-empty">
        <h1 className="x4-h1">{score.title}</h1>
        <p className="x4-lede">
          {score.composer} · {score.work}
        </p>
        {score.status === 'failed' ? (
          <p className="x4-empty-fail" role="alert">
            Reading failed. {score.failureReason}
          </p>
        ) : score.status === 'processing' ? (
          <p className="x4-empty-body">Reading, {pctDone}% done. The score opens here once its parts are split.</p>
        ) : (
          <p className="x4-empty-body">The pages are not ordered yet. Reading starts once the order is committed.</p>
        )}
        <div className="x4-empty-acts">
          <Link className="x4-btn" to="/4">
            Back to library
          </Link>
          {score.status !== 'processing' ? (
            <Link className="x4-btn" data-variant="solid" to="/4/scan">
              {score.status === 'failed' ? 'Retake pages' : 'Order pages'}
            </Link>
          ) : null}
        </div>
      </div>
    </main>
  )
}

export function Unavailable({ title, body }: { title: string; body: string }) {
  return (
    <main className="x4-main">
      <div className="x4-empty">
        <h1 className="x4-h1">{title}</h1>
        <p className="x4-empty-body">{body}</p>
        <div className="x4-empty-acts">
          <Link className="x4-btn" to="/4">
            Back to library
          </Link>
        </div>
      </div>
    </main>
  )
}
