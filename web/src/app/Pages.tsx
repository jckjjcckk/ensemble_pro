/** Open PDF: a PDF book's pages as printed (feature 010). The pages are the images the librarian rendered from the PDF
 *  (`{score_id}/pages/{n}.png`, 004) or the photographs of a camera intake (an `images` source in its page order). One
 *  page per screen in portrait, two facing pages in landscape, snapping page by page. Until the pages are rendered the
 *  PDF file itself opens in the iPad's own viewer. */
import { useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router'
import { supabase } from '../lib/supabase'
import { Screen, useViewport } from './layout'
import { DisplayButton } from './Display'
import { bookState } from './book'
import { useStore } from './store'
import { IExport, INote } from './icons'
import './groups.css'

const PAGE_FILE = /^(\d+)\.(png|jpe?g|webp)$/i

export default function Pages() {
  const { scoreId = '' } = useParams()
  const vp = useViewport()
  const { scoresById, world, jobsFor } = useStore()
  const score = scoresById[scoreId]
  const [keys, setKeys] = useState<string[] | null>(null)
  const [urls, setUrls] = useState<Record<string, string>>({})
  const [pdfUrl, setPdfUrl] = useState<string | null>(null)
  const src = score?.pageSource
  const srcKey = src ? `${src.kind}:${src.paths.join('|')}:${src.order?.join(',') ?? ''}` : ''

  // Which pages exist: the photographs in order, or the rendered pages of the PDF (listed again as reading lands).
  useEffect(() => {
    if (!score) return
    let live = true
    const run = async () => {
      if (src?.kind === 'images' && src.paths.length) {
        const order = src.order?.length ? src.order : src.paths.map((_, i) => i + 1)
        if (live) setKeys(order.map(i => src.paths[i - 1]).filter(Boolean))
        return
      }
      const { data } = await supabase.storage.from('scores').list(`${score.id}/pages`, { limit: 1000 })
      const found = (data ?? []).map(o => o.name).filter(n => PAGE_FILE.test(n))
        .sort((a, b) => parseInt(a, 10) - parseInt(b, 10)).map(n => `${score.id}/pages/${n}`)
      if (live) setKeys(found)
    }
    run().catch(() => { if (live) setKeys([]) })
    return () => { live = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [score?.id, srcKey, score?.status, score?.pages])

  // One batch of signed URLs per page set; the PDF itself is signed ahead so its link opens on the first tap.
  const keyList = keys?.join('\n') ?? ''
  useEffect(() => {
    if (!keyList) return
    let live = true
    supabase.storage.from('scores').createSignedUrls(keyList.split('\n'), 3600).then(({ data }) => {
      if (live && data) setUrls(Object.fromEntries(data.flatMap(u => (u.path && u.signedUrl ? [[u.path, u.signedUrl] as const] : []))))
    })
    return () => { live = false }
  }, [keyList])
  const pdfKey = src?.kind === 'pdf' ? src.paths[0] : undefined
  useEffect(() => {
    if (!pdfKey) return
    let live = true
    supabase.storage.from('scores').createSignedUrl(pdfKey, 3600).then(({ data }) => { if (live) setPdfUrl(data?.signedUrl ?? null) })
    return () => { live = false }
  }, [pdfKey])

  const facing = vp.w > vp.h && vp.w >= 900
  const spreads = useMemo(() => {
    const ks = keys ?? []
    if (!facing) return ks.map(k => [k])
    // Page 1 is a right-hand page, as in the printed book: it stands alone, then pairs follow.
    const out: string[][] = ks.length ? [[ks[0]]] : []
    for (let i = 1; i < ks.length; i += 2) out.push(ks.slice(i, i + 2))
    return out
  }, [keys, facing])

  if (!score) {
    return (
      <Screen header={<div className="ph"><div className="ph-title"><h1>{world.loaded ? 'This book is not in the library.' : 'Opening the book'}</h1></div></div>} dock={<div className="dock-spacer" />}>
        <div className="empty"><Link className="btn btn-line" to="/">Back to the library</Link></div>
      </Screen>
    )
  }

  const st = bookState(score, world.bookJobs, jobsFor(score.id))
  const n = keys?.length ?? 0
  const header = (
    <div className="ph">
      <div className="ph-title">
        <h1>{score.title}</h1>
        <p>{[score.composer, !n ? 'PDF' : `PDF · ${n} ${n === 1 ? 'page' : 'pages'}`].filter(Boolean).join(' · ')}</p>
      </div>
      <div className="grow" />
      <DisplayButton />
    </div>
  )
  const dock = (
    <div className="doc-dock">
      <div className="grow" />
      {pdfUrl && <a className="dbtn" href={pdfUrl} target="_blank" rel="noopener noreferrer"><IExport size={20} /><span>PDF file</span></a>}
      {st.digitalReady && <Link className="dbtn is-primary" to={`/score/${score.id}`}><INote size={20} /><span>Open Digital</span></Link>}
    </div>
  )

  return (
    <Screen header={header} dock={dock} className="is-doc">
      {n > 0 ? (
        <div className={`leaves ${facing ? 'is-facing' : ''}`} role="list" aria-label={`${score.title}, ${n} pages`}>
          {spreads.map(pair => (
            <div key={pair[0]} className="spread" role="listitem">
              {pair.map(k => {
                const i = keys!.indexOf(k)
                return (
                  <figure key={k} className="leaf">
                    {urls[k]
                      ? <img src={urls[k]} alt={`Page ${i + 1}`} loading={i < 3 ? 'eager' : 'lazy'} decoding="async" draggable={false} />
                      : <span className="leaf-wait" />}
                    <figcaption className="num">{i + 1}</figcaption>
                  </figure>
                )
              })}
            </div>
          ))}
        </div>
      ) : (
        <div className="empty">
          <p className="empty-title">{keys === null ? 'Opening the pages' : st.busy === 'reading' ? 'The pages are being prepared' : 'No pages to show yet'}</p>
          {keys !== null && <p>{st.busy === 'reading' ? 'They appear here as the librarian renders them.' : 'The rendered pages are not in the library yet.'}{pdfUrl ? ' The PDF itself opens in the iPad\'s viewer.' : ''}</p>}
          {pdfUrl && <a className="btn btn-line" href={pdfUrl} target="_blank" rel="noopener noreferrer"><IExport size={18} />Open the PDF file</a>}
        </div>
      )}
    </Screen>
  )
}
