import { useEffect, useState } from 'react'
import { apiHealth } from './lib/api'

export default function App() {
  const [api, setApi] = useState<'checking' | 'ok' | 'down'>('checking')

  useEffect(() => {
    apiHealth()
      .then(() => setApi('ok'))
      .catch(() => setApi('down'))
  }, [])

  return (
    <main className="min-h-screen bg-neutral-950 text-neutral-100 flex flex-col items-center justify-center gap-4 p-8">
      <h1 className="text-4xl font-semibold tracking-tight">Muse</h1>
      <p className="text-neutral-400">AI librarian for ensembles</p>
      <p className="text-sm">
        API:{' '}
        <span className={api === 'ok' ? 'text-emerald-400' : api === 'down' ? 'text-rose-400' : 'text-neutral-500'}>
          {api}
        </span>
      </p>
    </main>
  )
}
