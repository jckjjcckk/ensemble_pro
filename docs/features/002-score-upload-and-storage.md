# 002 Score upload and storage

Status: working for MusicXML (Path A); prototype for pages (Path B pages are seeded by script, not uploaded from the browser) | Meta model: none (reading the pages is 003 and 004).

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
  until the Spark `brief` job replaces it.
- Web: `importMusicXml` in `data.tsx` creates the row, uploads, calls the API; Import MusicXML in the dock for
  admins and owners; signed URLs for score files.
- `api/scripts/smoke_import.py` on the local stack: upload through RLS, job done in 3 s, reimport keeps measure
  ids, violin2 sees four parts.
- Storage key fix 2026-10-27 (commit 32ce9e5): keys are bucket-relative, per the contract.
- Fixtures: see 000 (PDFs in `api/fixtures/pdf/`, MusicXML in `web/public/fixtures/`).

## Rules and decisions

- Storage keys are bucket-relative `{score_id}/...`; never `scores/{score_id}/...`.
- The browser never writes a `jobs` row; the API does, with `created_by` set.
- Copyright: one line at import, "you are responsible for having the right to use this score"; demo uses
  public-domain IMSLP material only; scores stay in a private bucket per ensemble.
- IMSLP import is a paste-link flow (000, verified with curl 2026-10-26); the server never scrapes.
- Two intake paths, three data layers, stable measure ids (000).

## Open issues

- Browser pdf.js rasterise + upload + page ordering: designed, not built.
- IMSLP paste-link import: designed, not built.
- `measure_placements.page` should become nullable for measures a reprocess does not find (ask from the
  intelligence thread).
- `scores.status` has no `needs_review` (feature 001).

## Next steps

1. Scan screen on real data: rasterise, upload `{score_id}/pages/{n}.png`, commit `page_order`, queue
   `process_pages` (004).
2. Apply migration `20261028090000` when feature 008's handler is wired to a route.
3. IMSLP paste link, then the copyright line.
