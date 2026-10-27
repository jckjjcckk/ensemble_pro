import { useEffect } from 'react'
import { Navigate, Route, Routes } from 'react-router'
import { StoreProvider, useStore, type TokenSet } from './store'
import Library from './Library'
import Scan from './Scan'
import ScoreDoc from './ScoreDoc'
import Practice from './Practice'
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
  }, [display.theme])
  return (
    <div className="fo" data-tokens={display.tokens} data-theme={display.theme === 'system' ? undefined : display.theme}>
      <Routes>
        <Route index element={<Library />} />
        <Route path="scan" element={<Scan />} />
        <Route path="score/:scoreId" element={<ScoreDoc />} />
        <Route path="practice" element={<Practice />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </div>
  )
}

export default function Folio() {
  return (
    <StoreProvider>
      <Shell />
    </StoreProvider>
  )
}
