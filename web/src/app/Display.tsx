import { useEffect, useRef, useState } from 'react'
import { useStore, type Theme, type TokenSet } from './store'
import { IDisplay } from './icons'

const sets: { id: TokenSet; label: string }[] = [
  { id: 'instrument', label: 'Instrument' },
  { id: 'bound', label: 'Bound' },
]
const themes: { id: Theme; label: string }[] = [
  { id: 'system', label: 'Auto' },
  { id: 'light', label: 'Light' },
  { id: 'dark', label: 'Dark' },
]

/** Display settings: token set and theme. A small non-modal sheet under its button; closes on outside tap or Escape. */
export function DisplayButton() {
  const { display, setDisplay } = useStore()
  const [open, setOpen] = useState(false)
  const wrap = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onDown = (e: PointerEvent) => { if (!wrap.current?.contains(e.target as Node)) setOpen(false) }
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    window.addEventListener('pointerdown', onDown)
    window.addEventListener('keydown', onKey)
    return () => { window.removeEventListener('pointerdown', onDown); window.removeEventListener('keydown', onKey) }
  }, [open])

  return (
    <div className="disp-wrap" ref={wrap}>
      <button type="button" className="btn-icon" aria-label="Display settings" aria-expanded={open} aria-pressed={open} onClick={() => setOpen(v => !v)}>
        <IDisplay size={22} />
      </button>
      {open && (
        <div className="disp" role="dialog" aria-label="Display settings">
          <h2>Display</h2>
          <div className="disp-row">
            <span>Type and colour</span>
            <div className="seg" role="radiogroup" aria-label="Token set">
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
        </div>
      )}
    </div>
  )
}
