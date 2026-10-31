/** What a book is doing, in one place, for the cover, the book page and the "…" menu.
 *  Busy: the library is reading it (`scores.status` processing: a PDF being rasterised and read, 004, or a MusicXML
 *  import) or converting it to Digital (an `omr_convert` job queued or running, 005). A question: any parked job on the
 *  book (`needs_review`), or the reading run's interpretation marked `needs_review`. Failed: the read stopped, or the
 *  last conversion did and no transcription exists. A book carries one state at most: question over failure over work. */
import type { BookKind, Score } from '../mock'
import { partLabel, type AskJob, type BookJob, type PartJob, type ScoreShare } from './data'
import type { RopeState } from './Rope'

/** A job working on the book that the sheet and the card show in place of the action that started it (CK, 2026-10-31:
 *  one at a time, never a duplicate): a split by instrument or a conversion to Digital, from its row over Realtime. */
export interface LiveJob {
  id: string
  kind: 'part_cut' | 'omr_convert'
  /** queued (or resuming with an answer), working, or parked on a question. */
  state: 'queued' | 'running' | 'needs_review'
  /** Queued with the admin's answer: the question is answered and the run picks up from it. */
  resuming: boolean
  /** "Splitting out the Pianoforte", "Converting to Digital". */
  what: string
  /** Where it stands: "Page 2 of 4 · 3 systems cut", the handler's own note, or the question. */
  detail: string
  /** The question to answer, when it is parked on one. */
  ask: AskJob | null
}

export interface BookState {
  busy: 'reading' | 'converting' | null
  /** A parked job the confirmation sheet can answer. */
  ask: AskJob | null
  /** Yellow: the librarian has a question (there may be no answerable job, only the interpretation's flag). */
  asking: boolean
  question: string | null
  /** Red: the run failed; the reason, in the product's words. */
  failed: string | null
  kinds: BookKind[]
  hasPdf: boolean
  hasDigital: boolean
  /** Digital can be opened now: read, and a file to engrave. */
  digitalReady: boolean
  /** The book's live split by instrument and live conversion, if any. */
  split: LiveJob | null
  convert: LiveJob | null
}

const active = (j: { status: string }) => j.status === 'queued' || j.status === 'running'

export function bookState(s: Score, bookJobs: BookJob[], partJobs: PartJob[]): BookState {
  const mine = bookJobs.filter(j => j.scoreId === s.id)
  const convert = mine.filter(j => j.kind === 'omr_convert')
  const kinds: BookKind[] = s.kinds?.length ? s.kinds : s.book ? [s.book] : []
  const hasPdf = kinds.includes('pdf')
  const hasDigital = kinds.includes('digital')
  const parked = [...mine, ...partJobs.filter(j => j.scoreId === s.id)].find(j => j.status === 'needs_review' && j.question)
  const ask: AskJob | null = parked ? { id: parked.id, scoreId: parked.scoreId, kind: 'kind' in parked ? parked.kind : 'part_cut', question: parked.question, questionPayload: parked.questionPayload } : null
  // A reading parked on a question keeps its interpretation `needs_review` until the resumed run picks it up; once a
  // later job carries the answer (queued or running), the book is no longer asking.
  const readingResumes = mine.some(j => j.kind === 'process_pages' && active(j))
  const asking = !!ask || (!!s.review && !readingResumes)
  // A read parked on a question stays `processing` with its interpretation `needs_review`: that is waiting, not busy.
  const busy = s.status === 'processing' && !asking ? 'reading' : convert.some(active) ? 'converting' : null
  const lastConvert = convert[0]
  const failed = s.status === 'failed'
    ? s.failureReason || 'The librarian could not read this book.'
    : lastConvert?.status === 'failed' && !hasDigital
      ? lastConvert.error || 'The conversion to Digital stopped.'
      : null
  return {
    busy, ask, asking, question: ask?.question ?? s.review?.question ?? null, failed, kinds, hasPdf, hasDigital,
    digitalReady: hasDigital && s.status === 'ready' && !!s.fixture,
    split: liveSplit(partJobs.filter(j => j.scoreId === s.id)),
    convert: liveConvert(convert[0]),
  }
}

const live = (j: { status: string }) => j.status === 'queued' || j.status === 'running' || j.status === 'needs_review'
const plural = (n: number, w: string) => `${n} ${w}${n === 1 ? '' : 's'}`

/** The newest split still working or waiting on a question. */
function liveSplit(jobs: PartJob[]): LiveJob | null {
  const j = jobs.find(live)
  if (!j) return null
  const state = j.status as LiveJob['state']
  const detail = state === 'needs_review'
    ? (j.question?.split('?')[0] ?? 'A question about the staves') + '?'
    : state === 'queued'
      ? (j.resumed ? 'Picking up with your answer' : 'Starting')
      : j.phase
        ? `Page ${j.phase.page} of ${j.phase.pages} · ${plural(j.phase.systemsCut, 'system')} cut`
        : j.note ?? 'Reading the first page'
  return {
    id: j.id, kind: 'part_cut', state, resuming: state === 'queued' && j.resumed, what: `Splitting out ${partLabel(j.instruments)}`, detail,
    ask: state === 'needs_review' ? { id: j.id, scoreId: j.scoreId, kind: 'part_cut', question: j.question, questionPayload: j.questionPayload } : null,
  }
}

function liveConvert(j: BookJob | undefined): LiveJob | null {
  if (!j || !live(j)) return null
  const state = j.status as LiveJob['state']
  return {
    id: j.id, kind: 'omr_convert', state, resuming: state === 'queued' && j.resumed, what: 'Converting to Digital',
    detail: state === 'needs_review' ? j.question ?? 'A question' : state === 'queued' ? 'Starting' : j.note ?? 'Working',
    ask: state === 'needs_review' ? { id: j.id, scoreId: j.scoreId, kind: j.kind, question: j.question, questionPayload: j.questionPayload } : null,
  }
}

/** What a live job is doing, in a word, for whoever reads it. */
export function liveWord(j: LiveJob, canAnswer: boolean): string {
  if (j.state === 'needs_review') return canAnswer ? 'Waiting for you' : 'Waiting for the admin'
  if (j.state === 'queued') return j.resuming ? 'Resuming' : 'Queued'
  return 'Working'
}

/** The status dot's colour, or none when the book is fine. */
export const dotOf = (b: BookState): 'ask' | 'fail' | null => (b.asking ? 'ask' : b.failed ? 'fail' : null)

/** What the rope round the book's card says (Rope.tsx): a person is needed before anything else, else an agent at work. */
export function ropeOf(b: BookState): RopeState | null {
  const job = b.split ?? b.convert
  return b.asking || job?.state === 'needs_review' ? 'asking' : b.failed ? 'failed' : b.busy || job ? 'working' : null
}

/** How a book stands with groups (`score_shares`). A personal book can be shared by reference with the owner's groups:
 *  it stays in the owner's library and each group reads it from there. Its dot and tags (above) are the book's own and
 *  read the same on every shelf: they come from the book's rows and jobs, which a share lets the group read. */
export interface BookShare {
  /** The account owns this personal book: it may share it, and keeps every edit action on every shelf. */
  mine: boolean
  /** On a group's shelf: a book from someone's own library, read here through a share. */
  sharedHere: boolean
  /** Who shared it into the open group ("you" for the account's own). */
  sharedBy: string | null
  /** The groups the account's own book is shared with (ids), for the mark on its cover. */
  sharedWith: string[]
}

export function bookShare(s: Score, shares: ScoreShare[], owners: Record<string, string>, accountId: string, here: string): BookShare {
  const owner = owners[s.id]
  const mine = !!owner && owner === accountId
  const all = shares.filter(x => x.scoreId === s.id)
  const into = all.find(x => x.ensembleId === here)
  return {
    mine,
    sharedHere: !!owner && !!into,
    sharedBy: into ? (into.sharedBy === accountId ? 'you' : into.sharedByName) : null,
    sharedWith: mine ? all.map(x => x.ensembleId) : [],
  }
}
