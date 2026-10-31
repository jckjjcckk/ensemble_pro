/** "Remembered from page N" in the reader's questions (011; 006 agentic memory rule, follow-up 2026-10-31). The book
 *  keeps what earlier pages and the admin's answers settled (`scores.label_memory`), and a question carries what that
 *  memory placed on the line or knows for the page's shape, so the admin sees why only part of it is asked. */

/** One wanted instrument the memory placed on a staves question's line. */
export interface Placed { instrument: string; page: number | null; source: 'human' | 'model'; how: 'label' | 'layout'; label?: string | null }

/** A whole layout the memory holds for a staff count, offered on the parts question. */
export interface Layout { staves: number; parts: string[]; staves_per_part: number[]; page: number | null; source: 'human' | 'model' }

/** "page 2 (your answer)", "page 1 (its label read there)", "page 3": where a remembered value came from. */
export function fromPage(page: number | null | undefined, source: 'human' | 'model', how: 'label' | 'layout' = 'layout', label?: string | null): string {
  const where = page ? `page ${page}` : 'an earlier page'
  if (source === 'human') return `${where} (your answer)`
  return how === 'label' && label ? `${where} (“${label}” read there)` : where
}

/** "Violino I, remembered from page 2 (your answer)" for each remembered instrument; '' when nothing was. */
export function rememberedLine(places: Placed[] | null | undefined): string {
  return (places ?? []).map(p => `${p.instrument}, remembered from ${fromPage(p.page, p.source, p.how, p.label)}`).join('; ')
}

/** The memory's layout for a system of this many staves, if the question carries one that fits. */
export function layoutFor(layouts: Layout[] | null | undefined, staves: number): Layout | null {
  const lay = (layouts ?? []).find(l => l.staves === staves)
  if (!lay || lay.parts.length !== lay.staves_per_part.length || lay.staves_per_part.reduce((a, b) => a + b, 0) !== staves) return null
  return lay
}

/** One name per staff from a remembered layout. */
export function layoutLabels(lay: Layout): string[] {
  return lay.parts.flatMap((p, i) => Array<string>(lay.staves_per_part[i]).fill(p))
}
