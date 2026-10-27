import { useCallback, useEffect, useMemo, useState } from 'react'
import { Route, Routes } from 'react-router'
import { annotations, type Annotation, type Role } from '../shared'
import { Library } from './Library'
import { Practice } from './Practice'
import { Scan } from './Scan'
import { ScoreRoute, Unavailable } from './Score'
import { TopBar } from './TopBar'
import { ROLES } from './model'
import { X4Context, readStored, writeStored, type Theme, type X4State } from './state'
import './styles.css'

const FONTS_HREF =
  'https://fonts.googleapis.com/css2?family=EB+Garamond:ital,wght@0,400;0,500;0,600;1,400;1,500&family=Schibsted+Grotesk:wght@400;500;600;700&display=swap'

function useFonts() {
  useEffect(() => {
    const made: HTMLLinkElement[] = []
    const add = (rel: string, href: string, crossOrigin?: string) => {
      const l = document.createElement('link')
      l.rel = rel
      l.href = href
      if (crossOrigin !== undefined) l.crossOrigin = crossOrigin
      l.dataset.x4 = ''
      document.head.appendChild(l)
      made.push(l)
    }
    add('preconnect', 'https://fonts.googleapis.com')
    add('preconnect', 'https://fonts.gstatic.com', 'anonymous')
    add('stylesheet', FONTS_HREF)
    return () => made.forEach(l => l.remove())
  }, [])
}

const THEMES: readonly Theme[] = ['light', 'dim']

export default function Exploration4() {
  useFonts()
  const [role, setRoleState] = useState<Role>(() => readStored('x4.role', ROLES, 'leader'))
  const [theme, setThemeState] = useState<Theme>(() => readStored('x4.theme', THEMES, 'light'))
  const [notes, setNotes] = useState<Annotation[]>(annotations)

  const setRole = useCallback((r: Role) => {
    setRoleState(r)
    writeStored('x4.role', r)
  }, [])
  const setTheme = useCallback((t: Theme) => {
    setThemeState(t)
    writeStored('x4.theme', t)
  }, [])
  const addNote = useCallback((a: Annotation) => setNotes(ns => [...ns, a]), [])

  const value = useMemo<X4State>(
    () => ({ role, setRole, theme, setTheme, notes, addNote }),
    [role, setRole, theme, setTheme, notes, addNote],
  )

  return (
    <X4Context.Provider value={value}>
      <div className="x4" data-theme={theme}>
        <TopBar />
        <Routes>
          <Route index element={<Library />} />
          <Route path="scan" element={<Scan />} />
          <Route path="score/:id" element={<ScoreRoute />} />
          <Route path="practice" element={<Practice />} />
          <Route
            path="*"
            element={<Unavailable title="Nothing here" body="This page is not part of the library, scan, score or practice areas." />}
          />
        </Routes>
      </div>
    </X4Context.Provider>
  )
}
