import { useEffect, useState, type ReactNode } from 'react'
import { Link, useLocation, useNavigate } from 'react-router'
import { BASE, WORDMARK, useStore } from './store'
import { IChevronLeft } from './icons'

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

/** Two places (R3, CK 2026-10-28): the Shelf (My Library and Groups) and the Stand (the book being read, where Read
 *  and Practise are a toggle in its header). The Stand returns to the last book opened. */
type Area = 'shelf' | 'stand'

const BOOK_KEY = 'folio.book'
const PLACE_KEY = 'folio.place'

/** Where the reader last was: a score, its pages, or practice on it. Kept for the Stand. */
export function rememberBook(where: string) {
  try { window.localStorage.setItem(BOOK_KEY, where) } catch { /* private mode: the Stand falls back to the first book */ }
}
export function lastBook(): string | null {
  try { return window.localStorage.getItem(BOOK_KEY) } catch { return null }
}

/** The bar and page a book was last left at, for "Continues at bar N, page P" (per device). */
export interface Place { bar: number; page: number }
export function placeOf(scoreId: string): Place | null {
  try {
    const all = JSON.parse(window.localStorage.getItem(PLACE_KEY) ?? '{}') as Record<string, Place>
    const p = all[scoreId]
    return p && p.bar > 0 && p.page > 0 ? p : null
  } catch { return null }
}
export function rememberPlace(scoreId: string, place: Place) {
  try {
    const all = JSON.parse(window.localStorage.getItem(PLACE_KEY) ?? '{}') as Record<string, Place>
    all[scoreId] = place
    window.localStorage.setItem(PLACE_KEY, JSON.stringify(all))
  } catch { /* private mode: the book opens at its start */ }
}

/** `/score/{id}`, `/score/{id}/pages` (a PDF book's pages) or `/practice`: the stand. */
const isBookPath = (path: string) => path.startsWith(`${BASE}/score/`) || path.startsWith(`${BASE}/practice`)

const currentArea = (path: string): Area => (isBookPath(path) ? 'stand' : 'shelf')

/** The score a book path is about, when it names one. */
export function bookIdOf(path: string, search = ''): string | null {
  const m = path.match(/^\/score\/([^/?#]+)/)
  if (m) return decodeURIComponent(m[1])
  return new URLSearchParams(search).get('score')
}

/** Where the Stand opens: the last book still on a shelf, else the first readable book. Null with no book at all. */
export function useStandTarget(): string | null {
  const { world, scoresById } = useStore()
  const remembered = lastBook()
  const rememberedId = remembered ? bookIdOf(remembered.split('?')[0], remembered.split('?')[1] ?? '') : null
  if (remembered && rememberedId && scoresById[rememberedId]) return remembered
  const s = world.scores.find(x => x.status === 'ready' && x.engravings?.length) ?? world.scores.find(x => x.status === 'ready')
  if (!s) return null
  return s.engravings?.length || !s.pageSource ? `${BASE}/score/${s.id}` : `${BASE}/score/${s.id}/pages`
}

const IShelf = ({ size = 20 }: { size?: number }) => (
  <svg aria-hidden="true" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round"><path d="M4 7h16M4 12h16M4 17h16M8 4v16M14 4v16" /></svg>
)
export const IStand = ({ size = 20 }: { size?: number }) => (
  <svg aria-hidden="true" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinejoin="round"><path d="M4 5h6a2 2 0 0 1 2 2v13a2 2 0 0 0-2-2H4zM20 5h-6a2 2 0 0 0-2 2v13a2 2 0 0 1 2-2h6z" /></svg>
)

/** The two places as pills (the Shelf's own dock, and the left of the older screens' control row). */
export function Places({ compact = false }: { compact?: boolean }) {
  const { pathname } = useLocation()
  const here = currentArea(pathname)
  const stand = useStandTarget()
  return (
    <nav className={`places ${compact ? 'is-compact' : ''}`} aria-label="Places">
      <Link to={`${BASE}/`} className="place" aria-current={here === 'shelf' ? 'page' : undefined}><IShelf />Shelf</Link>
      {stand || here === 'stand' ? (
        <Link to={here === 'stand' ? pathname : stand!} className="place" aria-current={here === 'stand' ? 'page' : undefined}><IStand />Stand</Link>
      ) : (
        <span className="place is-off" aria-disabled="true" aria-label="Stand, open a book from the shelf first"><IStand />Stand</span>
      )}
    </nav>
  )
}

/** Read and Practise are two ways of being in one book: a segmented toggle in the book's header, not two places.
 *  Practise carries the book as `?score=` (the practice screen reads its own state; the id is there for it). */
export function BookModes({ scoreId }: { scoreId?: string | null }) {
  const { pathname, search } = useLocation()
  const navigate = useNavigate()
  const { scoresById } = useStore()
  const practising = pathname.startsWith(`${BASE}/practice`)
  const remembered = lastBook()
  const id = scoreId ?? bookIdOf(pathname, search)
    ?? (remembered && !remembered.startsWith(`${BASE}/practice`) ? bookIdOf(remembered.split('?')[0]) : null)
  const score = id ? scoresById[id] : undefined
  const back = score?.engravings?.length || !score?.pageSource ? `${BASE}/score/${id}` : `${BASE}/score/${id}/pages`
  return (
    <div className="r3-seg book-modes" role="radiogroup" aria-label="Mode">
      <button type="button" role="radio" aria-checked={!practising} disabled={practising && !score}
        onClick={() => { if (practising && id) navigate(back, { replace: true }) }}>Read</button>
      <button type="button" role="radio" aria-checked={practising}
        onClick={() => { if (!practising) navigate(`${BASE}/practice${id ? `?score=${encodeURIComponent(id)}` : ''}`, { replace: true }) }}>Practise</button>
    </div>
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

/** Screens reached by a push (scan, a book opened from a cover) rather than by the places in the dock. */
function isPushed(path: string): boolean {
  return path.startsWith(`${BASE}/scan`) || path.startsWith(`${BASE}/score`)
}

export function Screen({ header, children, ruler, dock, tall = false, className = '' }: ScreenProps) {
  const standalone = useStandalone()
  const { pathname, search } = useLocation()
  const back = standalone && isPushed(pathname)
  // Practice carries the Read / Practise toggle (the stand draws its own header); strips do not.
  const modes = pathname.startsWith(`${BASE}/practice`)
  useEffect(() => { if (isBookPath(pathname)) rememberBook(pathname + search) }, [pathname, search])
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
        {modes && <BookModes />}
      </header>
      <main className="main">{children}</main>
      <section className={`dock ${tall ? 'is-tall' : ''}`} aria-label="Controls">
        {ruler && <div className="dock-ruler">{ruler}</div>}
        <div className="dock-row">
          <Places compact />
          <div className="dock-body">{dock}</div>
        </div>
      </section>
    </div>
  )
}
