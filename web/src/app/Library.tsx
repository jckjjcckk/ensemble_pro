import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router'
import { AnimatePresence, LayoutGroup, motion } from 'motion/react'
import { practice, type BookKind, type Part, type Score } from '../mock'
import { useAuth } from './auth'
import { MY_LIBRARY, exportName, exportStored, importMusicXml } from './data'
import { Screen, useViewport } from './layout'
import { DisplayButton } from './Display'
import { EASE_OUT, Pop, SPRING_LAYOUT, Scrim, Sheet } from './Sheet'
import { PartsPanel } from './Parts'
import { Identity } from './Identity'
import { barRange, difficultyWord, fmtDateTime, partShort, useStore } from './store'
import { ICamera, IClose, IExport, IImport, IInfo, IRepeat, IWarning } from './icons'

const bookWord: Record<BookKind, string> = { pdf: 'PDF', digital: 'Digital' }
/** The status as a sentence fragment, for screen readers on a cover. */
const statusWord: Record<Score['status'], string> = { uploaded: 'not read yet', ordering: 'pages waiting for their order', processing: 'being read', ready: 'ready', failed: 'needs pages' }

/** The one tag a book carries: what it was made from. */
export function BookTag({ kind }: { kind?: BookKind }) {
  return kind ? <span className="book-tag">{bookWord[kind]}</span> : null
}

const roleWord = { owner: 'your own library', admin: 'you are the admin', player: 'you play' } as const

export default function Library() {
  const vp = useViewport()
  const navigate = useNavigate()
  const { context, contexts, setContext, scan, practiceUI, partsById, world } = useStore()
  const { session } = useAuth()
  const [selected, setSelected] = useState<string | null>(null)
  const [importing, setImporting] = useState<string | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)
  const docked = vp.w >= 1100
  const scores = world.scores

  // The Fauré moves to processing once its page order is committed on the scan screen.
  const live = useMemo(() => scores.map(s => (s.id === 's-faure' && scan.committed ? { ...s, status: 'processing' as const, progress: 0 } : s)), [scores, scan.committed])
  const mine = live.filter(s => s.ensembleId === context.ensemble.id)
  const folders = [...new Set(mine.map(s => s.folder))].map(name => ({ name, scores: mine.filter(s => s.folder === name) }))
  // A selection from another library simply finds nothing here; no reset effect needed.
  const open = selected ? mine.find(s => s.id === selected) ?? null : null

  const { persona, membership } = context
  const partName = persona.partId ? partsById[persona.partId]?.name : persona.instrument
  const canImport = membership.role !== 'player'

  const onFile = async (file: File | undefined) => {
    if (!file || !session) return
    setImporting(file.name)
    try {
      const apiBase = (import.meta.env.VITE_API_URL as string | undefined) ?? 'http://localhost:8000'
      await importMusicXml(file, {
        ensembleId: context.ensemble.id === MY_LIBRARY ? null : context.ensemble.id,
        ownerId: context.ensemble.id === MY_LIBRARY ? session.user.id : null,
        createdBy: session.user.id,
      }, apiBase, session.access_token)
      world.reload()
    } catch (e) {
      window.alert(`${file.name} was not imported. ${(e as Error).message}`)
    } finally {
      setImporting(null)
      if (fileRef.current) fileRef.current.value = ''
    }
  }
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
          <input ref={fileRef} type="file" accept=".musicxml,.xml,.mxl,application/vnd.recordare.musicxml+xml" className="sr-only" onChange={e => onFile(e.target.files?.[0])} aria-label="Import a MusicXML file" />
          <button type="button" className="dbtn" disabled={!!importing} onClick={() => fileRef.current?.click()}>
            <IImport size={20} /><span>{importing ? 'Importing' : 'Import MusicXML'}</span>
          </button>
        </>
      )}
      <Link to="/scan" className="dbtn is-primary"><ICamera size={20} /><span>Scan pages</span></Link>
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
            </div>

            {folders.length === 0 && (
              <div className="empty is-inline">
                <p>{world.loaded ? 'Nothing here yet. Scan the pages of a score, or import a notation file, and it appears here as a cover.' : 'Opening the library'}</p>
                {world.loaded && canImport && <button type="button" className="btn btn-line" onClick={() => fileRef.current?.click()}><IImport size={18} />Import MusicXML</button>}
                {world.loaded && <Link className="btn btn-line" to="/scan"><ICamera size={18} />Scan pages</Link>}
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
                      <Cover score={s} selected={selected === s.id} onSelect={() => setSelected(v => (v === s.id ? null : s.id))} />
                    </motion.li>
                  ))}
                </ul>
              </section>
            ))}
          </div>
        </motion.div>
        <InfoBox score={open} docked={docked} onClose={() => setSelected(null)} />
      </div>
      </LayoutGroup>
    </Screen>
  )
}

function StatusBadge({ score: s, partName }: { score: Score; partName?: string }) {
  if (s.status === 'processing') {
    const pct = Math.round((s.progress ?? 0) * 100)
    return (
      <span className="badge is-processing">
        <span className="meter" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100} aria-label="Reading">
          <motion.span initial={false} animate={{ width: `${pct}%` }} transition={{ duration: 0.3, ease: EASE_OUT }} />
        </span>
        <span>{pct ? `${pct}% read` : 'Waiting'}</span>
      </span>
    )
  }
  if (s.status === 'failed') return <span className="badge is-failed"><IWarning size={14} /><span>Needs pages</span></span>
  if (s.status === 'ordering') return <span className="badge">Order pages</span>
  if (s.status === 'uploaded') return <span className="badge">Not read yet</span>
  if (partName) return <span className="badge is-mine">{partName}</span>
  return null
}

function Cover({ score: s, selected, onSelect }: { score: Score; selected: boolean; onSelect: () => void }) {
  const { context, partsById } = useStore()
  const mine = context.membership.role === 'player' ? s.partIds.map(id => partsById[id]).find(p => p && p.name === context.persona.instrument) : undefined
  const myPart = mine ? partShort[mine.name] ?? mine.name : undefined
  return (
    <motion.button
      type="button" className={`cover ${s.status === 'ready' ? '' : 'is-unavailable'}`} aria-pressed={selected} onClick={onSelect}
      aria-label={`${s.title}, ${s.composer}${s.book ? `, ${bookWord[s.book]}` : ''}${s.status === 'ready' ? '' : `, ${statusWord[s.status]}`}`}
      initial={false} animate={{ y: selected ? -3 : 0, scale: selected ? 1.02 : 1 }} transition={SPRING_LAYOUT}
    >
      <span className="cover-composer">{s.composer}</span>
      {/* The title is the one thing the information box takes from the cover: it travels there and back. */}
      <motion.span className="cover-title" layoutId={`cover-title-${s.id}`} layout="position" transition={SPRING_LAYOUT}>{s.title}</motion.span>
      <span className="cover-work">{s.work}</span>
      <span className="cover-foot"><StatusBadge score={s} partName={myPart} /><BookTag kind={s.book} /></span>
    </motion.button>
  )
}

/** The information box as a sheet. Stays mounted with no score so the sheet can leave. */
function InfoBox({ score, docked, onClose }: { score: Score | null; docked: boolean; onClose: () => void }) {
  return (
    <Sheet open={!!score} docked={docked} onClose={onClose} label={score ? `${score.title}, information` : 'Information'} className="info">
      {score && <InfoBody score={score} onClose={onClose} />}
    </Sheet>
  )
}

function InfoBody({ score: s, onClose }: { score: Score; onClose: () => void }) {
  const { context, practiceUI, partsById } = useStore()
  const { membership, persona, ensemble } = context
  const parts = s.partIds.map(id => partsById[id]).filter(Boolean)
  // A seat is a part name on the membership; the holder of a part is the member whose seat matches.
  const holderOf = (p: Part) => ensemble.members.find(m => m.instrument === p.name)
  const myPart = membership.role === 'player' ? parts.find(p => p.name === persona.instrument) : undefined
  const ready = s.status === 'ready'
  const digital = s.book === 'digital'
  const flags = s.flags
  const flagText = flags && (flags.pagesUnreadable || flags.barsDoubtful)
    ? [flags.pagesUnreadable ? `${flags.pagesUnreadable} ${flags.pagesUnreadable === 1 ? 'page' : 'pages'} unreadable` : null,
       flags.barsDoubtful ? `${flags.barsDoubtful} ${flags.barsDoubtful === 1 ? 'bar' : 'bars'} doubtful` : null].filter(Boolean).join(', ')
    : null
  const isPractice = practice.scoreId === s.id
  const [exporting, setExporting] = useState(false)

  const exportBook = async () => {
    if (!s.sourcePath) return
    setExporting(true)
    try {
      await exportStored(s.sourcePath, exportName(s.title, s.sourcePath, s.sourceName))
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
        <BookTag kind={s.book} />
        <span className="grow" />
        <Details score={s} digital={digital} flagText={flagText} />
        <button type="button" className="btn-icon" onClick={onClose} aria-label="Close"><IClose size={20} /></button>
      </div>
      <div className="side-scroll">
        <div>
          <motion.h2 className="info-title" layoutId={`cover-title-${s.id}`} layout="position" transition={SPRING_LAYOUT}>{s.title}</motion.h2>
          <p className="info-sub">{[s.composer, s.work].filter(Boolean).join(' · ')}</p>
        </div>

        <Identity score={s} digital={digital} />

        {s.status === 'failed' && (
          <div className="info-state is-failed">
            <span className="reason">Reading stopped</span>
            <span>{s.failureReason}</span>
            {flagText && <span className="flags">{flagText}</span>}
          </div>
        )}
        {s.status === 'processing' && (
          <div className="info-state">
            <StatusBadge score={s} />
            <span>{digital ? 'Reading the file. The parts appear when it finishes.' : `${s.pages} pages. The parts appear when reading finishes.`}</span>
          </div>
        )}
        {s.status === 'ordering' && (
          <div className="info-state">
            <span>{s.pages} pages waiting for their order. Nothing is read until you confirm it.</span>
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
          {ready && <Link to={`/score/${s.id}`} className="btn btn-solid">Open score</Link>}
          {ready && isPractice && (
            <Link to="/practice" className="btn btn-line">
              Practise {partsById[practice.partId]?.name}{practiceUI.loop ? `, loop ${barRange(practiceUI.loop.from, practiceUI.loop.to)}` : ''}
            </Link>
          )}
          {ready && digital && s.sourcePath && (
            <button type="button" className="btn btn-line" disabled={exporting} onClick={exportBook}>
              <IExport size={18} />{exporting ? 'Exporting' : 'Export MusicXML'}
            </button>
          )}
          {s.status === 'ordering' && <Link to="/scan" className="btn btn-solid">Order pages</Link>}
          {s.status === 'failed' && <Link to="/scan" className="btn btn-solid"><ICamera size={18} />Retake pages</Link>}
        </div>

        {s.status === 'processing' && !digital && <p className="info-log">The librarian is reading the pages. It will say what it did, and ask if a page cannot be placed.</p>}
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
