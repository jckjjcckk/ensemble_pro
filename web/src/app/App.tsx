import { useEffect } from 'react'
import { Navigate, Route, Routes } from 'react-router'
import { StoreProvider, readDisplay, useStore } from './store'
import { AuthProvider, SignIn, useAuth } from './auth'
import { useWorld } from './data'
import Shelf from './Shelf'
import Scan from './Scan'
import ScoreDoc from './ScoreDoc'
import { CheckBars } from './CheckBars'
import { syncStatusBar } from '../lib/native'
import './styles.css'
import './r3.css'

/** R3's three faces (docs/design/r3/README.md): EB Garamond for display and numbers, Inter for the interface, Noto Music
 *  for clefs and accidentals. Loaded once, before sign-in, and kept for the session. */
const FONTS = 'https://fonts.googleapis.com/css2?family=EB+Garamond:ital,wght@0,400;0,500;0,600;1,400&family=Inter:wght@400;500;600&family=Noto+Music&display=swap'

function useFonts() {
  useEffect(() => {
    if (document.getElementById('fo-fonts')) return
    const pre = document.createElement('link')
    pre.rel = 'preconnect'
    pre.href = 'https://fonts.gstatic.com'
    pre.crossOrigin = ''
    const link = document.createElement('link')
    link.id = 'fo-fonts'
    link.rel = 'stylesheet'
    link.href = FONTS
    document.head.append(pre, link)
  }, [])
}

function Shell() {
  const { display } = useStore()
  useEffect(() => {
    // The browser chrome (status bar, scrollbars, form controls) follows the theme too.
    const meta = document.querySelector<HTMLMetaElement>('meta[name="color-scheme"]') ?? (() => {
      const m = document.createElement('meta')
      m.name = 'color-scheme'
      document.head.append(m)
      return m
    })()
    meta.content = display.theme === 'system' ? 'light dark' : display.theme
    // In the iPad app the status bar's text follows the same theme.
    const m = window.matchMedia('(prefers-color-scheme: dark)')
    const apply = () => { void syncStatusBar(display.theme === 'dark' || (display.theme === 'system' && m.matches)) }
    apply()
    m.addEventListener('change', apply)
    return () => m.removeEventListener('change', apply)
  }, [display.theme])
  return (
    <div className="fo" data-theme={display.theme === 'system' ? undefined : display.theme} data-page={display.page}>
      <Routes>
        <Route index element={<Shelf />} />
        <Route path="groups" element={<Shelf />} />
        <Route path="group" element={<Shelf />} />
        <Route path="scan" element={<Scan />} />
        <Route path="score/:scoreId" element={<ScoreDoc />} />
        <Route path="score/:scoreId/pages" element={<ScoreDoc pages />} />
        <Route path="score/:scoreId/check" element={<CheckBars />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </div>
  )
}

function Gate() {
  const { session, ready } = useAuth()
  const world = useWorld(session)
  const d = readDisplay()
  useFonts()
  const theme = d.theme === 'system' ? undefined : d.theme
  if (!ready) return <div className="fo" data-theme={theme} />
  if (!session) return <div className="fo" data-theme={theme}><SignIn /></div>
  return (
    <StoreProvider world={world}>
      <Shell />
    </StoreProvider>
  )
}

export default function Folio() {
  return (
    <AuthProvider>
      <Gate />
    </AuthProvider>
  )
}
