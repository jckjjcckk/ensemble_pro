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
  loaded: boolean
  reload: () => void
}

export const MY_LIBRARY = 'me'

type Row = Record<string, any>

async function load(session: Session): Promise<Omit<World, 'reload'>> {
  const uid = session.user.id
  const [mem, sc, pa, prof] = await Promise.all([
    supabase.from('members').select('id,role,part,ensemble_id,user_id,display_name,ensembles(id,name)'),
    supabase.from('scores').select('*').order('updated_at', { ascending: false }),
    supabase.from('parts').select('*').order('position'),
    supabase.from('profiles').select('display_name,email').eq('id', uid).maybeSingle(),
  ])
  const memberRows: Row[] = mem.data ?? []
  const scoreRows: Row[] = sc.data ?? []
  const partRows: Row[] = pa.data ?? []
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

  return { account: { id: uid, name: myName, email: session.user.email ?? '', memberships }, ensembles, members, scores, parts, loaded: true }
}

const empty = (uid = '', name = ''): Omit<World, 'reload'> => ({
  account: { id: uid, name, email: '', memberships: [{ ensembleId: MY_LIBRARY, role: 'owner', memberId: MY_LIBRARY }] },
  ensembles: [{ id: MY_LIBRARY, name: 'My library', kind: 'solo', members: [{ id: MY_LIBRARY, name: name || 'You', role: 'pianist', instrument: 'Piano', online: true }] }],
  members: [], scores: [], parts: [], loaded: false,
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
