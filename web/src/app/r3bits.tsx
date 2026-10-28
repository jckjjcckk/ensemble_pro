/** Small pieces the R3 surfaces share: icons drawn as in the artboards, the card's engraved staff, copy-to-clipboard. */
import { useState } from 'react'
import type { Score } from '../mock'
import { IdentityStaff } from './Identity'
import { keyName, parseKey, parseMeter } from './keysig'

export const IGroupR3 = ({ size = 18 }: { size?: number }) => <svg aria-hidden="true" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"><circle cx="9" cy="8" r="3.5" /><circle cx="17" cy="9" r="2.5" /><path d="M3 19c0-3.3 2.7-6 6-6s6 2.7 6 6M15 18c0-2 1.3-4 3.5-4 1.4 0 2.5 1 2.5 3" /></svg>
export const ICopy = ({ size = 14 }: { size?: number }) => <svg aria-hidden="true" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><rect x="8" y="8" width="12" height="12" rx="2" /><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2" /></svg>

/** The engraved key and time signature on a short staff (Identity.tsx), sized for a card. */
export function MiniStaff({ score, unit = 0.8, width = 168 }: { score: Score; unit?: number; width?: number }) {
  const keySig = parseKey(score.key)
  const meter = parseMeter(score.meter)
  const label = [keySig ? keyName(keySig) : null, meter ? `${meter.top}/${meter.bottom} time` : null].filter(Boolean).join(', ') || 'Signature not read yet'
  return <span className="card-staff"><IdentityStaff keySig={keySig} meter={meter} unit={unit} minWidth={width} label={label} /></span>
}

export function useCopy(): [string | null, (text: string, id: string) => void] {
  const [copied, setCopied] = useState<string | null>(null)
  const copy = (text: string, id: string) => {
    void navigator.clipboard?.writeText(text).catch(() => {})
    setCopied(id)
    window.setTimeout(() => setCopied(c => (c === id ? null : c)), 1600)
  }
  return [copied, copy]
}

