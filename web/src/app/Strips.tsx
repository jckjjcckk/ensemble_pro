/** Feature 010 for a PDF book's splits (008): one strip per system, full width, stacked in reading order, snapping strip by
 *  strip. The `part_images` source lists the crops; the images come from the private bucket through signed URLs. */
import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router'
import type { Score } from '../mock'
import { supabase } from '../lib/supabase'
import { Screen, useViewport } from './layout'
import { fmtDateTime, useStore } from './store'
import { AccountButton } from './Display'
import { ILibrary } from './icons'
import './parts.css'

export default function Strips({ score }: { score: Score }) {
  const vp = useViewport()
  const { stripsFor } = useStore()
  // A digital split reads on the stage with its instruments (ScoreDoc, `?split=`); strips are a PDF book's.
  const strips = stripsFor(score.id).filter(s => s.kind === 'images')
  const [search, setSearch] = useSearchParams()
  const wanted = search.get('strip')
  const strip = strips.find(s => s.id === wanted) ?? strips[0] ?? null
  const [urls, setUrls] = useState<Record<string, string>>({})

  // One batch of signed URLs per strip; a realtime reload that leaves the paths alone does not sign them again.
  const pathKey = strip?.paths.join('\n') ?? ''
  useEffect(() => {
    if (!pathKey) return
    let live = true
    supabase.storage.from('scores').createSignedUrls(pathKey.split('\n'), 3600).then(({ data }) => {
      if (live && data) setUrls(Object.fromEntries(data.flatMap(u => (u.path && u.signedUrl ? [[u.path, u.signedUrl] as const] : []))))
    })
    return () => { live = false }
  }, [pathKey])

  const systems = strip?.systems ?? []
  const capOf = (path: string) => {
    const s = systems.find(x => x.key === path)
    return s ? { page: s.page, system: s.system, bars: s.bars } : null
  }

  const header = (
    <div className="ph">
      <div className="ph-title">
        <h1>{score.title}</h1>
        <p>{strip ? `${strip.label} · ${strip.paths.length} ${strip.paths.length === 1 ? 'system' : 'systems'}` : 'Nothing split out yet'}</p>
      </div>
      <div className="grow" />
      <AccountButton />
    </div>
  )

  const dock = (
    <div className="doc-dock">
      {strips.length > 1 && (
        <div className="seg dseg strips-seg" role="radiogroup" aria-label="Instruments">
          {strips.map(s => (
            <button key={s.id} type="button" role="radio" aria-checked={s.id === strip?.id} onClick={() => setSearch({ view: 'strips', strip: s.id }, { replace: true })}>
              {s.label}{strips.filter(x => x.label === s.label).length > 1 && <span className="strip-when"> · {fmtDateTime(s.createdAt)}</span>}
            </button>
          ))}
        </div>
      )}
      <div className="grow" />
      <Link to="/" className="dbtn"><ILibrary size={20} /><span>Library</span></Link>
    </div>
  )

  return (
    <Screen header={header} dock={dock} className="is-doc">
      {strip ? (
        <div className="strips" role="list" aria-label={`${strip.label}, ${score.title}, ${strip.paths.length} systems`}>
          {strip.paths.map((p, i) => {
            const cap = capOf(p)
            return (
              <figure key={p} className="strip" role="listitem">
                {urls[p]
                  ? <img src={urls[p]} alt={cap ? `${strip.label}, page ${cap.page} system ${cap.system}` : `${strip.label}, system ${i + 1}`} loading={i < 2 ? 'eager' : 'lazy'} decoding="async" draggable={false} />
                  : <div style={{ minHeight: vp.w * 0.18 }} />}
                <figcaption className="strip-cap">
                  <span className="num">{i + 1} / {strip.paths.length}</span>
                  {cap && <span>Page <span className="num">{cap.page}</span>, system <span className="num">{cap.system}</span></span>}
                  {cap?.bars != null && <span><span className="num">{cap.bars}</span> bars</span>}
                </figcaption>
              </figure>
            )
          })}
        </div>
      ) : (
        <div className="empty">
          <p className="empty-title">Nothing split out yet</p>
          <p>Choose Split by instrument in the score's information box in the library; each split appears here as a strip.</p>
          <Link className="btn btn-line" to="/">Back to the library</Link>
        </div>
      )}
    </Screen>
  )
}
