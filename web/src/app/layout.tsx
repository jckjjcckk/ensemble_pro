import { useEffect, useState, type ReactNode } from 'react'
import { Link, useLocation, useNavigate } from 'react-router'
import { BASE, WORDMARK, useStore } from './store'
import { IBook, IChevronLeft, ILibrary, IPeople } from './icons'

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

/** Three places (CK, 2026-10-28): the library, the book being read (its reader, where Read and Practise are a toggle in
 *  the header), and the group. The book place returns to the last book opened. */
type Area = 'library' | 'book' | 'group'

const BOOK_KEY = 'folio.book'

/** Where the reader last was: a score, its pages, or practice on it. Kept for the Book place. */
function rememberBook(where: string) {
  try { window.localStorage.setItem(BOOK_KEY, where) } catch { /* private mode: the Book place falls back to the first book */ }
}
function lastBook(): string | null {
  try { return window.localStorage.getItem(BOOK_KEY) } catch { return null }
}

/** `/score/{id}`, `/score/{id}/pages` (a PDF book's pages) or `/practice`: the book place. */
const isBookPath = (path: string) => path.startsWith(`${BASE}/score/`) || path.startsWith(`${BASE}/practice`)

function currentArea(path: string): Area {
  if (isBookPath(path)) return 'book'
  if (path.startsWith(`${BASE}/group`)) return 'group'
  return 'library'
}

/** The score a book path is about, when it names one. */
export function bookIdOf(path: string, search = ''): string | null {
  const m = path.match(/^\/score\/([^/?#]+)/)
  if (m) return decodeURIComponent(m[1])
  return new URLSearchParams(search).get('score')
}

export function AreaNav({ stacked }: { stacked: boolean }) {
  const { pathname } = useLocation()
  const { world, context, scoresById } = useStore()
  const here = currentArea(pathname)
  // The last book still in the library; else the first readable one here; else the first anywhere.
  const remembered = lastBook()
  const rememberedId = remembered ? bookIdOf(remembered.split('?')[0], remembered.split('?')[1] ?? '') : null
  const fallback = world.scores.find(s => s.status === 'ready' && s.ensembleId === context.ensemble.id) ?? world.scores.find(s => s.status === 'ready')
  const bookTo = remembered && rememberedId && scoresById[rememberedId] ? remembered
    : fallback ? (fallback.fixture ? `${BASE}/score/${fallback.id}` : `${BASE}/score/${fallback.id}/pages`) : null
  const areas: { id: Area; label: string; to: string | null; Icon: typeof ILibrary }[] = [
    { id: 'library', label: 'Library', to: `${BASE}/`, Icon: ILibrary },
    { id: 'book', label: 'Book', to: bookTo, Icon: IBook },
    { id: 'group', label: 'Group', to: `${BASE}/group`, Icon: IPeople },
  ]
  return (
    <nav className={`areas ${stacked ? 'is-stacked' : ''}`} aria-label="Places">
      {areas.map(({ id, label, to, Icon }) => (to || here === id ? (
        <Link key={id} to={here === id && id === 'book' ? pathname : to ?? '/'} className="area" aria-current={here === id ? 'page' : undefined}>
          <Icon size={22} />
          <span>{label}</span>
        </Link>
      ) : (
        <span key={id} className="area is-off" aria-disabled="true" aria-label="Book, open one from the library first">
          <Icon size={22} />
          <span>{label}</span>
        </span>
      )))}
    </nav>
  )
}

/** Read and Practise are two ways of being in one book: a segmented toggle in the reader's header, not two places.
 *  Practise carries the book as `?score=` (the practice screen reads its own state; the id is there for it). */
function BookModes() {
  const { pathname, search } = useLocation()
  const navigate = useNavigate()
  const { scoresById } = useStore()
  const practising = pathname.startsWith(`${BASE}/practice`)
  const remembered = lastBook()
  const id = bookIdOf(pathname, search)
    ?? (remembered && !remembered.startsWith(`${BASE}/practice`) ? bookIdOf(remembered.split('?')[0]) : null)
  const score = id ? scoresById[id] : undefined
  const canRead = !!score?.fixture
  return (
    <div className="seg book-modes" role="radiogroup" aria-label="Mode">
      <button type="button" role="radio" aria-checked={!practising} disabled={practising && !canRead}
        onClick={() => { if (practising && id) navigate(`${BASE}/score/${id}`, { replace: true }) }}>Read</button>
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
  // The digital reader and practice carry the Read / Practise toggle; a PDF book's pages and its strips do not.
  const modes = (/^\/score\/[^/]+$/.test(pathname) && !new URLSearchParams(search).has('view')) || pathname.startsWith(`${BASE}/practice`)
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
          <AreaNav stacked={tall} />
          <div className="dock-body">{dock}</div>
        </div>
      </section>
    </div>
  )
}
