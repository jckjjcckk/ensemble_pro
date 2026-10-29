import { useEffect, useState } from 'react'
import { AnimatePresence } from 'motion/react'
import { useStore, type DarkPage, type Theme } from './store'
import { useAuth } from './auth'
import { Pop, Scrim } from './Sheet'

const themes: { id: Theme; label: string }[] = [
  { id: 'system', label: 'Auto' },
  { id: 'light', label: 'Light' },
  { id: 'dark', label: 'Dark' },
]
const pages: { id: DarkPage; label: string; sub: string }[] = [
  { id: 'dim', label: 'Dimmed paper', sub: 'The page stays paper, turned down for the room' },
  { id: 'invert', label: 'Inverted', sub: 'Light notes on a dark page' },
]

/** The account circle (R3): the account's initial; opens appearance (theme, and how a page reads on the stand in the
 *  dark) and the account itself. A popover growing out of the circle; a clear scrim takes the closing tap; Escape too. */
export function AccountButton({ className = '' }: { className?: string }) {
  const { display, setDisplay, world } = useStore()
  const { session, signOut } = useAuth()
  const [open, setOpen] = useState(false)
  const name = world.account.name || session?.user.email || '?'

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open])

  return (
    <div className={`acct ${className}`}>
      <button type="button" className="acct-circle" aria-label="Account and appearance" aria-expanded={open} aria-haspopup="dialog" onClick={() => setOpen(v => !v)}>
        {name.trim()[0]?.toUpperCase()}
      </button>
      <AnimatePresence>{open && <Scrim key="scrim" clear fixed onClose={() => setOpen(false)} />}</AnimatePresence>
      <Pop open={open} origin="top right" className="r3-pop acct-pop" role="dialog" aria-label="Account and appearance">
        <p className="acct-who">
          <span className="acct-name">{name}</span>
          {session?.user.email && session.user.email !== name && <span className="acct-mail">{session.user.email}</span>}
        </p>
        <div className="acct-sec">
          <span className="r3-label" id="acct-theme">Appearance</span>
          <div className="r3-seg is-fill" role="radiogroup" aria-labelledby="acct-theme">
            {themes.map(t => (
              <button key={t.id} type="button" role="radio" aria-checked={display.theme === t.id} onClick={() => setDisplay(d => ({ ...d, theme: t.id }))}>{t.label}</button>
            ))}
          </div>
        </div>
        <div className="acct-sec">
          <span className="r3-label" id="acct-page">Pages on the stand in the dark</span>
          <div className="acct-pages" role="radiogroup" aria-labelledby="acct-page">
            {pages.map(p => (
              <button key={p.id} type="button" role="radio" aria-checked={display.page === p.id} className="acct-page" onClick={() => setDisplay(d => ({ ...d, page: p.id }))}>
                <span className={`acct-swatch is-${p.id}`} aria-hidden="true"><span /><span /><span /></span>
                <span className="acct-page-text"><b>{p.label}</b><span>{p.sub}</span></span>
              </button>
            ))}
          </div>
        </div>
        <button type="button" className="r3-btn is-quiet acct-out" onClick={() => signOut()}>Sign out</button>
      </Pop>
    </div>
  )
}
