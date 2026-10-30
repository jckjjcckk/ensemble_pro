/** The Stand (R3, replaces the reader; docs/design/r3 R2_Stand*, R3_StandPortrait, R3_StandZoom). One header (Shelf,
 *  the book's title and where you are in it, Read | Practise, the Mine | Group layer, who else is on the stand, and the
 *  "…" menu), then the pages: two facing in landscape, one in portrait, a pinch into one page. A tap on a bar opens the
 *  vertical quick menu (Highlight, Note, Scribble, Loop from here); notes stand above their bar with their author's face;
 *  the others' faces wait at the page edge level with their bar; "Following Anna's page turns" sits at the foot. PDF
 *  page images and engraved digital pages are the same stage (`EngravedStage`); a single part or a split without
 *  engraved pages is engraved on the device (`ScoreStage`). Three appearances: light, dark with the paper dimmed, dark
 *  with the page inverted (the account menu). */
import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useLocation, useNavigate, useSearchParams } from 'react-router'
import { AnimatePresence, motion } from 'motion/react'
import type { Annotation, AnnotationKind, Engraving, Member, Score } from '../mock'
import { LAYOUT_WORDS } from '../mock'
import { supabase } from '../lib/supabase'
import { ScoreStage, type StageView } from './ScoreStage'
import { EngravedStage, type ZoomView } from './EngravedStage'
import { Fade, Pop, Scrim, Sheet } from './Sheet'
import { spanRects, type Geo } from './geometry'
import { CutLayer, KindIcon, NoteBody } from './marks'
import { barRange, firstName, initials, kindLabel, useStore, type Span } from './store'
import { IClose, IMic } from './icons'
import { useAuth } from './auth'
import { MY_LIBRARY, setDigitalLayout } from './data'
import { isSyncedScore, useBarMarks, useScribbles, type BarMark, type Me, type PenColor } from './ink'
import { usePresence } from './presence'
import { BarSelection, HighlightLayer, MarkMenu, useBarMenu } from './MarkMenu'
import { InkBar, InkLayer, type InkTool } from './InkLayer'
import { BookModes, placeOf, rememberBook, rememberPlace, useReducedMotion, useViewport } from './layout'
import { bookShare, bookState } from './book'
import { faceColor } from './GroupsDialog'
import { StaffQuestion } from './StaffQuestion'
import { ScanPatches, UnreadablePages, useBarDecisions } from './CheckBars'
import { useVoice, type Card } from './voice'
import { PickHint, VoiceButton, VoiceGhosts, VoiceTray } from './VoiceNotes'

type Tool = null | 'marking' | 'cut' | 'voice'

const markKinds: { kind: AnnotationKind; label: string }[] = [
  { kind: 'dynamic', label: 'Dynamic' },
  { kind: 'bowing', label: 'Bowing' },
  { kind: 'text', label: 'Note' },
  { kind: 'breath', label: 'Breath' },
]

const PAGE_FILE = /^(\d+)\.(png|jpe?g|webp)$/i

/** A PDF book's pages as an engraving: the rendered page images (or the photographs, in order) with the bar boxes the
 *  librarian placed (`measure_placements` of its latest finished reading, as page fractions). */
function usePdfPages(score: Score | undefined, on: boolean): { engraving: Engraving | null; aspect: number; state: 'loading' | 'ready' | 'none' } {
  const [keys, setKeys] = useState<string[] | null>(null)
  const [bars, setBars] = useState<Engraving['bars']>([])
  const [aspect, setAspect] = useState(1.414)
  const src = score?.pageSource
  const srcKey = src ? `${src.kind}:${src.paths.join('|')}:${src.order?.join(',') ?? ''}` : ''
  const id = score?.id

  useEffect(() => {
    if (!on || !id) return
    let live = true
    const run = async () => {
      let found: string[]
      if (src?.kind === 'images' && src.paths.length) {
        const order = src.order?.length ? src.order : src.paths.map((_, i) => i + 1)
        found = order.map(i => src.paths[i - 1]).filter(Boolean)
      } else {
        const { data } = await supabase.storage.from('scores').list(`${id}/pages`, { limit: 1000 })
        found = (data ?? []).map(o => o.name).filter(n => PAGE_FILE.test(n))
          .sort((a, b) => parseInt(a, 10) - parseInt(b, 10)).map(n => `${id}/pages/${n}`)
      }
      if (live) setKeys(found)
      // The bar boxes of the latest finished reading that placed any.
      const { data: runs } = await supabase.from('interpretations').select('id').eq('score_id', id).in('status', ['done', 'ready']).order('created_at', { ascending: false }).limit(4)
      for (const r of runs ?? []) {
        const { data: pl } = await supabase.from('measure_placements').select('page,box,measures(number)').eq('interpretation_id', r.id)
        const rows = (pl ?? []) as unknown as { page: number; box: { x0: number; y0: number; x1: number; y1: number }; measures: { number: number } | null }[]
        if (rows.length) {
          if (live) setBars(rows.filter(x => x.measures && x.box).map(x => [x.measures!.number, x.page, x.box.x0, x.box.y0, x.box.x1 - x.box.x0, x.box.y1 - x.box.y0]))
          break
        }
      }
      // The page's own shape, from the first image.
      if (found[0]) {
        const { data: u } = await supabase.storage.from('scores').createSignedUrl(found[0], 3600)
        if (u?.signedUrl) {
          const img = new Image()
          img.onload = () => { if (live && img.naturalWidth) setAspect(img.naturalHeight / img.naturalWidth) }
          img.src = u.signedUrl
        }
      }
    }
    run().catch(() => { if (live) setKeys([]) })
    return () => { live = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [on, id, srcKey, score?.status, score?.pages])

  const engraving = useMemo<Engraving | null>(() => (keys?.length && id ? { id: `pdf:${id}`, layout: 'original', paths: keys, pageCount: keys.length, bars } : null), [keys, bars, id])
  return { engraving, aspect, state: keys === null ? 'loading' : keys.length ? 'ready' : 'none' }
}

/** A member without a display name (a fresh account) is named by their seat. */
const unnamed = (m: Member) => !m.name || m.name === 'A member'
const memberName = (m: Member) => (unnamed(m) ? m.instrument || 'A member' : firstName(m.name))
const faceLabel = (m: Member) => initials(unnamed(m) ? m.instrument || '?' : m.name)

export default function Stand({ score, pages }: { score: Score; pages: boolean }) {
  const vp = useViewport()
  const reduced = useReducedMotion()
  const navigate = useNavigate()
  const { pathname, search: rawSearch } = useLocation()
  const { contextFor, context, annotations, addAnnotation, partsById, membersById, stripsFor, world, jobsFor, canEditBook, setPracticeUI, display, setDisplay } = useStore()
  const { session } = useAuth()
  const userId = session?.user.id ?? null
  const [search] = useSearchParams()

  // ---------------------------------------------------------------- the group this book is read in, and its layer

  const share = bookShare(score, world.shares, world.owners, world.account.id, context.ensemble.id)
  const sharedGroups = share.mine ? share.sharedWith : []
  // An owner's book shared with groups: the group it was opened from, else the first it is shared with.
  const ownerGroup = sharedGroups.length ? (sharedGroups.includes(context.ensemble.id) ? context.ensemble.id : sharedGroups[0]) : null
  const sharedInto = world.shares.filter(x => x.scoreId === score.id).map(x => x.ensembleId)
  const groupId = ownerGroup
    ?? (score.ensembleId !== MY_LIBRARY && score.ensembleId !== 'shared' ? score.ensembleId : null)
    ?? (sharedInto.find(g => contextFor(g)) ?? null)
  const group = groupId ? contextFor(groupId) : undefined
  // Mine | Group. On the owner's shared book it switches the layer (private marks, or the group's); elsewhere in a group
  // it filters the group's layer to the reader's own marks.
  const [side, setSide] = useState<'mine' | 'group'>(() => (groupId && (context.ensemble.id === groupId || !ownerGroup) ? 'group' : 'mine'))
  // A group's own book has one layer (null); someone's personal book read through a share is marked in the group's.
  const personal = !!world.owners[score.id]
  const layer: string | null = ownerGroup ? (side === 'group' ? ownerGroup : null) : personal && groupId ? groupId : null
  const filterMine = !ownerGroup && side === 'mine'

  const ctx = group ?? contextFor(score.ensembleId)
  const role = ctx?.membership.role ?? 'owner'
  const persona = ctx?.persona ?? world.ensembles[0].members[0]
  const canCut = role !== 'player'
  const memberId = ctx?.membership.memberId ?? persona.id
  const ensemble = group?.ensemble

  // ---------------------------------------------------------------- what is on the stand

  const parts = score.partIds.map(id => partsById[id]).filter(Boolean)
  const splitId = search.get('split')
  const split = splitId ? stripsFor(score.id).find(x => x.id === splitId && x.kind === 'musicxml') : undefined
  const splitSel = split ? `split:${split.id}` : null
  const seat = parts.find(p => p.name === persona.instrument)?.id
  const defaultPart = splitSel ?? (role === 'player' && seat && !pages ? seat : 'full')
  const [partSel, setPartSel] = useState<string>(defaultPart)
  useEffect(() => { setPartSel(defaultPart) }, [defaultPart])
  const isFull = partSel === 'full'
  const isSplit = !!split && partSel === splitSel
  const splitKey = split ? parts.filter(p => split.instruments.includes(p.name)).map(p => p.id).join('\n') : ''
  const splitPartIds = splitKey ? splitKey.split('\n') : []
  const splitIdx = splitPartIds.map(id => score.partIds.indexOf(id)).filter(i => i >= 0)
  const instruments = isFull ? null : isSplit ? (splitIdx.length ? splitIdx : null) : [score.partIds.indexOf(partSel)]
  const partName = isFull || isSplit ? null : partsById[partSel]?.name ?? null
  const inkPart = isSplit && split ? `split:${split.id}` : partName

  const pdf = usePdfPages(score, pages)
  const engraving = pages ? pdf.engraving : isFull ? score.engravings?.find(e => e.layout === (score.digitalLayout ?? 'display')) ?? score.engravings?.[0] : undefined
  const st = bookState(score, world.bookJobs, jobsFor(score.id))

  // ---------------------------------------------------------------- marks, ink, presence

  const inEnsemble = groupId != null
  const me = useMemo<Me>(() => ({ userId, memberId, ensemble: inEnsemble, admin: canCut }), [userId, memberId, inEnsemble, canCut])
  const partIdByName = useMemo(() => Object.fromEntries(parts.map(p => [p.name, p.id])), [parts])
  const quick = useBarMarks(score.id, me, { partIdByName, ensembleId: groupId ?? score.ensembleId, layer })
  const ink = useScribbles(score.id, inkPart, me, layer)

  const [focus, setFocus] = useState(() => ({ bar: placeOf(score.id)?.bar ?? 1, key: 0 }))
  const [view, setView] = useState<StageView | null>(null)
  const [zoom, setZoom] = useState<ZoomView | null>(null)
  const presenceMe = useMemo(
    () => (groupId && userId && isSyncedScore(score.id) && ctx?.ensemble.id === groupId ? { memberId: ctx.membership.memberId, userId } : null),
    [groupId, userId, score.id, ctx],
  )
  const presence = usePresence(score.id, presenceMe, view ? { bar: view.first, part: partName } : null)
  const hasPresence = !!presenceMe
  const performers = useMemo<Member[]>(() => {
    if (!hasPresence) return []
    const at = new Map(presence.rows.map(p => [p.memberId, p.bar]))
    return (ensemble?.members ?? [])
      .filter(m => m.id !== presenceMe?.memberId)
      .map(m => ({ ...m, online: at.has(m.id), atBar: at.get(m.id) }))
      .sort((a, b) => Number(b.role === 'leader') - Number(a.role === 'leader') || Number(b.online) - Number(a.online))
  }, [hasPresence, presence.rows, ensemble, presenceMe?.memberId])
  const online = performers.filter(m => m.online)
  const leader = online.find(m => m.role === 'leader')
  const colorOf = (id: string) => {
    const m = ensemble?.members.find(x => x.id === id)
    return id === memberId || !m || !ensemble ? 'var(--solid)' : faceColor(ensemble.members, m)
  }

  // ---------------------------------------------------------------- the reader's own state

  const [pin, setPin] = useState<string | null>(null)
  const [listOpen, setListOpen] = useState(false)
  const [moreOpen, setMoreOpen] = useState(false)
  const [asking, setAsking] = useState(false)
  const [tool, setTool] = useState<Tool>(null)
  const [draftBar, setDraftBar] = useState(1)
  const [draftSpan, setDraftSpan] = useState<Span>({ from: 1, to: 8 })
  const [draftKind, setDraftKind] = useState<AnnotationKind>('dynamic')
  const [draftText, setDraftText] = useState('')
  const [draftAll, setDraftAll] = useState(true)
  const [rec, setRec] = useState<{ on: boolean; sec: number }>({ on: false, sec: 0 })
  const menu = useBarMenu()
  const [scribble, setScribble] = useState(false)
  const { decisions } = useBarDecisions(!pages && score.flaggedBars?.length ? score.id : undefined)
  const [shownScans, setShownScans] = useState<Set<number>>(() => new Set())
  const [rescanMsg, setRescanMsg] = useState<number | null>(null)
  const [inkTool, setInkTool] = useState<InkTool>('pen')
  const [inkColor, setInkColor] = useState<PenColor>('ink')
  const [switching, setSwitching] = useState(false)

  // Voice notes (013): whoever leads the layer on screen (a group's admin, a book's owner) speaks marks; Muse proposes,
  // they confirm. Proposals live in Supabase, so only a synced book has them.
  const canVoice = canCut && quick.synced
  const [trayOpen, setTrayOpen] = useState(false)
  const [voiceFocus, setVoiceFocus] = useState<string | null>(null)
  const [picking, setPicking] = useState<Card | null>(null)
  const listening = useRef(false)
  const voice = useVoice({
    scoreId: score.id, layer, token: session?.access_token ?? null, proposed: canVoice ? quick.proposed : [],
    // A take that found something opens the tray, unless the admin is in the middle of another tool.
    onArrive: () => { if (!tool && !scribble && !menu.menu && !picking && !listening.current) setTrayOpen(true) },
  })
  const voiceCards = useMemo(() => voice.groups.flatMap(g => g.cards), [voice.groups])
  const roster = useMemo(() => ({
    parts: ensemble ? parts.map(p => p.name) : [],
    members: (ensemble?.members ?? []).map(m => ({ id: m.id, name: memberName(m) })),
  }), [ensemble, parts])

  // Follow the admin (players): the spread follows the admin's bar; the reader's own turn lets go.
  const [following, setFollowing] = useState(false)
  const canFollow = hasPresence && role === 'player'
  const followBar = canFollow && following && !menu.menu && !scribble && !tool ? leader?.atBar : undefined

  useEffect(() => { rememberBook(pathname + rawSearch) }, [pathname, rawSearch])
  useEffect(() => {
    if (!moreOpen) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') { e.stopImmediatePropagation(); setMoreOpen(false) } }
    window.addEventListener('keydown', onKey, true)
    return () => window.removeEventListener('keydown', onKey, true)
  }, [moreOpen])
  useEffect(() => {
    if (!view) return
    rememberPlace(score.id, { bar: view.first, page: view.spread * view.perView + 1 })
  }, [view, score.id])

  // Simulated recorder clock. Audio capture and transcription belong to the backend workstream.
  useEffect(() => {
    if (!rec.on) return
    const id = window.setInterval(() => setRec(r => ({ ...r, sec: r.sec + 1 })), 1000)
    return () => window.clearInterval(id)
  }, [rec.on])

  const visible = useMemo<BarMark[]>(
    () => [
      ...annotations.filter(a => a.scoreId === score.id).map(a => ({ ...a, mine: false, removable: false, audience: a.partId ? 'part' as const : 'ensemble' as const })),
      ...quick.marks,
    ].filter(a => isFull || a.partId === null || a.partId === partSel || (isSplit && !!a.partId && splitPartIds.includes(a.partId)))
      .filter(a => !filterMine || a.mine)
      .sort((a, b) => a.barFrom - b.barFrom),
    // splitKey stands in for splitPartIds (a fresh array each render).
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [annotations, quick.marks, score.id, isFull, isSplit, splitKey, partSel, filterMine],
  )
  // A voice cut's text is already "Cut 42–48" (013): say it once.
  const cuts = visible.filter(a => a.kind === 'cut').map(a => {
    const title = `Cut ${barRange(a.barFrom, a.barTo)}`
    const text = (a.text ?? '').trim()
    return { from: a.barFrom, to: a.barTo, arriving: a.arriving, label: text && text.replace(/[–-]/g, '-') !== title.replace(/[–-]/g, '-') ? `${title} · ${text}` : title }
  })
  const bubbles = visible.filter(a => a.kind !== 'cut' && a.kind !== 'highlight')
  const inkRows = filterMine ? ink.rows.filter(r => r.userId === ink.uid) : ink.rows

  /** The reader asked for a bar (a face, a note): their own move, so Follow lets go. */
  const jump = (bar: number) => { setFollowing(false); setFocus(f => ({ bar, key: f.key + 1 })) }

  const startTool = (t: Tool) => {
    menu.close()
    setMoreOpen(false)
    if (scribble) { void ink.flush(); setScribble(false) }
    setTool(t)
    setDraftText('')
    setRec({ on: false, sec: 0 })
    const start = view?.first ?? 1
    setDraftBar(start)
    if (t === 'cut') setDraftSpan({ from: start, to: Math.min(score.bars || start + 7, start + 7) })
  }
  const save = () => {
    if (tool === 'marking') {
      void quick.add({
        kind: draftKind, barFrom: draftBar, text: draftText.trim() || kindLabel[draftKind], part: partName,
        audience: !canCut ? 'self' : draftAll || isFull || isSplit || !partName ? 'ensemble' : { part: partName },
      })
    }
    if (tool === 'cut') void quick.add({ kind: 'cut', barFrom: draftSpan.from, barTo: draftSpan.to, text: 'Proposed cut', audience: 'ensemble', part: partName })
    if (tool === 'voice') {
      const a: Annotation = { id: `n${Date.now()}`, scoreId: score.id, authorId: persona.id, createdAt: new Date().toISOString(), kind: 'voice', partId: draftAll || isFull || isSplit ? null : partSel, barFrom: draftBar, barTo: draftBar, durationSec: rec.sec }
      addAnnotation(a)
    }
    setTool(null)
  }

  const onBarTap = (bar: number) => {
    if (picking?.unplaced) {
      voice.placeUnplaced(picking.unplaced.takeKey, picking.unplaced.id, bar)
      setVoiceFocus(picking.key)
      setPicking(null)
      setTrayOpen(true)
      return
    }
    if (tool === 'marking' || tool === 'voice') setDraftBar(bar)
    else if (tool === 'cut') setDraftSpan(s => (bar < s.from ? { from: bar, to: s.to } : { from: s.from, to: bar }))
    else if (pin) setPin(null)
    else menu.tap(bar)
  }
  // Long press on a bar: the admin's full composer on that bar.
  const onBarHold = (bar: number) => {
    if (tool) { onBarTap(bar); return }
    if (!canCut) { menu.tap(bar); return }
    startTool('marking')
    setDraftBar(bar)
  }
  const loopFrom = (bar: number) => {
    menu.close()
    setPracticeUI(p => ({ ...p, loop: { from: bar, to: Math.min(score.bars || bar + 3, bar + 3) }, bar }))
    navigate(`/practice?score=${encodeURIComponent(score.id)}`)
  }

  const menuBar = menu.menu?.bar ?? null
  const onBar = menuBar == null ? [] : visible.filter(a => a.kind !== 'cut' && a.barFrom <= menuBar && menuBar <= a.barTo)
  const highlighted = onBar.some(a => a.kind === 'highlight' && a.mine)
  // The reader's own highlight is the Highlight row itself (pressed); the list holds everything else on the bar.
  const onMenuBar = onBar.filter(a => !(a.kind === 'highlight' && a.mine))
  const nameOf = (m: BarMark) => firstName(membersById[m.authorId]?.name ?? 'Someone')
  const endScribble = () => { void ink.flush(); setScribble(false) }
  const arrivingBars = new Set(visible.filter(a => a.kind === 'highlight' && a.arriving).map(a => a.barFrom))

  const underlay = (g: Geo) => (
    <>
      <CutLayer geo={g} cuts={cuts} />
      {tool === 'cut' && spanRects(g, draftSpan.from, draftSpan.to).map(r => (
        <div key={`d${r.first}`} className="u-cut is-draft" style={{ left: r.x, top: r.y - 10, width: r.w, height: r.h + 20 }} />
      ))}
      <HighlightLayer geo={g} bars={visible.filter(a => a.kind === 'highlight').map(a => a.barFrom)} arriving={arrivingBars} />
      {!tool && !scribble && <BarSelection geo={g} bar={menuBar} />}
      {(tool === 'marking' || tool === 'voice') && g.bars.get(draftBar) && (() => {
        const b = g.bars.get(draftBar)!
        return <div className="u-loop" style={{ left: b.x - 4, top: b.y - 14, width: b.w + 8, height: b.h + 28 }} />
      })()}
    </>
  )

  const overlay = (g: Geo, z?: ZoomView | null) => (
    <>
      {!pages && decisions.size > 0 && <ScanPatches geo={g} score={score} decisions={decisions} />}
      {pages && !!score.unreadable?.length && (
        <UnreadablePages geo={g} score={score} shown={shownScans} rescanMsg={rescanMsg}
          onShow={p => setShownScans(s => new Set(s).add(p))} onRescan={p => setRescanMsg(p)} />
      )}
      {canVoice && <VoiceGhosts geo={g} cards={voiceCards} focus={voiceFocus} onOpen={k => { setVoiceFocus(k); setTrayOpen(true) }} />}
      <Bubbles geo={g} items={bubbles} big={!!z} selected={pin} colorOf={colorOf} nameOf={nameOf} faceOf={a => initials(membersById[a.authorId]?.name ?? nameOf(a))} onSelect={a => { setPin(a.id); menu.tap(a.barFrom) }} />
      <EdgeFaces geo={g} people={online} zoom={z ?? null} colorOf={colorOf} onJump={jump} />
      <InkLayer
        geo={g} rows={inkRows} uid={ink.uid} active={scribble} tool={inkTool} color={inkColor}
        onStroke={ink.addStroke} onErase={ink.erase} arriving={ink.arriving}
      />
      <MarkMenu
        geo={g} state={scribble || tool ? null : menu.menu} marks={onMenuBar} highlighted={highlighted} nameOf={nameOf}
        onHighlight={() => { if (menuBar != null) void quick.toggleHighlight(menuBar, partName); menu.close() }}
        onNote={() => menu.setMenu(m => (m ? { ...m, note: !m.note } : m))}
        onSaveNote={text => { if (menuBar != null) void quick.add({ kind: 'text', barFrom: menuBar, text, audience: canCut && side === 'group' && groupId ? 'ensemble' : 'self', part: partName }); menu.close() }}
        onScribble={() => { menu.close(); setPin(null); setScribble(true) }}
        onLoop={() => { if (menuBar != null) loopFrom(menuBar) }}
        onRemove={id => void quick.remove(id)}
        onClose={menu.close}
      />
    </>
  )

  // ---------------------------------------------------------------- header

  // "Beethoven, Ludwig van" and "Ludwig van Beethoven" both read "Beethoven".
  const composerLast = score.composer.includes(',') ? score.composer.split(',')[0].trim() : score.composer.split(/\s+/).slice(-1)[0] || score.composer
  const partWord = isSplit ? split!.label : partName
  const where = zoom && view
    ? `${barRange(view.first, view.last).includes('–') ? 'bars' : 'bar'} ${barRange(view.first, view.last)} · p. ${zoom.page + 1}${zoom.bottom - zoom.top < 0.92 ? `, ${zoom.top < 0.12 ? 'upper' : zoom.bottom > 0.88 ? 'lower' : 'middle'} ${zoom.bottom - zoom.top < 0.6 ? 'half' : 'part'}` : ''}`
    : view ? `bars ${view.first}–${view.last}${score.bars ? ` of ${score.bars}` : ''}` : pages ? 'PDF' : ''
  // A page on view that the reader could not read says so in the where-line (F_Unreadable).
  const unreadOnView = pages && view ? (score.unreadable ?? []).find(u => !shownScans.has(u.page) && u.page > view.spread * view.perView && u.page <= (view.spread + 1) * view.perView) : undefined
  const whereLine = [where, unreadOnView ? `page ${unreadOnView.page} could not be read` : null].filter(Boolean).join(' · ')
  const layerName = ownerGroup ? contextFor(ownerGroup)?.ensemble.name : group?.ensemble.name
  const showLayer = !!groupId && !!layerName
  const canLayout = !pages && isFull && canEditBook(score) && !!score.engravings?.length
  const layout = score.digitalLayout ?? 'display'
  const switchLayout = async () => {
    setSwitching(true)
    try { await setDigitalLayout(score.id, layout === 'original' ? 'display' : 'original'); world.reload() } catch { /* the menu keeps the old state */ }
    setSwitching(false)
    setMoreOpen(false)
  }
  const pdfFile = score.pageSource?.kind === 'pdf' ? score.pageSource.paths[0] : undefined
  const openPdfFile = async () => {
    if (!pdfFile) return
    const { data } = await supabase.storage.from('scores').createSignedUrl(pdfFile, 3600)
    if (data?.signedUrl) window.open(data.signedUrl, '_blank', 'noopener')
  }
  const backTo = context.ensemble.id === MY_LIBRARY ? '/' : '/groups'

  const header = (
    <header className="stand-top">
      <div className="stand-left">
        <Link to={backTo} className="stand-back" aria-label="Back to the shelf">
          <svg aria-hidden="true" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M15 5l-7 7 7 7" /></svg>Shelf
        </Link>
        <div className="stand-title">
          <span className="stand-name"><span className="stand-name-t">{score.title}</span>{partWord && <span className="stand-name-p"> — {partWord}</span>}</span>
          <span className="stand-where">{[composerLast, whereLine].filter(Boolean).join(' · ')}</span>
        </div>
      </div>
      <BookModes scoreId={score.id} />
      <div className="stand-right">
        {showLayer && (
          <div className="r3-seg is-outline stand-layer" role="radiogroup" aria-label="Whose marks">
            <button type="button" role="radio" aria-checked={side === 'mine'} onClick={() => { setSide('mine'); menu.close() }}>Mine</button>
            <button type="button" role="radio" aria-checked={side === 'group'} onClick={() => { setSide('group'); menu.close() }}><span className="g-dot" aria-hidden="true" /><span className="stand-layer-name">{layerName}</span></button>
          </div>
        )}
        {online.length > 0 && (
          <ul className="stand-faces" aria-label="Who else is on the stand">
            {online.slice(0, 3).map(m => (
              <li key={m.id}>
                <button type="button" className="r3-face" style={{ background: colorOf(m.id) }} onClick={() => m.atBar && jump(m.atBar)}
                  aria-label={`${memberName(m)}${m.role === 'leader' ? ', leads' : ''}, at bar ${m.atBar}. Show bar ${m.atBar}`}>{faceLabel(m)}</button>
              </li>
            ))}
            {online.length > 3 && <li className="r3-face is-more" aria-label={`${online.length - 3} more`}>+{online.length - 3}</li>}
          </ul>
        )}
        <div className="stand-more">
          <button type="button" className="r3-icon" aria-label="More" aria-haspopup="menu" aria-expanded={moreOpen} onClick={() => setMoreOpen(v => !v)}>
            <svg aria-hidden="true" width="22" height="22" viewBox="0 0 24 24">{[6, 12, 18].map(x => <circle key={x} cx={x} cy="12" r="1.7" fill="currentColor" />)}</svg>
          </button>
          <AnimatePresence>{moreOpen && <Scrim key="scrim" clear fixed onClose={() => setMoreOpen(false)} />}</AnimatePresence>
          <Pop open={moreOpen} origin="top right" className="r3-pop stand-menu" role="menu" aria-label={`${score.title}, more`}>
            {st.asking && (
              <button type="button" role="menuitem" className="sm-item is-status" disabled={!st.ask || !canEditBook(score)} onClick={() => { setMoreOpen(false); setAsking(true) }}>
                <span className="card-dot is-ask is-inline" aria-hidden="true" />The librarian has a question
              </button>
            )}
            {!st.asking && st.busy && <div role="menuitem" aria-disabled="true" className="sm-item is-status"><span className="r3-ring" aria-hidden="true" />Digitalising in progress</div>}
            {!st.asking && !st.busy && st.failed && <div role="menuitem" aria-disabled="true" className="sm-item is-status"><span className="card-dot is-fail is-inline" aria-hidden="true" />{score.status === 'failed' ? 'Reading stopped' : 'The conversion stopped'}</div>}
            {st.hasPdf && st.digitalReady && (
              <button type="button" role="menuitem" className="sm-item" onClick={() => { setMoreOpen(false); navigate(pages ? `/score/${score.id}` : `/score/${score.id}/pages`, { replace: true }) }}>
                {pages ? 'Show the digital pages' : 'Show the PDF pages'}
              </button>
            )}
            {!pages && (parts.length > 1 || split) && (
              <div className="sm-group" role="group" aria-label="Part">
                <span className="r3-label">Part</span>
                {[{ id: 'full', name: 'Score' }, ...(split && splitSel ? [{ id: splitSel, name: split.label }] : []), ...parts].map(pt => (
                  <button key={pt.id} type="button" role="menuitemradio" aria-checked={partSel === pt.id} className="sm-item is-radio" onClick={() => { setPartSel(pt.id); setMoreOpen(false) }}>{pt.name}</button>
                ))}
              </div>
            )}
            {canLayout && (
              <button type="button" role="menuitemcheckbox" aria-checked={layout === 'original'} className="sm-item is-check" disabled={switching} onClick={() => void switchLayout()}>
                <span className="sm-text"><span>{LAYOUT_WORDS.original}</span><small>{layout === 'original' ? 'On: the pages as the file prints them' : `Off: ${LAYOUT_WORDS.display.toLowerCase()}`}</small></span>
              </button>
            )}
            <button type="button" role="menuitem" className="sm-item" onClick={() => { setMoreOpen(false); setListOpen(true) }}>Markings <span className="sm-count">{visible.length}</span></button>
            {canFollow && leader && (
              <button type="button" role="menuitemcheckbox" aria-checked={following} className="sm-item is-check" onClick={() => { setFollowing(v => !v); setMoreOpen(false) }}>Follow {memberName(leader)}'s page turns</button>
            )}
            {canCut && (
              <div className="sm-group" role="group" aria-label="Add for everyone">
                <span className="r3-label">Add</span>
                <button type="button" role="menuitem" className="sm-item" onClick={() => startTool('marking')}>A marking</button>
                <button type="button" role="menuitem" className="sm-item" onClick={() => startTool('cut')}>A cut</button>
                {!canVoice && <button type="button" role="menuitem" className="sm-item" onClick={() => startTool('voice')}>A voice note</button>}
              </div>
            )}
            {pages && pdfFile && <button type="button" role="menuitem" className="sm-item" onClick={() => { setMoreOpen(false); void openPdfFile() }}>Open the PDF file</button>}
            <div className="sm-group" role="group" aria-label="Appearance">
              <span className="r3-label">Appearance</span>
              <div className="r3-seg is-fill" role="radiogroup" aria-label="Theme">
                {(['system', 'light', 'dark'] as const).map(t => (
                  <button key={t} type="button" role="radio" aria-checked={display.theme === t} onClick={() => setDisplay(d => ({ ...d, theme: t }))}>{t === 'system' ? 'Auto' : t === 'light' ? 'Light' : 'Dark'}</button>
                ))}
              </div>
              <div className="r3-seg is-fill" role="radiogroup" aria-label="Pages in the dark">
                <button type="button" role="radio" aria-checked={display.page === 'dim'} onClick={() => setDisplay(d => ({ ...d, page: 'dim' }))}>Dimmed paper</button>
                <button type="button" role="radio" aria-checked={display.page === 'invert'} onClick={() => setDisplay(d => ({ ...d, page: 'invert' }))}>Inverted</button>
              </div>
            </div>
          </Pop>
        </div>
      </div>
    </header>
  )

  // ---------------------------------------------------------------- the composer (admin tools), floating at the foot

  const barStepper = (
    <div className="stepper" role="group" aria-label="Bar">
      <button type="button" className="dbtn is-icon" onClick={() => setDraftBar(b => Math.max(1, b - 1))} aria-label="Previous bar">−</button>
      <span className="stepper-val"><span className="stepper-k">bar</span><span className="num">{draftBar}</span></span>
      <button type="button" className="dbtn is-icon" onClick={() => setDraftBar(b => Math.min(score.bars || b + 1, b + 1))} aria-label="Next bar">+</button>
    </div>
  )
  const audience = canCut && !isFull && !isSplit && (
    <label className="check"><input type="checkbox" checked={draftAll} onChange={e => setDraftAll(e.target.checked)} /><span>Everyone</span></label>
  )
  const composer = tool && (
    <motion.form
      key={tool} className="composer stand-composer"
      initial={reduced ? { opacity: 0 } : { opacity: 0, y: 24 }} animate={{ opacity: 1, y: 0 }}
      exit={reduced ? { opacity: 0 } : { opacity: 0, y: 16, transition: { duration: 0.14 } }}
      transition={reduced ? { duration: 0.16 } : { type: 'spring', stiffness: 320, damping: 26, mass: 0.8 }}
      onSubmit={e => { e.preventDefault(); save() }} aria-label={`New ${tool === 'voice' ? 'voice note' : tool}`}
    >
      {tool === 'marking' && <>
        {barStepper}
        <div className="seg dseg is-small" role="radiogroup" aria-label="Kind">
          {markKinds.map(k => <button key={k.kind} type="button" role="radio" aria-checked={draftKind === k.kind} onClick={() => setDraftKind(k.kind)}>{k.label}</button>)}
        </div>
        <input className="dinput" value={draftText} onChange={e => setDraftText(e.target.value)} placeholder={draftKind === 'dynamic' ? 'e.g. sub. p' : 'What should everyone see?'} aria-label="Marking text" autoFocus />
        {audience}
      </>}
      {tool === 'cut' && (
        <p className="composer-msg">Cut bars <span className="num">{barRange(draftSpan.from, draftSpan.to)}</span><span className="composer-hint">Tap the first and last bar. Goes to every part.</span></p>
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
      <button type="button" className="dbtn" onClick={() => setTool(null)}>Cancel</button>
      <button type="submit" className="dbtn is-primary" disabled={tool === 'voice' && (rec.on || rec.sec === 0)}>{tool === 'cut' ? 'Add cut' : tool === 'voice' ? 'Save note' : 'Add marking'}</button>
    </motion.form>
  )

  const scoreParts = isFull ? 'Full score' : isSplit ? split!.label : partsById[partSel]?.name

  return (
    <div className="stand">
      {header}
      <main className="stand-desk">
        {pages ? (
          pdf.engraving ? (
            <EngravedStage
              engraving={pdf.engraving} aspect={pdf.aspect} focus={focus} follow={followBar} onUserTurn={() => setFollowing(false)}
              underlay={underlay} overlay={overlay} onBarTap={onBarTap} onBarHold={onBarHold} onEmptyTap={() => { setPin(null); menu.close() }}
              onView={(v, z) => { setView(v); setZoom(z) }} still={scribble} label={`${score.title}, PDF pages`}
            />
          ) : (
            <div className="stand-empty">
              <p className="stand-empty-title">{pdf.state === 'loading' ? 'Opening the pages' : st.busy === 'reading' ? 'The pages are being prepared' : 'No pages to show yet'}</p>
              {pdf.state === 'none' && <p>{st.busy === 'reading' ? 'They appear here as the librarian renders them.' : 'The rendered pages are not in the library yet.'}</p>}
              {pdf.state === 'none' && pdfFile && <button type="button" className="r3-btn is-card" onClick={() => void openPdfFile()}>Open the PDF file</button>}
            </div>
          )
        ) : engraving ? (
          <EngravedStage
            engraving={engraving} focus={focus} follow={followBar} onUserTurn={() => setFollowing(false)}
            underlay={underlay} overlay={overlay} onBarTap={onBarTap} onBarHold={onBarHold} onEmptyTap={() => { setPin(null); menu.close() }}
            onView={(v, z) => { setView(v); setZoom(z) }} still={scribble}
            label={`${scoreParts}, ${score.title}, ${engraving.layout === 'original' ? 'original formatting' : 'optimised for digital display'}`}
          />
        ) : (
          <ScoreStage
            src={score.fixture} instruments={instruments} scale={isFull || (isSplit && splitIdx.length > 2) ? (vp.wide ? 0.6 : 0.64) : (vp.wide ? 0.78 : 0.84)}
            focus={focus} follow={followBar} onUserTurn={() => setFollowing(false)}
            underlay={underlay} overlay={g => overlay(g, null)} onBarTap={onBarTap} onBarHold={onBarHold} onView={v => { setView(v); setZoom(null) }}
            onEmptyTap={() => { setPin(null); menu.close() }} label={`${scoreParts}, ${score.title}`}
          />
        )}

        <AnimatePresence>
          {canFollow && leader && !tool && !scribble && (
            <motion.button
              key="follow" type="button" className={`follow-pill ${following ? 'is-on' : ''}`} aria-pressed={following}
              onClick={() => setFollowing(v => !v)}
              initial={{ opacity: 0, y: 12, x: '-50%' }} animate={{ opacity: 1, y: 0, x: '-50%' }} exit={{ opacity: 0, y: 12, x: '-50%' }}
              transition={reduced ? { duration: 0.12 } : { type: 'spring', stiffness: 380, damping: 30 }}
            >
              <span className="r3-face" style={{ background: colorOf(leader.id) }} aria-hidden="true">{faceLabel(leader)}</span>
              {following ? `Following ${memberName(leader)}'s page turns` : `Follow ${memberName(leader)}'s page turns`}
            </motion.button>
          )}
        </AnimatePresence>
        <AnimatePresence initial={false}>{composer}</AnimatePresence>
        {canVoice && !tool && !scribble && !picking && (
          <VoiceButton voice={voice} reduced={reduced} lifted={!!zoom} under={trayOpen} onListening={on => { listening.current = on }} onOpen={() => setTrayOpen(true)} />
        )}
        <PickHint card={picking} onCancel={() => { setPicking(null); setTrayOpen(true) }} />
        <InkBar open={scribble} tool={inkTool} color={inkColor} status={ink.synced ? ink.state : 'local'} onTool={setInkTool} onColor={setInkColor} onDone={endScribble} />
        <Fade show={!!quick.error} className="mark-error" role="alert">Could not save that mark. {quick.error}</Fade>
      </main>

      <Sheet open={listOpen} onClose={() => setListOpen(false)} label="Markings" portal>
        <div className="side-head">
          <h2>Markings <span className="count">{visible.length}</span></h2>
          <button type="button" className="btn-icon" onClick={() => setListOpen(false)} aria-label="Close markings"><IClose size={20} /></button>
        </div>
        <div className="side-scroll">
          <p className="side-sub">{scoreParts}{showLayer ? `, ${side === 'mine' ? 'yours' : layerName}` : ''}.</p>
          <ol className="notes">
            {visible.map(a => (
              <li key={a.id} className={`note ${pin === a.id ? 'is-sel' : ''}`}>
                <NoteBody a={a} />
                <button type="button" className="btn btn-line is-small" onClick={() => { jump(a.barFrom); setListOpen(false) }}>
                  <KindIcon kind={a.kind} size={15} />Show bar <span className="num">{a.barFrom}</span>
                </button>
              </li>
            ))}
          </ol>
          {visible.length === 0 && <p className="side-sub">Nothing marked yet. Tap a bar to highlight it, write a note or draw on the page.</p>}
        </div>
      </Sheet>
      {canVoice && (
        <VoiceTray
          open={trayOpen} onClose={() => setTrayOpen(false)} voice={voice} commit={quick.commit} roster={roster} focus={voiceFocus}
          onShow={c => { if (c.barFrom != null) { setVoiceFocus(c.key); jump(c.barFrom) } }}
          onPick={c => { setPicking(c); setVoiceFocus(c.key); setTrayOpen(false); menu.close() }}
        />
      )}
      <StaffQuestion job={st.ask} open={asking && !!st.ask} onClose={() => setAsking(false)} />
    </div>
  )
}

// ---------------------------------------------------------------- notes above their bar

/** Notes stand above their bar as small bubbles with the author's face (R3). Bubbles on one system step up when they
 *  would overlap. A tap opens the bar's quick menu, where its author can remove it. */
function Bubbles({ geo, items, big, selected, colorOf, nameOf, faceOf, onSelect }: {
  geo: Geo; items: BarMark[]; big: boolean; selected: string | null
  colorOf: (memberId: string) => string; nameOf: (m: BarMark) => string; faceOf: (m: BarMark) => string; onSelect: (a: BarMark) => void
}) {
  const placed: { x: number; y: number; w: number }[] = []
  return (
    <>
      {items.map(a => {
        const b = geo.bars.get(a.barFrom)
        if (!b) return null
        const text = a.kind === 'voice' ? `Voice note${a.durationSec ? ` ${Math.floor(a.durationSec / 60)}:${String(a.durationSec % 60).padStart(2, '0')}` : ''}` : a.text || a.transcript || kindLabel[a.kind]
        const w = Math.min(big ? 360 : 260, 46 + text.length * (big ? 7.4 : 6.2) + 52)
        const h = big ? 42 : 34
        let y = b.y - h - 10
        const page = geo.pages[b.page]
        const x = page ? Math.max(page.x + 6, Math.min(b.x, page.x + page.w - w - 6)) : b.x
        while (placed.some(p => Math.abs(p.y - y) < h && x < p.x + p.w && p.x < x + w)) y -= h + 4
        placed.push({ x, y, w })
        const who = a.mine ? 'You' : nameOf(a)
        return (
          <button
            key={a.id} type="button" className={`bubble ${big ? 'is-big' : ''} ${selected === a.id ? 'is-sel' : ''} ${a.arriving ? 'is-arriving' : ''}`}
            style={{ left: x, top: y, maxWidth: w }} onClick={() => onSelect(a)} aria-label={`${who}: ${text}, bar ${a.barFrom}`}
          >
            <span className="r3-face" style={{ background: a.mine ? 'var(--solid)' : colorOf(a.authorId), color: a.mine ? 'var(--on-solid)' : '#fff' }} aria-hidden="true">{a.mine ? 'Me' : faceOf(a)}</span>
            {a.kind === 'voice' && <IMic size={14} />}
            <span className="bubble-text">{text} <span className="bubble-bar">— bar {a.barFrom}</span></span>
          </button>
        )
      })}
    </>
  )
}

// ---------------------------------------------------------------- the others, at the page edge

/** Each reader's face at the edge of the page their bar is on, level with the bar, with "bar N" under it. Zoomed, a
 *  bar above or below the visible part keeps its face at the top or bottom with an arrow. */
function EdgeFaces({ geo, people, zoom, colorOf, onJump }: { geo: Geo; people: Member[]; zoom: ZoomView | null; colorOf: (id: string) => string; onJump: (bar: number) => void }) {
  const shown = geo.pages.map((p, i) => ({ p, i })).filter(x => !!x.p)
  if (!shown.length) return null
  const used: { side: string; y: number }[] = []
  return (
    <>
      {people.map(m => {
        const b = m.atBar != null ? geo.bars.get(m.atBar) : undefined
        if (!b) return null
        const page = geo.pages[b.page]!
        const isRight = shown.length > 1 && b.page === shown[shown.length - 1].i
        // The spread has room for "bar 58" in its margins; a single page or a zoomed one says "b.58".
        const narrow = shown.length < 2 || !!zoom
        let y = b.y + b.h / 2 - 17
        let arrow = ''
        if (zoom) {
          const lo = page.y + zoom.top * page.h + 8, hi = page.y + zoom.bottom * page.h - 56
          if (y < lo) { y = lo; arrow = ' ↑' }
          if (y > hi) { y = hi; arrow = ' ↓' }
        }
        const side = isRight ? 'r' : 'l'
        while (used.some(u => u.side === side && Math.abs(u.y - y) < 50)) y += 52
        used.push({ side, y })
        const left = zoom ? Math.max(zoom.left + 4, page.x - 40) : isRight ? page.x + page.w + (narrow ? 4 : 12) : Math.max(2, page.x - (narrow ? 40 : 46))
        return (
          <motion.button
            key={m.id} type="button" className="edge-face" style={{ left, top: y }} onClick={() => m.atBar && onJump(m.atBar)}
            aria-label={`${memberName(m)} is at bar ${m.atBar}`} layout transition={{ type: 'spring', stiffness: 300, damping: 30 }}
          >
            <span className="r3-face" style={{ background: colorOf(m.id) }}>{faceLabel(m)}</span>
            <span className="edge-bar">{narrow ? `b.${m.atBar}` : `bar ${m.atBar}`}{arrow}</span>
          </motion.button>
        )
      })}
    </>
  )
}
