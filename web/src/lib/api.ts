const base = (import.meta.env.VITE_API_URL as string | undefined) ?? 'http://localhost:8000'

export async function apiHealth(): Promise<{ status: string }> {
  const res = await fetch(`${base}/health`)
  if (!res.ok) throw new Error(`API ${res.status}`)
  return res.json()
}
