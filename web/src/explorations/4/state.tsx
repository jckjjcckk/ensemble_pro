import { createContext, useContext } from 'react'
import type { Annotation, Role } from '../shared'

export type Theme = 'light' | 'dim'

export interface X4State {
  role: Role
  setRole: (r: Role) => void
  theme: Theme
  setTheme: (t: Theme) => void
  /** Every marking on every score, the shared mock plus anything added this session. */
  notes: Annotation[]
  addNote: (a: Annotation) => void
}

export const X4Context = createContext<X4State | null>(null)

export function useX4(): X4State {
  const v = useContext(X4Context)
  if (!v) throw new Error('Exploration 4 state is missing')
  return v
}

export function readStored<T extends string>(key: string, allowed: readonly T[], fallback: T): T {
  try {
    const v = window.localStorage.getItem(key)
    return v && (allowed as readonly string[]).includes(v) ? (v as T) : fallback
  } catch {
    return fallback
  }
}

export function writeStored(key: string, value: string) {
  try {
    window.localStorage.setItem(key, value)
  } catch {
    /* storage unavailable: the choice lasts for this visit only */
  }
}
