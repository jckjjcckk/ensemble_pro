import { Link, NavLink, useLocation } from 'react-router'
import { ensembles, practice, type Role } from '../shared'
import { IconChevronDown, IconMoon, IconSun } from './icons'
import { ROLES, ROLE_LABEL, WORDMARK, ensembleOfScore, ensemblesOf, memberForRole } from './model'
import { useX4 } from './state'

/** The ensemble the current screen belongs to. */
function useEnsembleName(role: Role) {
  const { pathname } = useLocation()
  const scoreMatch = pathname.match(/^\/4\/score\/([^/]+)/)
  if (scoreMatch) return ensembleOfScore(scoreMatch[1])?.name ?? ''
  if (pathname.startsWith('/4/scan')) return ensembleOfScore('s-faure')?.name ?? ''
  if (pathname.startsWith('/4/practice')) return ensembleOfScore(practice.scoreId)?.name ?? ''
  const mine = ensemblesOf(memberForRole(role).id)
  return (mine[0] ?? ensembles[0])?.name ?? ''
}

export function TopBar() {
  const { role, setRole, theme, setTheme } = useX4()
  const { pathname } = useLocation()
  const ensName = useEnsembleName(role)
  const navClass = ({ isActive }: { isActive: boolean }) => (isActive ? 'active' : undefined)

  return (
    <header className="x4-top">
      <Link to="/4" className="x4-wordmark" aria-label={`${WORDMARK}, library`}>
        {WORDMARK}
      </Link>
      {ensName ? (
        <span className="x4-ens" title={ensName}>
          {ensName}
        </span>
      ) : null}
      <nav className="x4-nav" aria-label="Areas">
        <NavLink to="/4" end className={navClass}>
          Library
        </NavLink>
        <NavLink to="/4/scan" className={navClass}>
          Scan
        </NavLink>
        <NavLink to="/4/score/s-beethoven" className={() => (pathname.startsWith('/4/score') ? 'active' : undefined)}>
          Score
        </NavLink>
        <NavLink to="/4/practice" className={navClass}>
          Practice
        </NavLink>
      </nav>
      <div className="x4-top-end">
        <div className="x4-seg x4-role-seg" role="group" aria-label="Role">
          {ROLES.map(r => (
            <button key={r} type="button" aria-pressed={role === r} onClick={() => setRole(r)}>
              {ROLE_LABEL[r]}
            </button>
          ))}
        </div>
        <label className="x4-select x4-role-select">
          <span className="sr-only">Role</span>
          <select value={role} onChange={e => setRole(e.target.value as Role)}>
            {ROLES.map(r => (
              <option key={r} value={r}>
                {ROLE_LABEL[r]}
              </option>
            ))}
          </select>
          <IconChevronDown size={18} />
        </label>
        <button
          type="button"
          className="x4-iconbtn"
          aria-pressed={theme === 'dim'}
          aria-label={theme === 'dim' ? 'Dim light on. Switch to daylight.' : 'Switch to dim light'}
          title={theme === 'dim' ? 'Daylight' : 'Dim light'}
          onClick={() => setTheme(theme === 'dim' ? 'light' : 'dim')}
        >
          {theme === 'dim' ? <IconSun /> : <IconMoon />}
        </button>
      </div>
    </header>
  )
}
