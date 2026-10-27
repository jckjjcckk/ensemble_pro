import { lazy, Suspense } from 'react'
import { BrowserRouter, Link, Route, Routes } from 'react-router'

const explorations = [4, 5].map(n => ({
  n,
  Component: lazy(() => import(`./explorations/${n}/App.tsx`)),
}))

function Index() {
  return (
    <main className="min-h-screen bg-neutral-950 text-neutral-100 p-10">
      <h1 className="text-2xl font-semibold tracking-tight">Folio design explorations</h1>
      <p className="text-neutral-400 mt-1">Two survivors of five. 5 (Instrument) is the base; 4 (Bound) lends its type, palette and book view. Explorations 1 to 3 are archived outside the repo.</p>
      <ul className="mt-8 flex flex-col gap-2">
        {explorations.map(({ n }) => (
          <li key={n}><Link className="underline underline-offset-4 hover:text-white" to={`/${n}`}>Exploration {n}</Link></li>
        ))}
      </ul>
    </main>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <Suspense fallback={null}>
        <Routes>
          <Route path="/" element={<Index />} />
          {explorations.map(({ n, Component }) => (
            <Route key={n} path={`/${n}/*`} element={<Component />} />
          ))}
        </Routes>
      </Suspense>
    </BrowserRouter>
  )
}
