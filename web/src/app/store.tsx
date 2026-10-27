import { createContext, useCallback, useContext, useEffect, useMemo, useState, type Dispatch, type ReactNode, type SetStateAction } from 'react'
import {
  annotations as seedAnnotations, practice, scanDraft,
  type Annotation, type Ensemble, type Member, type Membership, type Part, type ScanPage, type Score,
} from '../mock'
import type { World } from './data'

export const BASE = ''
export const WORDMARK = 'Folio'

export interface Span { from: number; to: number }

export interface PracticeUI {
  loop: Span | null
  tempo: number
  metronome: boolean
  others: 'off' | 'orchestra' | 'all'
  listenOn: boolean
  bar: number
  beat: number
  playing: boolean
}

export interface ScanUI {
  pages: ScanPage[]
  retaking: string[]
  committed: boolean
}

/** Display settings: a token set and a theme. Tokens change type, colour and line; never the layout. */
export type TokenSet = 'instrument' | 'bound'
export type Theme = 'system' | 'light' | 'dark'
export interface Display { tokens: TokenSet; theme: Theme }

const DISPLAY_KEY = 'folio.display'
const defaultDisplay: Display = { tokens: 'instrument', theme: 'system' }

function readDisplay(): Display {
  try {
    const raw = window.localStorage.getItem(DISPLAY_KEY)
    if (!raw) return defaultDisplay
    const d = JSON.parse(raw) as Partial<Display>
    return {
      tokens: d.tokens === 'bound' ? 'bound' : 'instrument',
      theme: d.theme === 'light' || d.theme === 'dark' ? d.theme : 'system',
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
  display: Display
  setDisplay: Dispatch<SetStateAction<Display>>
  practiceUI: PracticeUI
  setPracticeUI: Dispatch<SetStateAction<PracticeUI>>
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
  const [practiceUI, setPracticeUI] = useState<PracticeUI>({
    loop: practice.loop ? { from: practice.loop.barFrom, to: practice.loop.barTo } : null,
    tempo: practice.tempoBpm,
    metronome: practice.metronome,
    others: practice.otherParts,
    listenOn: practice.listening !== 'off',
    bar: practice.bar,
    beat: practice.beat,
    playing: false,
  })
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

  const value = useMemo<Store>(() => ({
    world, contexts, scoresById, partsById, membersById,
    context: contextFor(contextId) ?? contexts[0], setContext, contextFor,
    display, setDisplay,
    practiceUI, setPracticeUI,
    annotations, addAnnotation: a => setAnnotations(xs => [...xs, a]),
    scan, setScan,
  }), [world, contexts, scoresById, partsById, membersById, contextId, contextFor, setContext, display, practiceUI, annotations, scan])

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
  marking: 'Pencil', cut: 'Cut', voice: 'Voice note', text: 'Note', dynamic: 'Dynamic', bowing: 'Bowing', breath: 'Breath',
}

/** Difficulty is one word per part, never a number (decided 2026-10-26). */
export const difficultyWord: Record<1 | 2 | 3 | 4 | 5, string> = { 1: 'Easy', 2: 'Moderate', 3: 'Demanding', 4: 'Hard', 5: 'Very hard' }

export const barRange = (a: number, b: number) => (a === b ? `${a}` : `${a}–${b}`)
