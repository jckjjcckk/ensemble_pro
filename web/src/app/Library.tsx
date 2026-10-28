import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router'
import { AnimatePresence, LayoutGroup, motion } from 'motion/react'
import { practice, type BookKind, type Part, type Score } from '../mock'
import { apiFailure, convertToDigital } from '../lib/api'
import { useAuth } from './auth'
import { MY_LIBRARY, exportName, exportStored, importMusicXml, importPdf, isPdf, type AskJob } from './data'
import { Screen, useViewport } from './layout'
import { DisplayButton } from './Display'
import { Pop, SPRING_LAYOUT, Scrim, Sheet } from './Sheet'
import { PartsPanel } from './Parts'
import { Identity } from './Identity'
import { StaffQuestion } from './StaffQuestion'
import { GroupSheet, type GroupFace } from './Groups'
import { bookState, dotOf, type BookState } from './book'
import { barRange, difficultyWord, fmtDateTime, partShort, useStore } from './store'
import { ICamera, IChevronRight, IClose, IExport, IImport, IInfo, IKeypad, IMore, INote, IPeople, IPlusCircle, IRepeat, IScore, IWarning } from './icons'
import './groups.css'

const bookWord: Record<BookKind, string> = { pdf: 'PDF', digital: 'Digital' }
/** The status as a sentence fragment, for screen readers on a cover. */
const statusWord: Record<Score['status'], string> = { uploaded: 'not read yet', ordering: 'pages waiting for their order', processing: 'being read', ready: 'ready', failed: 'reading stopped' }

/** The tags a book carries: what it exists as. PDF, Digital, or both once a PDF book is converted. */
export function BookTags({ kinds }: { kinds: BookKind[] }) {
  return <>{kinds.map(k => <span key={k} className="book-tag">{bookWord[k]}</span>)}</>
}

/** One small dot: yellow while the librarian has a question, red when the run failed; nothing when all is well. */
function StatusDot({ state, className = '' }: { state: BookState; className?: string }) {
  const dot = dotOf(state)
  if (!dot) return null
  return <span className={`dot is-${dot} ${className}`} role="img" aria-label={dot === 'ask' ? 'The librarian has a question' : 'Reading stopped'} />
}

const roleWord = { owner: 'your own library', admin: 'you are the admin', player: 'you play' } as const

export default function Library() {
  const vp = useViewport()
  const navigate = useNavigate()
  const { pathname } = useLocation()
  const { context, contexts, contextFor, setContext, scan, practiceUI, partsById, world, jobsFor } = useStore()
  const { session } = useAuth()
  const [selected, setSelected] = useState<string | null>(null)
  const [importing, setImporting] = useState<string | null>(null)
  const [importMsg, setImportMsg] = useState<string | null>(null)
  const [asking, setAsking] = useState<AskJob | null>(null)
  const [face, setFace] = useState<GroupFace | null>(null)
  const [pendingGroup, setPendingGroup] = useState<string | null>(null)
  // Conversions asked for here, until the job row arrives; and what a refused one said.
  const [converting, setConverting] = useState<Record<string, boolean>>({})
  const [convertMsg, setConvertMsg] = useState<Record<string, string>>({})
  const fileRef = useRef<HTMLInputElement>(null)
  const docked = vp.w >= 1100
  const scores = world.scores
  const groupRoute = pathname.startsWith('/group')
  const inGroup = context.ensemble.id !== MY_LIBRARY

  // The Fauré moves to processing once its page order is committed on the scan screen.
  const live = useMemo(() => scores.map(s => (s.id === 's-faure' && scan.committed ? { ...s, status: 'processing' as const, progress: 0 } : s)), [scores, scan.committed])
  const mine = live.filter(s => s.ensembleId === context.ensemble.id)
  const folders = [...new Set(mine.map(s => s.folder))].map(name => ({ name, scores: mine.filter(s => s.folder === name) }))
  // A selection from another library simply finds nothing here; no reset effect needed.
  const open = selected ? mine.find(s => s.id === selected) ?? null : null
  const stateOf = useCallback((s: Score): BookState => {
    const st = bookState(s, world.bookJobs, jobsFor(s.id))
    return converting[s.id] && !st.busy && !st.hasDigital ? { ...st, busy: 'converting' } : st
  }, [world.bookJobs, jobsFor, converting])

  // A group made or joined opens as soon as the world has it.
  useEffect(() => {
    if (pendingGroup && contextFor(pendingGroup)) { setContext(pendingGroup); setPendingGroup(null) }
  }, [pendingGroup, contextFor, setContext])
  // A conversion's own job row takes over from the local flag.
  useEffect(() => {
    const done = Object.keys(converting).filter(id => world.bookJobs.some(j => j.scoreId === id && j.kind === 'omr_convert'))
    if (done.length) setConverting(c => Object.fromEntries(Object.entries(c).filter(([id]) => !done.includes(id))))
  }, [world.bookJobs, converting])

  const { persona, membership } = context
  const partName = persona.partId ? partsById[persona.partId]?.name : persona.instrument
  const canImport = membership.role !== 'player'

  const onFile = async (file: File | undefined) => {
    if (!file || !session) return
    setImporting(file.name); setImportMsg(null)
    try {
      const apiBase = (import.meta.env.VITE_API_URL as string | undefined) ?? 'http://localhost:8000'
      const where = {
        ensembleId: context.ensemble.id === MY_LIBRARY ? null : context.ensemble.id,
        ownerId: context.ensemble.id === MY_LIBRARY ? session.user.id : null,
        createdBy: session.user.id,
      }
      await (isPdf(file) ? importPdf : importMusicXml)(file, where, apiBase, session.access_token)
      world.reload()
    } catch (e) {
      setImportMsg(`${file.name} was not imported. ${(e as Error).message}`)
      world.reload()
    } finally {
      setImporting(null)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  const convert = async (s: Score) => {
    if (!session) return
    setConverting(c => ({ ...c, [s.id]: true }))
    setConvertMsg(m => { const { [s.id]: _, ...rest } = m; return rest })
    try {
      await convertToDigital(s.id, session.access_token)
      world.reload()
    } catch (e) {
      setConverting(c => { const { [s.id]: _, ...rest } = c; return rest })
      setConvertMsg(m => ({ ...m, [s.id]: apiFailure(e, 'Converting to Digital') }))
      setSelected(s.id)   // the book page says why
    }
  }

  const openGroups = (f: GroupFace) => {
    if (f === 'group') navigate('/group')
    else setFace(f)
  }
  const closeGroups = () => {
    setFace(null)
    if (groupRoute) navigate('/')
  }
  const groupOpen = groupRoute || face !== null
  const groupFace: GroupFace = face ?? (inGroup ? 'group' : 'start')
  const onOpened = (id: string) => { if (contextFor(id)) setContext(id); else setPendingGroup(id) }

  const practiceHere = practice.scoreId && live.find(s => s.id === practice.scoreId)?.ensembleId === context.ensemble.id ? live.find(s => s.id === practice.scoreId)! : null

  const header = (
    <div className="ph">
      <div className="ph-title">
        <h1>{context.ensemble.name}</h1>
        <p>
          {mine.length} {mine.length === 1 ? 'score' : 'scores'} · {membership.role === 'player' ? `you play ${partName}` : roleWord[membership.role]}
        </p>
      </div>
      <div className="grow" />
      <DisplayButton />
    </div>
  )

  const dock = (
    <div className="lib-dock">
      {practiceHere && (
        <button type="button" className="dbtn" onClick={() => navigate('/practice')}>
          <IRepeat size={20} />
          <span>Resume · {partsById[practice.partId]?.name}{practiceUI.loop ? `, ${barRange(practiceUI.loop.from, practiceUI.loop.to)}` : ''}</span>
        </button>
      )}
      <div className="grow" />
      {canImport && (
        <>
          <input ref={fileRef} type="file" accept=".pdf,application/pdf,.musicxml,.xml,.mxl,application/vnd.recordare.musicxml+xml" className="sr-only" onChange={e => onFile(e.target.files?.[0])} aria-label="Import a PDF or MusicXML file" />
          <button type="button" className="dbtn is-primary" disabled={!!importing} onClick={() => fileRef.current?.click()}>
            <IImport size={20} /><span>{importing ? 'Importing' : 'Import PDF or MusicXML'}</span>
          </button>
        </>
      )}
      <Link to="/scan" className={`dbtn ${canImport ? '' : 'is-primary'}`}><ICamera size={20} /><span>Photograph pages</span></Link>
    </div>
  )

  return (
    <Screen header={header} dock={dock} className="is-library">
      <LayoutGroup id="library">
      <div className={`lib-work ${open ? 'has-side' : ''} ${open && docked ? 'side-docked' : ''}`}>
        <motion.div className="lib" layoutScroll>
          <div className="lib-inner">
            <div className="ctx">
              {vp.narrow ? (
                <select className="ctx-select" value={context.ensemble.id} onChange={e => setContext(e.target.value)} aria-label="Library">
                  {contexts.map(c => <option key={c.ensemble.id} value={c.ensemble.id}>{c.ensemble.name}</option>)}
                </select>
              ) : (
                <div className="seg" role="radiogroup" aria-label="Library">
                  {contexts.map(c => (
                    <button key={c.ensemble.id} type="button" role="radio" aria-checked={context.ensemble.id === c.ensemble.id} onClick={() => setContext(c.ensemble.id)}>
                      {c.ensemble.name}
                    </button>
                  ))}
                </div>
              )}
              {/* The group shelf's people control: name, code, members, leave and delete. */}
              {inGroup && (
                <button type="button" className="btn btn-line g-people" onClick={() => navigate('/group')} aria-haspopup="dialog">
                  <IPeople size={20} /><span className="num">{context.ensemble.members.length}</span><span>{context.ensemble.members.length === 1 ? 'person' : 'people'}</span>
                </button>
              )}
              <span className="grow" />
              <button type="button" className="btn btn-quiet" onClick={() => openGroups('create')} aria-haspopup="dialog" aria-label="Create a group"><IPlusCircle size={20} /><span className="g-act-word">Create a group</span></button>
              <button type="button" className="btn btn-quiet" onClick={() => openGroups('join')} aria-haspopup="dialog" aria-label="Join a group"><IKeypad size={20} /><span className="g-act-word">Join a group</span></button>
            </div>

            {importMsg && (
              <p className="lib-msg" role="alert"><IWarning size={16} /><span>{importMsg}</span>
                <button type="button" className="btn-icon" aria-label="Dismiss" onClick={() => setImportMsg(null)}><IClose size={18} /></button>
              </p>
            )}

            {folders.length === 0 && (
              <div className="empty is-inline">
                <p>{world.loaded ? 'Nothing here yet. Import a PDF or a MusicXML file, or photograph the pages, and the score appears here as a cover. A PDF reads itself.' : 'Opening the library'}</p>
                {world.loaded && canImport && <button type="button" className="btn btn-line" onClick={() => fileRef.current?.click()}><IImport size={18} />Import PDF or MusicXML</button>}
                {world.loaded && <Link className="btn btn-line" to="/scan"><ICamera size={18} />Photograph pages</Link>}
              </div>
            )}

            {folders.map(f => (
              <section key={f.name} className="folder" aria-label={f.name}>
                <div className="folder-h">
                  <h2>{f.name}</h2>
                  <span>{f.scores.length}</span>
                </div>
                <ul className="covers">
                  {f.scores.map(s => (
                    <motion.li key={s.id} layout transition={SPRING_LAYOUT}>
                      <Cover
                        score={s} state={stateOf(s)} selected={selected === s.id}
                        onSelect={() => setSelected(v => (v === s.id ? null : s.id))}
                        onInfo={() => setSelected(s.id)} onAsk={setAsking} onConvert={() => convert(s)}
                      />
                    </motion.li>
                  ))}
                </ul>
              </section>
            ))}
          </div>
        </motion.div>
        <InfoBox
          score={open} state={open ? stateOf(open) : null} docked={docked} onClose={() => setSelected(null)}
          onAsk={setAsking} onConvert={convert} convertMsg={open ? convertMsg[open.id] : undefined}
        />
      </div>
      </LayoutGroup>
      <StaffQuestion job={asking} open={!!asking} onClose={() => setAsking(null)} />
      <GroupSheet open={groupOpen} face={groupFace} onFace={setFace} onClose={closeGroups} onOpened={onOpened} />
    </Screen>
  )
}

function StatusBadge({ score: s, partName }: { score: Score; partName?: string }) {
  if (s.status === 'ordering') return <span className="badge">Order pages</span>
  if (s.status === 'uploaded') return <span className="badge">Not read yet</span>
  if (partName) return <span className="badge is-mine">{partName}</span>
  return null
}

function Cover({ score: s, state, selected, onSelect, onInfo, onAsk, onConvert }: {
  score: Score; state: BookState; selected: boolean; onSelect: () => void; onInfo: () => void; onAsk: (j: AskJob) => void; onConvert: () => void
}) {
  const { context, partsById } = useStore()
  const mine = context.membership.role === 'player' ? s.partIds.map(id => partsById[id]).find(p => p && p.name === context.persona.instrument) : undefined
  const myPart = mine ? partShort[mine.name] ?? mine.name : undefined
  const dot = dotOf(state)
  const said = [
    s.title, s.composer, state.kinds.map(k => bookWord[k]).join(' and '),
    state.busy === 'converting' ? 'converting to Digital' : s.status === 'ready' ? '' : statusWord[s.status],
    dot === 'ask' ? 'the librarian has a question' : dot === 'fail' && s.status !== 'failed' ? 'the conversion stopped' : '',
  ].filter(Boolean).join(', ')
  return (
    // The whole book lifts when chosen: cover, dot, ring and menu move as one.
    <motion.div className="cover-wrap" initial={false} animate={{ y: selected ? -3 : 0, scale: selected ? 1.02 : 1 }} transition={SPRING_LAYOUT}>
      {state.busy && <span className="cover-ring" aria-hidden="true" />}
      <button type="button" className={`cover ${s.status === 'ready' ? '' : 'is-unavailable'}`} aria-pressed={selected} onClick={onSelect} aria-label={said}>
        <span className="cover-composer">{s.composer}</span>
        {/* The title is the one thing the information box takes from the cover: it travels there and back. */}
        <motion.span className="cover-title" layoutId={`cover-title-${s.id}`} layout="position" transition={SPRING_LAYOUT}>{s.title}</motion.span>
        <span className="cover-work">{s.work}</span>
        <span className="cover-foot"><StatusBadge score={s} partName={myPart} /><span className="cover-tags"><BookTags kinds={state.kinds} /></span></span>
      </button>
      <StatusDot state={state} className="cover-dot" />
      <BookMenu score={s} state={state} onInfo={onInfo} onAsk={onAsk} onConvert={onConvert} className="cover-more" />
    </motion.div>
  )
}

/** The book's "…" menu: its state first (a question waiting, digitalising in progress, a stop), then how to open it. */
function BookMenu({ score: s, state, onInfo, onAsk, onConvert, className = '' }: {
  score: Score; state: BookState; onInfo?: () => void; onAsk: (j: AskJob) => void; onConvert: () => void; className?: string
}) {
  const { contextFor } = useStore()
  const [open, setOpen] = useState(false)
  const canEdit = (contextFor(s.ensembleId)?.membership.role ?? 'player') !== 'player'
  useEffect(() => {
    if (!open) return
    // Capture phase, so Escape closes this menu and leaves a sheet under it open.
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') { e.stopImmediatePropagation(); setOpen(false) } }
    window.addEventListener('keydown', onKey, true)
    return () => window.removeEventListener('keydown', onKey, true)
  }, [open])
  const close = () => setOpen(false)
  const canConvert = canEdit && state.hasPdf && !state.hasDigital && s.status === 'ready' && !state.busy && !state.asking
  return (
    <div className={`book-menu ${className}`}>
      <button type="button" className="btn-icon" aria-label={`${s.title}, more`} aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen(v => !v)}>
        <IMore size={22} />
      </button>
      <AnimatePresence>{open && <Scrim key="scrim" clear fixed onClose={close} />}</AnimatePresence>
      <Pop open={open} origin="top right" className="menu" role="menu" aria-label={`${s.title}`}>
        {state.asking && (
          state.ask && canEdit
            ? <button type="button" role="menuitem" className="menu-item is-status" onClick={() => { close(); onAsk(state.ask!) }}><span className="dot is-ask" aria-hidden="true" />The librarian has a question<IChevronRight size={18} /></button>
            : <button type="button" role="menuitem" className="menu-item is-status" onClick={() => { close(); onInfo?.() }}><span className="dot is-ask" aria-hidden="true" />The librarian has a question</button>
        )}
        {!state.asking && state.busy && (
          <div role="menuitem" aria-disabled="true" className="menu-item is-status is-busy"><span className="busy-ring" aria-hidden="true" />Digitalising in progress</div>
        )}
        {!state.asking && !state.busy && state.failed && (
          <button type="button" role="menuitem" className="menu-item is-status" onClick={() => { close(); onInfo?.() }}><span className="dot is-fail" aria-hidden="true" />{s.status === 'failed' ? 'Reading stopped' : 'The conversion stopped'}</button>
        )}
        {state.hasPdf && <Link role="menuitem" className="menu-item" to={`/score/${s.id}/pages`} onClick={close}><IScore size={20} />Open PDF</Link>}
        {state.digitalReady && <Link role="menuitem" className="menu-item" to={`/score/${s.id}`} onClick={close}><INote size={20} />Open Digital</Link>}
        {canConvert && <button type="button" role="menuitem" className="menu-item" onClick={() => { close(); onConvert() }}><INote size={20} />Convert to Digital</button>}
        {onInfo && <button type="button" role="menuitem" className="menu-item" onClick={() => { close(); onInfo() }}><IInfo size={20} />Book page</button>}
      </Pop>
    </div>
  )
}

/** The information box as a sheet. Stays mounted with no score so the sheet can leave. */
function InfoBox({ score, state, docked, onClose, onAsk, onConvert, convertMsg }: {
  score: Score | null; state: BookState | null; docked: boolean; onClose: () => void; onAsk: (j: AskJob) => void; onConvert: (s: Score) => void; convertMsg?: string
}) {
  return (
    <Sheet open={!!score} docked={docked} onClose={onClose} label={score ? `${score.title}, information` : 'Information'} className="info">
      {score && state && <InfoBody score={score} state={state} onClose={onClose} onAsk={onAsk} onConvert={() => onConvert(score)} convertMsg={convertMsg} />}
    </Sheet>
  )
}

function InfoBody({ score: s, state: st, onClose, onAsk, onConvert, convertMsg }: {
  score: Score; state: BookState; onClose: () => void; onAsk: (j: AskJob) => void; onConvert: () => void; convertMsg?: string
}) {
  const { context, practiceUI, partsById, contextFor } = useStore()
  const { membership, persona, ensemble } = context
  const parts = s.partIds.map(id => partsById[id]).filter(Boolean)
  // A seat is a part name on the membership; the holder of a part is the member whose seat matches.
  const holderOf = (p: Part) => ensemble.members.find(m => m.instrument === p.name)
  const myPart = membership.role === 'player' ? parts.find(p => p.name === persona.instrument) : undefined
  const ready = s.status === 'ready'
  const digital = s.book === 'digital'
  const canEdit = (contextFor(s.ensembleId)?.membership.role ?? 'player') !== 'player'
  const flags = s.flags
  const flagText = flags && (flags.pagesUnreadable || flags.barsDoubtful)
    ? [flags.pagesUnreadable ? `${flags.pagesUnreadable} ${flags.pagesUnreadable === 1 ? 'page' : 'pages'} unreadable` : null,
       flags.barsDoubtful ? `${flags.barsDoubtful} ${flags.barsDoubtful === 1 ? 'bar' : 'bars'} doubtful` : null].filter(Boolean).join(', ')
    : null
  const isPractice = practice.scoreId === s.id
  const [exporting, setExporting] = useState(false)
  // A digital book exports what it was imported as; a converted PDF book exports its transcription.
  const exportPath = digital ? s.sourcePath : s.transcriptionPath
  const canConvert = canEdit && st.hasPdf && !st.hasDigital && ready && !st.asking
  const fromCamera = s.pageSource?.kind === 'images'

  const exportBook = async () => {
    if (!exportPath) return
    setExporting(true)
    try {
      await exportStored(exportPath, exportName(s.title, exportPath, digital ? s.sourceName : undefined))
    } catch (e) {
      window.alert((e as Error).message)
    } finally {
      setExporting(false)
    }
  }

  return (
    <>
      <div className="side-head">
        <h2 className="sr-only">Information</h2>
        <StatusDot state={st} />
        <BookTags kinds={st.kinds} />
        <span className="grow" />
        <BookMenu score={s} state={st} onAsk={onAsk} onConvert={onConvert} />
        <Details score={s} digital={digital} flagText={flagText} />
        <button type="button" className="btn-icon" onClick={onClose} aria-label="Close"><IClose size={20} /></button>
      </div>
      <div className="side-scroll">
        <div>
          <motion.h2 className="info-title" layoutId={`cover-title-${s.id}`} layout="position" transition={SPRING_LAYOUT}>{s.title}</motion.h2>
          <p className="info-sub">{[s.composer, s.work].filter(Boolean).join(' · ')}</p>
        </div>

        <Identity score={s} digital={digital} />

        {/* The two ways into the book. PDF: the pages as printed. Digital: the engraving, parts and practice. */}
        {(st.hasPdf || st.hasDigital) && (
          <div className={`modes ${st.hasPdf && st.hasDigital ? 'is-pair' : ''}`}>
            {st.hasPdf && (
              <Link className="mode" to={`/score/${s.id}/pages`}>
                <IScore size={22} />
                <span className="mode-text"><b>Open PDF</b><span>As printed</span></span>
              </Link>
            )}
            {st.hasDigital && (st.digitalReady ? (
              <Link className="mode" to={`/score/${s.id}`}>
                <INote size={22} />
                <span className="mode-text"><b>Open Digital</b><span>Part by part</span></span>
              </Link>
            ) : (
              <span className="mode is-off" aria-disabled="true">
                <INote size={22} />
                <span className="mode-text"><b>Open Digital</b><span>{st.busy ? 'When reading finishes' : 'Not ready'}</span></span>
              </span>
            ))}
          </div>
        )}
        {st.hasPdf && !st.hasDigital && (canConvert || st.busy === 'converting') && (
          <div className="convert">
            <button type="button" className={`btn btn-line ${st.busy === 'converting' ? 'is-busy' : ''}`} disabled={!!st.busy} onClick={onConvert}>
              {st.busy === 'converting' ? <><span className="busy-ring" aria-hidden="true" />Digitalising</> : <><INote size={18} />Convert to Digital</>}
            </button>
            <p className="info-log">{st.busy === 'converting'
              ? 'The librarian is writing the notes out from the pages. The PDF stays open to read meanwhile.'
              : 'The librarian writes the notes out from the pages, so the book can be read part by part and practised.'}</p>
            {convertMsg && <p className="sheet-msg" role="alert">{convertMsg}</p>}
          </div>
        )}

        {st.asking && (
          <div className="info-state is-ask">
            <span className="reason"><span className="dot is-ask" aria-hidden="true" />The librarian has a question</span>
            {st.question && <span>{st.question}</span>}
            {st.ask && canEdit
              ? <button type="button" className="btn btn-solid is-small" onClick={() => onAsk(st.ask!)}>Answer</button>
              : !canEdit && <span className="flags">The admin answers it.</span>}
          </div>
        )}
        {st.failed && !st.asking && (
          <div className="info-state is-failed">
            <span className="reason"><span className="dot is-fail" aria-hidden="true" />{s.status === 'failed' ? 'Reading stopped' : 'The conversion stopped'}</span>
            <span>{st.failed}</span>
            {flagText && <span className="flags">{flagText}</span>}
          </div>
        )}
        {st.busy === 'reading' && !st.asking && (
          <div className="info-state">
            <span className="reason is-busy"><span className="busy-ring" aria-hidden="true" />Digitalising in progress</span>
            <span>{digital ? 'Reading the file. The parts appear when it finishes.' : 'The librarian is reading the pages. It asks here if a page cannot be placed.'}</span>
          </div>
        )}
        {s.status === 'ordering' && (
          <div className="info-state">
            <span>{s.pages} photographed pages waiting for their order.</span>
          </div>
        )}
        {ready && !digital && flagText && <p className="info-flags"><IWarning size={15} />{flagText}</p>}

        {parts.length > 0 && (
          <div>
            <h3>{myPart ? 'Your part, and the others' : 'Parts'}</h3>
            <ul className="parts-list">
              {[...parts].sort((a, b) => (a.id === myPart?.id ? -1 : b.id === myPart?.id ? 1 : 0)).map(p => {
                const who = holderOf(p)
                const isMine = p.id === myPart?.id
                return (
                  <li key={p.id}>
                    <span className="pname">{p.name}{isMine && <span className="badge is-mine">You</span>}</span>
                    <span className={`pwho ${who || isMine ? '' : 'is-unassigned'}`}>{isMine ? persona.name : who ? who.name : 'No player yet'}</span>
                    <span className="pdiff">{difficultyWord[p.difficulty] ?? ''}</span>
                  </li>
                )
              })}
            </ul>
          </div>
        )}

        {ready && s.brief && membership.role !== 'player' && (
          <div>
            <h3>Brief</h3>
            <blockquote className="info-brief">{s.brief}</blockquote>
          </div>
        )}

        <PartsPanel score={s} />

        <div className="info-actions">
          {ready && isPractice && (
            <Link to="/practice" className="btn btn-line">
              Practise {partsById[practice.partId]?.name}{practiceUI.loop ? `, loop ${barRange(practiceUI.loop.from, practiceUI.loop.to)}` : ''}
            </Link>
          )}
          {ready && exportPath && (
            <button type="button" className="btn btn-line" disabled={exporting} onClick={exportBook}>
              <IExport size={18} />{exporting ? 'Exporting' : 'Export MusicXML'}
            </button>
          )}
          {s.status === 'ordering' && <Link to="/scan" className="btn btn-solid">Order pages</Link>}
          {s.status === 'failed' && fromCamera && <Link to="/scan" className="btn btn-solid"><ICamera size={18} />Retake pages</Link>}
        </div>
      </div>
    </>
  )
}

/** The (i) beside the close button: the book's housekeeping, which the box itself does not lead with. */
function Details({ score: s, digital, flagText }: { score: Score; digital: boolean; flagText: string | null }) {
  const [open, setOpen] = useState(false)
  useEffect(() => {
    if (!open) return
    // Capture phase, so Escape closes this popover and leaves the sheet under it open.
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') { e.stopImmediatePropagation(); setOpen(false) } }
    window.addEventListener('keydown', onKey, true)
    return () => window.removeEventListener('keydown', onKey, true)
  }, [open])
  const rows: [string, string][] = [
    ...(!digital && s.pages ? [['Pages', String(s.pages)] as [string, string]] : []),
    ...(s.tempoBpm ? [['Tempo', `${s.tempoBpm} bpm, as marked`] as [string, string]] : []),
    ...(!digital && s.status === 'ready' ? [['Read', flagText ?? 'Every page and bar placed'] as [string, string]] : []),
    ...(digital && s.sourceName ? [['Imported from', s.sourceName.replace(/\.[a-z]+$/i, '')] as [string, string]] : []),
    ['Last changed', fmtDateTime(s.updatedAt)],
  ]
  return (
    <div className="disp-wrap">
      <button type="button" className="btn-icon" aria-label="Details" aria-expanded={open} aria-pressed={open} onClick={() => setOpen(v => !v)}>
        <IInfo size={21} />
      </button>
      <AnimatePresence>{open && <Scrim key="scrim" clear fixed onClose={() => setOpen(false)} />}</AnimatePresence>
      <Pop open={open} origin="top right" className="disp info-more" role="dialog" aria-label="Details">
        <dl className="facts">
          {rows.map(([k, v]) => <div key={k} className="facts-row"><dt>{k}</dt><dd>{v}</dd></div>)}
        </dl>
      </Pop>
    </div>
  )
}
