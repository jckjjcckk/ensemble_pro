/** The Book sheet (R3, docs/design/r3/R2_BookSheet): a bottom sheet over the dimmed shelf. The book's identity (composer,
 *  title, length, its PDF / Digital tag, the engraved key and time signature, dates under the (i)), then what can be done
 *  with it: Open on the stand (where it was left), Split by instrument, Convert to Digital, Share with a group; Export
 *  MusicXML, Rename and Delete book in the foot. The book's state (being read, a question for you, a stop) sits above the
 *  actions in one line each, and the question opens the confirmation screen (011). */
import { useEffect, useRef, useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router'
import { AnimatePresence, motion } from 'motion/react'
import type { Score } from '../mock'
import { MY_LIBRARY, deleteBook, exportName, exportStored, renameBook, type AskJob } from './data'
import { BottomSheet, Confirm } from './Surfaces'
import { MiniStaff, IGroupR3 } from './r3bits'
import { PartsPanel } from './Parts'
import { ShareSheet } from './Groups'
import { placeOf, IStand } from './layout'
import { EASE_OUT } from './Sheet'
import type { BookShare, BookState } from './book'
import { fmtDateTime, useStore } from './store'

const kindWord = { pdf: 'PDF', digital: 'Digital' } as const
/** Convert to Digital runs about 40 s a page on the box (005). */
const convertMinutes = (pages: number) => Math.max(1, Math.round((pages * 40) / 60))

const IChev = () => <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M9 5l7 7-7 7" /></svg>
const ISplit = () => <svg aria-hidden="true" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"><path d="M4 6h16M4 12h16M4 18h16M12 3v18" /></svg>
const IConvert = () => <svg aria-hidden="true" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M4 12a8 8 0 0 1 14-5M20 12a8 8 0 0 1-14 5M18 3v4h-4M6 21v-4h4" /></svg>

/** Where a book opens on the stand: its engraved pages when it has them, else its PDF pages. */
export function standPath(s: Score, prefer?: 'pdf' | 'digital'): string {
  const digital = !!s.engravings?.length || (!s.pageSource && !!s.fixture)
  if (prefer === 'pdf' && s.pageSource) return `/score/${s.id}/pages`
  if (prefer === 'digital' && digital) return `/score/${s.id}`
  return digital ? `/score/${s.id}` : `/score/${s.id}/pages`
}

export function BookSheet({ score, open, state, share, onClose, onAsk, onConvert, convertMsg }: {
  score: Score | null; open: boolean; state: BookState | null; share: BookShare | null
  onClose: () => void; onAsk: (j: AskJob) => void; onConvert: (s: Score) => void; convertMsg?: string
}) {
  // The last book shown stays while the sheet leaves, so its content does not vanish mid-exit.
  const last = useRef<{ score: Score; state: BookState; share: BookShare } | null>(null)
  if (score && state && share) last.current = { score, state, share }
  const shown = last.current
  return (
    <BottomSheet open={open} onClose={onClose} label={shown?.score.title ?? 'Book'} className="book-sheet">
      {shown && <Body key={shown.score.id} {...shown} onClose={onClose} onAsk={onAsk} onConvert={() => onConvert(shown.score)} convertMsg={convertMsg} />}
    </BottomSheet>
  )
}

function Body({ score: s, state: st, share, onClose, onAsk, onConvert, convertMsg }: {
  score: Score; state: BookState; share: BookShare; onClose: () => void; onAsk: (j: AskJob) => void; onConvert: () => void; convertMsg?: string
}) {
  const navigate = useNavigate()
  const { canEditBook, world, contextFor } = useStore()
  const canEdit = canEditBook(s)
  const borrowed = share.sharedHere && !share.mine
  const ready = s.status === 'ready'
  const digital = s.book === 'digital'
  const place = placeOf(s.id)
  const [parts, setParts] = useState(false)
  const [sharing, setSharing] = useState(false)
  const [renaming, setRenaming] = useState(false)
  const [title, setTitle] = useState(s.title)
  const [confirm, setConfirm] = useState(false)
  const [busy, setBusy] = useState<'rename' | 'delete' | 'export' | null>(null)
  const [msg, setMsg] = useState<string | null>(null)

  const parts_n = s.partIds.length
  const facts = [s.bars ? `${s.bars.toLocaleString('en')} bars` : null, parts_n > 1 ? `${parts_n} parts` : null, !digital && s.pages ? `${s.pages} ${s.pages === 1 ? 'page' : 'pages'}` : null].filter(Boolean).join(' · ')
  const canOpen = ready && (!!s.pageSource || !!s.engravings?.length || !!s.fixture)
  const openWhy = s.status === 'processing' ? 'Opens when the reading finishes' : s.status === 'failed' ? 'The pages could not be read' : s.status === 'ordering' ? 'The pages wait for their order' : 'Not read yet'
  const canConvert = canEdit && st.hasPdf && !st.hasDigital && ready && !st.busy && !st.asking
  const canSplit = !borrowed && canEdit && (!digital || (ready && parts_n > 1))
  const convertTile = st.hasPdf && (st.hasDigital || canConvert || st.busy === 'converting')
  const exportPath = digital ? s.sourcePath : s.transcriptionPath
  const sharedGroups = share.sharedWith.map(id => contextFor(id)?.ensemble.name).filter((n): n is string => !!n)
  const home = s.ensembleId !== MY_LIBRARY ? contextFor(s.ensembleId)?.ensemble.name : null

  const go = (prefer?: 'pdf' | 'digital') => { onClose(); navigate(standPath(s, prefer)) }

  const saveTitle = async (e?: FormEvent) => {
    e?.preventDefault()
    const t = title.trim()
    if (!t || t === s.title) { setRenaming(false); return }
    setBusy('rename'); setMsg(null)
    try { await renameBook(s.id, t); world.reload(); setRenaming(false) } catch (err) { setMsg((err as Error).message) } finally { setBusy(null) }
  }
  const remove = async () => {
    setBusy('delete'); setMsg(null)
    try { await deleteBook(s.id); world.reload(); onClose() } catch (err) { setMsg((err as Error).message); setBusy(null) }
  }
  const exportBook = async () => {
    if (!exportPath) return
    setBusy('export'); setMsg(null)
    try { await exportStored(exportPath, exportName(s.title, exportPath, digital ? s.sourceName : undefined)) } catch (err) { setMsg((err as Error).message) } finally { setBusy(null) }
  }

  return (
    <div className="bs">
      <div className="bs-id">
        <div className="bs-id-text">
          <span className="card-composer bs-composer">{s.composer || ' '}</span>
          {renaming ? (
            <form className="bs-rename" onSubmit={saveTitle}>
              <input value={title} onChange={e => setTitle(e.target.value)} aria-label="Title" autoFocus maxLength={200} enterKeyHint="done" onKeyDown={e => { if (e.key === 'Escape') { e.stopPropagation(); setRenaming(false); setTitle(s.title) } }} />
              <button type="button" className="r3-btn is-line" onClick={() => { setRenaming(false); setTitle(s.title) }}>Cancel</button>
              <button type="submit" className="r3-btn is-solid" disabled={!title.trim() || busy === 'rename'}>{busy === 'rename' ? 'Saving' : 'Save'}</button>
            </form>
          ) : <h2 className="bs-title">{s.title}</h2>}
          <div className="bs-facts">
            {facts && <span>{facts}</span>}
            {st.kinds.map(k => <span key={k} className="r3-tag">{kindWord[k]}</span>)}
            <Dates score={s} digital={digital} />
          </div>
          {share.sharedHere && share.sharedBy && <span className="bs-by">{borrowed ? `Shared by ${share.sharedBy} from their own library` : 'Shared by you from your library'}</span>}
        </div>
        <div className="bs-staff"><MiniStaff score={s} unit={1.2} width={262} /></div>
      </div>

      <StateLine score={s} state={st} canEdit={canEdit} borrowed={borrowed} onAsk={onAsk} />

      <div className="bs-tiles">
        <button type="button" className="bs-tile is-open" disabled={!canOpen} onClick={() => go()}>
          <span className="bs-tile-in">
            <IStand size={22} />
            <span className="bs-tile-text">
              <b>Open on the stand</b>
              <span>{!canOpen ? openWhy : place ? `Continues at bar ${place.bar}, page ${place.page}` : 'Starts at bar 1'}</span>
            </span>
          </span>
          <IChev />
        </button>
        {canSplit && (
          <button type="button" className={`bs-tile ${convertTile ? '' : 'is-wide'}`} onClick={() => setParts(true)} aria-haspopup="dialog">
            <ISplit />
            <span className="bs-tile-text"><b>Split by instrument</b><span>One book per part</span></span>
          </button>
        )}
        {st.hasPdf && (st.hasDigital ? (
          <button type="button" className={`bs-tile ${canSplit ? '' : 'is-wide'}`} disabled={!st.digitalReady} onClick={() => go('digital')}>
            <IConvert />
            <span className="bs-tile-text"><b>Digital</b><span>{st.digitalReady ? 'Read the engraved pages' : 'Being prepared'}</span></span>
          </button>
        ) : (canConvert || st.busy === 'converting') && (
          <button type="button" className={`bs-tile ${canSplit ? '' : 'is-wide'} ${st.busy === 'converting' ? 'is-busy' : ''}`} disabled={!!st.busy} onClick={onConvert}>
            {st.busy === 'converting' ? <span className="r3-ring" aria-hidden="true" /> : <IConvert />}
            <span className="bs-tile-text">
              <b>{st.busy === 'converting' ? 'Digitalising in progress' : 'Convert to Digital'}</b>
              <span>{st.busy === 'converting' ? 'The PDF stays open to read meanwhile' : s.pages ? `About ${convertMinutes(s.pages)} minutes for ${s.pages} ${s.pages === 1 ? 'page' : 'pages'}` : 'About a minute a page'}</span>
            </span>
          </button>
        ))}
        {share.mine && (
          <button type="button" className="bs-tile is-wide is-row" onClick={() => setSharing(true)} aria-haspopup="dialog">
            <span className="bs-tile-in"><IGroupR3 size={22} /><b>Share with a group</b></span>
            <span className="bs-tile-end">
              {sharedGroups.slice(0, 2).map(n => <span key={n} className="g-chip"><span aria-hidden="true" />{n}</span>)}
              {sharedGroups.length > 2 && <span className="g-chip is-more">+{sharedGroups.length - 2}</span>}
              <IChev />
            </span>
          </button>
        )}
        {!share.mine && home && (
          <div className="bs-tile is-wide is-row is-static">
            <span className="bs-tile-in"><IGroupR3 size={22} /><b>{borrowed ? 'Read through a share' : "The group's own book"}</b></span>
            <span className="bs-tile-end"><span className="g-chip"><span aria-hidden="true" />{share.sharedHere ? contextFor(world.shares.find(x => x.scoreId === s.id)?.ensembleId ?? '')?.ensemble.name ?? home : home}</span></span>
          </div>
        )}
      </div>
      {convertMsg && <p className="r3-msg" role="alert">{convertMsg}</p>}

      <AnimatePresence initial={false}>
        {confirm ? (
          <Confirm
            key="confirm"
            question={`Delete ${s.title}?`}
            why={share.sharedWith.length ? 'It leaves your library and every group it is shared with, with its splits and markings. This cannot be undone.' : 'It leaves the shelf with its splits and markings. This cannot be undone.'}
            act="Delete book" busyWord="Deleting" busy={busy === 'delete'} msg={msg}
            onCancel={() => { setConfirm(false); setMsg(null) }} onAct={() => void remove()}
          />
        ) : (
          <motion.div key="foot" className="bs-foot" initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.16, ease: EASE_OUT }}>
            <div className="bs-foot-l">
              {ready && exportPath && !borrowed && <button type="button" className="r3-btn is-quiet" disabled={busy === 'export'} onClick={() => void exportBook()}>{busy === 'export' ? 'Exporting' : 'Export MusicXML'}</button>}
              {canEdit && !renaming && <button type="button" className="r3-btn is-quiet" onClick={() => setRenaming(true)}>Rename</button>}
            </div>
            {canEdit && <button type="button" className="r3-btn is-quiet is-red" onClick={() => setConfirm(true)}>Delete book…</button>}
            {msg && <p className="r3-msg bs-foot-msg" role="alert">{msg}</p>}
          </motion.div>
        )}
      </AnimatePresence>

      <BottomSheet open={parts} onClose={() => setParts(false)} label="Split by instrument" className="parts-sheet">
        <div className="sheet-h"><h2>Split by instrument</h2><button type="button" className="r3-btn is-quiet" onClick={() => setParts(false)}>Done</button></div>
        <div className="r3-scroll parts-sheet-body info"><PartsPanel score={s} /></div>
      </BottomSheet>
      <ShareSheet score={s} open={sharing} onClose={() => setSharing(false)} />
    </div>
  )
}

/** The book's state in one line: being read, a question for you (opens the confirmation screen), or why it stopped. */
function StateLine({ score: s, state: st, canEdit, borrowed, onAsk }: { score: Score; state: BookState; canEdit: boolean; borrowed: boolean; onAsk: (j: AskJob) => void }) {
  const navigate = useNavigate()
  if (st.asking) {
    return (
      <div className="bs-state is-ask">
        <span className="card-dot is-ask is-inline" aria-hidden="true" />
        <span className="bs-state-text"><b>The librarian has a question</b>{st.question && <span>{st.question}</span>}</span>
        {st.ask && canEdit
          ? <button type="button" className="r3-btn is-solid" onClick={() => onAsk(st.ask!)}>Answer</button>
          : <span className="bs-state-who">{borrowed ? 'Its owner answers it' : 'The admin answers it'}</span>}
      </div>
    )
  }
  if (st.busy === 'reading') {
    return (
      <div className="bs-state">
        <span className="r3-ring" aria-hidden="true" />
        <span className="bs-state-text"><b>Digitalising in progress</b><span>{s.book === 'digital' ? 'Reading the file. The parts appear when it finishes.' : 'The librarian is reading the pages. It asks here if a page cannot be placed.'}</span></span>
      </div>
    )
  }
  if (st.failed) {
    const camera = s.pageSource?.kind === 'images'
    return (
      <div className="bs-state is-fail">
        <span className="card-dot is-fail is-inline" aria-hidden="true" />
        <span className="bs-state-text"><b>{s.status === 'failed' ? 'Reading stopped' : 'The conversion stopped'}</b><span>{st.failed}</span></span>
        {s.status === 'failed' && camera && !borrowed && <button type="button" className="r3-btn is-line" onClick={() => navigate('/scan')}>Rescan</button>}
      </div>
    )
  }
  if (s.status === 'ordering') {
    return (
      <div className="bs-state">
        <span className="bs-state-text"><b>{s.pages} photographed pages wait for their order</b></span>
        {!borrowed && <button type="button" className="r3-btn is-line" onClick={() => navigate('/scan')}>Order pages</button>}
      </div>
    )
  }
  return null
}

/** The (i): the book's housekeeping, which the sheet does not lead with. */
function Dates({ score: s, digital }: { score: Score; digital: boolean }) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const onDown = (e: PointerEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false) }
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') { e.stopImmediatePropagation(); setOpen(false) } }
    window.addEventListener('pointerdown', onDown, true)
    window.addEventListener('keydown', onKey, true)
    return () => { window.removeEventListener('pointerdown', onDown, true); window.removeEventListener('keydown', onKey, true) }
  }, [open])
  const rows: [string, string][] = [
    ...(s.tempoBpm ? [['Tempo', `${s.tempoBpm} bpm, as marked`] as [string, string]] : []),
    ...(!digital && s.pages ? [['Pages', String(s.pages)] as [string, string]] : []),
    ...(digital && s.sourceName ? [['Imported from', s.sourceName.replace(/\.[a-z]+$/i, '')] as [string, string]] : []),
    ['Last changed', fmtDateTime(s.updatedAt)],
  ]
  return (
    <div className="bs-dates" ref={ref}>
      <button type="button" className="bs-i" aria-label="Dates and provenance" aria-expanded={open} onClick={() => setOpen(v => !v)}>i</button>
      <AnimatePresence>
        {open && (
          <motion.dl
            className="r3-pop bs-dates-pop" role="dialog" aria-label="Dates and provenance"
            initial={{ opacity: 0, scale: 0.96 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0, scale: 0.98, transition: { duration: 0.12 } }}
            transition={{ duration: 0.18, ease: EASE_OUT }} style={{ transformOrigin: 'top left' }}
          >
            {rows.map(([k, v]) => <div key={k}><dt>{k}</dt><dd>{v}</dd></div>)}
          </motion.dl>
        )}
      </AnimatePresence>
    </div>
  )
}
