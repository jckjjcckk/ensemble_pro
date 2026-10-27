import { createContext, useContext, useMemo, useState, type Dispatch, type ReactNode, type SetStateAction } from 'react'
import {
  annotations as seedAnnotations, members, practice, scanDraft,
  type Annotation, type Member, type Role, type ScanPage,
} from '../shared'

export const BASE = '/5'
export const WORDMARK = 'Muse'

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

/** Who the app is being viewed as, per role. The role switch picks the persona. */
export const personaFor: Record<Role, Member> = {
  player: members.find(m => m.id === 'm-lin')!,
  leader: members.find(m => m.id === 'm-ada')!,
  pianist: members.find(m => m.id === 'm-ck')!,
  librarian: members.find(m => m.id === 'm-sam')!,
}

interface Store {
  role: Role
  setRole: (r: Role) => void
  persona: Member
  practiceUI: PracticeUI
  setPracticeUI: Dispatch<SetStateAction<PracticeUI>>
  annotations: Annotation[]
  addAnnotation: (a: Annotation) => void
  scan: ScanUI
  setScan: Dispatch<SetStateAction<ScanUI>>
}

const Ctx = createContext<Store | null>(null)

export function StoreProvider({ children }: { children: ReactNode }) {
  const [role, setRole] = useState<Role>('pianist')
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

  const value = useMemo<Store>(() => ({
    role, setRole, persona: personaFor[role],
    practiceUI, setPracticeUI,
    annotations, addAnnotation: a => setAnnotations(xs => [...xs, a]),
    scan, setScan,
  }), [role, practiceUI, annotations, scan])

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

export const barRange = (a: number, b: number) => (a === b ? `${a}` : `${a}–${b}`)
