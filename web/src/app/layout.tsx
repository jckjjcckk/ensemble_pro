import { useEffect, useState, type ReactNode } from 'react'
import { Link, useLocation } from 'react-router'
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

/** Two places (R3, CK 2026-10-28): the Shelf (My Library and Groups) and the Stand (the book being read; its player
 *  opens from the book's "…" menu, 014). The Stand returns to the last book opened. */
type Area = 'shelf' | 'stand'

const BOOK_KEY = 'folio.book'
const PLACE_KEY = 'folio.place'

/** Where the reader last was: a score or its pages. Kept for the Stand. */
export function rememberBook(where: string) {
  try { window.localStorage.setItem(BOOK_KEY, where) } catch { /* private mode: the Stand falls back to the first book */ }
}
export function lastBook(): string | null {
  // A `/practice` entry is from the retired practice screen (014): the Stand falls back as if nothing were kept.
  try { const w = window.localStorage.getItem(BOOK_KEY); return w && !w.startsWith(`${BASE}/practice`) ? w : null } catch { return null }
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

/** `/score/{id}` or `/score/{id}/pages` (a PDF book's pages): the stand. */
const isBookPath = (path: string) => path.startsWith(`${BASE}/score/`)

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

/** The app icon's forte f (Bravura, OFL), cropped to the glyph. */
export function FolioMark({ size = 18 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="236 196 552 632" aria-hidden="true">
      <path fill="currentColor" d="M412.65 389.25C401.21 389.25 396.01 394.45 396.01 405.89C396.01 416.30 401.21 421.50 411.61 421.50L471.95 421.50C478.19 421.50 480.27 421.50 480.27 425.66C480.27 427.74 479.23 430.86 478.19 436.06L412.65 663.88C383.53 765.83 364.80 799.11 323.19 799.11C309.67 799.11 304.47 794.95 304.47 789.75C304.47 781.43 313.83 786.63 329.43 776.23C341.92 767.91 350.24 754.38 350.24 737.74C350.24 710.69 331.51 695.09 303.43 695.09C272.22 695.09 249.33 720.05 249.33 752.30C249.33 798.07 283.66 822 327.35 822C406.41 822 455.31 768.95 512.52 651.40C542.69 587.94 565.57 523.44 590.54 436.06C590.54 435.02 591.58 433.98 591.58 432.94C591.58 430.86 599.90 421.50 605.10 421.50L672.72 421.50C684.16 421.50 689.37 416.30 689.37 404.85C689.37 394.45 684.16 389.25 673.76 389.25L611.35 389.25C604.06 389.25 600.94 389.25 600.94 384.05C600.94 380.93 601.98 377.81 603.02 371.56C623.83 281.06 646.71 225.93 698.73 225.93C707.05 225.93 715.37 228.01 715.37 234.25C715.37 240.49 710.17 239.45 698.73 244.65C685.20 250.89 676.88 265.46 676.88 284.18C676.88 313.31 697.69 327.87 723.69 327.87C750.74 327.87 774.67 310.19 774.67 271.70C774.67 233.21 750.74 202 685.20 202C584.30 202 528.12 273.78 493.80 373.64C488.59 389.25 487.55 389.25 472.99 389.25Z" />
    </svg>
  )
}

export function Wordmark() {
  return (
    <Link to="/" className="wordmark" aria-label={`${WORDMARK}, library`}>
      <FolioMark />
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
  className?: string
}

/** Screens reached by a push (scan, a book opened from a cover) rather than by the places in the dock. */
function isPushed(path: string): boolean {
  return path.startsWith(`${BASE}/scan`) || path.startsWith(`${BASE}/score`)
}

export function Screen({ header, children, ruler, dock, className = '' }: ScreenProps) {
  const standalone = useStandalone()
  const { pathname, search } = useLocation()
  const back = standalone && isPushed(pathname)
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
      </header>
      <main className="main">{children}</main>
      <section className="dock" aria-label="Controls">
        {ruler && <div className="dock-ruler">{ruler}</div>}
        <div className="dock-row">
          <Places compact />
          <div className="dock-body">{dock}</div>
        </div>
      </section>
    </div>
  )
}
