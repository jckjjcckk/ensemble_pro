/** What a book is doing, in one place, for the cover, the book page and the "…" menu.
 *  Busy: the library is reading it (`scores.status` processing: a PDF being rasterised and read, 004, or a MusicXML
 *  import) or converting it to Digital (an `omr_convert` job queued or running, 005). A question: any parked job on the
 *  book (`needs_review`), or the reading run's interpretation marked `needs_review`. Failed: the read stopped, or the
 *  last conversion did and no transcription exists. A book carries one status dot at most: question over failure. */
import type { BookKind, Score } from '../mock'
import type { AskJob, BookJob, PartJob } from './data'

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
  const asking = !!ask || !!s.review
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
  }
}

/** The status dot's colour, or none when the book is fine. */
export const dotOf = (b: BookState): 'ask' | 'fail' | null => (b.asking ? 'ask' : b.failed ? 'fail' : null)
