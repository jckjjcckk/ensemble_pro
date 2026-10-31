# 002 Score upload and storage

Status: working for MusicXML (Path A); working on the local stack for a PDF that reads itself (API side, 2026-10-28; the browser half is not built); prototype for photographed pages | Meta model: none here (rendering is PyMuPDF; reading the pages is Muse Spark 1.3 in 004).

## Purpose

Get a score into Folio: a MusicXML file (Path A, full product at once) or a PDF / photographed pages (Path
B, the original pages are what people read). Store the file in the private bucket, record a `sources` row,
keep the page order, and hand off to a job. OMR is never a prerequisite (000).

## What exists

- `sources` row per upload: `kind` pdf | images | musicxml (migration `20261028090000_part_images_source.sql`
  widens it to `part_images` for feature 008; **applied to the local stack 2026-10-28, not hosted**), `storage_paths` as object keys
  inside the `scores` bucket, always `{score_id}/...` (the storage policies read the score id from the first
  folder), `page_order` = committed reading order (1-based indexes into the upload set), `page_count`, `meta`.
- Pages: the app thread rasterises in the browser (pdf.js) and uploads `{score_id}/pages/{n}.png`; a handler
  reads pages in `page_order`. The browser rasterise and upload are **not built**: `web/src/app/Scan.tsx` is
  the mock draft (eight thumbnails, drag to reorder, delete, retake, two warnings, one Process action;
  processing never starts until the order is committed). Pages are seeded today with
  `uv run -m app.librarian.run seed --pages <png...>` (feature 004).
- `POST /scores/{score_id}/import` (`api/app/routes/scores.py`): the browser creates the score row and
  uploads through RLS; the route records the source and queues the `import_musicxml` job. Budget checked by
  the route (`BudgetedUser`).
- `import_musicxml` handler (`api/app/librarian/import_musicxml.py`, music21, no model): parts with
  disambiguated names (two "Violin" become Violin I / Violin II, "Violoncello" becomes Cello; piano exports
  are one part, commit 2c2a6b9), one stable `measures` row per number (313 for Op. 18/1), interpretation
  v(n+1) with engine `musicxml`, score facts (F major, 3/4, 132 bpm, 426 s; key mode by analysis), title
  from the file when the MusicXML has none. Difficulty is a density heuristic (too high: 5/4/4/5 for Op. 18)
  until the Spark `brief` job replaces it. Since 2026-10-30 (013 prompt v4e) the import also reads the book's
  landmarks (`landmarks.from_musicxml`, no model): key and meter changes after the first, printed tempo words and
  metronome changes (music21's own name for a bare metronome mark is skipped), double bars and repeat barlines as
  "between bars N and N+1", 1st/2nd-time bars, segno, coda, To Coda, Fine, D.C./D.S., section titles, rehearsal
  marks; dolce, cresc. and the like are not places. They go to `scores.landmarks` with source `musicxml` (Convert
  to Digital does the same and replaces the page reading's). Op. 18/1 i: one, the exposition's end repeat between
  bars 114 and 115 (the file prints a metronome mark and no tempo word). Tests: `test_landmarks_musicxml.py`.
- Web: `importMusicXml` in `data.tsx` creates the row, uploads, calls the API; Import MusicXML in the dock for
  admins and owners; signed URLs for score files.
- `api/scripts/smoke_import.py` on the local stack: upload through RLS, job done in 3 s, reimport keeps measure
  ids, violin2 sees four parts.
- Storage key fix 2026-10-27 (commit 32ce9e5): keys are bucket-relative, per the contract.
- Fixtures: see 000 (PDFs in `api/fixtures/pdf/`, MusicXML in `web/public/fixtures/`).

## A PDF that reads itself (2026-10-28)

CK: a PDF is read automatically on import, with no page-ordering step and no confirmation; the musician sees a
busy state and later a coloured dot. The scan path (`images` source, `page_order` committed by the scan screen)
is unchanged.

The browser's contract, the same route as MusicXML:

1. Insert the `scores` row through RLS (`status: 'uploaded'`, owner or ensemble, `created_by`), as `importMusicXml` does.
2. Upload the file to the bucket-relative key `{score_id}/source.pdf` (`contentType: 'application/pdf'`).
3. Insert a `sources` row through RLS: `{score_id, kind: 'pdf', storage_paths: [key], meta: {filename}, created_by}`.
   Leave `page_order` and `page_count` null; the job fills them. (If the browser skips this step the route
   records the row itself.)
4. `POST /scores/{score_id}/import` with `{path: key, filename}` (optional `kind: 'pdf' | 'musicxml'`; a key
   ending `.pdf` is a PDF). Returns `{source_id, job_id, kind: 'import_pdf'}`. Errors: 400 path outside the
   score's folder, 402 budget spent, 403 not owner or admin, 404 no such score, 409 "This score is already
   being read" (an `import_pdf` or `process_pages` job for the score is queued or running).
5. Watch `scores` by Realtime: `status` goes `processing` (set by the route, `progress` 0, `failure_reason`
   cleared) → `ready`, or `failed` with `failure_reason` as a sentence to show as it is. `progress` climbs
   0 → 0.04 while pages are prepared, then 0.05-0.80 page by page, 1.0 at ready. A run that parks on a
   question leaves the score `processing` with `key_sig`/`meter` already set; the waiting state is
   `interpretations.status = 'needs_review'` and `jobs.result.question` on the `process_pages` job, as before
   (004, 011). So the dot has four states to tell apart: ready, failed, waiting on a question (`processing`
   with the newest interpretation `needs_review`), and busy (any other `processing`).

What the API does (`api/app/librarian/import_pdf.py`, job kind `import_pdf`, payload `{score_id, source_id}`):
open the PDF with PyMuPDF, render every page in the file's own order to a greyscale PNG at 150 dpi (the call the
experiments and the Beethoven 9 seeds used; a page narrower than 1100 px is scaled up to 1100, wider than
3200 px down to 3200), upload `{score_id}/pages/{n}.png` (1-based, the key `process_pages.page_paths` already
reads for a `pdf` source), set `sources.page_order = [1..n]`, `page_count = n` and `meta.render = {engine, dpi,
px, seconds}`, then insert the `process_pages` job (`{score_id, source_id}`, same `created_by`). The worker picks
it up next; nobody waits. A retried import does not queue a second reading.

Failures a musician reads (`ScoreFailure` in `api/app/librarian/__init__.py`: no retry, the sentence goes to
`scores.failure_reason` as it is): not a PDF; damaged; locked with a password; no pages; longer than
`PDF_MAX_PAGES` (setting, default 40: "This PDF has 92 pages; Folio reads up to 40 at a time for now. Import one
movement or section as its own PDF."); the upload missing; and from `process_pages`, no staves on any page.
Any other failure is retried by the worker and then reported in general words per job kind ("Folio could not
finish reading the pages. Try the import again."); the technical text stays in `jobs.error`. This applies to every
job kind now, not only PDFs (`worker.failure_reason`).

`process_pages` change for whole PDFs: the signature read (004) takes the first system on the first page where the
geometry finds one (at most page 4), not always page 1, because a real PDF opens with a title page and often a
blank page. The crop is `{score_id}/signature/p{page:03}-s1.png` and `summary.signature.page` says which.

Measured on the local stack, 2026-10-28, first 5 pages of each file, Muse Spark 1.3 at effort low, the real
route and handlers (`import_score`, then `run_one` per job as the worker runs them):

| PDF (pages 1-5) | Outcome | Wall time after the route | Spark calls | Spend |
|---|---|---|---|---|
| Goldberg BGA (`goldberg-bga.pdf`), five pages of music | `ready`: 30 systems, 119 bars, G major 3/4, 5 bars doubtful | 73.0 s (render 0.3 s) | 6 | $0.0584 |
| same pages (`goldberg-bga-p1-5.pdf`), 2026-10-30, pages in two waves (004) | `ready`: 119 bars, 3 doubtful, 24 landmarks | 46.4 s (render 0.4 s); 110.9 s page by page at bfac5d9, after the header read and the landmarks | 7 | $0.0728 |
| Rach 1 two-piano, Gutheil 1919: title, blank, 3 of music | parked on page 4 (piano II drops out of the first two systems, so systems disagree); F# minor 4/4 read from page 3 | 65.7 s | 3 | $0.0345 |
| same file, before the signature fix | parked on page 4; key and meter blank (read on the title page) | 56.9 s | 2 | $0.0461 |
| Rach 1 full score, Gutheil 1919 | parked on page 1 (17 staves, the 004 geometry's 10 + 7 split); F# minor 4/4 | 31.4 s | 2 | $0.0193 |

Per page of music: about 13.5 s and $0.011, almost all of it the one Spark labelling call (12-15 s between
calls; geometry is milliseconds, rendering 0.07 s a page). The signature read adds one call, 4-17 s and
$0.004-0.010. So a 10-page PDF that reads cleanly took about 2.5 minutes after the upload and cost about
$0.12; a 40-page one about 9 minutes and $0.45. Since 2026-10-30 (004, two waves) the signature and header
are read at once and the pages after the first four at a time: the five-page Goldberg reads in 46 s (110.9 s page by
page), so by estimate 70 to 80 s for ten pages and about 3 minutes for forty, at the same spend per call. Total spend for these four runs: $0.158 (Meta).
An orchestral or two-piano PDF whose systems change shape mid-page parks at the first such page and waits for
the parts answer: automatic reading holds today for books whose systems keep the same parts on a page (keyboard,
chamber music without dropped staves).

### The browser half (web, 2026-10-28)

- The library's Import (dock, and the empty state) is "Import PDF or MusicXML"; the file input takes `.pdf` too.
  `importPdf` in `web/src/app/data.tsx` does steps 1-4 above (title from the file name, folder "Imported", body
  `{path, filename, kind: 'pdf'}`); MusicXML goes through `importMusicXml` as before. A refused import is said in a
  line above the covers (no `window.alert`). Photograph pages (`/scan`) stays for the camera only and gates nothing.
- Each book's state is derived in one place, `web/src/app/book.ts` (`bookState`): **busy** = `processing` with no
  question, or an `omr_convert` job queued or running; **waiting** (yellow dot) = a parked job on the book
  (`process_pages`, `part_cut`, any kind whose `result.question` is set and not yet answered) or the newest
  interpretation `needs_review`; **failed** (red dot) = `failed`, or the last conversion failed with no
  transcription; else nothing. Jobs other than `part_cut` load as `world.bookJobs` (chained like part jobs by
  `payload.resume_from`); Realtime now also watches `sources` and `ensembles`.
- On the cover: busy is a quiet ring around the book that breathes (opacity 0.18 to 0.85 over 1.6 s, no spinner,
  static under reduced motion); the dot sits in the top corner; the progress meter and "Needs pages" badge are gone.
  Tokens `--ask` and `--fail` per token set and theme (styles.css).
- Every cover and the book page have a "…" menu: its first item is the state ("The librarian has a question",
  which opens the confirmation sheet; "Digitalising in progress" while a read or a conversion runs; "Reading
  stopped"), then Open PDF, Open Digital, Convert to Digital and, on the cover, Book page.
- The confirmation sheet (`StaffQuestion.tsx`) answers both kinds: `choose_staves` as before, and the reader's page
  question: the page image (`{score_id}/pages/{n}.png`, signed), the sentence, `options` (with `spark_parts` and
  `known_parts`) as tappable rows, a free line, posted as `{answer: "Piano I, Piano II"}`.
- Verified on fake data only (temporary `?view=harness`, removed). Not run end to end with a real PDF upload.

## Rules and decisions

- Storage keys are bucket-relative `{score_id}/...`; never `scores/{score_id}/...`.
- The browser never writes a `jobs` row; the API does, with `created_by` set.
- Copyright: one line at import, "you are responsible for having the right to use this score"; demo uses
  public-domain IMSLP material only; scores stay in a private bucket per ensemble.
- IMSLP import is a paste-link flow (000, verified with curl 2026-10-26); the server never scrapes.
- Two intake paths, three data layers, stable measure ids (000).

## Open issues

- PDF import, browser half: built (above), not yet run signed in against the local stack with a real PDF.
- `scores.status` has no waiting value, so a parked PDF reads `processing` on the score; the dot looks at the
  interpretation and the parked job (`book.ts`). A `needs_review` status (feature 001) would make it one read.
- Spark's parts answer on a page whose systems differ is the 004 rule's limit; the page question now has a sheet.
- `PDF_MAX_PAGES` = 40 is a guess at cost and time; CK to set it.
- PyMuPDF is AGPL-3.0; fine for this public repo, a question if Folio is ever closed-source (pypdfium2 is the
  permissive alternative).
- Browser pdf.js rasterise + page ordering for the scan path: designed, not built.
- IMSLP paste-link import: designed, not built.
- `measure_placements.page` should become nullable for measures a reprocess does not find (ask from the
  intelligence thread).
- `scores.status` has no `needs_review` (feature 001).

## Next steps

1. Run a real PDF import signed in on the local stack and on the iPad; answer a parked page question there.
2. Scan screen on real data: rasterise, upload `{score_id}/pages/{n}.png`, commit `page_order`, queue
   `process_pages` (004).
3. Apply migration `20261028090000` when feature 008's handler is wired to a route.
4. IMSLP paste link, then the copyright line.
