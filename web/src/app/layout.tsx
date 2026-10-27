import { useEffect, useState, type ReactNode } from 'react'
import { Link, useLocation } from 'react-router'
import { BASE, WORDMARK, useStore } from './store'
import { ILibrary, IPractice, IScore } from './icons'

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

export function Screen({ header, children, ruler, dock, tall = false, className = '' }: ScreenProps) {
  return (
    <div className={`scr ${className}`}>
      <header className="hdr">
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
