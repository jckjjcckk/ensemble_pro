import { createClient } from '@supabase/supabase-js'

const url = import.meta.env.VITE_SUPABASE_URL as string | undefined
const publishableKey = import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY as string | undefined

if (!url || !publishableKey) {
  console.warn('Supabase env vars missing: copy web/.env.example to web/.env')
}

export const supabase = createClient(url ?? 'http://localhost', publishableKey ?? "publishable")
