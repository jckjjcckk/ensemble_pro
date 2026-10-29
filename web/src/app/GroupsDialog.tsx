/** The Groups sheet (R3, docs/design/r3/R2_GroupSheet): a centred dialog over the dimmed shelf. One group open as a card
 *  (its join code large enough to read out, with Copy; its members with their roles; Delete group, or Leave group for a
 *  member, behind one message box), the other groups as rows that open in its place, Join with a code, and Create a
 *  group. The RPCs are the existing ones (`create_ensemble`, `join_ensemble`, `leave_ensemble`, `delete_ensemble`);
 *  their own messages are shown as sentences. */
import { useEffect, useState, type FormEvent } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { MY_LIBRARY, createGroup, deleteGroup, joinGroup, leaveGroup } from './data'
import { Confirm, Dialog } from './Surfaces'
import { ICopy, useCopy } from './r3bits'
import { codeWords } from './Groups'
import { EASE_OUT, SPRING_LAYOUT } from './Sheet'
import { initials, useStore, type Context } from './store'
import type { Member } from '../mock'

export { codeWords }

/** A face colour per member, in the group's own order; the account itself is drawn in ink. */
export const FACE_COLORS = ['#5B86C8', '#C8905B', '#7A9A6B', '#9A6B8F', '#5E9A9A', '#B0874F', '#7D7DB8']
export function faceColor(ensembleMembers: Member[], m: Member): string {
  const i = ensembleMembers.findIndex(x => x.id === m.id)
  return FACE_COLORS[(i < 0 ? 0 : i) % FACE_COLORS.length]
}

const IChev = () => <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M9 5l7 7-7 7" /></svg>
const IPlus = () => <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"><path d="M12 5v14M5 12h14" /></svg>

export function GroupsDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  return (
    <Dialog open={open} onClose={onClose} label="Groups" className="groups-dialog">
      <div className="gd-head">
        <h2>Groups</h2>
        <button type="button" className="r3-btn is-quiet is-strong" onClick={onClose}>Done</button>
      </div>
      <GroupsBody onClose={onClose} />
    </Dialog>
  )
}

function GroupsBody({ onClose }: { onClose: () => void }) {
  const { contexts, world, context, setContext } = useStore()
  const groups = contexts.filter(c => c.ensemble.id !== MY_LIBRARY)
  const first = (context.ensemble.id !== MY_LIBRARY ? context.ensemble.id : null) ?? groups.find(g => g.membership.role === 'admin')?.ensemble.id ?? groups[0]?.ensemble.id ?? null
  const [openId, setOpenId] = useState<string | null>(first)
  const [pending, setPending] = useState<string | null>(null)
  const shown = groups.find(g => g.ensemble.id === openId) ?? groups[0]
  const others = groups.filter(g => g !== shown)
  const sharedN = (id: string) => new Set([...world.shares.filter(x => x.ensembleId === id).map(x => x.scoreId), ...world.scores.filter(s => s.ensembleId === id && !world.owners[s.id]).map(s => s.id)]).size

  // A group made or joined opens as soon as the world has it.
  useEffect(() => {
    if (pending && groups.some(g => g.ensemble.id === pending)) { setOpenId(pending); setContext(pending); setPending(null) }
  }, [pending, groups, setContext])

  return (
    <div className="gd-body r3-scroll">
      <AnimatePresence mode="popLayout" initial={false}>
        {shown && <GroupCard key={shown.ensemble.id} context={shown} shared={sharedN(shown.ensemble.id)} onGone={() => { setOpenId(null); setContext(MY_LIBRARY) }} />}
      </AnimatePresence>

      {others.map(c => (
        <motion.button key={c.ensemble.id} layout="position" transition={SPRING_LAYOUT} type="button" className="gd-row" onClick={() => setOpenId(c.ensemble.id)}>
          <span className="gd-row-text"><span className="gd-row-name">{c.ensemble.name}</span><span className="gd-row-meta">{metaOf(c)} · {sharedN(c.ensemble.id)} shared {sharedN(c.ensemble.id) === 1 ? 'book' : 'books'}</span></span>
          <IChev />
        </motion.button>
      ))}

      <JoinForm onJoined={id => { world.reload(); setPending(id) }} />
      <CreateForm onMade={id => { world.reload(); setPending(id) }} />
      {!groups.length && <button type="button" className="sr-only" onClick={onClose}>Close</button>}
    </div>
  )
}

const metaOf = (c: Context) => {
  const n = c.ensemble.members.length
  const admin = c.membership.role === 'admin'
  const leader = c.ensemble.members.find(m => m.role === 'leader' && m.id !== c.persona.id)
  return `${n} ${n === 1 ? 'member' : 'members'} · ${admin ? 'you are admin' : leader ? `${leader.name.split(' ')[0]} is admin` : 'you are a member'}`
}

function GroupCard({ context: c, shared, onGone }: { context: Context; shared: number; onGone: () => void }) {
  const { world } = useStore()
  const [copied, copy] = useCopy()
  const g = c.ensemble
  const admin = c.membership.role === 'admin'
  const code = world.groups[g.id]?.joinCode
  const [confirm, setConfirm] = useState(false)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)
  const members = [...g.members].sort((a, b) => (a.id === c.persona.id ? -1 : b.id === c.persona.id ? 1 : (a.role === 'leader' ? 0 : 1) - (b.role === 'leader' ? 0 : 1)))

  const act = async () => {
    setBusy(true); setMsg(null)
    try {
      await (admin ? deleteGroup : leaveGroup)(g.id)
      world.reload()
      onGone()
    } catch (e) {
      setMsg((e as Error).message)
      setBusy(false)
    }
  }

  return (
    <motion.section
      className="gd-card" aria-label={g.name} layout="position"
      initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -4, transition: { duration: 0.12 } }}
      transition={{ duration: 0.22, ease: EASE_OUT }}
    >
      <div className="gd-card-head">
        <span className="gd-card-name"><b>{g.name}</b><span>{metaOf(c)}</span></span>
        <span className="gd-card-books">{shared} shared {shared === 1 ? 'book' : 'books'}</span>
      </div>
      <div className="gd-code">
        <span className="gd-code-text">
          <span className="r3-label">Join code</span>
          {code
            ? <span className="gd-digits" aria-label={code.split('').join(' ')}>{codeWords(code)}</span>
            : <span className="gd-code-none">Not available on this server yet</span>}
        </span>
        {code && (
          <button type="button" className="r3-btn is-card" aria-label={copied === g.id ? 'Join code copied' : 'Copy the join code'} onClick={() => copy(code, g.id)}>
            <ICopy size={16} />{copied === g.id ? 'Copied' : 'Copy'}
          </button>
        )}
      </div>
      <ul className="gd-members" aria-label="Members">
        {members.map(m => {
          const me = m.id === c.persona.id
          return (
            <li key={m.id}>
              <span className="r3-face" style={{ background: me ? 'var(--solid)' : faceColor(g.members, m), color: me ? 'var(--on-solid)' : '#fff' }} aria-hidden="true">{initials(m.name || m.instrument || '?')}</span>
              <span className="gd-member-name">{m.name}{me ? ' (you)' : ''}</span>
              <span className="gd-member-role">{m.role === 'leader' ? 'admin' : m.instrument || 'member'}</span>
            </li>
          )
        })}
      </ul>
      <AnimatePresence initial={false} mode="wait">
        {confirm ? (
          <Confirm
            key="c"
            question={admin ? `Delete ${g.name}?` : `Leave ${g.name}?`}
            why={admin ? 'Every member loses it, with its books, splits and markings. Books shared into it stay in their owners’ libraries. This cannot be undone.' : 'Its books and markings leave your shelf. You can join again with the code.'}
            act={admin ? 'Delete group' : 'Leave group'} busyWord={admin ? 'Deleting' : 'Leaving'} busy={busy} msg={msg}
            onCancel={() => { setConfirm(false); setMsg(null) }} onAct={() => void act()}
          />
        ) : (
          <motion.button key="b" type="button" className="r3-btn is-quiet is-red gd-delete" onClick={() => setConfirm(true)} initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
            {admin ? 'Delete group…' : 'Leave group…'}
          </motion.button>
        )}
      </AnimatePresence>
    </motion.section>
  )
}

function JoinForm({ onJoined }: { onJoined: (id: string) => void }) {
  const [digits, setDigits] = useState('')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)
  const ready = digits.length === 8
  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (!ready || busy) return
    setBusy(true); setMsg(null)
    try { const id = await joinGroup(digits); setDigits(''); onJoined(id) } catch (err) { setMsg((err as Error).message) } finally { setBusy(false) }
  }
  return (
    <form className="gd-join" onSubmit={submit}>
      <label htmlFor="gd-join-code" className="r3-label">Join with a code</label>
      <div className="gd-join-row">
        <input
          id="gd-join-code" value={codeWords(digits)} onChange={e => { setDigits(e.target.value.replace(/\D/g, '').slice(0, 8)); setMsg(null) }}
          inputMode="numeric" pattern="[0-9 ]*" autoComplete="off" enterKeyHint="go" placeholder="0000 0000" aria-label="8-digit join code" aria-describedby="gd-join-why"
        />
        <button type="submit" className="r3-btn is-solid is-tall" disabled={!ready || busy}>{busy ? 'Joining' : 'Join'}</button>
      </div>
      {msg ? <p className="r3-msg" role="alert">{msg}</p> : <span id="gd-join-why" className="gd-hint">8 digits, from whoever runs the group.</span>}
    </form>
  )
}

function CreateForm({ onMade }: { onMade: (id: string) => void }) {
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)
  const submit = async (e: FormEvent) => {
    e.preventDefault()
    const n = name.trim()
    if (!n || busy) return
    setBusy(true); setMsg(null)
    try { const g = await createGroup(n); setName(''); setOpen(false); onMade(g.id) } catch (err) { setMsg((err as Error).message) } finally { setBusy(false) }
  }
  return (
    <div className="gd-create">
      <AnimatePresence initial={false} mode="wait">
        {open ? (
          <motion.form key="f" className="gd-create-form" onSubmit={submit} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} transition={{ duration: 0.18, ease: EASE_OUT }}>
            <label htmlFor="gd-new-name" className="r3-label">New group</label>
            <div className="gd-join-row">
              <input id="gd-new-name" value={name} onChange={e => setName(e.target.value)} placeholder="e.g. Hart House Chamber Players" autoCapitalize="words" autoComplete="off" enterKeyHint="go" maxLength={80} autoFocus className="is-text" />
              <button type="button" className="r3-btn is-line is-tall" onClick={() => { setOpen(false); setMsg(null) }}>Cancel</button>
              <button type="submit" className="r3-btn is-solid is-tall" disabled={!name.trim() || busy}>{busy ? 'Creating' : 'Create'}</button>
            </div>
            {msg ? <p className="r3-msg" role="alert">{msg}</p> : <span className="gd-hint">You become its admin; it gets an eight-digit code for the others.</span>}
          </motion.form>
        ) : (
          <motion.button key="b" type="button" className="r3-btn is-line is-tall gd-create-btn" onClick={() => setOpen(true)} initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
            <IPlus />Create a group
          </motion.button>
        )}
      </AnimatePresence>
    </div>
  )
}
