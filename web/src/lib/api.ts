/** The FastAPI side. The browser sends the Supabase access token; the API owns every model call and every job row. */

export const apiBase = (import.meta.env.VITE_API_URL as string | undefined) ?? 'http://localhost:8000'

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function request<T>(path: string, token: string, body?: unknown): Promise<T> {
  let res: Response
  try {
    res = await fetch(`${apiBase}${path}`, {
      method: body === undefined ? 'GET' : 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: body === undefined ? undefined : JSON.stringify(body),
    })
  } catch {
    throw new ApiError(0, 'The librarian could not be reached. Check the connection and try again.')
  }
  if (!res.ok) {
    const detail = (await res.json().catch(() => ({})))?.detail
    throw new ApiError(res.status, typeof detail === 'string' ? detail : `The librarian could not do that just now (error ${res.status}). Try again in a moment.`)
  }
  return res.json() as Promise<T>
}

export async function apiHealth(): Promise<{ status: string }> {
  const res = await fetch(`${apiBase}/health`)
  if (!res.ok) throw new Error(`API ${res.status}`)
  return res.json()
}

/** A `jobs` row as the routes return it. */
export interface JobRow {
  id: string
  kind: string
  status: 'queued' | 'running' | 'done' | 'failed'
  progress: number
  score_id: string | null
  payload: Record<string, unknown>
  result: Record<string, unknown>
  error?: string | null
  created_at: string
}

/** Feature 008, Split by instrument: a selection of instruments out of a score (a PDF book's pages, or a digital book's file). `POST /scores/{id}/parts` with
 *  `{instruments: [string], pages?: [int]}`; the API queues a `part_cut` job and returns its row. */
export interface CutPartsBody { instruments: string[]; pages?: number[] }
export const cutParts = (scoreId: string, body: CutPartsBody, token: string) =>
  request<JobRow>(`/scores/${scoreId}/parts`, token, body)

/** Feature 011: answer a parked question. `POST /jobs/{id}/answer` with the answer in the shape the question's
 *  `answer_format` gives; for `choose_staves` that is `{staves: [11, 12]}` or `{staves: "absent"}`. The API queues
 *  the follow-up job (same kind, `answer` and `resume_from` set) and returns it. */
export type ChooseStavesAnswer = { staves: number[] | 'absent' }
export const answerJob = (jobId: string, answer: ChooseStavesAnswer, token: string) =>
  request<JobRow>(`/jobs/${jobId}/answer`, token, answer)

/** The words for a failed call, in the product's voice. A 404 means the route is not on this server yet. */
export function apiFailure(e: unknown, what: string): string {
  if (e instanceof ApiError) {
    if (e.status === 404) return `${what} is not available yet.`
    if (e.status === 402) return 'The reading budget is used up for now.'
    if (e.status === 403) return 'Only the owner or an admin can do this.'
    return e.message
  }
  return (e as Error)?.message ?? 'Something went wrong.'
}
