/** Groups (feature 001; the `ensembles` table, "group" on screen). One raised sheet with four faces:
 *  the open group (its name, the 8-digit join code large enough to read out, the members with their parts, Leave and,
 *  for an admin, Delete, each behind one confirmation box), Create a group (a name, then the code), Join a group (the
 *  eight digits on the numeric keyboard), and, with no group open, the start: your groups, create, join.
 *  Calls the RPCs `create_ensemble`, `join_ensemble`, `leave_ensemble`, `delete_ensemble` through supabase-js; their
 *  own messages are shown as sentences. Also the book page's Share with a group sheet (`share_score`, `unshare_score`). */
import { useEffect, useState, type FormEvent } from 'react'
import type { Score } from '../mock'
import { MY_LIBRARY, createGroup, deleteGroup, joinGroup, leaveGroup, shareBook, unshareBook, type NewGroup } from './data'
import { Sheet } from './Sheet'
import { SheetHead } from './Parts'
import { useStore, type Context } from './store'
import { IChevronRight, IKeypad, IPeople, IPlusCircle } from './icons'
import './groups.css'

export type GroupFace = 'group' | 'create' | 'join' | 'start'

/** "4820 1937": the code in two groups of four, the way it is read aloud. */
export const codeWords = (code: string) => code.replace(/\D/g, '').replace(/^(\d{4})(\d{1,4})$/, '$1 $2')

export function GroupSheet({ open, face, onFace, onClose, onOpened }: {
  open: boolean
  face: GroupFace
  onFace: (f: GroupFace) => void
  onClose: () => void
  /** A group was made or joined: the library opens it once the world has it. */
  onOpened: (id: string) => void
}) {
  const { context } = useStore()
  const inGroup = context.ensemble.id !== MY_LIBRARY
  const shown: GroupFace = face === 'group' && !inGroup ? 'start' : face
  const label = shown === 'group' ? `${context.ensemble.name}, group` : shown === 'create' ? 'Create a group' : shown === 'join' ? 'Join a group' : 'Groups'
  return (
    <Sheet open={open} onClose={onClose} label={label} portal className="group-sheet">
      {shown === 'group' && <GroupFaceView context={context} onClose={onClose} />}
      {shown === 'create' && <CreateFace onClose={onClose} onOpened={onOpened} />}
      {shown === 'join' && <JoinFace onClose={onClose} onOpened={onOpened} />}
      {shown === 'start' && <StartFace onFace={onFace} onClose={onClose} onOpened={onOpened} />}
    </Sheet>
  )
}

// ---------------------------------------------------------------- the open group

function GroupFaceView({ context, onClose }: { context: Context; onClose: () => void }) {
  const { world, setContext } = useStore()
  const { ensemble, membership, persona } = context
  const admin = membership.role === 'admin'
  const code = world.groups[ensemble.id]?.joinCode
  const [confirm, setConfirm] = useState<'leave' | 'delete' | null>(null)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)
  const members = [...ensemble.members].sort((a, b) => (a.id === persona.id ? -1 : b.id === persona.id ? 1 : (a.role === 'leader' ? 0 : 1) - (b.role === 'leader' ? 0 : 1) || a.name.localeCompare(b.name)))

  const act = async () => {
    if (!confirm) return
    setBusy(true); setMsg(null)
    try {
      if (confirm === 'leave') await leaveGroup(ensemble.id)
      else await deleteGroup(ensemble.id)
      setContext(MY_LIBRARY)
      world.reload()
      onClose()
    } catch (e) {
      setMsg((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <SheetHead title={ensemble.name} sub={admin ? 'You are the admin' : persona.instrument ? `You play ${persona.instrument}` : 'You are a member'} onClose={onClose} />
      <div className="sheet-body">
        <section className="g-code" aria-label="Join code">
          <h3>Join code</h3>
          {code ? (
            <>
              <p className="g-digits num" aria-label={code.split('').join(' ')}>{codeWords(code)}</p>
              <p className="g-note">{admin ? 'Read it out. Members open Folio, choose Join a group in the library, and type these eight digits.' : 'Anyone with these eight digits can join the group.'}</p>
            </>
          ) : (
            <p className="g-note">The join code is not available on this server yet.</p>
          )}
        </section>
        <section aria-label="Members">
          <h3 className="g-h">Members <span className="num">{members.length}</span></h3>
          <ul className="g-members">
            {members.map(m => (
              <li key={m.id}>
                <span className="g-name">{m.name}{m.id === persona.id && <span className="badge is-mine">You</span>}</span>
                <span className={`g-part ${m.instrument ? '' : 'is-none'}`}>{m.instrument || 'No part yet'}</span>
                <span className="g-role">{m.role === 'leader' ? 'Admin' : ''}</span>
              </li>
            ))}
          </ul>
        </section>
      </div>
      <div className="sheet-foot">
        {confirm ? (
          <div className="g-confirm" role="alertdialog" aria-label={confirm === 'leave' ? 'Leave the group' : 'Delete the group'}>
            <p className="g-confirm-q">{confirm === 'leave' ? `Leave ${ensemble.name}?` : `Delete ${ensemble.name}?`}</p>
            <p className="g-confirm-why">
              {confirm === 'leave'
                ? 'Its books and markings leave your library. You can join again with the code.'
                : `Every member loses it, with its books, splits and markings. This cannot be undone.`}
            </p>
            {msg && <p className="sheet-msg" role="alert">{msg}</p>}
            <div className="g-confirm-acts">
              <button type="button" className="btn btn-line" disabled={busy} onClick={() => { setConfirm(null); setMsg(null) }}>Cancel</button>
              <button type="button" className="btn btn-solid is-danger" disabled={busy} onClick={act}>
                {busy ? (confirm === 'leave' ? 'Leaving' : 'Deleting') : confirm === 'leave' ? 'Leave group' : 'Delete group'}
              </button>
            </div>
          </div>
        ) : (
          <>
            <button type="button" className="btn btn-line" onClick={() => setConfirm('leave')}>Leave group</button>
            {admin && <button type="button" className="btn btn-line is-danger" onClick={() => setConfirm('delete')}>Delete group</button>}
          </>
        )}
      </div>
    </>
  )
}

// ---------------------------------------------------------------- create

function CreateFace({ onClose, onOpened }: { onClose: () => void; onOpened: (id: string) => void }) {
  const { world } = useStore()
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)
  const [made, setMade] = useState<NewGroup | null>(null)

  const submit = async (e?: FormEvent) => {
    e?.preventDefault()
    const n = name.trim()
    if (!n || busy) return
    setBusy(true); setMsg(null)
    try {
      const g = await createGroup(n)
      setMade(g)
      world.reload()
      onOpened(g.id)
    } catch (err) {
      setMsg((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  if (made) {
    return (
      <>
        <SheetHead title={made.name} sub="The group is made. You are its admin." onClose={onClose} />
        <div className="sheet-body">
          <section className="g-code" aria-label="Join code">
            <h3>Join code</h3>
            {made.joinCode
              ? <p className="g-digits num" aria-label={made.joinCode.split('').join(' ')}>{codeWords(made.joinCode)}</p>
              : <p className="g-note">The join code appears in the group once the server has made it.</p>}
            <p className="g-note">Read it out. Members open Folio, choose Join a group in the library, and type these eight digits.</p>
          </section>
        </div>
        <div className="sheet-foot"><button type="button" className="btn btn-solid" onClick={onClose}>Done</button></div>
      </>
    )
  }

  return (
    <>
      <SheetHead title="Create a group" sub="A quartet, a choir, an orchestra: everyone who reads the same books." onClose={onClose} />
      <form className="sheet-body" onSubmit={submit}>
        <label className="field">
          <span>Name</span>
          <input value={name} onChange={e => setName(e.target.value)} placeholder="e.g. Hart House Chamber Players" autoCapitalize="words" autoComplete="off" enterKeyHint="go" maxLength={80} />
        </label>
        <p className="g-note">You become its admin. The group gets an eight-digit code for the others to join with.</p>
      </form>
      <div className="sheet-foot">
        {msg && <p className="sheet-msg" role="alert">{msg}</p>}
        <button type="button" className="btn btn-line" onClick={onClose}>Cancel</button>
        <button type="button" className="btn btn-solid" disabled={!name.trim() || busy} onClick={() => submit()}>{busy ? 'Creating' : 'Create group'}</button>
      </div>
    </>
  )
}

// ---------------------------------------------------------------- join

function JoinFace({ onClose, onOpened }: { onClose: () => void; onOpened: (id: string) => void }) {
  const { world } = useStore()
  const [digits, setDigits] = useState('')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)
  const ready = digits.length === 8

  const submit = async (e?: FormEvent) => {
    e?.preventDefault()
    if (!ready || busy) return
    setBusy(true); setMsg(null)
    try {
      const id = await joinGroup(digits)
      world.reload()
      onOpened(id)
      onClose()
    } catch (err) {
      setMsg((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <SheetHead title="Join a group" sub="The admin reads out the group's eight-digit code." onClose={onClose} />
      <form className="sheet-body" onSubmit={submit}>
        <label className="field g-code-field">
          <span>Join code</span>
          <input
            value={codeWords(digits)} onChange={e => { setDigits(e.target.value.replace(/\D/g, '').slice(0, 8)); setMsg(null) }}
            inputMode="numeric" pattern="[0-9 ]*" autoComplete="off" enterKeyHint="go" placeholder="0000 0000" aria-describedby="g-join-why"
            className="num"
          />
        </label>
        <p id="g-join-why" className="g-note">You join as a member. The admin gives you your part.</p>
      </form>
      <div className="sheet-foot">
        {msg && <p className="sheet-msg" role="alert">{msg}</p>}
        <button type="button" className="btn btn-line" onClick={onClose}>Cancel</button>
        <button type="button" className="btn btn-solid" disabled={!ready || busy} onClick={() => submit()}>{busy ? 'Joining' : 'Join group'}</button>
      </div>
    </>
  )
}

// ---------------------------------------------------------------- share a book with a group

/** "Share with a group", from a personal book's page: the owner's groups, one switch each. Turning one on shares the
 *  book there at once (`share_score`); turning it off asks once (`unshare_score`). By reference: the book stays in
 *  the owner's library, nothing is copied, and the owner's own marks stay private. */
export function ShareSheet({ score, open, onClose }: { score: Score | null; open: boolean; onClose: () => void }) {
  return (
    <Sheet open={open} onClose={onClose} label="Share with a group" portal className="group-sheet share-sheet">
      {score && <ShareFace score={score} onClose={onClose} />}
    </Sheet>
  )
}

function ShareFace({ score, onClose }: { score: Score; onClose: () => void }) {
  const { contexts, world, sharesFor } = useStore()
  const groups = contexts.filter(c => c.ensemble.id !== MY_LIBRARY)
  const shared = new Set(sharesFor(score.id).map(s => s.ensembleId))
  // What a tap asked for, until the reloaded world says the same.
  const [wanted, setWanted] = useState<Record<string, boolean>>({})
  const [busy, setBusy] = useState<string | null>(null)
  const [confirm, setConfirm] = useState<string | null>(null)
  const [msg, setMsg] = useState<string | null>(null)
  const sharedKey = [...shared].sort().join()
  useEffect(() => {
    setWanted(w => Object.fromEntries(Object.entries(w).filter(([id, on]) => on !== sharedKey.split(',').includes(id))))
  }, [sharedKey])
  const isOn = (id: string) => wanted[id] ?? shared.has(id)
  const confirming = groups.find(c => c.ensemble.id === confirm)

  const share = async (id: string) => {
    setBusy(id); setMsg(null)
    try {
      await shareBook(score.id, id)
      setWanted(w => ({ ...w, [id]: true }))
      world.reload()
    } catch (e) {
      setMsg((e as Error).message)
    } finally {
      setBusy(null)
    }
  }
  const unshare = async () => {
    if (!confirm) return
    const id = confirm
    setBusy(id); setMsg(null)
    try {
      await unshareBook(score.id, id)
      setWanted(w => ({ ...w, [id]: false }))
      setConfirm(null)
      world.reload()
    } catch (e) {
      setMsg((e as Error).message)
    } finally {
      setBusy(null)
    }
  }
  const tap = (id: string) => {
    if (busy) return
    if (isOn(id)) { setConfirm(id); setMsg(null) }
    else { setConfirm(null); void share(id) }
  }

  return (
    <>
      <SheetHead title="Share with a group" sub={score.title} onClose={onClose} />
      <div className="sheet-body">
        <p className="g-note">The group reads this book from your library. Nothing is copied, and your own marks stay yours: the group sees only what is marked for it.</p>
        {groups.length > 0 ? (
          <ul className="share-list" aria-label="Your groups">
            {groups.map(c => {
              const id = c.ensemble.id
              const on = isOn(id)
              return (
                <li key={id}>
                  <button
                    type="button" role="switch" aria-checked={on} aria-busy={busy === id} disabled={!!busy && busy !== id}
                    className="share-row" onClick={() => tap(id)}
                  >
                    <IPeople size={20} />
                    <span className="share-name">
                      <b>{c.ensemble.name}</b>
                      <span>{busy === id ? (on ? 'Stopping' : 'Sharing') : on ? 'Reads this book' : `${c.ensemble.members.length} ${c.ensemble.members.length === 1 ? 'person' : 'people'}`}</span>
                    </span>
                    <span className={`switch ${on ? 'is-on' : ''}`} aria-hidden="true"><span /></span>
                  </button>
                </li>
              )
            })}
          </ul>
        ) : (
          <p className="g-note">You are not in a group yet. Create or join one from the library, then share books with it here.</p>
        )}
      </div>
      <div className="sheet-foot">
        {confirming ? (
          <div className="g-confirm" role="alertdialog" aria-label={`Stop sharing with ${confirming.ensemble.name}`}>
            <p className="g-confirm-q">Stop sharing with {confirming.ensemble.name}?</p>
            <p className="g-confirm-why">The group stops seeing this book at once. What its members marked on it is kept, and comes back if you share it again.</p>
            {msg && <p className="sheet-msg" role="alert">{msg}</p>}
            <div className="g-confirm-acts">
              <button type="button" className="btn btn-line" disabled={!!busy} onClick={() => { setConfirm(null); setMsg(null) }}>Cancel</button>
              <button type="button" className="btn btn-solid is-danger" disabled={!!busy} onClick={unshare}>{busy ? 'Stopping' : 'Stop sharing'}</button>
            </div>
          </div>
        ) : (
          <>
            {msg && <p className="sheet-msg" role="alert">{msg}</p>}
            <button type="button" className="btn btn-solid" onClick={onClose}>Done</button>
          </>
        )}
      </div>
    </>
  )
}

// ---------------------------------------------------------------- no group open: yours, create, join

function StartFace({ onFace, onClose, onOpened }: { onFace: (f: GroupFace) => void; onClose: () => void; onOpened: (id: string) => void }) {
  const { contexts } = useStore()
  const groups = contexts.filter(c => c.ensemble.id !== MY_LIBRARY)
  return (
    <>
      <SheetHead title="Groups" sub={groups.length ? 'Open one, or start another.' : 'Read the same books as the people you play with.'} onClose={onClose} />
      <div className="sheet-body">
        {groups.length > 0 && (
          <ul className="g-list" aria-label="Your groups">
            {groups.map(c => (
              <li key={c.ensemble.id}>
                <button type="button" className="g-open" onClick={() => { onOpened(c.ensemble.id); onFace('group') }}>
                  <IPeople size={20} />
                  <span className="g-open-name">{c.ensemble.name}</span>
                  <span className="g-open-role">{c.membership.role === 'admin' ? 'Admin' : `${c.ensemble.members.length} people`}</span>
                  <IChevronRight size={18} />
                </button>
              </li>
            ))}
          </ul>
        )}
        <div className="g-start">
          <button type="button" className="g-choice" onClick={() => onFace('create')}>
            <IPlusCircle size={22} />
            <span><b>Create a group</b><span>Name it; it gets a code for the others.</span></span>
          </button>
          <button type="button" className="g-choice" onClick={() => onFace('join')}>
            <IKeypad size={22} />
            <span><b>Join a group</b><span>Type the eight digits the admin reads out.</span></span>
          </button>
        </div>
      </div>
    </>
  )
}
