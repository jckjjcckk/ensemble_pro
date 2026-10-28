import { useEffect, useState, type ReactNode } from 'react'
import { Link, useLocation } from 'react-router'
import { BASE, WORDMARK, useStore } from './store'
import { IChevronLeft, ILibrary, IPractice, IScore } from './icons'

/**
 * The on-screen keyboard. Safari does not shrink the layout for it; the visual viewport shrinks instead.
 * `--kb` on the document is the keyboard's overlap in px (0 when it is down), and the dock rides above it
 * (styles.css). When the keyboard goes away, any scroll Safari made to expose the input is undone.
 */
function installKeyboardLift() {
  const vv = window.visualViewport
  if (!vv) return
  let last = 0
  const measure = () => {
    const kb = Math.max(0, Math.round(window.innerHeight - vv.height - vv.offsetTop))
    if (kb === last) return
    last = kb
    document.documentElement.style.setProperty('--kb', `${kb}px`)
    if (kb === 0) window.scrollTo(0, 0)
  }
  vv.addEventListener('resize', measure)
  vv.addEventListener('scroll', measure)
}
if (typeof window !== 'undefined') installKeyboardLift()

/** Opened from the home screen: no browser chrome, so pushed screens draw their own way back. */
export function useStandalone(): boolean {
  const q = '(display-mode: standalone)'
  const [standalone, setStandalone] = useState(() => window.matchMedia(q).matches || (navigator as Navigator & { standalone?: boolean }).standalone === true)
  useEffect(() => {
    const m = window.matchMedia(q)
    const on = () => setStandalone(m.matches)
    m.addEventListener('change', on)
    return () => m.removeEventListener('change', on)
  }, [])
  return standalone
}

export interface Viewport { w: number; h: number; /** landscape with room for a tall control surface */ wide: boolean; narrow: boolean }

function read(): Viewport {
  const w = window.innerWidth
  const h = window.innerHeight
  return { w, h, wide: w >= 1000 && w > h, narrow: w < 780 }
}

export function useViewport(): Viewport {
  const [vp, setVp] = useState<Viewport>(read)
  useEffect(() => {
    const on = () => setVp(read())
    window.addEventListener('resize', on)
    return () => window.removeEventListener('resize', on)
  }, [])
  return vp
}

export function useReducedMotion(): boolean {
  const q = '(prefers-reduced-motion: reduce)'
  const [reduced, setReduced] = useState(() => window.matchMedia(q).matches)
  useEffect(() => {
    const m = window.matchMedia(q)
    const on = () => setReduced(m.matches)
    m.addEventListener('change', on)
    return () => m.removeEventListener('change', on)
  }, [])
  return reduced
}

type Area = 'library' | 'score' | 'practice'

const AREAS: { id: Area; label: string; to: string; Icon: typeof ILibrary }[] = [
  { id: 'library', label: 'Library', to: '/', Icon: ILibrary },
  { id: 'score', label: 'Score', to: `${BASE}/score/s-beethoven`, Icon: IScore },
  { id: 'practice', label: 'Practice', to: `${BASE}/practice`, Icon: IPractice },
]

function currentArea(path: string): Area {
  if (path.startsWith(`${BASE}/practice`)) return 'practice'
  if (path.startsWith(`${BASE}/score`)) return 'score'
  return 'library'
}

export function AreaNav({ stacked }: { stacked: boolean }) {
  const { pathname } = useLocation()
  const { world, context } = useStore()
  const here = currentArea(pathname)
  const firstScore = world.scores.find(s => s.status === 'ready' && s.ensembleId === context.ensemble.id) ?? world.scores.find(s => s.status === 'ready')
  const areas = AREAS.map(a => (a.id === 'score' && firstScore ? { ...a, to: `${BASE}/score/${firstScore.id}` } : a))
  return (
    <nav className={`areas ${stacked ? 'is-stacked' : ''}`} aria-label="Areas">
      {areas.map(({ id, label, to, Icon }) => (
        <Link key={id} to={to} className="area" aria-current={here === id ? 'page' : undefined}>
          <Icon size={22} />
          <span>{label}</span>
        </Link>
      ))}
    </nav>
  )
}

export function Wordmark() {
  return (
    <Link to="/" className="wordmark" aria-label={`${WORDMARK}, library`}>
      <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true">
        <path d="M3 3.5v11M15 3.5v11M3 3.5h2.6M3 14.5h2.6M15 3.5h-2.6M15 14.5h-2.6" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" />
      </svg>
      <span>{WORDMARK}</span>
    </Link>
  )
}

interface ScreenProps {
  header: ReactNode
  children: ReactNode
  /** The bar ruler that sits above the dock row. */
  ruler?: ReactNode
  /** Screen-specific controls; the area nav is always at the dock's left. */
  dock: ReactNode
  /** Practice grows the dock into a tall control surface on wide landscape screens. */
  tall?: boolean
  className?: string
}

/** Screens reached by a push (scan, a score opened from a cover) rather than by the area nav. */
function isPushed(path: string): boolean {
  return path.startsWith(`${BASE}/scan`) || path.startsWith(`${BASE}/score`)
}

export function Screen({ header, children, ruler, dock, tall = false, className = '' }: ScreenProps) {
  const standalone = useStandalone()
  const { pathname } = useLocation()
  const back = standalone && isPushed(pathname)
  return (
    <div className={`scr ${className}`}>
      <header className="hdr">
        {back && (
          <Link to="/" className="back" aria-label="Back to the library">
            <IChevronLeft size={24} />
          </Link>
        )}
        <Wordmark />
        <div className="hdr-body">{header}</div>
      </header>
      <main className="main">{children}</main>
      <section className={`dock ${tall ? 'is-tall' : ''}`} aria-label="Controls">
        {ruler && <div className="dock-ruler">{ruler}</div>}
        <div className="dock-row">
          <AreaNav stacked={tall} />
          <div className="dock-body">{dock}</div>
        </div>
      </section>
    </div>
  )
}
