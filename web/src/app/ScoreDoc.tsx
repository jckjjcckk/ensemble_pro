/** The book routes: `/score/{id}` (a digital book's pages, or a part or split engraved on the device) and
 *  `/score/{id}/pages` (a PDF book's pages) both open the Stand; `?view=strips` reads a PDF book's split as strips. */
import { Link, useParams, useSearchParams } from 'react-router'
import Stand from './Stand'
import Strips from './Strips'
import { useStore } from './store'

export default function ScoreDoc({ pages = false }: { pages?: boolean }) {
  const { scoreId = '' } = useParams()
  const { scoresById, world } = useStore()
  const score = scoresById[scoreId]
  const [search] = useSearchParams()
  if (!score) return <Unavailable title={world.loaded ? 'This book is not on your shelf.' : 'Opening the book'} />
  if (search.get('view') === 'strips') return <Strips score={score} />   // a PDF book's split (008) reads as strips (010)
  const readable = pages ? !!score.pageSource : score.status === 'ready' && (!!score.engravings?.length || !!score.fixture)
  if (!readable) {
    const why = score.status === 'failed' ? score.failureReason
      : score.status === 'processing' ? 'Still being read. It opens here when the reading finishes.'
      : pages ? 'This book has no pages to show.' : 'The notes have not been written out yet.'
    return <Unavailable title={score.title} detail={why} />
  }
  return <Stand key={`${score.id}:${pages}`} score={score} pages={pages} />
}

function Unavailable({ title, detail }: { title: string; detail?: string }) {
  return (
    <div className="stand">
      <header className="stand-top">
        <div className="stand-left">
          <Link to="/" className="stand-back" aria-label="Back to the shelf">
            <svg aria-hidden="true" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M15 5l-7 7 7 7" /></svg>Shelf
          </Link>
        </div>
      </header>
      <main className="stand-desk">
        <div className="stand-empty">
          <p className="stand-empty-title">{title}</p>
          {detail && <p>{detail}</p>}
          <Link className="r3-btn is-card" to="/">Back to the shelf</Link>
        </div>
      </main>
    </div>
  )
}
