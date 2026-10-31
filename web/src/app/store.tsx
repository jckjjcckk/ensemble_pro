import { createContext, useCallback, useContext, useEffect, useMemo, useState, type Dispatch, type ReactNode, type SetStateAction } from 'react'
import {
  annotations as seedAnnotations, scanDraft,
  type Annotation, type Ensemble, type Member, type Membership, type Part, type ScanPage, type Score,
} from '../mock'
import { MY_LIBRARY, type PartJob, type PartStrip, type ScoreShare, type World } from './data'

export const BASE = ''
export const WORDMARK = 'Folio'

export interface Span { from: number; to: number }

export interface ScanUI {
  pages: ScanPage[]
  retaking: string[]
  committed: boolean
}

/** Appearance (R3): the theme, and how a page reads on the stand in the dark. One look; tokens change colour only. */
export type Theme = 'system' | 'light' | 'dark'
/** In the dark the page is either paper dimmed to the room (`dim`) or inverted, light notes on a dark leaf (`invert`). */
export type DarkPage = 'dim' | 'invert'
export interface Display { theme: Theme; page: DarkPage }

const DISPLAY_KEY = 'folio.display'
const defaultDisplay: Display = { theme: 'system', page: 'dim' }

export function readDisplay(): Display {
  try {
    const raw = window.localStorage.getItem(DISPLAY_KEY)
    if (!raw) return defaultDisplay
    const d = JSON.parse(raw) as Partial<Display>
    return {
      theme: d.theme === 'light' || d.theme === 'dark' ? d.theme : 'system',
      page: d.page === 'invert' ? 'invert' : 'dim',
    }
  } catch {
    return defaultDisplay
  }
}

/** A context is one library the account can open: its own, or one ensemble. */
export interface Context {
  ensemble: Ensemble
  membership: Membership
  /** The seat the account occupies there. */
  persona: Member
}

const contextsOf = (world: World): Context[] =>
  world.account.memberships
    .map(m => {
      const ensemble = world.ensembles.find(e => e.id === m.ensembleId)
      const persona = ensemble?.members.find(x => x.id === m.memberId)
      return ensemble && persona ? { ensemble, membership: m, persona } : null
    })
    .filter((c): c is Context => c !== null)

interface Store {
  world: World
  /** Every library the account can open: its own, then each ensemble. */
  contexts: Context[]
  scoresById: Record<string, Score>
  partsById: Record<string, Part>
  membersById: Record<string, Member>
  /** The library currently open. */
  context: Context
  setContext: (ensembleId: string) => void
  /** The account's standing in the ensemble that owns a score, whatever library is open. */
  contextFor: (ensembleId: string) => Context | undefined
  /** Part-cut jobs of a score, newest first (008). */
  jobsFor: (scoreId: string) => PartJob[]
  /** Finished splits by instrument of a score, newest first (008, 010). */
  stripsFor: (scoreId: string) => PartStrip[]
  /** The groups a personal book is shared with, as far as the account can see (its own books: every share). */
  sharesFor: (scoreId: string) => ScoreShare[]
  /** May the account change the book (split, convert, export, order pages, share)? A personal book: its owner only,
   *  whichever shelf it is opened from. A group's book: its admins. */
  canEditBook: (score: Score) => boolean
  /** The `ensemble_id` a mark on this book is written with and read by (`annotations`, `scribbles`): null on a
   *  group's own book (the book's group) and for the owner's private marks in their own library; the group's id when
   *  a shared book is open from that group's shelf (or, for someone else's book, the first group it reaches them
   *  through). See supabase/migrations/20261028200000_score_shares.sql. */
  markGroupFor: (score: Score) => string | null
  display: Display
  setDisplay: Dispatch<SetStateAction<Display>>
  annotations: Annotation[]
  addAnnotation: (a: Annotation) => void
  scan: ScanUI
  setScan: Dispatch<SetStateAction<ScanUI>>
}

const Ctx = createContext<Store | null>(null)

export function StoreProvider({ world, children }: { world: World; children: ReactNode }) {
  const contexts = useMemo(() => contextsOf(world), [world])
  const [contextId, setContextId] = useState(contexts[0].ensemble.id)
  const [display, setDisplay] = useState<Display>(readDisplay)
  const [annotations, setAnnotations] = useState<Annotation[]>(seedAnnotations)
  const [scan, setScan] = useState<ScanUI>({ pages: scanDraft.pages, retaking: [], committed: false })

  useEffect(() => {
    try { window.localStorage.setItem(DISPLAY_KEY, JSON.stringify(display)) } catch { /* private mode: settings last for the session */ }
  }, [display])

  const contextFor = useCallback((ensembleId: string) => contexts.find(c => c.ensemble.id === ensembleId), [contexts])
  const setContext = useCallback((id: string) => { if (contextFor(id)) setContextId(id) }, [contextFor])
  const byId = <T extends { id: string }>(xs: T[]) => Object.fromEntries(xs.map(x => [x.id, x])) as Record<string, T>
  const scoresById = useMemo(() => byId(world.scores), [world.scores])
  const partsById = useMemo(() => byId(world.parts), [world.parts])
  const membersById = useMemo(() => byId(world.ensembles.flatMap(e => e.members)), [world.ensembles])
  const jobsFor = useCallback((scoreId: string) => world.jobs.filter(j => j.scoreId === scoreId), [world.jobs])
  const stripsFor = useCallback((scoreId: string) => world.strips.filter(s => s.scoreId === scoreId), [world.strips])
  const sharesFor = useCallback((scoreId: string) => world.shares.filter(s => s.scoreId === scoreId), [world.shares])
  const canEditBook = useCallback((score: Score) => {
    const owner = world.owners[score.id]
    if (owner) return owner === world.account.id
    return (contextFor(score.ensembleId)?.membership.role ?? 'player') !== 'player'
  }, [world.owners, world.account.id, contextFor])
  const markGroupFor = useCallback((score: Score): string | null => {
    const owner = world.owners[score.id]
    if (!owner) return null
    const groups = world.shares.filter(s => s.scoreId === score.id).map(s => s.ensembleId)
    const here = contextFor(contextId)?.ensemble.id ?? MY_LIBRARY
    if (groups.includes(here)) return here
    if (owner === world.account.id) return null
    return groups.find(g => contexts.some(c => c.ensemble.id === g)) ?? null
  }, [world.owners, world.shares, world.account.id, contextFor, contextId, contexts])

  const value = useMemo<Store>(() => ({
    world, contexts, scoresById, partsById, membersById,
    context: contextFor(contextId) ?? contexts[0], setContext, contextFor, jobsFor, stripsFor, sharesFor, canEditBook, markGroupFor,
    display, setDisplay,
    annotations, addAnnotation: a => setAnnotations(xs => [...xs, a]),
    scan, setScan,
  }), [world, contexts, scoresById, partsById, membersById, contextId, contextFor, setContext, jobsFor, stripsFor, sharesFor, canEditBook, markGroupFor, display, annotations, scan])

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useStore(): Store {
  const s = useContext(Ctx)
  if (!s) throw new Error('useStore outside StoreProvider')
  return s
}

// ---------------------------------------------------------------- small formatting helpers

export const initials = (name: string) => name.split(/\s+/).map(w => w[0]).join('').slice(0, 2).toUpperCase()
export const firstName = (name: string) => name.split(/\s+/)[0]

const dayFmt = new Intl.DateTimeFormat('en-GB', { weekday: 'short', day: 'numeric', month: 'short', timeZone: 'UTC' })
const dateTimeFmt = new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', timeZone: 'UTC' })
export const fmtDay = (iso: string) => dayFmt.format(new Date(iso))
export const fmtDateTime = (iso: string) => dateTimeFmt.format(new Date(iso))

/** "Today" for the mock world: the date the shared data treats as now. */
export const TODAY = '2026-10-26'

export const partShort: Record<string, string> = {
  'Violin I': 'Vn I', 'Violin II': 'Vn II', Viola: 'Va', Cello: 'Vc',
  Soprano: 'S', Alto: 'A', Tenor: 'T', Bass: 'B', Piano: 'Pf',
}

export const kindLabel: Record<Annotation['kind'], string> = {
  marking: 'Pencil', cut: 'Cut', voice: 'Voice note', text: 'Note', dynamic: 'Dynamic', bowing: 'Bowing', breath: 'Breath', highlight: 'Highlight',
}

/** Difficulty is one word per part, never a number (decided 2026-10-26). */
export const difficultyWord: Record<1 | 2 | 3 | 4 | 5, string> = { 1: 'Easy', 2: 'Moderate', 3: 'Demanding', 4: 'Hard', 5: 'Very hard' }

export const barRange = (a: number, b: number) => (a === b ? `${a}` : `${a}–${b}`)
