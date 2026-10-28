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
  /** Finished cut parts: one `part_images` source each, strips in reading order (008, 010). */
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
  instruments: string[]
  /** "Piano", or "Soprano & Alto" for a selection of parts. */
  label: string
  /** Bucket-relative keys of the cut system images, in reading order. */
  paths: string[]
  systems: { page: number; system: number; staves: number[] | 'absent'; key: string | null; bars: number | null }[]
  createdAt: string
}

export const partLabel = (instruments: string[]) => instruments.join(' & ')

export const MY_LIBRARY = 'me'

type Row = Record<string, any>

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
    supabase.from('sources').select('id,score_id,storage_paths,meta,created_at').eq('kind', 'part_images').order('created_at'),
    supabase.from('interpretations').select('id,score_id,engine,status,created_at,header:params->state->header->instruments,summary_header:summary->header->instruments,summary_parts:summary->parts').order('created_at'),
  ])
  const memberRows: Row[] = mem.data ?? []
  const scoreRows: Row[] = sc.data ?? []
  const partRows: Row[] = pa.data ?? []
  const jobRows: Row[] = jb.data ?? []
  const stripRows: Row[] = src.data ?? []
  const interpRows: Row[] = itp.data ?? []
  const myName = prof.data?.display_name || session.user.email?.split('@')[0] || 'You'

  const members: Member[] = memberRows.map(m => ({
    id: m.id, name: m.display_name || 'Member', role: m.role === 'admin' ? 'leader' : 'player',
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
  const ready = scoreRows.filter(s => s.status === 'ready')
  const firstPath = (s: Row) => partRows.find(p => p.score_id === s.id && p.storage_path)?.storage_path as string | undefined
  const paths = [...new Set(ready.map(firstPath).filter((p): p is string => !!p))]
  const signed = paths.length ? (await supabase.storage.from('scores').createSignedUrls(paths, 3600)).data ?? [] : []
  const urlFor = (path?: string) => (path ? signed.find(u => u.path === path)?.signedUrl ?? '' : '')

  const parts: Part[] = partRows.map(p => ({
    id: p.id, scoreId: p.score_id, name: p.name, fixture: urlFor(p.storage_path), pages: 0,
    difficulty: (p.difficulty ?? 3) as Part['difficulty'],
  }))
  const scores: Score[] = scoreRows.map(s => ({
    id: s.id, ensembleId: s.ensemble_id ?? MY_LIBRARY,
    title: s.title || 'Untitled', composer: s.composer ?? '', work: s.work ?? '',
    status: s.status, progress: s.progress ?? undefined, failureReason: s.failure_reason ?? undefined,
    fixture: urlFor(firstPath(s)), pages: s.pages ?? 0, bars: s.bars ?? 0, tempoBpm: s.tempo_bpm ?? 0,
    key: s.key_sig ?? '', meter: s.meter ?? '', durationSec: s.duration_sec ?? 0, updatedAt: s.updated_at,
    partIds: partRows.filter(p => p.score_id === s.id).map(p => p.id), folder: s.folder || 'Scores', brief: s.brief ?? undefined,
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
        note: r.note ?? undefined, log, error: r.error ?? (status === 'failed' && r.status === 'done' ? 'The run stopped without cutting anything.' : undefined),
        question: parked ? r.question : undefined, questionPayload: parked ? q! : undefined,
        sourceId: r.source_id ?? undefined, systemsCut: r.systems_cut ?? undefined, createdAt: r.created_at,
      }
    })
    .reverse()
}

function partStrips(rows: Row[]): PartStrip[] {
  return rows.map(r => {
    const instruments = instrumentsOf(r.meta)
    return {
      id: r.id, scoreId: r.score_id, instruments, label: partLabel(instruments.length ? instruments : ['Part']),
      paths: (r.storage_paths as string[]) ?? [], systems: (r.meta?.systems as PartStrip['systems']) ?? [], createdAt: r.created_at,
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
  if (error || !row) throw new Error(error?.message ?? 'Could not create the score')
  const key = `${row.id}/source.musicxml`
  const up = await supabase.storage.from('scores').upload(key, file, { contentType: 'application/vnd.recordare.musicxml+xml', upsert: true })
  if (up.error) throw new Error(up.error.message)
  const res = await fetch(`${apiBase}/scores/${row.id}/import`, {
    method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` }, body: JSON.stringify({ path: key, filename: file.name }),
  })
  if (!res.ok) throw new Error((await res.json().catch(() => ({})))?.detail ?? `API ${res.status}`)
}
