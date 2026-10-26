import { ScoreView, scores } from './shared'

export function Placeholder({ n }: { n: number }) {
  const score = scores[0]
  return (
    <div style={{ padding: 24, fontFamily: 'system-ui' }}>
      <p style={{ opacity: 0.6, marginBottom: 12 }}>Exploration {n} — not built yet. Shared fixture below.</p>
      <ScoreView src={score.fixture} zoom={0.7} />
    </div>
  )
}
