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
  const [mem, sc, pa, prof, jb, src, itp] = await Promise.all([
    supabase.from('members').select('id,role,part,ensemble_id,user_id,display_name,ensembles(id,name)'),
    supabase.from('scores').select('*').order('updated_at', { ascending: false }),
    supabase.from('parts').select('*').order('position'),
    supabase.from('profiles').select('display_name,email').eq('id', uid).maybeSingle(),
    // Narrow JSON paths: a job's result also holds the agent transcript, which nobody on the iPad reads.
    supabase.from('jobs')
      .select('id,kind,status,progress,error,score_id,created_at,payload,note:result->>note,question:result->>question,question_payload:result->question_payload,source_id:result->>source_id,systems_cut:result->systems_cut,log:result->agent->scratch->log,agent_log:result->agent->log')
      .eq('kind', 'part_cut').order('created_at'),
    supabase.from('sources').select('id,score_id,kind,storage_paths,meta,created_at').order('created_at'),
    supabase.from('interpretations').select('id,score_id,engine,status,created_at,header:params->state->header->instruments,summary_header:summary->header->instruments,summary_parts:summary->parts').order('created_at'),
  ])
  const memberRows: Row[] = mem.data ?? []
  const scoreRows: Row[] = sc.data ?? []
  const partRows: Row[] = pa.data ?? []
  const jobRows: Row[] = jb.data ?? []
  const sourceRows: Row[] = src.data ?? []
  const stripRows = sourceRows.filter(isSplit)
  const interpRows: Row[] = itp.data ?? []
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
      id, name: memberRows.find(m => m.ensemble_id === id)?.ensembles?.name ?? 'Ensemble', kind: 'chamber' as const,
      members: members.filter(m => memberRows.find(r => r.id === m.id)?.ensemble_id === id),
    })),
  ]
  const memberships: Membership[] = [
    { ensembleId: MY_LIBRARY, role: 'owner', memberId: MY_LIBRARY },
    ...memberRows.filter(m => m.user_id === uid).map(m => ({ ensembleId: m.ensemble_id as string, role: m.role as 'admin' | 'player', memberId: m.id as string })),
  ]

  // One signed URL per ready score: the file OSMD renders (the whole score for now; parts come from it).
  // A URL is kept across reloads while it has time left: the stage treats a new URL as a new score and engraves again.
  const ready = scoreRows.filter(s => s.status === 'ready')
  const firstPath = (s: Row) => partRows.find(p => p.score_id === s.id && p.storage_path)?.storage_path as string | undefined
  const now = Date.now()
  const paths = [...new Set(ready.map(firstPath).filter((p): p is string => !!p && (signedUrls.get(p)?.until ?? 0) <= now))]
  const signed = paths.length ? (await supabase.storage.from('scores').createSignedUrls(paths, SIGN_SEC)).data ?? [] : []
  for (const u of signed) if (u.path && u.signedUrl) signedUrls.set(u.path, { url: u.signedUrl, until: now + (SIGN_SEC - SIGN_KEEP_MARGIN_SEC) * 1000 })
  const urlFor = (path?: string) => (path ? signedUrls.get(path)?.url ?? '' : '')

  const parts: Part[] = partRows.map(p => ({
    id: p.id, scoreId: p.score_id, name: p.name, fixture: urlFor(p.storage_path), pages: 0,
    difficulty: (p.difficulty ?? 3) as Part['difficulty'],
  }))
  // A book is what it was first made from; splits (images or notation) are its children, not its kind.
  const bookOf = (s: Row): Pick<Score, 'book' | 'sourcePath' | 'sourceName'> => {
    const first = sourceRows.find(r => r.score_id === s.id && !isSplit(r))
    if (first) {
      const digital = first.kind === 'musicxml'
      return { book: digital ? 'digital' : 'pdf', sourcePath: digital ? (first.storage_paths as string[])?.[0] : undefined, sourceName: digital ? first.meta?.filename ?? undefined : undefined }
    }
    if (firstPath(s)) return { book: 'digital', sourcePath: firstPath(s) }
    if (stripRows.some(r => r.score_id === s.id && r.kind === 'part_images')) return { book: 'pdf' }
    return {}
  }
  const scores: Score[] = scoreRows.map(s => ({
    id: s.id, ensembleId: s.ensemble_id ?? MY_LIBRARY,
    title: s.title || 'Untitled', composer: s.composer ?? '', work: s.work ?? '',
    status: s.status, progress: s.progress ?? undefined, failureReason: s.failure_reason ?? undefined,
    fixture: urlFor(firstPath(s)), pages: s.pages ?? 0, bars: s.bars ?? 0, tempoBpm: s.tempo_bpm ?? 0,
    key: s.key_sig ?? '', meter: s.meter ?? '', durationSec: s.duration_sec ?? 0, updatedAt: s.updated_at,
    partIds: partRows.filter(p => p.score_id === s.id).map(p => p.id), folder: s.folder || 'Scores', brief: s.brief ?? undefined,
    ...bookOf(s),
  }))

  return {
    account: { id: uid, name: myName, email: session.user.email ?? '', memberships }, ensembles, members, scores, parts,
    jobs: partJobs(jobRows), strips: partStrips(stripRows), headers: headersOf(interpRows, partRows), loaded: true,
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

/** A split is a source made from another one: strips cut from pages, or a notation file holding some instruments. */
const isSplit = (r: Row) => r.kind === 'part_images' || (r.kind === 'musicxml' && (Array.isArray(r.meta?.instruments) || !!r.meta?.slug))

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
  members: [], scores: [], parts: [], jobs: [], strips: [], headers: {}, loaded: false,
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
