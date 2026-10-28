/** The real world: scores, parts, ensembles and memberships from Supabase, in the shapes the screens use.
 *  RLS decides what comes back, so the query is the same for every account. Realtime row changes trigger a
 *  refetch (notification only; the database is truth). */
import { useCallback, useEffect, useRef, useState } from 'react'
import type { Session } from '@supabase/supabase-js'
import { supabase } from '../lib/supabase'
import type { Ensemble, Member, Membership, Part, Score } from '../mock'

export interface Account { id: string; name: string; email: string; memberships: Membership[] }
export interface World {
  account: Account
  ensembles: Ensemble[]
  members: Member[]
  scores: Score[]
  parts: Part[]
  /** Part-cut jobs (008), the latest of each chain of question and answer. */
  jobs: PartJob[]
  /** Finished splits by instrument: a `part_images` source (a PDF book's strips, 008, 010) or a `musicxml` source
   *  holding only the chosen instruments (a digital book's split). */
  strips: PartStrip[]
  /** Instrument names the librarian read from each score's header (003), in score order. */
  headers: Record<string, string[]>
  /** Every other job on a book (reading a PDF, an import, a conversion to Digital), the latest of each chain. */
  bookJobs: BookJob[]
  /** What the account may see of each group beyond its name: the join code (members only) and who made it. */
  groups: Record<string, GroupInfo>
  /** Personal books shared with a group by reference (`score_shares`): the account's own shares and every share into
   *  its groups. The book stays in its owner's library; the group reads it. */
  shares: ScoreShare[]
  /** The owner of every personal book the account can read (score id → user id). A group's own book is absent. */
  owners: Record<string, string>
  loaded: boolean
  reload: () => void
}

/** One staff box on the numbered overlay, in the overlay image's own pixels. */
export interface StaffBox { index: number; y_top: number; y_bottom: number; x0: number; x1: number }

/** The typed question a parked `part_cut` job asks (011, kind `choose_staves`). */
export interface ChooseStaves {
  kind: 'choose_staves'
  page: number
  system: number
  instrument: string
  interpretation_id?: string
  proposal: number[] | 'absent' | null
  last_attempt: number[] | 'absent' | null
  feedback?: string | null
  staff_boxes: StaffBox[]
  image_key: string | null
  allowed: { staves: string; absent: boolean }
  answer_format: string
}

export type PartJobStatus = 'queued' | 'running' | 'needs_review' | 'done' | 'failed'

export interface PartJob {
  id: string
  scoreId: string
  status: PartJobStatus
  progress: number
  instruments: string[]
  pages?: number[]
  /** The handler's last progress note. */
  note?: string
  /** The handler's log lines (what it read, what it cut) while it runs. */
  log: string[]
  error?: string
  question?: string
  questionPayload?: ChooseStaves
  sourceId?: string
  systemsCut?: number
  createdAt: string
}

/** A job on a book that is not a split: `process_pages` (reading a PDF), `import_musicxml`, `omr_convert` (005). */
export interface BookJob {
  id: string
  scoreId: string
  kind: string
  status: PartJobStatus
  progress: number
  error?: string
  question?: string
  /** The typed question: `choose_staves` (011), or the reader's "which parts are on page N" (004). */
  questionPayload?: Record<string, unknown>
  createdAt: string
}

/** Any parked job the confirmation sheet can answer (`POST /jobs/{id}/answer`). */
export interface AskJob { id: string; scoreId: string; kind?: string; question?: string; questionPayload?: Record<string, unknown> | ChooseStaves }

export interface GroupInfo { joinCode?: string; createdBy?: string }

/** One personal book shared with one group (`score_shares`; 001, 010). */
export interface ScoreShare {
  scoreId: string
  ensembleId: string
  sharedBy: string
  /** The sharer as the group knows them (their member name), or the account's own name. */
  sharedByName: string
  createdAt: string
}

/** A book the account reads only through a share into a group it is not looking at: on no shelf. */
export const SHARED_ELSEWHERE = 'shared'

export interface PartStrip {
  id: string
  scoreId: string
  /** `images`: system strips cut from a PDF book's pages. `musicxml`: a digital book's notation, only these instruments. */
  kind: 'images' | 'musicxml'
  instruments: string[]
  /** "Piano", or "Soprano & Alto" for a selection of parts. */
  label: string
  /** Bucket-relative keys of the cut system images, in reading order (empty for a digital split). */
  paths: string[]
  /** The split's own MusicXML file (digital splits only). */
  path?: string
  systems: { page: number; system: number; staves: number[] | 'absent'; key: string | null; bars: number | null }[]
  createdAt: string
}

export const partLabel = (instruments: string[]) => instruments.join(' & ')

export const MY_LIBRARY = 'me'

type Row = Record<string, any>

const SIGN_SEC = 3600
/** A signed URL is re-signed this long before it expires, so a score opened late in the hour still loads. */
const SIGN_KEEP_MARGIN_SEC = 600
const signedUrls = new Map<string, { url: string; until: number }>()

async function load(session: Session): Promise<Omit<World, 'reload'>> {
  const uid = session.user.id
  const [mem, sc, pa, prof, jb, src, itp, bj, grp, sh] = await Promise.all([
    supabase.from('members').select('id,role,part,ensemble_id,user_id,display_name,ensembles(id,name)'),
    supabase.from('scores').select('*').order('updated_at', { ascending: false }),
    supabase.from('parts').select('*').order('position'),
    supabase.from('profiles').select('display_name,email').eq('id', uid).maybeSingle(),
    // Narrow JSON paths: a job's result also holds the agent transcript, which nobody on the iPad reads.
    supabase.from('jobs')
      .select('id,kind,status,progress,error,score_id,created_at,payload,note:result->>note,question:result->>question,question_payload:result->question_payload,source_id:result->>source_id,systems_cut:result->systems_cut,log:result->agent->scratch->log,agent_log:result->agent->log')
      .eq('kind', 'part_cut').order('created_at'),
    supabase.from('sources').select('id,score_id,kind,storage_paths,page_order,meta,created_at').order('created_at'),
    supabase.from('interpretations').select('id,score_id,engine,status,created_at,header:params->state->header->instruments,summary_header:summary->header->instruments,summary_parts:summary->parts,summary_question:summary->>question').order('created_at'),
    supabase.from('jobs')
      .select('id,kind,status,progress,error,score_id,created_at,payload,question:result->>question,question_payload:result->question_payload')
      .neq('kind', 'part_cut').order('created_at'),
    // `*` so a stack without `join_code` yet still answers (the code then simply does not show).
    supabase.from('ensembles').select('*'),
    // Shares of the account's own books, and every share into its groups (RLS). A stack without the table answers
    // with an error and the shelves simply have no shared books.
    supabase.from('score_shares').select('score_id,ensemble_id,shared_by,created_at').order('created_at'),
  ])
  const memberRows: Row[] = mem.data ?? []
  const scoreRows: Row[] = sc.data ?? []
  const partRows: Row[] = pa.data ?? []
  const jobRows: Row[] = jb.data ?? []
  const sourceRows: Row[] = src.data ?? []
  const stripRows = sourceRows.filter(isSplit)
  const interpRows: Row[] = itp.data ?? []
  const bookJobRows: Row[] = bj.data ?? []
  const groupRows: Row[] = grp.data ?? []
  const shareRows: Row[] = sh.data ?? []
  const myName = prof.data?.display_name || session.user.email?.split('@')[0] || 'You'

  const members: Member[] = memberRows.map(m => ({
    id: m.id, name: m.display_name || 'A member', role: m.role === 'admin' ? 'leader' : 'player',
    instrument: m.part ?? '', online: false,
  }))
  const self: Member = { id: MY_LIBRARY, name: myName, role: 'pianist', instrument: 'Piano', online: true }
  const ensembleIds = [...new Set(memberRows.map(m => m.ensemble_id as string))]
  const ensembles: Ensemble[] = [
    { id: MY_LIBRARY, name: 'My library', kind: 'solo', members: [self] },
    ...ensembleIds.map(id => ({
      id, name: memberRows.find(m => m.ensemble_id === id)?.ensembles?.name ?? 'Group', kind: 'chamber' as const,
      members: members.filter(m => memberRows.find(r => r.id === m.id)?.ensemble_id === id),
    })),
  ]
  // A personal book is the owner's: in their library. Someone else's personal book is read through a share, and
  // belongs (for roles, the roster, the reader) to the first of the account's groups it is shared with.
  const myGroups = new Set(memberRows.filter(m => m.user_id === uid).map(m => m.ensemble_id as string))
  const homeOf = (s: Row): string => {
    if (s.ensemble_id) return s.ensemble_id
    if (!s.owner_user_id || s.owner_user_id === uid) return MY_LIBRARY
    return shareRows.find(r => r.score_id === s.id && myGroups.has(r.ensemble_id))?.ensemble_id ?? SHARED_ELSEWHERE
  }
  const shares: ScoreShare[] = shareRows.map(r => ({
    scoreId: r.score_id, ensembleId: r.ensemble_id, sharedBy: r.shared_by, createdAt: r.created_at,
    sharedByName: r.shared_by === uid ? myName : memberRows.find(m => m.ensemble_id === r.ensemble_id && m.user_id === r.shared_by)?.display_name || 'a member',
  }))
  const owners: Record<string, string> = Object.fromEntries(scoreRows.filter(s => s.owner_user_id).map(s => [s.id as string, s.owner_user_id as string]))
  const memberships: Membership[] = [
    { ensembleId: MY_LIBRARY, role: 'owner', memberId: MY_LIBRARY },
    ...memberRows.filter(m => m.user_id === uid).map(m => ({ ensembleId: m.ensemble_id as string, role: m.role as 'admin' | 'player', memberId: m.id as string })),
  ]

  // One signed URL per ready score: the file OSMD renders (the whole score for now; parts come from it).
  // A URL is kept across reloads while it has time left: the stage treats a new URL as a new score and engraves again.
  const ready = scoreRows.filter(s => s.status === 'ready')
  const firstPath = (s: Row) => partRows.find(p => p.score_id === s.id && p.storage_path)?.storage_path as string | undefined
  // A PDF book converted to Digital (005) reads from its transcription when no part carries a file of its own.
  const transcriptionOf = (s: Row) => (sourceRows.filter(r => r.score_id === s.id && r.kind === 'musicxml' && r.meta?.transcribed_from).pop()?.storage_paths as string[] | undefined)?.[0]
  const playPath = (s: Row) => firstPath(s) ?? transcriptionOf(s)
  const now = Date.now()
  const paths = [...new Set(ready.map(playPath).filter((p): p is string => !!p && (signedUrls.get(p)?.until ?? 0) <= now))]
  const signed = paths.length ? (await supabase.storage.from('scores').createSignedUrls(paths, SIGN_SEC)).data ?? [] : []
  for (const u of signed) if (u.path && u.signedUrl) signedUrls.set(u.path, { url: u.signedUrl, until: now + (SIGN_SEC - SIGN_KEEP_MARGIN_SEC) * 1000 })
  const urlFor = (path?: string) => (path ? signedUrls.get(path)?.url ?? '' : '')

  const parts: Part[] = partRows.map(p => ({
    id: p.id, scoreId: p.score_id, name: p.name, fixture: urlFor(p.storage_path), pages: 0,
    difficulty: (p.difficulty ?? 3) as Part['difficulty'],
  }))
  // A book is what it was first made from; splits (images or notation) are its children, not its kind.
  const bookOf = (s: Row): Pick<Score, 'book' | 'sourcePath' | 'sourceName'> => {
    const first = sourceRows.find(r => r.score_id === s.id && !isSplit(r) && !r.meta?.transcribed_from)
    if (first) {
      const digital = first.kind === 'musicxml'
      return { book: digital ? 'digital' : 'pdf', sourcePath: digital ? (first.storage_paths as string[])?.[0] : undefined, sourceName: digital ? first.meta?.filename ?? undefined : undefined }
    }
    if (firstPath(s)) return { book: 'digital', sourcePath: firstPath(s) }
    if (stripRows.some(r => r.score_id === s.id && r.kind === 'part_images')) return { book: 'pdf' }
    return {}
  }
  /** The forms a book exists in, its pages, its transcription, and an open question on its reading run. */
  const formsOf = (s: Row, book: Score['book']): Pick<Score, 'kinds' | 'pageSource' | 'transcriptionPath' | 'review'> => {
    const pagesRow = sourceRows.find(r => r.score_id === s.id && (r.kind === 'pdf' || r.kind === 'images'))
    const transcriptionPath = transcriptionOf(s)
    const kinds: NonNullable<Score['kinds']> = []
    if (book === 'pdf' || pagesRow) kinds.push('pdf')
    if (book === 'digital' || transcriptionPath || (book === 'pdf' && firstPath(s))) kinds.push('digital')
    const latest = interpRows.filter(r => r.score_id === s.id).pop()
    return {
      kinds,
      pageSource: pagesRow ? { kind: pagesRow.kind, paths: (pagesRow.storage_paths as string[]) ?? [], order: (pagesRow.page_order as number[] | null) ?? null } : undefined,
      transcriptionPath,
      review: latest?.status === 'needs_review' ? { question: latest.summary_question ?? undefined } : undefined,
    }
  }
  const scores: Score[] = scoreRows.map(s => ({
    id: s.id, ensembleId: homeOf(s),
    title: s.title || 'Untitled', composer: s.composer ?? '', work: s.work ?? '',
    status: s.status, progress: s.progress ?? undefined, failureReason: s.failure_reason ?? undefined,
    fixture: urlFor(playPath(s)), pages: s.pages ?? 0, bars: s.bars ?? 0, tempoBpm: s.tempo_bpm ?? 0,
    key: s.key_sig ?? '', meter: s.meter ?? '', durationSec: s.duration_sec ?? 0, updatedAt: s.updated_at,
    partIds: partRows.filter(p => p.score_id === s.id).map(p => p.id), folder: s.folder || 'Scores', brief: s.brief ?? undefined,
    ...bookOf(s),
  })).map(sc => ({ ...sc, ...formsOf(scoreRows.find(r => r.id === sc.id)!, sc.book) }))

  return {
    account: { id: uid, name: myName, email: session.user.email ?? '', memberships }, ensembles, members, scores, parts,
    jobs: partJobs(jobRows), strips: partStrips(stripRows), headers: headersOf(interpRows, partRows), loaded: true,
    bookJobs: chainedBookJobs(bookJobRows),
    groups: Object.fromEntries(groupRows.map(g => [g.id as string, { joinCode: g.join_code ?? undefined, createdBy: g.created_by ?? undefined }])),
    shares, owners,
  }
}

const instrumentsOf = (o: Row | null | undefined): string[] => {
  const xs = Array.isArray(o?.instruments) ? o!.instruments : o?.instrument ? [o.instrument] : []
  return xs.map((x: unknown) => String(x)).filter(Boolean)
}

/** A job that asked a question is answered by a later job carrying `resume_from`; the chain shows its last link. */
function partJobs(rows: Row[]): PartJob[] {
  const answered = new Set(rows.map(r => r.payload?.resume_from as string | undefined).filter(Boolean))
  return rows
    .filter(r => !answered.has(r.id))
    .map(r => {
      const q = r.question_payload as ChooseStaves | null
      const parked = r.status === 'done' && !!r.question && q?.kind === 'choose_staves'
      const status: PartJobStatus = parked ? 'needs_review' : r.status === 'done' && !r.source_id && !r.systems_cut ? 'failed' : r.status
      const log = [...((r.log as string[] | null) ?? []), ...((r.agent_log as string[] | null) ?? [])].map(String)
      return {
        id: r.id, scoreId: r.score_id, status, progress: Number(r.progress ?? 0),
        instruments: instrumentsOf(r.payload), pages: Array.isArray(r.payload?.pages) ? r.payload.pages : undefined,
        note: r.note ?? undefined, log, error: r.error ?? (status === 'failed' && r.status === 'done' ? 'The split stopped before anything was made.' : undefined),
        question: parked ? r.question : undefined, questionPayload: parked ? q! : undefined,
        sourceId: r.source_id ?? undefined, systemsCut: r.systems_cut ?? undefined, createdAt: r.created_at,
      }
    })
    .reverse()
}

/** The other jobs on a book, chained the same way: a parked one is `needs_review` until a later job answers it. */
function chainedBookJobs(rows: Row[]): BookJob[] {
  const answered = new Set(rows.map(r => r.payload?.resume_from as string | undefined).filter(Boolean))
  return rows
    .filter(r => !answered.has(r.id) && r.score_id)
    .map(r => {
      const parked = r.status === 'done' && !!r.question
      return {
        id: r.id, scoreId: r.score_id, kind: r.kind, status: (parked ? 'needs_review' : r.status) as PartJobStatus, progress: Number(r.progress ?? 0),
        error: r.error ?? undefined, question: parked ? r.question : undefined,
        questionPayload: parked ? (r.question_payload as Record<string, unknown> | null) ?? {} : undefined, createdAt: r.created_at,
      }
    })
    .reverse()
}

/** A split is a source made from another one: strips cut from pages, or a notation file holding some instruments.
 *  A transcription of the pages (`meta.transcribed_from`) is the book's Digital form, not a split. */
const isSplit = (r: Row) => !r.meta?.transcribed_from && (r.kind === 'part_images' || (r.kind === 'musicxml' && (Array.isArray(r.meta?.instruments) || !!r.meta?.slug)))

function partStrips(rows: Row[]): PartStrip[] {
  return rows.map(r => {
    const instruments = instrumentsOf(r.meta)
    const digital = r.kind === 'musicxml'
    const keys = (r.storage_paths as string[]) ?? []
    return {
      id: r.id, scoreId: r.score_id, kind: digital ? 'musicxml' as const : 'images' as const, instruments,
      label: partLabel(instruments.length ? instruments : ['Part']),
      paths: digital ? [] : keys, path: digital ? keys[0] : undefined,
      systems: (r.meta?.systems as PartStrip['systems']) ?? [], createdAt: r.created_at,
    }
  }).reverse()
}

/** The header read by the latest run that has one; else the parts the page reader found; else the parts rows. */
function headersOf(interps: Row[], parts: Row[]): Record<string, string[]> {
  const out: Record<string, string[]> = {}
  const clean = (xs: unknown): string[] => (Array.isArray(xs) ? xs : []).map(x => (typeof x === 'string' ? x : x?.name ?? x?.label ?? '')).map(x => String(x).trim().replace(/\.$/, '')).filter(Boolean)
  for (const r of interps) {
    const names = [r.header, r.summary_header, r.summary_parts].map(clean).find(xs => xs.length)
    if (names) out[r.score_id] = names   // ordered by created_at, so the latest wins
  }
  for (const p of parts) if (!out[p.score_id]?.length && p.name && !p.storage_path?.includes('/parts/')) out[p.score_id] = [...(out[p.score_id] ?? []), p.name]
  return out
}

const empty = (uid = '', name = ''): Omit<World, 'reload'> => ({
  account: { id: uid, name, email: '', memberships: [{ ensembleId: MY_LIBRARY, role: 'owner', memberId: MY_LIBRARY }] },
  ensembles: [{ id: MY_LIBRARY, name: 'My library', kind: 'solo', members: [{ id: MY_LIBRARY, name: name || 'You', role: 'pianist', instrument: 'Piano', online: true }] }],
  members: [], scores: [], parts: [], jobs: [], strips: [], headers: {}, loaded: false, bookJobs: [], groups: {},
  shares: [], owners: {},
})

export function useWorld(session: Session | null): World {
  const [world, setWorld] = useState(() => empty())
  const timer = useRef<number | null>(null)
  const reload = useCallback(() => {
    if (!session) return
    if (timer.current) window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => { load(session).then(setWorld).catch(e => console.warn('world', e)) }, 150)
  }, [session])

  useEffect(() => {
    if (!session) { setWorld(empty()); return }
    load(session).then(setWorld).catch(e => console.warn('world', e))
    const ch = supabase.channel('world')
      .on('postgres_changes', { event: '*', schema: 'public', table: 'scores' }, reload)
      .on('postgres_changes', { event: '*', schema: 'public', table: 'parts' }, reload)
      .on('postgres_changes', { event: '*', schema: 'public', table: 'members' }, reload)
      .on('postgres_changes', { event: '*', schema: 'public', table: 'jobs' }, reload)
      .on('postgres_changes', { event: '*', schema: 'public', table: 'interpretations' }, reload)
      .on('postgres_changes', { event: '*', schema: 'public', table: 'sources' }, reload)
      .on('postgres_changes', { event: '*', schema: 'public', table: 'ensembles' }, reload)
      .on('postgres_changes', { event: '*', schema: 'public', table: 'score_shares' }, reload)
      .subscribe()
    return () => { supabase.removeChannel(ch) }
  }, [session, reload])

  return { ...world, reload }
}

/** Path A intake from the browser: a MusicXML file becomes a score row, an upload, and an import job. */
export async function importMusicXml(file: File, where: { ensembleId: string | null; ownerId: string | null; createdBy: string }, apiBase: string, token: string): Promise<void> {
  const { data: row, error } = await supabase.from('scores').insert({
    ensemble_id: where.ensembleId, owner_user_id: where.ownerId, title: '', folder: 'Imported', status: 'uploaded', created_by: where.createdBy,
  }).select('id').single()
  if (error || !row) throw new Error('The score could not be added to this library.')
  const key = `${row.id}/source.musicxml`
  const up = await supabase.storage.from('scores').upload(key, file, { contentType: 'application/vnd.recordare.musicxml+xml', upsert: true })
  if (up.error) throw new Error('The file did not upload. Check the connection and try again.')
  const res = await fetch(`${apiBase}/scores/${row.id}/import`, {
    method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` }, body: JSON.stringify({ path: key, filename: file.name }),
  })
  if (!res.ok) throw new Error((await res.json().catch(() => ({})))?.detail ?? 'The file is stored, but the librarian could not start reading it. Try the import again.')
}

/** Hand a stored notation file to the device: Safari on the iPad offers to save it to Files. The bytes come through the
 *  storage API (RLS decides) and leave as a same-origin blob, so the file name holds on every browser. */
export async function exportStored(path: string, filename: string): Promise<void> {
  const { data, error } = await supabase.storage.from('scores').download(path)
  if (error || !data) throw new Error('The file could not be fetched. Check the connection and try again.')
  const compressed = /\.mxl$/i.test(filename)
  const blob = new Blob([data], { type: compressed ? 'application/vnd.recordare.musicxml' : 'application/vnd.recordare.musicxml+xml' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.rel = 'noopener'
  document.body.append(a)
  a.click()
  a.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 30_000)
}

/** A name a musician recognises in Files: the imported file's own name, or the title (and the instruments of a split). */
export function exportName(title: string, path: string, sourceName?: string, label?: string): string {
  if (!label && sourceName) return sourceName
  const ext = /\.mxl$/i.test(sourceName ?? path) ? 'mxl' : 'musicxml'
  const base = [title.trim() || 'Score', label].filter(Boolean).join(' – ').replace(/[\\/:*?"<>|]+/g, ' ').replace(/\s+/g, ' ').trim()
  return `${base}.${ext}`
}

/** A score row in the library the user is in: theirs, or the group's. */
export interface Where { ensembleId: string | null; ownerId: string | null; createdBy: string }

/** A PDF reads itself (002): the browser makes the score row, uploads the file to `{score_id}/source.pdf`, records a
 *  `pdf` source, and asks the API to read it (`POST /scores/{id}/import`), which rasterises the pages and queues the
 *  reading (004). No page order to confirm; the cover shows a busy ring until the row says `ready` or `failed`. */
export async function importPdf(file: File, where: Where, apiBase: string, token: string): Promise<void> {
  const title = file.name.replace(/\.pdf$/i, '').replace(/_+/g, ' ').replace(/\s+/g, ' ').trim()
  const { data: row, error } = await supabase.from('scores').insert({
    ensemble_id: where.ensembleId, owner_user_id: where.ownerId, title, folder: 'Imported', status: 'uploaded', created_by: where.createdBy,
  }).select('id').single()
  if (error || !row) throw new Error('The score could not be added to this library.')
  const key = `${row.id}/source.pdf`
  const up = await supabase.storage.from('scores').upload(key, file, { contentType: 'application/pdf', upsert: true })
  if (up.error) throw new Error('The file did not upload. Check the connection and try again.')
  const src = await supabase.from('sources').insert({
    score_id: row.id, kind: 'pdf', storage_paths: [key], meta: { filename: file.name }, created_by: where.createdBy,
  }).select('id').single()
  if (src.error || !src.data) throw new Error('The file is stored, but it could not be recorded as the book\'s pages. Try the import again.')
  const res = await fetch(`${apiBase}/scores/${row.id}/import`, {
    method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify({ path: key, filename: file.name, kind: 'pdf' }),
  })
  if (!res.ok) throw new Error((await res.json().catch(() => ({})))?.detail ?? 'The file is stored, but the librarian could not start reading it. Try the import again.')
}

/** A PDF or a notation file, by what it is. */
export const isPdf = (file: File) => file.type === 'application/pdf' || /\.pdf$/i.test(file.name)

// ---------------------------------------------------------------- groups (the `ensembles` table, "group" on screen)

/** A refusal from the RPCs carries a stable key in `hint` (bad_name, bad_code, unknown_code, not_member, last_admin,
 *  not_admin, not_found, not_signed_in) and its sentence in `message`, shown as is. Anything else (a missing function,
 *  a network failure, a signed-out call) becomes a sentence here. */
function groupError(error: { message?: string; hint?: string | null } | null | undefined, fallback: string): string {
  const m = (error?.message ?? '').trim()
  if (error?.hint && m) return m
  if (/could not find the function|schema cache/i.test(m)) return 'Groups are not available on this server yet.'
  if (!m || /function|permission denied|violates|syntax|JWT|fetch|network/i.test(m)) return fallback
  const sentence = m.charAt(0).toUpperCase() + m.slice(1)
  return /[.!?]$/.test(sentence) ? sentence : `${sentence}.`
}

export interface NewGroup { id: string; name: string; joinCode?: string }

/** `create_ensemble(name)` returns the new row; the creator is its admin. */
export async function createGroup(name: string): Promise<NewGroup> {
  const { data, error } = await supabase.rpc('create_ensemble', { name })
  if (error) throw new Error(groupError(error, 'The group could not be created. Try again in a moment.'))
  const row = (Array.isArray(data) ? data[0] : data) as Row | null
  if (!row?.id) throw new Error('The group could not be created. Try again in a moment.')
  return { id: row.id, name: row.name ?? name, joinCode: row.join_code ?? undefined }
}

/** `join_ensemble(code)` returns the group's id; an unknown code comes back as the RPC's own sentence. */
export async function joinGroup(code: string): Promise<string> {
  const { data, error } = await supabase.rpc('join_ensemble', { code })
  if (error) throw new Error(groupError(error, 'That code did not open a group. Check the eight digits and try again.'))
  const id = typeof data === 'string' ? data : (Array.isArray(data) ? data[0] : data)?.id
  if (!id) throw new Error('That code did not open a group. Check the eight digits and try again.')
  return id as string
}

/** `leave_ensemble(ensemble)`: refused while the account is the group's last admin. */
export async function leaveGroup(id: string): Promise<void> {
  const { error } = await supabase.rpc('leave_ensemble', { ensemble: id })
  if (error) throw new Error(groupError(error, 'You could not leave the group just now. Try again in a moment.'))
}

/** `delete_ensemble(ensemble)`: admins only; the group's books go with it. */
export async function deleteGroup(id: string): Promise<void> {
  const { error } = await supabase.rpc('delete_ensemble', { ensemble: id })
  if (error) throw new Error(groupError(error, 'The group could not be deleted just now. Try again in a moment.'))
}

// ---------------------------------------------------------------- sharing a book with a group (`score_shares`)

/** `share_score(score, ensemble)`: the owner lets one of their groups read a book of their own library. Nothing is
 *  copied and nothing moves; sharing twice changes nothing. Refusals: not_owner, not_member, not_found. */
export async function shareBook(scoreId: string, ensembleId: string): Promise<void> {
  const { error } = await supabase.rpc('share_score', { score: scoreId, ensemble: ensembleId })
  if (error) throw new Error(groupError(error, 'The book could not be shared just now. Try again in a moment.'))
}

/** `unshare_score(score, ensemble)`: the group stops reading the book at once. Its marks on the book are kept. */
export async function unshareBook(scoreId: string, ensembleId: string): Promise<void> {
  const { error } = await supabase.rpc('unshare_score', { score: scoreId, ensemble: ensembleId })
  if (error) throw new Error(groupError(error, 'The book is still shared. Try again in a moment.'))
}
