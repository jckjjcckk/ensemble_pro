/** The Shelf (R3, replaces the library; docs/design/r3 Main, R3_ShelfMineEmpty, R3_ShelfGroups). Two shelves behind one
 *  segmented tab: My Library (the account's own books, a card grid) and Groups (one row per group: its books, shared by
 *  reference or the group's own, its code and who is on the stand). A card opens the Book sheet; Manage groups opens
 *  the Groups dialog. The dock carries the two places, Shelf and Stand. Everything is the real world (`useStore`). */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router'
import { AnimatePresence, motion } from 'motion/react'
import type { Score } from '../mock'
import { ApiError, apiFailure, convertToDigital } from '../lib/api'
import { supabase } from '../lib/supabase'
import { useAuth } from './auth'
import { MY_LIBRARY, importMusicXml, importPdf, isPdf, shareBook, unshareBook, type AskJob } from './data'
import { Places, useReducedMotion } from './layout'
import { AccountButton } from './Display'
import { ICopy, IGroupR3, MiniStaff, useCopy } from './r3bits'
import { StaffQuestion } from './StaffQuestion'
import { BookSheet } from './BookSheet'
import { GroupsDialog, codeWords } from './GroupsDialog'
import { BottomSheet, Confirm } from './Surfaces'
import { SPRING_LAYOUT } from './Sheet'
import { bookShare, bookState, dotOf, type BookShare, type BookState } from './book'
import { useStore, type Context } from './store'
import { IClose, IWarning } from './icons'

type Tab = 'mine' | 'groups'

const IImportR3 = () => <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M12 4v12M7 11l5 5 5-5M5 20h14" /></svg>
const IScanR3 = () => <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M4 8V5a1 1 0 0 1 1-1h3M16 4h3a1 1 0 0 1 1 1v3M20 16v3a1 1 0 0 1-1 1h-3M8 20H5a1 1 0 0 1-1-1v-3M4 12h16" /></svg>
const IPlusR3 = () => <svg aria-hidden="true" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"><path d="M12 5v14M5 12h14" /></svg>

const kindWord = { pdf: 'PDF', digital: 'Digital' } as const
const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`

/** Who on each group is on the stand right now: presence rows written in the last ten minutes (012), by group. */
function useOnStand(groupIds: string[], selfIds: Set<string>): Record<string, number> {
  const [counts, setCounts] = useState<Record<string, number>>({})
  const key = groupIds.join(',')
  const selfKey = [...selfIds].join(',')
  useEffect(() => {
    if (!key) return
    let live = true
    const read = async () => {
      const since = new Date(Date.now() - 10 * 60_000).toISOString()
      const { data } = await supabase.from('presence').select('ensemble_id,member_id').gte('updated_at', since)
      if (!live || !data) return
      const out: Record<string, Set<string>> = {}
      for (const r of data as { ensemble_id: string; member_id: string }[]) {
        if (selfKey.split(',').includes(r.member_id)) continue
        ;(out[r.ensemble_id] ??= new Set()).add(r.member_id)
      }
      setCounts(Object.fromEntries(Object.entries(out).map(([g, s]) => [g, s.size])))
    }
    void read()
    const id = window.setInterval(read, 30_000)
    return () => { live = false; window.clearInterval(id) }
  }, [key, selfKey])
  return counts
}

export default function Shelf() {
  const navigate = useNavigate()
  const { pathname } = useLocation()
  const { context, contexts, setContext, world, jobsFor, scoresById } = useStore()
  const { session } = useAuth()
  const tab: Tab = pathname.startsWith('/group') ? 'groups' : 'mine'
  const [selected, setSelected] = useState<string | null>(null)
  const [sheetOpen, setSheetOpen] = useState(false)
  const [importing, setImporting] = useState<string | null>(null)
  const [importMsg, setImportMsg] = useState<string | null>(null)
  const [asking, setAsking] = useState<AskJob | null>(null)
  const [groupsOpen, setGroupsOpen] = useState(pathname === '/group')
  const [shareHere, setShareHere] = useState<string | null>(null)
  // Conversions asked for here, until the job row arrives; and what a refused one said.
  const [converting, setConverting] = useState<Record<string, boolean>>({})
  const [convertMsg, setConvertMsg] = useState<Record<string, string>>({})
  const fileRef = useRef<HTMLInputElement>(null)

  useEffect(() => { if (pathname === '/group') setGroupsOpen(true) }, [pathname])

  const here = context.ensemble.id
  const shareOf = useCallback((s: Score, where = here): BookShare => bookShare(s, world.shares, world.owners, world.account.id, where), [world.shares, world.owners, world.account.id, here])
  const stateOf = useCallback((s: Score): BookState => {
    const st = bookState(s, world.bookJobs, jobsFor(s.id))
    return converting[s.id] && !st.busy && !st.hasDigital ? { ...st, busy: 'converting' } : st
  }, [world.bookJobs, jobsFor, converting])

  // A conversion's own job row takes over from the local flag.
  useEffect(() => {
    const done = Object.keys(converting).filter(id => world.bookJobs.some(j => j.scoreId === id && j.kind === 'omr_convert'))
    if (done.length) setConverting(c => Object.fromEntries(Object.entries(c).filter(([id]) => !done.includes(id))))
  }, [world.bookJobs, converting])

  const mine = world.scores.filter(s => s.ensembleId === MY_LIBRARY)
  const groups = contexts.filter(c => c.ensemble.id !== MY_LIBRARY)
  const shelfOf = useCallback((c: Context) => {
    const gid = c.ensemble.id
    const own = world.scores.filter(s => s.ensembleId === gid && !world.owners[s.id])
    const shared = world.shares.filter(x => x.ensembleId === gid).map(x => scoresById[x.scoreId]).filter((s): s is Score => !!s)
    return [...new Map([...shared, ...own].map(s => [s.id, s])).values()]
  }, [world.scores, world.owners, world.shares, scoresById])
  const selfIds = useMemo(() => new Set(world.account.memberships.map(m => m.memberId)), [world.account.memberships])
  const onStand = useOnStand(groups.map(g => g.ensemble.id), selfIds)

  const open = selected ? scoresById[selected] ?? null : null
  const openBook = (s: Score, from: string) => {
    // The shelf a book is opened from decides its mark layer on the stand (`markGroupFor`).
    setContext(from)
    setSelected(s.id)
    setSheetOpen(true)
  }

  const onFile = async (file: File | undefined) => {
    if (!file || !session) return
    setImporting(file.name); setImportMsg(null)
    try {
      const apiBase = (import.meta.env.VITE_API_URL as string | undefined) ?? 'http://localhost:8000'
      await (isPdf(file) ? importPdf : importMusicXml)(file, { ensembleId: null, ownerId: session.user.id, createdBy: session.user.id }, apiBase, session.access_token)
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
      // Already converting (409 names the live job): the sheet shows that one; nothing to say.
      if (e instanceof ApiError && e.status === 409 && e.live) { world.reload(); return }
      setConvertMsg(m => ({ ...m, [s.id]: apiFailure(e, 'Converting to Digital') }))
    }
  }

  // "9 books · 2 being read · 1 needs you"; "3 groups · 3 shared books · Quartet is rehearsing now".
  const states = mine.map(stateOf)
  const busyN = states.filter(s => s.busy).length
  const needN = states.filter(s => dotOf(s)).length
  const mineLine = !world.loaded ? 'Opening the shelf'
    : !mine.length ? 'No books yet'
    : [plural(mine.length, 'book'), busyN ? `${busyN} being read` : '', needN ? `${needN} ${needN === 1 ? 'needs' : 'need'} you` : ''].filter(Boolean).join(' · ')
  const sharedN = new Set(world.shares.filter(x => groups.some(g => g.ensemble.id === x.ensembleId)).map(x => x.scoreId)).size
  const rehearsing = groups.find(g => (onStand[g.ensemble.id] ?? 0) > 0)
  const groupsLine = !world.loaded ? 'Opening the shelf'
    : !groups.length ? 'No groups yet'
    : [plural(groups.length, 'group'), plural(sharedN, 'shared book'), rehearsing ? `${rehearsing.ensemble.name} is rehearsing now` : ''].filter(Boolean).join(' · ')

  const empty = tab === 'mine' && world.loaded && mine.length === 0

  return (
    <div className="shelf">
      <header className="shelf-top">
        <AnimatePresence mode="popLayout" initial={false}>
          <motion.h1 key={tab} className="shelf-title" initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -6 }} transition={{ duration: 0.18 }}>
            {tab === 'mine' ? 'My Library' : 'Groups'}
          </motion.h1>
        </AnimatePresence>
        <div className="shelf-acts">
          {tab === 'mine' && !empty && (
            <>
              <button type="button" className="r3-btn is-card" aria-label="Import a PDF or MusicXML file" disabled={!!importing} onClick={() => fileRef.current?.click()}>
                <IImportR3 />{importing ? 'Importing' : 'Import'}
              </button>
              <Link to="/scan" className="r3-btn is-card" aria-label="Scan a paper score with the camera"><IScanR3 />Scan</Link>
            </>
          )}
          {tab === 'groups' && (
            <button type="button" className="r3-btn is-solid" aria-label="Manage groups: join, create, members" aria-haspopup="dialog" onClick={() => setGroupsOpen(true)}>
              <IGroupR3 />Manage groups
            </button>
          )}
          <AccountButton />
        </div>
        <input ref={fileRef} type="file" accept=".pdf,application/pdf,.musicxml,.xml,.mxl,application/vnd.recordare.musicxml+xml" className="sr-only" tabIndex={-1} onChange={e => onFile(e.target.files?.[0])} aria-label="Import a PDF or MusicXML file" />
      </header>

      <div className="shelf-sub">
        <div className="r3-seg" role="tablist" aria-label="Which shelf">
          <button type="button" role="tab" aria-selected={tab === 'mine'} onClick={() => navigate('/', { replace: true })}>My Library</button>
          <button type="button" role="tab" aria-selected={tab === 'groups'} onClick={() => navigate('/groups', { replace: true })}>Groups</button>
        </div>
        <span className="shelf-line" aria-live="polite">{tab === 'mine' ? mineLine : groupsLine}</span>
      </div>

      {importMsg && (
        <p className="shelf-msg" role="alert"><IWarning size={16} /><span>{importMsg}</span>
          <button type="button" className="btn-icon" aria-label="Dismiss" onClick={() => setImportMsg(null)}><IClose size={18} /></button>
        </p>
      )}

      <main className="shelf-body">
        {tab === 'mine' && (empty
          ? <EmptyShelf importing={!!importing} onImport={() => fileRef.current?.click()} onGroups={() => navigate('/groups', { replace: true })} />
          : (
            <ul className="shelf-grid" aria-label="My Library">
              {mine.map(s => (
                <motion.li key={s.id} layout="position" transition={SPRING_LAYOUT}>
                  <BookCard score={s} state={stateOf(s)} share={shareOf(s, MY_LIBRARY)} selected={sheetOpen && selected === s.id} onOpen={() => openBook(s, MY_LIBRARY)} />
                </motion.li>
              ))}
            </ul>
          ))}
        {tab === 'groups' && (
          <div className="g-rows">
            {groups.map(c => (
              <GroupRow
                key={c.ensemble.id} context={c} books={shelfOf(c)} live={onStand[c.ensemble.id] ?? 0} stateOf={stateOf}
                hasOwn={mine.length > 0} selected={sheetOpen ? selected : null}
                onOpen={s => openBook(s, c.ensemble.id)} onShare={() => setShareHere(c.ensemble.id)}
              />
            ))}
            {world.loaded && !groups.length && (
              <div className="g-none">
                <span className="g-none-title">No groups yet</span>
                <span>A quartet, a choir, a duo: everyone who reads the same books. Join one with its eight-digit code, or make one.</span>
                <button type="button" className="r3-btn is-solid" onClick={() => setGroupsOpen(true)}><IGroupR3 />Manage groups</button>
              </div>
            )}
          </div>
        )}
      </main>

      <footer className="shelf-dock"><Places /></footer>

      <BookSheet
        score={open} open={sheetOpen && !!open} state={open ? stateOf(open) : null} share={open ? shareOf(open) : null}
        onClose={() => setSheetOpen(false)} onAsk={setAsking} onConvert={convert} convertMsg={open ? convertMsg[open.id] : undefined}
      />
      <StaffQuestion job={asking} open={!!asking} onClose={() => setAsking(null)} />
      <GroupsDialog open={groupsOpen} onClose={() => { setGroupsOpen(false); if (pathname === '/group') navigate('/groups', { replace: true }) }} />
      <ShareHere groupId={shareHere} onClose={() => setShareHere(null)} />
    </div>
  )
}

// ---------------------------------------------------------------- the card

/** "Page 3 could not be read — rescan it": a failure as one line. */
const oneLine = (s: string) => s.split(/(?<=[.!?])\s/)[0].replace(/\.$/, '')

function BookCard({ score: s, state, share, selected, onOpen, owner }: {
  score: Score; state: BookState; share: BookShare; selected: boolean; onOpen: () => void
  /** On a group's shelf: whose book it is ("Yours", "Anna K.", "Group") in place of its length. */
  owner?: string
}) {
  const reduced = useReducedMotion()
  const dot = dotOf(state)
  const shared = !owner && share.sharedWith.length > 0
  // A split or conversion at work, in a line: what, then where it stands or that it waits.
  const job = state.split ?? state.convert
  const jobLine = job ? `${job.kind === 'part_cut' ? 'Splitting' : 'Converting'} · ${job.state === 'needs_review' ? 'needs you' : job.state === 'queued' ? (job.resuming ? 'resuming' : 'queued') : job.detail.charAt(0).toLowerCase() + job.detail.slice(1)}` : null
  const said = [
    s.composer, s.title, state.kinds.map(k => kindWord[k]).join(' and '),
    s.bars ? `${s.bars} bars` : '', owner ? `${owner === 'Yours' ? 'your book' : `from ${owner}`}` : '',
    state.busy === 'converting' ? 'converting to Digital' : state.busy ? 'being read' : '', jobLine ?? '',
    dot === 'ask' ? 'needs your confirmation' : dot === 'fail' ? `import failed: ${oneLine(state.failed ?? '')}` : '',
    shared ? 'shared with a group' : '',
  ].filter(Boolean).join(', ')
  return (
    <motion.button
      type="button" className={`card ${owner ? 'is-row' : ''}`} onClick={onOpen} aria-label={said} aria-haspopup="dialog"
      initial={false} animate={reduced ? undefined : { y: selected ? -3 : 0 }} transition={SPRING_LAYOUT}
      whileTap={reduced ? undefined : { scale: 0.985 }}
    >
      <span className="card-composer">{s.composer || ' '}</span>
      <span className="card-title">{s.title}</span>
      <span className="grow" />
      <MiniStaff score={s} />
      <span className="card-foot">
        <span>{owner ?? (s.bars ? `${s.bars.toLocaleString('en')} bars` : '—')}</span>
        <span className="card-tags">
          {shared && <span className="card-shared" aria-hidden="true" />}
          {state.kinds.map(k => <span key={k} className="r3-tag">{kindWord[k]}</span>)}
        </span>
      </span>
      {dot === 'fail' && state.failed && <span className="card-fail">{oneLine(state.failed)}</span>}
      {jobLine && <span className="card-live" aria-hidden="true">{jobLine}</span>}
      {(state.busy || job?.state === 'running' || job?.state === 'queued') && !dot && <span className="card-ring" aria-hidden="true" />}
      {dot && <span className={`card-dot is-${dot}`} aria-hidden="true" />}
    </motion.button>
  )
}

// ---------------------------------------------------------------- empty shelf (first import)

function EmptyShelf({ importing, onImport, onGroups }: { importing: boolean; onImport: () => void; onGroups: () => void }) {
  return (
    <div className="shelf-empty">
      <div className="shelf-empty-staff" aria-hidden="true"><span className="clef">𝄞</span></div>
      <div className="shelf-empty-text">
        <span className="shelf-empty-title">Nothing on your shelf yet</span>
        <span className="shelf-empty-why">Bring a score in and Folio reads it into numbered bars on its own. A ten-page PDF takes about two minutes.</span>
      </div>
      <div className="shelf-empty-acts">
        <button type="button" className="r3-btn is-solid is-big" onClick={onImport} disabled={importing}><IImportR3 />{importing ? 'Importing' : 'Import a PDF or MusicXML'}</button>
        <Link to="/scan" className="r3-btn is-card is-big"><IScanR3 />Scan paper pages</Link>
      </div>
      <span className="shelf-empty-note">Books shared with you by a group live under <button type="button" className="r3-link" onClick={onGroups}>Groups</button>.</span>
    </div>
  )
}

// ---------------------------------------------------------------- a group's row

function GroupRow({ context: c, books, live, stateOf, hasOwn, selected, onOpen, onShare }: {
  context: Context; books: Score[]; live: number; stateOf: (s: Score) => BookState; hasOwn: boolean; selected: string | null
  onOpen: (s: Score) => void; onShare: () => void
}) {
  const { world } = useStore()
  const [copied, copy] = useCopy()
  const g = c.ensemble
  const code = world.groups[g.id]?.joinCode
  const admin = c.membership.role === 'admin'
  const leader = g.members.find(m => m.role === 'leader' && m.id !== c.persona.id)
  const meta = `${plural(g.members.length, 'member')} · ${admin ? 'you are admin' : leader ? `${leader.name.split(' ')[0]} is admin` : 'you are a member'}`
  const ownerOf = (s: Score) => {
    const sh = world.shares.find(x => x.scoreId === s.id && x.ensembleId === g.id)
    if (!sh) return 'Group'
    return sh.sharedBy === world.account.id ? 'Yours' : sh.sharedByName
  }
  return (
    <section className="g-row" aria-label={g.name}>
      <div className="g-row-head">
        <div className="g-row-name">
          <h2>{g.name}</h2>
          <span className="g-row-meta">{meta}</span>
          {live > 0 && <span className="g-live"><span aria-hidden="true" />{live} on the stand</span>}
        </div>
        {code && (
          <button type="button" className="g-code-chip" aria-label={copied === g.id ? 'Join code copied' : `Copy the join code, ${code.split('').join(' ')}`} onClick={() => copy(code, g.id)}>
            {copied === g.id ? 'Copied' : codeWords(code)}<ICopy />
          </button>
        )}
      </div>
      <ul className="g-books">
        {books.map(s => (
          <li key={s.id}>
            <BookCard score={s} state={stateOf(s)} share={bookShare(s, world.shares, world.owners, world.account.id, g.id)} owner={ownerOf(s)} selected={selected === s.id} onOpen={() => onOpen(s)} />
          </li>
        ))}
        {books.length === 0 ? (
          <li className="g-empty">
            <span className="g-empty-title">No books on this shelf yet</span>
            <span>Anyone in the group can share one of their own books here. Everyone then reads the same copy.</span>
            {hasOwn && <button type="button" className="r3-btn is-card" onClick={onShare}>Share one of mine</button>}
          </li>
        ) : hasOwn && (
          <li><button type="button" className="g-cta" onClick={onShare}><IPlusR3 />Share a book here</button></li>
        )}
      </ul>
    </section>
  )
}

// ---------------------------------------------------------------- share one of mine into a group

/** "Share a book here": the account's own books, one switch each, for one group. On shares at once (`share_score`);
 *  off asks once (`unshare_score`). By reference: the book stays in the owner's library. */
function ShareHere({ groupId, onClose }: { groupId: string | null; onClose: () => void }) {
  const { world, contextFor } = useStore()
  const [shown, setShown] = useState<string | null>(groupId)
  useEffect(() => { if (groupId) setShown(groupId) }, [groupId])
  const g = shown ? contextFor(shown)?.ensemble : undefined
  const mine = world.scores.filter(s => s.ensembleId === MY_LIBRARY)
  const [busy, setBusy] = useState<string | null>(null)
  const [confirm, setConfirm] = useState<string | null>(null)
  const [msg, setMsg] = useState<string | null>(null)
  const isOn = (id: string) => world.shares.some(x => x.scoreId === id && x.ensembleId === shown)
  const run = async (id: string, on: boolean) => {
    if (!shown) return
    setBusy(id); setMsg(null)
    try { await (on ? shareBook : unshareBook)(id, shown); setConfirm(null); world.reload() } catch (e) { setMsg((e as Error).message) } finally { setBusy(null) }
  }
  const confirming = mine.find(s => s.id === confirm)
  return (
    <BottomSheet open={!!groupId && !!g} onClose={onClose} label={`Share a book with ${g?.name ?? 'the group'}`} className="share-here">
      <div className="sheet-h">
        <h2>Share with {g?.name}</h2>
        <button type="button" className="r3-btn is-quiet" onClick={onClose}>Done</button>
      </div>
      <p className="sheet-note">The group reads the book from your library. Nothing is copied, and your own marks stay yours.</p>
      <ul className="share-rows r3-scroll">
        {mine.map(s => {
          const on = isOn(s.id)
          return (
            <li key={s.id}>
              <button type="button" role="switch" aria-checked={on} aria-busy={busy === s.id} disabled={!!busy && busy !== s.id} className="share-row2"
                onClick={() => (on ? setConfirm(s.id) : void run(s.id, true))}>
                <span className="share-row2-text"><span className="card-composer">{s.composer}</span><b>{s.title}</b></span>
                <span className={`switch ${on ? 'is-on' : ''}`} aria-hidden="true"><span /></span>
              </button>
            </li>
          )
        })}
      </ul>
      {msg && !confirming && <p className="r3-msg" role="alert">{msg}</p>}
      {confirming && g && (
        <Confirm
          question={`Stop sharing ${confirming.title} with ${g.name}?`}
          why="The group stops seeing it at once. What its members marked on it is kept, and comes back if you share it again."
          act="Stop sharing" busyWord="Stopping" busy={!!busy} msg={msg}
          onCancel={() => { setConfirm(null); setMsg(null) }} onAct={() => void run(confirming.id, false)}
        />
      )}
    </BottomSheet>
  )
}
