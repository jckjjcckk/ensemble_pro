import { useEffect } from 'react'
import { Navigate, Route, Routes } from 'react-router'
import { StoreProvider, useStore, type TokenSet } from './store'
import { AuthProvider, SignIn, useAuth } from './auth'
import { useWorld } from './data'
import Library from './Library'
import Scan from './Scan'
import ScoreDoc from './ScoreDoc'
import Practice from './Practice'
import Pages from './Pages'
import { syncStatusBar } from '../lib/native'
import './styles.css'

/** Each token set brings its own faces. A set's fonts load the first time it is shown and stay for the session. */
const FONTS: Record<TokenSet, string> = {
  instrument: 'https://fonts.googleapis.com/css2?family=Archivo:wdth,wght@62..125,100..900&family=Martian+Mono:wdth,wght@75..112.5,100..800&display=swap',
  bound: 'https://fonts.googleapis.com/css2?family=EB+Garamond:ital,wght@0,400;0,500;0,600;1,400;1,500&family=Schibsted+Grotesk:wght@400;500;600;700&display=swap',
}

function useFonts(set: TokenSet) {
  useEffect(() => {
    if (!document.querySelector('link[rel="preconnect"][href="https://fonts.gstatic.com"]')) {
      const pre = document.createElement('link')
      pre.rel = 'preconnect'
      pre.href = 'https://fonts.gstatic.com'
      pre.crossOrigin = ''
      document.head.append(pre)
    }
    const id = `fo-fonts-${set}`
    if (document.getElementById(id)) return
    const link = document.createElement('link')
    link.id = id
    link.rel = 'stylesheet'
    link.href = FONTS[set]
    document.head.append(link)
  }, [set])
}

function Shell() {
  const { display } = useStore()
  useFonts(display.tokens)
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
    <div className="fo" data-tokens={display.tokens} data-theme={display.theme === 'system' ? undefined : display.theme}>
      <Routes>
        <Route index element={<Library />} />
        <Route path="group" element={<Library />} />
        <Route path="scan" element={<Scan />} />
        <Route path="score/:scoreId" element={<ScoreDoc />} />
        <Route path="score/:scoreId/pages" element={<Pages />} />
        <Route path="practice" element={<Practice />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </div>
  )
}

function Gate() {
  const { session, ready } = useAuth()
  const world = useWorld(session)
  const theme = readTheme()
  if (!ready) return <div className="fo" data-tokens={theme.tokens} data-theme={theme.theme} />
  if (!session) return <div className="fo" data-tokens={theme.tokens} data-theme={theme.theme}><SignIn /></div>
  return (
    <StoreProvider world={world}>
      <Shell />
    </StoreProvider>
  )
}

/** Before the store exists (sign-in), the saved display setting still styles the page. */
function readTheme(): { tokens: TokenSet; theme?: string } {
  try {
    const d = JSON.parse(window.localStorage.getItem('folio.display') ?? '{}')
    return { tokens: d.tokens === 'bound' ? 'bound' : 'instrument', theme: d.theme === 'light' || d.theme === 'dark' ? d.theme : undefined }
  } catch { return { tokens: 'instrument' } }
}

export default function Folio() {
  return (
    <AuthProvider>
      <Gate />
    </AuthProvider>
  )
}
