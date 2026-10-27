import {
  ensembles,
  fmtDuration,
  membersById,
  scoresById,
  type Annotation,
  type AnnotationKind,
  type Ensemble,
  type Member,
  type Role,
} from '../shared'

/** Placeholder wordmark. The product name is undecided; swap it here. */
export const WORDMARK = 'Muse'

export const ROLES: Role[] = ['player', 'leader', 'pianist', 'librarian']

export const ROLE_LABEL: Record<Role, string> = {
  player: 'Player',
  leader: 'Leader',
  pianist: 'Pianist',
  librarian: 'Librarian',
}

/** Which member the prototype acts as for each role. */
const ROLE_MEMBER: Record<Role, string> = {
  player: 'm-lin',
  leader: 'm-ada',
  pianist: 'm-ck',
  librarian: 'm-sam',
}

export const memberForRole = (r: Role): Member => membersById[ROLE_MEMBER[r]]

export const ensemblesOf = (memberId: string): Ensemble[] =>
  ensembles.filter(e => e.members.some(m => m.id === memberId))

export const ensembleOfScore = (scoreId: string): Ensemble | undefined => {
  const s = scoresById[scoreId]
  return s ? ensembles.find(e => e.id === s.ensembleId) : undefined
}

export const ENSEMBLE_KIND: Record<Ensemble['kind'], string> = {
  orchestra: 'Orchestra',
  choir: 'Choir',
  chamber: 'Chamber ensemble',
  solo: 'Solo',
}

export const initials = (name: string) =>
  name
    .split(/\s+/)
    .map(w => w[0] ?? '')
    .join('')
    .slice(0, 2)
    .toUpperCase()

export const firstName = (name: string) => name.split(/\s+/)[0]

export const barRange = (a: number, b: number) => (a === b ? `${a}` : `${a}–${b}`)

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

/** Dates are shown in UTC so every device renders the same mock values. */
export function fmtDate(iso: string, time = false) {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  const day = `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]}`
  if (!time) return day
  const hh = String(d.getUTCHours()).padStart(2, '0')
  const mm = String(d.getUTCMinutes()).padStart(2, '0')
  return `${day}, ${hh}:${mm}`
}

export const KIND_LABEL: Record<AnnotationKind, string> = {
  marking: 'Pencil',
  cut: 'Cut',
  voice: 'Voice note',
  text: 'Note',
  dynamic: 'Dynamic',
  bowing: 'Bowing',
  breath: 'Breath',
}

/** A marking addressed to everyone shows on every part; a part marking shows on its part and the full score. */
export const appliesTo = (a: Annotation, partId: string | null) =>
  partId === null || a.partId === null || a.partId === partId

/** The short label a marking carries on the page. */
export function pinText(a: Annotation): string {
  if (a.kind === 'voice') return a.durationSec ? fmtDuration(a.durationSec) : 'Voice'
  const t = a.text?.trim() || KIND_LABEL[a.kind]
  return t.split(' — ')[0]
}

export const beatsPerBar = (meter: string) => {
  const n = parseInt(meter.split('/')[0] ?? '', 10)
  return Number.isFinite(n) && n > 0 ? n : 4
}
