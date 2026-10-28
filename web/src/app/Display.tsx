import { useEffect, useState } from 'react'
import { AnimatePresence } from 'motion/react'
import { useStore, type Theme, type TokenSet } from './store'
import { IDisplay } from './icons'
import { useAuth } from './auth'
import { Pop, Scrim } from './Sheet'

const sets: { id: TokenSet; label: string }[] = [
  { id: 'instrument', label: 'Instrument' },
  { id: 'bound', label: 'Bound' },
]
const themes: { id: Theme; label: string }[] = [
  { id: 'system', label: 'Auto' },
  { id: 'light', label: 'Light' },
  { id: 'dark', label: 'Dark' },
]

/** Display settings: token set and theme. A small popover growing out of its button; a clear scrim swallows the tap that closes it, Escape closes too. */
export function DisplayButton() {
  const { display, setDisplay } = useStore()
  const { session, signOut } = useAuth()
  const [open, setOpen] = useState(false)

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open])

  return (
    <div className="disp-wrap">
      <button type="button" className="btn-icon" aria-label="Display settings" aria-expanded={open} aria-pressed={open} onClick={() => setOpen(v => !v)}>
        <IDisplay size={22} />
      </button>
      <AnimatePresence>{open && <Scrim key="scrim" clear fixed onClose={() => setOpen(false)} />}</AnimatePresence>
      <Pop open={open} origin="top right" className="disp" role="dialog" aria-label="Display settings">
        <h2>Display</h2>
        <div className="disp-row">
          <span>Type and colour</span>
          <div className="seg" role="radiogroup" aria-label="Type and colour">
            {sets.map(s => (
              <button key={s.id} type="button" role="radio" aria-checked={display.tokens === s.id} onClick={() => setDisplay(d => ({ ...d, tokens: s.id }))}>{s.label}</button>
            ))}
          </div>
        </div>
        <div className="disp-row">
          <span>Theme</span>
          <div className="seg" role="radiogroup" aria-label="Theme">
            {themes.map(t => (
              <button key={t.id} type="button" role="radio" aria-checked={display.theme === t.id} onClick={() => setDisplay(d => ({ ...d, theme: t.id }))}>{t.label}</button>
            ))}
          </div>
        </div>
        <p className="disp-note">Auto follows the iPad's own light and dark switching. Settings change type, colour and line only; nothing moves.</p>
        <div className="disp-row disp-account">
          <span>{session?.user.email}</span>
          <button type="button" className="btn btn-line is-small" onClick={() => signOut()}>Sign out</button>
        </div>
      </Pop>
    </div>
  )
}
