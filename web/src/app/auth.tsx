import { createContext, useContext, useEffect, useState, type FormEvent, type ReactNode } from 'react'
import type { Session } from '@supabase/supabase-js'
import { supabase } from '../lib/supabase'
import { WORDMARK } from './store'

interface Auth { session: Session | null; ready: boolean; signOut: () => Promise<void> }
const Ctx = createContext<Auth>({ session: null, ready: false, signOut: async () => {} })

/** Holds the Supabase session. Children render only once the stored session has been read. */
export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null)
  const [ready, setReady] = useState(false)
  useEffect(() => {
    supabase.auth.getSession().then(({ data }) => { setSession(data.session); setReady(true) })
    const { data: sub } = supabase.auth.onAuthStateChange((_e, s) => setSession(s))
    return () => sub.subscription.unsubscribe()
  }, [])
  const signOut = async () => { await supabase.auth.signOut() }
  return <Ctx.Provider value={{ session, ready, signOut }}>{children}</Ctx.Provider>
}

export const useAuth = () => useContext(Ctx)

/** Email and password, nothing else: accounts are created by hand, so there is no sign-up and no reset here. */
export function SignIn() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true); setError(null)
    const { error } = await supabase.auth.signInWithPassword({ email: email.trim(), password })
    setBusy(false)
    if (error) setError(error.message === 'Invalid login credentials' ? 'That email and password do not match an account.' : error.message)
  }

  return (
    <div className="signin">
      <form className="signin-card" onSubmit={submit}>
        <div className="signin-mark" aria-hidden="true">
          <svg width="22" height="22" viewBox="0 0 18 18"><path d="M3 3.5v11M15 3.5v11M3 3.5h2.6M3 14.5h2.6M15 3.5h-2.6M15 14.5h-2.6" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" /></svg>
          <span>{WORDMARK}</span>
        </div>
        <h1>Sign in</h1>
        <p className="signin-sub">One score for the whole ensemble.</p>
        <label className="field">
          <span>Email</span>
          <input type="email" name="email" autoComplete="username" inputMode="email" autoCapitalize="none" value={email} onChange={e => setEmail(e.target.value)} required />
        </label>
        <label className="field">
          <span>Password</span>
          <input type="password" name="password" autoComplete="current-password" value={password} onChange={e => setPassword(e.target.value)} required />
        </label>
        {error && <p className="field-error" role="alert">{error}</p>}
        <button type="submit" className="btn btn-solid signin-go" disabled={busy}>{busy ? 'Signing in' : 'Sign in'}</button>
        <p className="signin-note">Accounts are made by the ensemble's admin. Ask them if you need one.</p>
      </form>
    </div>
  )
}
