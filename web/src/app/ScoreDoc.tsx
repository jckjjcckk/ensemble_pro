import { useEffect, useLayoutEffect, useMemo, useRef, useState, type CSSProperties } from 'react'
import { Link, useParams, useSearchParams } from 'react-router'
import { AnimatePresence, motion } from 'motion/react'
import type { Annotation, AnnotationKind } from '../mock'
import { Screen, useReducedMotion, useViewport } from './layout'
import { ScoreStage, type StageView } from './ScoreStage'
import { Ruler, type RulerMark } from './Ruler'
import { Sheet } from './Sheet'
import Strips from './Strips'
import { spanRects, type Geo } from './geometry'
import { CutLayer, KindIcon, MarginLayer, NoteBody, PinLayer, inMargin } from './marks'
import { barRange, firstName, initials, kindLabel, partShort, useStore, type Span } from './store'
import { IClose, IList, IMic, IMinus, IPencil, IPlus, IScissors } from './icons'

type Tool = null | 'marking' | 'cut' | 'voice'

/** The composer rises out of the dock on this spring; the tools it covers fade. */
const RISE = { type: 'spring', stiffness: 320, damping: 20, mass: 0.8 } as const
/** The composer floats over the whole dock row (growing upward if it wraps), so the stage never changes size for it. */
// It starts at the row's top rule (so the edge is invisible on one row) and draws its own when it rises past it.
const composerStyle: CSSProperties = {
  position: 'absolute', bottom: 0, minHeight: 'calc(100% + 6px)', padding: '6px 12px 0', zIndex: 2,
  background: 'var(--dk)', boxShadow: '0 -1px 0 var(--dk-rule)',
}
const dockWrapStyle: CSSProperties = { position: 'relative', flex: 1, minWidth: 0, display: 'flex' }

const markKinds: { kind: AnnotationKind; label: string }[] = [
  { kind: 'dynamic', label: 'Dynamic' },
  { kind: 'bowing', label: 'Bowing' },
  { kind: 'text', label: 'Note' },
  { kind: 'breath', label: 'Breath' },
]

export default function ScoreDoc() {
  const { scoreId = '' } = useParams()
  const { scoresById, world } = useStore()
  const score = scoresById[scoreId]
  const [search] = useSearchParams()
  if (!score) return <Unavailable title={world.loaded ? 'This score is not in the library.' : 'Opening the score'} />
  if (search.get('view') === 'strips') return <Strips score={score} />   // a cut part (008) reads as strips (010)
  if (score.status !== 'ready' || !score.fixture) {
    const why = score.status === 'failed' ? score.failureReason
      : score.status === 'processing' ? `Still processing, ${Math.round((score.progress ?? 0) * 100)} percent read.`
      : 'The pages have not been processed yet.'
    return <Unavailable title={score.title} detail={why} />
  }
  return <Doc scoreId={score.id} />
}

function Unavailable({ title, detail }: { title: string; detail?: string }) {
  return (
    <Screen header={<div className="ph"><div className="ph-title"><h1>{title}</h1></div></div>} dock={<div className="dock-spacer" />}>
      <div className="empty">
        <p className="empty-title">{title}</p>
        {detail && <p>{detail}</p>}
        <Link className="btn btn-line" to="/">Back to the library</Link>
      </div>
    </Screen>
  )
}

function Doc({ scoreId }: { scoreId: string }) {
  const vp = useViewport()
  const reduced = useReducedMotion()
  const { contextFor, annotations, addAnnotation, scoresById, partsById, world } = useStore()
  const score = scoresById[scoreId]
  // Standing comes from the membership in the ensemble that owns the score, not from which library is open.
  const ctx = contextFor(score.ensembleId)
  const role = ctx?.membership.role ?? 'player'
  const persona = ctx?.persona ?? world.ensembles[0].members[0]
  const canCut = role !== 'player'
  const parts = score.partIds.map(id => partsById[id]).filter(Boolean)
  const ensemble = world.ensembles.find(e => e.id === score.ensembleId)
  const hasPresence = false
  const performers = hasPresence ? (ensemble?.members ?? []).filter(m => m.role === 'leader' || m.role === 'player') : []
  const leader = performers.find(m => m.role === 'leader' && m.online)
  const groupBar = leader?.atBar ?? 1

  const seat = parts.find(p => p.name === persona.instrument)?.id
  const defaultPart = role === 'player' && seat ? seat : 'full'
  const [partSel, setPartSel] = useState<string>(defaultPart)
  useEffect(() => { setPartSel(defaultPart) }, [defaultPart])
  const [focus, setFocus] = useState({ bar: groupBar, key: 0 })
  const [view, setView] = useState<StageView | null>(null)
  const [pin, setPin] = useState<string | null>(null)
  // The Markings panel floats over the stage at every width, so the score never re-engraves for it; it opens on demand.
  const [listOpen, setListOpen] = useState(false)
  const [tool, setTool] = useState<Tool>(null)
  const [draftBar, setDraftBar] = useState(groupBar)
  const [draftSpan, setDraftSpan] = useState<Span>({ from: 260, to: 267 })
  const [draftKind, setDraftKind] = useState<AnnotationKind>('dynamic')
  const [draftText, setDraftText] = useState('')
  const [draftAll, setDraftAll] = useState(true)
  const [rec, setRec] = useState<{ on: boolean; sec: number }>({ on: false, sec: 0 })
  const listRef = useRef<HTMLDivElement>(null)
  const dockWrapRef = useRef<HTMLDivElement>(null)
  // How far the dock body sits from the dock's edges (the area nav and the row padding): the composer reaches past them.
  const [reach, setReach] = useState({ left: 0, right: 0 })
  useLayoutEffect(() => {
    const el = dockWrapRef.current
    const dock = el?.offsetParent as HTMLElement | null
    if (!el || !dock) return
    const left = el.offsetLeft
    const right = dock.clientWidth - left - el.offsetWidth
    setReach(r => (r.left === left && r.right === right ? r : { left, right }))
  }, [tool, vp.w])

  const isFull = partSel === 'full'
  const instruments = isFull ? null : [score.partIds.indexOf(partSel)]
  // Words go to the outer margin when there is room for one beside each page; otherwise the Markings panel carries them.
  // Depends on the viewport only: the panel floating over a margin must not change the engraving.
  const marginW = vp.w >= 1180 ? 184 : 0
  const visible = useMemo(
    () => annotations.filter(a => a.scoreId === score.id && (isFull || a.partId === null || a.partId === partSel)).sort((a, b) => a.barFrom - b.barFrom),
    [annotations, score.id, isFull, partSel],
  )
  const cuts = visible.filter(a => a.kind === 'cut').map(a => ({ from: a.barFrom, to: a.barTo, label: `Cut ${barRange(a.barFrom, a.barTo)} · ${a.text ?? ''}`.replace(/ · $/, '') }))
  const marks: RulerMark[] = visible.filter(a => a.kind !== 'cut').map(a => ({ id: a.id, bar: a.barFrom, kind: a.kind === 'voice' ? 'voice' : 'mark', label: kindLabel[a.kind] }))

  const jump = (bar: number) => setFocus(f => ({ bar, key: f.key + 1 }))
  const openNote = (id: string) => {
    const a = visible.find(x => x.id === id)
    if (!a) return
    jump(a.barFrom)
    setPin(id)
    setListOpen(true)
    window.setTimeout(() => listRef.current?.querySelector(`[data-note="${id}"]`)?.scrollIntoView({ block: 'nearest', behavior: 'smooth' }), 60)
  }

  // Simulated recorder clock. Audio capture and transcription belong to the backend workstream.
  useEffect(() => {
    if (!rec.on) return
    const id = window.setInterval(() => setRec(r => ({ ...r, sec: r.sec + 1 })), 1000)
    return () => window.clearInterval(id)
  }, [rec.on])

  const startTool = (t: Tool) => {
    setTool(t)
    setDraftText('')
    setRec({ on: false, sec: 0 })
    const start = view?.first ?? groupBar
    setDraftBar(start)
    if (t === 'cut') setDraftSpan({ from: start, to: Math.min(score.bars, start + 7) })
  }

  const save = () => {
    const base = { id: `n${Date.now()}`, scoreId: score.id, authorId: persona.id, createdAt: new Date().toISOString() }
    let a: Annotation | null = null
    if (tool === 'marking') a = { ...base, kind: draftKind, partId: draftAll || isFull ? null : partSel, barFrom: draftBar, barTo: draftBar, text: draftText.trim() || kindLabel[draftKind] }
    if (tool === 'cut') a = { ...base, kind: 'cut', partId: null, barFrom: draftSpan.from, barTo: draftSpan.to, text: 'Proposed cut' }
    if (tool === 'voice') a = { ...base, kind: 'voice', partId: draftAll || isFull ? null : partSel, barFrom: draftBar, barTo: draftBar, durationSec: rec.sec }
    if (a) addAnnotation(a)
    setTool(null)
  }

  const onBarTap = (bar: number) => {
    if (tool === 'marking' || tool === 'voice') setDraftBar(bar)
    else if (tool === 'cut') setDraftSpan(s => (bar < s.from ? { from: bar, to: s.to } : { from: s.from, to: bar }))
    else setPin(null)
  }

  // Long press on a bar: annotate it from the music, without reaching for the dock first.
  const onBarHold = (bar: number) => {
    if (tool) { onBarTap(bar); return }
    startTool('marking')
    setDraftBar(bar)
  }

  const presenceAt = (bar: number) => performers.filter(m => m.online && m.atBar === bar)

  const underlay = (g: Geo) => (
    <>
      <CutLayer geo={g} cuts={cuts} />
      {tool === 'cut' && spanRects(g, draftSpan.from, draftSpan.to).map(r => (
        <div key={`d${r.first}`} className="u-cut is-draft" style={{ left: r.x, top: r.y - 10, width: r.w, height: r.h + 20 }} />
      ))}
      {(tool === 'marking' || tool === 'voice') && g.bars.get(draftBar) && (() => {
        const b = g.bars.get(draftBar)!
        return <div className="u-loop" style={{ left: b.x - 4, top: b.y - 14, width: b.w + 8, height: b.h + 28 }} />
      })()}
    </>
  )

  const overlay = (g: Geo) => (
    <>
      {[...new Set(performers.filter(m => m.online && m.atBar).map(m => m.atBar!))].map(bar => {
        const b = g.bars.get(bar)
        if (!b) return null
        const who = presenceAt(bar)
        return (
          <span key={`p${bar}`} className="o-presence" style={{ left: b.x + b.w - 4, top: b.y - 30 }} title={who.map(m => m.name).join(', ')}>
            {who.map(m => <span key={m.id} className="o-face">{initials(m.name)}</span>)}
          </span>
        )
      })}
      <PinLayer geo={g} items={marginW ? visible.filter(a => !inMargin(a)) : visible} selected={pin} onSelect={setPin} />
      {marginW > 0 && <MarginLayer geo={g} items={visible.filter(inMargin)} width={marginW} selected={pin} onSelect={setPin} />}
    </>
  )

  const header = (
    <div className="ph">
      <div className="ph-title">
        <h1>{score.title}</h1>
        <p>{score.composer.split(' ').slice(-1)[0]} · {score.work}</p>
      </div>
      <div className="grow" />
      {hasPresence && !vp.narrow && <span className="presence-sum">{performers.filter(m => m.online).length} online</span>}
      {hasPresence && (
        <ul className="presence" aria-label="Who is reading">
          {performers.map(m => (
            <li key={m.id}>
              <button type="button" className={`face ${m.online ? '' : 'is-off'}`} disabled={!m.online || !m.atBar} onClick={() => m.atBar && jump(m.atBar)}
                aria-label={m.online ? `${m.name}, ${m.instrument}, at bar ${m.atBar}` : `${m.name}, ${m.instrument}, offline`}
                title={m.online ? `${m.name} · bar ${m.atBar}` : `${m.name} · offline`}>
                <span className="face-i">{initials(m.name)}</span>
                <span className="face-bar num">{m.online ? m.atBar : 'off'}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
      <button type="button" className="btn btn-quiet" aria-pressed={listOpen} onClick={() => setListOpen(v => !v)}>
        <IList size={20} /><span>Markings</span><span className="count">{visible.length}</span>
      </button>
    </div>
  )

  const ruler = (
    <Ruler
      total={score.bars}
      span={tool === 'cut' ? draftSpan : view ? { from: view.first, to: view.last } : null}
      mode={tool === 'cut' ? 'range' : 'view'}
      spanLabel={tool === 'cut' ? 'Cut' : 'Bars on screen'}
      onSpan={s => (tool === 'cut' ? setDraftSpan(s) : jump(s.from))}
      cuts={cuts} marks={marks} onMark={openNote}
      presence={performers.filter(m => m.online && m.atBar).map(m => ({ bar: m.atBar!, label: m.name }))}
      onSeek={b => (tool === 'cut' ? onBarTap(b) : jump(b))}
      compact={!vp.wide}
      label={`Bar ruler, bars 1 to ${score.bars}, with markings, cuts and who is where`}
    />
  )

  const partSwitcher = (
    <div className="seg dseg" role="radiogroup" aria-label="Part">
      {[{ id: 'full', name: 'Score' }, ...parts].map(pt => (
        <button key={pt.id} type="button" role="radio" aria-checked={partSel === pt.id} onClick={() => setPartSel(pt.id)}>
          {pt.id === 'full' ? 'Score' : vp.narrow ? partShort[pt.name] ?? pt.name : pt.name}
        </button>
      ))}
    </div>
  )

  const tools = (
    <div className="doc-tools" role="group" aria-label="Add">
      <button type="button" className="dbtn" onClick={() => startTool('marking')}><IPencil size={20} /><span>Marking</span></button>
      <button type="button" className="dbtn" onClick={() => startTool('cut')} disabled={!canCut} title={canCut ? undefined : 'Only the admin can cut'}><IScissors size={20} /><span>Cut</span></button>
      <button type="button" className="dbtn" onClick={() => startTool('voice')}><IMic size={20} /><span>Voice note</span></button>
    </div>
  )

  const barStepper = (
    <div className="stepper" role="group" aria-label="Bar">
      <button type="button" className="dbtn is-icon" onClick={() => setDraftBar(b => Math.max(1, b - 1))} aria-label="Previous bar"><IMinus size={18} /></button>
      <span className="stepper-val"><span className="stepper-k">bar</span><span className="num">{draftBar}</span></span>
      <button type="button" className="dbtn is-icon" onClick={() => setDraftBar(b => Math.min(score.bars, b + 1))} aria-label="Next bar"><IPlus size={18} /></button>
    </div>
  )

  const audience = !isFull && (
    <label className="check">
      <input type="checkbox" checked={draftAll} onChange={e => setDraftAll(e.target.checked)} />
      <span>Everyone</span>
    </label>
  )

  const composer = tool && (
    <motion.form
      key={tool} className="composer" style={{ ...composerStyle, left: -reach.left, right: -reach.right }} layout
      initial={reduced ? { opacity: 0 } : { opacity: 0, y: 28 }}
      animate={{ opacity: 1, y: 0 }}
      exit={reduced ? { opacity: 0, transition: { duration: 0.12 } } : { opacity: 0, y: 18, transition: { duration: 0.14 } }}
      transition={reduced ? { duration: 0.16 } : RISE}
      onSubmit={e => { e.preventDefault(); save() }} aria-label={`New ${tool === 'voice' ? 'voice note' : tool}`}
    >
      {tool === 'marking' && <>
        {barStepper}
        <div className="seg dseg is-small" role="radiogroup" aria-label="Kind">
          {markKinds.map(k => (
            <button key={k.kind} type="button" role="radio" aria-checked={draftKind === k.kind} onClick={() => setDraftKind(k.kind)}>{k.label}</button>
          ))}
        </div>
        <input className="dinput" value={draftText} onChange={e => setDraftText(e.target.value)} placeholder={draftKind === 'dynamic' ? 'e.g. sub. p' : 'What should everyone see?'} aria-label="Marking text" autoFocus />
        {audience}
      </>}
      {tool === 'cut' && (
        <p className="composer-msg">
          Cut bars <span className="num">{barRange(draftSpan.from, draftSpan.to)}</span>
          <span className="composer-hint">Drag the bracket or tap the first and last bar. Goes to every part.</span>
        </p>
      )}
      {tool === 'voice' && <>
        {barStepper}
        <button type="button" className={`dbtn rec ${rec.on ? 'is-on' : ''}`} onClick={() => setRec(r => ({ on: !r.on, sec: r.on ? r.sec : 0 }))} aria-pressed={rec.on}>
          <span className="rec-dot" aria-hidden="true" />{rec.on ? 'Stop' : rec.sec ? 'Record again' : 'Record'}
        </button>
        <span className="composer-msg num" aria-live="polite">{`${Math.floor(rec.sec / 60)}:${String(rec.sec % 60).padStart(2, '0')}`}</span>
        {audience}
      </>}
      <div className="grow" />
      <button type="button" className="dbtn" style={{ marginLeft: 'auto' }} onClick={() => setTool(null)}>Cancel</button>
      <button type="submit" className="dbtn is-primary" disabled={(tool === 'voice' && (rec.on || rec.sec === 0))}>
        {tool === 'cut' ? 'Add cut' : tool === 'voice' ? 'Save note' : 'Add marking'}
      </button>
    </motion.form>
  )

  // The dock row keeps its height whatever is in it: the tools fade under the composer, which floats over them.
  const dock = (
    <div style={dockWrapStyle} ref={dockWrapRef}>
      <AnimatePresence initial={false}>
        {!tool && (
          <motion.div key="tools" className="doc-dock" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: reduced ? 0 : 0.12 }}>
            {partSwitcher}
            <div className="grow" />
            {tools}
          </motion.div>
        )}
      </AnimatePresence>
      <AnimatePresence initial={false}>{composer}</AnimatePresence>
    </div>
  )

  const scale = isFull ? (vp.wide ? 0.6 : 0.64) : (vp.wide ? 0.78 : 0.84)
  const scoreParts = isFull ? 'Full score' : partsById[partSel]?.name

  return (
    <Screen header={header} ruler={ruler} dock={dock} className="is-doc">
      <div className={`work ${listOpen ? 'has-side' : ''}`}>
        <ScoreStage
          src={score.fixture}
          instruments={instruments}
          scale={scale}
          focus={focus}
          underlay={underlay}
          overlay={overlay}
          onBarTap={onBarTap}
          onBarHold={onBarHold}
          onView={setView}
          margin={marginW || undefined}
          label={`${scoreParts}, ${score.title}`}
        />
        {/* The Markings panel is a sprung sheet over the stage (never docked: the score must not re-engrave for it). */}
        <Sheet open={listOpen} onClose={() => setListOpen(false)} label="Markings" docked={false}>
            <div className="side-head">
              <h2>Markings <span className="count">{visible.length}</span></h2>
              <button type="button" className="btn-icon" onClick={() => setListOpen(false)} aria-label="Close markings"><IClose size={20} /></button>
            </div>
            <div className="side-scroll" ref={listRef}>
              <p className="side-sub">{scoreParts}. Markings for everyone and for this part.</p>
              <ol className="notes">
                {visible.map(a => (
                  <li key={a.id} data-note={a.id} className={`note ${pin === a.id ? 'is-sel' : ''}`}>
                    <NoteBody a={a} />
                    <button type="button" className="btn btn-line is-small" onClick={() => { jump(a.barFrom); setPin(a.kind === 'cut' ? null : a.id) }}>
                      <KindIcon kind={a.kind} size={15} />Show bar <span className="num">{a.barFrom}</span>
                    </button>
                  </li>
                ))}
              </ol>
              {hasPresence && (
                <>
                  <h3 className="side-h">Reading now</h3>
                  <ul className="readers">
                    {performers.map(m => (
                      <li key={m.id} className={m.online ? '' : 'is-off'}>
                        <span className="face-i">{initials(m.name)}</span>
                        <span>{firstName(m.name)} <span className="muted">{m.instrument}</span></span>
                        <span className="num">{m.online ? `bar ${m.atBar}` : 'offline'}</span>
                      </li>
                    ))}
                  </ul>
                </>
              )}
            </div>
        </Sheet>
      </div>
    </Screen>
  )
}
