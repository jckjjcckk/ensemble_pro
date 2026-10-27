import { useEffect } from 'react'
import { Navigate, Route, Routes } from 'react-router'
import { StoreProvider } from './store'
import Library from './Library'
import Scan from './Scan'
import ScoreDoc from './ScoreDoc'
import Practice from './Practice'
import './styles.css'

const FONT_ID = 'x5-fonts'
const FONT_HREF = 'https://fonts.googleapis.com/css2?family=Archivo:wdth,wght@62..125,100..900&family=Martian+Mono:wdth,wght@75..112.5,100..800&display=swap'

function useFonts() {
  useEffect(() => {
    if (document.getElementById(FONT_ID)) return
    const pre = document.createElement('link')
    pre.rel = 'preconnect'
    pre.href = 'https://fonts.gstatic.com'
    pre.crossOrigin = ''
    const link = document.createElement('link')
    link.id = FONT_ID
    link.rel = 'stylesheet'
    link.href = FONT_HREF
    document.head.append(pre, link)
  }, [])
}

export default function Exploration5() {
  useFonts()
  return (
    <StoreProvider>
      <div className="x5">
        <Routes>
          <Route index element={<Library />} />
          <Route path="scan" element={<Scan />} />
          <Route path="score/:scoreId" element={<ScoreDoc />} />
          <Route path="practice" element={<Practice />} />
          <Route path="*" element={<Navigate to="/5" replace />} />
        </Routes>
      </div>
    </StoreProvider>
  )
}
