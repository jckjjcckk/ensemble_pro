// Shared mock data for the design explorations. Realistic values, no placeholders.
// Every exploration reads from here so the five designs show the same world.

/** Seat a member holds in the mock ensemble data. The product has two roles per ensemble, admin and player; leader maps to admin. */
export type Role = 'player' | 'leader' | 'pianist' | 'librarian'

/** Role on a membership. Every account owns a personal library; in an ensemble it is admin or player. */
export type MembershipRole = 'owner' | 'admin' | 'player'

export interface Membership {
  ensembleId: string
  role: MembershipRole
  /** The member record this account acts as inside that ensemble (the mock has no auth). */
  memberId: string
}

/** Counts only: no percentages, no per-note heat. A doubtful page or bar gets a quiet mark; the box shows the numbers. */
export interface ReadFlags {
  pagesUnreadable: number
  barsDoubtful: number
}

export type ScoreStatus = 'uploaded' | 'ordering' | 'processing' | 'ready' | 'failed'

export interface Member {
  id: string
  name: string
  role: Role
  instrument: string
  partId?: string
  online: boolean
  /** Bar the member is currently looking at, when online in doc mode. */
  atBar?: number
}

export interface Ensemble {
  id: string
  name: string
  kind: 'orchestra' | 'choir' | 'chamber' | 'solo'
  members: Member[]
}

export interface Part {
  id: string
  scoreId: string
  name: string
  /** Fixture file under /fixtures that renders this part (whole score for now). */
  fixture: string
  pages: number
  difficulty: 1 | 2 | 3 | 4 | 5
}

export interface Score {
  id: string
  ensembleId: string
  title: string
  composer: string
  work: string
  status: ScoreStatus
  /** 0..1 while processing */
  progress?: number
  failureReason?: string
  fixture: string
  pages: number
  bars: number
  tempoBpm: number
  key: string
  meter: string
  durationSec: number
  updatedAt: string
  partIds: string[]
  /** Folder inside the library, named by the admin or the owner. */
  folder: string
  /** Short brief written by the model after processing. */
  brief?: string
  /** What the reader could not resolve, as counts. Absent for MusicXML imports, which have nothing to read. */
  flags?: ReadFlags
  /** What the book was made from: scanned pages (`pdf`, `images` sources) or a notation file (`musicxml`). Unknown
   *  only in the moment between creating the row and recording its first source. */
  book?: BookKind
  /** The stored notation file of a digital book (bucket-relative), and the name it was imported under. */
  sourcePath?: string
  sourceName?: string
  /** Every form the book exists in: a PDF book with a finished transcription (feature 005) is both. */
  kinds?: BookKind[]
  /** A PDF book's pages: the PDF file itself, or photographed pages in reading order (1-based `order` into `paths`). */
  pageSource?: { kind: 'pdf' | 'images'; paths: string[]; order?: number[] | null }
  /** The MusicXML transcribed from a PDF book's pages (a `musicxml` source with `meta.transcribed_from`). */
  transcriptionPath?: string
  /** The reading run is parked on a question (the latest interpretation is `needs_review`). */
  review?: { question?: string }
  /** The engraved page sets of a digital book (one per layout) and the layout it opens in (`scores.digital_layout`). */
  engravings?: Engraving[]
  digitalLayout?: DigitalLayout
  /** The reader's best guess at the key and meter when it was unsure (`scores.key_sig_guess`, `meter_guess`), its
   *  confidence, and whether the owner confirmed them in Details (then `key` / `meter` are the owner's). */
  keyGuess?: string
  meterGuess?: string
  sigConfidence?: { key?: string; time?: string }
  sigConfirmed?: boolean
  /** Details (F_Details): the tempo marking, the cover's clef, and where bar numbering starts. */
  tempoText?: string
  coverClef?: CoverClef
  firstBar?: number
  firstBarPage?: number
  createdAt?: string
  /** The Digital copy's doubtful bars (`flagged_bars` of the transcription's meta, 005): box = fractions of the PDF page. */
  flaggedBars?: FlaggedBar[]
  /** Pages the reader found no staves on, with its reason (the latest interpretation's summary). */
  unreadable?: { page: number; reason: string }[]
  /** Questions on this book already answered (jobs carrying `resume_from`). */
  answered?: number
  /** Play the parts (014): the book's MIDI (one track per part) and bar map in the bucket (`scores.playback`). Only
   *  digital books have one; a scanned book gets it when it is converted. */
  playback?: Playback
}

export interface Playback { midi: string; barMap: string; parts: string[]; madeAt?: string }

export type CoverClef = 'treble' | 'bass' | 'alto' | 'grand'

export interface FlaggedBar { number: number; page: number; box?: { x0: number; y0: number; x1: number; y1: number }; reasons: string[] }

/** The one tag every book carries. "MusicXML" names the file format, on import and export only; the book is Digital. */
export type BookKind = 'pdf' | 'digital'

/** The two ways a digital book's pages are laid out (005): reflowed to the iPad page, or as the file prints them. */
export type DigitalLayout = 'display' | 'original'
export const LAYOUT_WORDS: Record<DigitalLayout, string> = { display: 'Optimised for digital display', original: 'Preserve original formatting' }

/** A digital book's pages as MuseScore drew them on the box, one layout (an `engraving` source, 005). `bars` are
 *  `[number, page (1-based), x, y, w, h]`, the box as fractions of its page. */
export interface Engraving {
  id: string
  layout: DigitalLayout
  /** Bucket-relative keys of the SVG pages, in order. */
  paths: string[]
  pageCount: number
  pageMm?: [number, number]
  bars: [number, number, number, number, number, number][]
}

export type AnnotationKind = 'marking' | 'cut' | 'voice' | 'text' | 'dynamic' | 'bowing' | 'breath' | 'highlight'

export interface Annotation {
  id: string
  scoreId: string
  /** null = whole ensemble, otherwise one part */
  partId: string | null
  authorId: string
  kind: AnnotationKind
  barFrom: number
  barTo: number
  text?: string
  /** voice notes: seconds and transcript */
  durationSec?: number
  transcript?: string
  createdAt: string
}

export interface TroubleSpot {
  barFrom: number
  barTo: number
  /** 0..1, higher = more wrong notes / hesitations */
  severity: number
  note: string
}

export interface ScanPage {
  id: string
  index: number
  source: 'camera' | 'pdf'
  thumb: string
  warning?: string
}

export interface ScanDraft {
  id: string
  title: string
  pages: ScanPage[]
}

// ---------------------------------------------------------------- ensembles

export const members: Member[] = [
  { id: 'm-ada',   name: 'Ada Okafor',     role: 'leader',    instrument: 'Conductor',   online: true,  atBar: 41 },
  { id: 'm-ck',    name: 'CK Jiang',       role: 'pianist',   instrument: 'Piano',       online: true,  atBar: 41 },
  { id: 'm-lin',   name: 'Lin Zhou',       role: 'player',    instrument: 'Violin I',    partId: 'p-bq-vn1', online: true,  atBar: 41 },
  { id: 'm-noor',  name: 'Noor Haddad',    role: 'player',    instrument: 'Violin II',   partId: 'p-bq-vn2', online: true,  atBar: 39 },
  { id: 'm-tomas', name: 'Tomás Reyes',    role: 'player',    instrument: 'Viola',       partId: 'p-bq-vla', online: false },
  { id: 'm-ines',  name: 'Inès Marchand',  role: 'player',    instrument: 'Cello',       partId: 'p-bq-vc',  online: true,  atBar: 41 },
  { id: 'm-sam',   name: 'Sam Whitfield',  role: 'librarian', instrument: 'Library',     online: true },
  { id: 'm-yuki',  name: 'Yuki Tanaka',    role: 'player',    instrument: 'Soprano',     partId: 'p-ch-s',   online: false },
  { id: 'm-dev',   name: 'Dev Patel',      role: 'player',    instrument: 'Tenor',       partId: 'p-ch-t',   online: false },
]

export const ensembles: Ensemble[] = [
  { id: 'e-hart', name: 'Hart House Chamber Players', kind: 'chamber', members: members.filter(m => ['m-ada','m-lin','m-noor','m-tomas','m-ines','m-sam'].includes(m.id)) },
  { id: 'e-choir', name: 'MacMillan Singers', kind: 'choir', members: members.filter(m => ['m-ada','m-yuki','m-dev','m-sam'].includes(m.id)) },
  { id: 'e-solo', name: 'My library', kind: 'solo', members: members.filter(m => m.id === 'm-ck') },
]

// ---------------------------------------------------------------- scores and parts

export const parts: Part[] = [
  { id: 'p-bq-vn1', scoreId: 's-beethoven', name: 'Violin I',   fixture: '/fixtures/beethoven-op18no1-mv1.musicxml', pages: 6, difficulty: 4 },
  { id: 'p-bq-vn2', scoreId: 's-beethoven', name: 'Violin II',  fixture: '/fixtures/beethoven-op18no1-mv1.musicxml', pages: 5, difficulty: 3 },
  { id: 'p-bq-vla', scoreId: 's-beethoven', name: 'Viola',      fixture: '/fixtures/beethoven-op18no1-mv1.musicxml', pages: 5, difficulty: 3 },
  { id: 'p-bq-vc',  scoreId: 's-beethoven', name: 'Cello',      fixture: '/fixtures/beethoven-op18no1-mv1.musicxml', pages: 5, difficulty: 3 },
  { id: 'p-ch-s',   scoreId: 's-bach',      name: 'Soprano',    fixture: '/fixtures/bach-bwv66-6.musicxml', pages: 1, difficulty: 2 },
  { id: 'p-ch-a',   scoreId: 's-bach',      name: 'Alto',       fixture: '/fixtures/bach-bwv66-6.musicxml', pages: 1, difficulty: 2 },
  { id: 'p-ch-t',   scoreId: 's-bach',      name: 'Tenor',      fixture: '/fixtures/bach-bwv66-6.musicxml', pages: 1, difficulty: 2 },
  { id: 'p-ch-b',   scoreId: 's-bach',      name: 'Bass',       fixture: '/fixtures/bach-bwv66-6.musicxml', pages: 1, difficulty: 2 },
  { id: 'p-pf-solo', scoreId: 's-piano',    name: 'Piano',      fixture: '/fixtures/piano-chopin-mazurka06-2.musicxml', pages: 3, difficulty: 3 },
]

export const scores: Score[] = [
  {
    id: 's-beethoven', ensembleId: 'e-hart',
    title: 'String Quartet No. 1 in F major', composer: 'Ludwig van Beethoven', work: 'Op. 18 No. 1, I. Allegro con brio',
    status: 'ready', fixture: '/fixtures/beethoven-op18no1-mv1.musicxml', pages: 12, bars: 313, tempoBpm: 132, key: 'F major', meter: '3/4', durationSec: 540,
    updatedAt: '2026-10-25T19:42:00Z', partIds: ['p-bq-vn1','p-bq-vn2','p-bq-vla','p-bq-vc'], folder: 'Autumn programme',
    brief: 'Opening motif must be unanimous in rhythm and bow placement; the development (b. 115–178) modulates quickly, so tune the viola entry at 121. The recapitulation cut at 227–246 agreed on 25 Oct stands.',
  },
  {
    id: 's-bach', ensembleId: 'e-choir',
    title: 'Christ ist erstanden', composer: 'Johann Sebastian Bach', work: 'BWV 66.6, chorale',
    status: 'ready', fixture: '/fixtures/bach-bwv66-6.musicxml', pages: 1, bars: 10, tempoBpm: 72, key: 'F# minor', meter: '4/4', durationSec: 55,
    updatedAt: '2026-10-24T09:12:00Z', partIds: ['p-ch-s','p-ch-a','p-ch-t','p-ch-b'], folder: 'Advent',
    brief: 'Short SATB chorale. Breath marks after each fermata; tenors carry the moving line in b. 6–7.',
  },
  {
    id: 's-piano', ensembleId: 'e-solo',
    title: 'Mazurka in C\u266f minor', composer: 'Frédéric Chopin', work: 'Op. 6 No. 2',
    status: 'ready', fixture: '/fixtures/piano-chopin-mazurka06-2.musicxml', pages: 3, bars: 75, tempoBpm: 126, key: 'C\u266f minor', meter: '3/4', durationSec: 160,
    updatedAt: '2026-10-26T14:03:00Z', partIds: ['p-pf-solo'], folder: 'Chopin',
    brief: 'Rubato is written into the phrasing; keep the left-hand mazurka accent on beat two steady so the right hand can bend. Bars 33–48 carry the trio.',
    flags: { pagesUnreadable: 0, barsDoubtful: 2 },
  },
  {
    id: 's-mozart', ensembleId: 'e-hart',
    title: 'Piano Concerto No. 21 in C major', composer: 'Wolfgang Amadeus Mozart', work: 'K. 467, II. Andante',
    status: 'processing', progress: 0.62, fixture: '', pages: 9, bars: 104, tempoBpm: 66, key: 'F major', meter: '4/4', durationSec: 420,
    updatedAt: '2026-10-26T14:20:00Z', partIds: [], folder: 'Autumn programme',
  },
  {
    id: 's-brahms', ensembleId: 'e-hart',
    title: 'Clarinet Quintet in B minor', composer: 'Johannes Brahms', work: 'Op. 115, I. Allegro',
    status: 'failed', failureReason: 'Pages 4 and 7 were too blurred to read staff lines. Retake them and process again.', fixture: '', pages: 14, bars: 218, tempoBpm: 120, key: 'B minor', meter: '6/8', durationSec: 780,
    updatedAt: '2026-10-26T11:48:00Z', partIds: [], folder: 'Reading week', flags: { pagesUnreadable: 2, barsDoubtful: 0 },
  },
  {
    id: 's-faure', ensembleId: 'e-choir',
    title: 'Cantique de Jean Racine', composer: 'Gabriel Fauré', work: 'Op. 11',
    status: 'ordering', fixture: '', pages: 8, bars: 0, tempoBpm: 0, key: 'D♭ major', meter: '4/4', durationSec: 0,
    updatedAt: '2026-10-26T15:01:00Z', partIds: [], folder: 'Advent',
  },
]

// ---------------------------------------------------------------- annotations on the Beethoven

export const annotations: Annotation[] = [
  { id: 'a1', scoreId: 's-beethoven', partId: null, authorId: 'm-ada', kind: 'cut', barFrom: 227, barTo: 246, text: 'Cut agreed 25 Oct', createdAt: '2026-10-25T19:40:00Z' },
  { id: 'a2', scoreId: 's-beethoven', partId: null, authorId: 'm-ada', kind: 'voice', barFrom: 1, barTo: 8, durationSec: 14, transcript: 'Everyone, the opening motif: same bow placement, upper half, and nothing before the downbeat. Think of it as one voice.', createdAt: '2026-10-25T19:05:00Z' },
  { id: 'a3', scoreId: 's-beethoven', partId: 'p-bq-vla', authorId: 'm-ada', kind: 'text', barFrom: 121, barTo: 124, text: 'Tune the F# to the cello, not the violins.', createdAt: '2026-10-25T19:22:00Z' },
  { id: 'a4', scoreId: 's-beethoven', partId: null, authorId: 'm-ada', kind: 'dynamic', barFrom: 41, barTo: 48, text: 'sub. p — real piano, we were mf last time', createdAt: '2026-10-25T19:31:00Z' },
  { id: 'a5', scoreId: 's-beethoven', partId: 'p-bq-vn1', authorId: 'm-lin', kind: 'bowing', barFrom: 57, barTo: 60, text: 'Start down-bow, hooked', createdAt: '2026-10-25T20:02:00Z' },
  { id: 'a6', scoreId: 's-beethoven', partId: 'p-bq-vn1', authorId: 'm-lin', kind: 'marking', barFrom: 178, barTo: 182, text: 'Pencil: circled rest', createdAt: '2026-10-25T20:04:00Z' },
  { id: 'a7', scoreId: 's-beethoven', partId: null, authorId: 'm-ada', kind: 'voice', barFrom: 178, barTo: 190, durationSec: 22, transcript: 'From 178 we are rushing. Cello, you lead the tempo here, violins sit on top of it. Let’s take it at 120 next time and bring it up.', createdAt: '2026-10-26T14:25:00Z' },
]

// ---------------------------------------------------------------- scan intake (Fauré, 8 pages being ordered)

export const scanDraft: ScanDraft = {
  id: 'sc-faure', title: 'Cantique de Jean Racine',
  pages: Array.from({ length: 8 }, (_, i) => ({
    id: `pg${i + 1}`, index: i, source: i < 6 ? 'camera' : 'pdf', thumb: '',
    warning: i === 3 ? 'Blurred, retake suggested' : i === 5 ? 'Page edge cut off' : undefined,
  })),
}

// ---------------------------------------------------------------- helpers

/** The signed-in account of the mock. One account, three contexts: its own library, admin of the quartet, player in the choir. */
export const account = {
  name: 'CK Jiang',
  memberships: [
    { ensembleId: 'e-solo', role: 'owner', memberId: 'm-ck' },
    { ensembleId: 'e-hart', role: 'admin', memberId: 'm-ada' },
    { ensembleId: 'e-choir', role: 'player', memberId: 'm-yuki' },
  ] as Membership[],
}
export const me: Member = members[1] // CK, the account's own seat
export const byId = <T extends { id: string }>(xs: T[]) => Object.fromEntries(xs.map(x => [x.id, x])) as Record<string, T>
export const membersById = byId(members)
export const scoresById = byId(scores)
export const partsById = byId(parts)
export const fmtDuration = (s: number) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
