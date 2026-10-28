# 004 PDF to bar-numbered pages

Status: working (`process_pages` handler; acceptance passes on the local stack; CK says this is close to closed) | Meta model: Muse Spark 1.3 labels what geometry found (first measure number, parts, rehearsal marks, title, composer, key, meter, difficulty, brief).

## Purpose

Scanned pages become a score with stable measure identities: every bar has an id, a page, a system and a box
on the page image, so annotations, cuts and distribution work on page coordinates with no transcription.
Reprocessing keeps every id. This is build-queue item 6's engine (Path B).

## What exists

- `api/app/librarian/process_pages.py` (job kind `process_pages`, payload `{score_id, source_id, answer?}`):
  per page, download the PNG, `geometry.measures_on_page` (feature 003; boxes as fractions, confidence from
  geometry), `labels.label_page` (one Spark call per page through `ctx.complete`, effort low, about $0.008
  a page: first measure number, part names per system, rehearsal marks, doubtful bars, title, composer, key,
  meter, 1..5 difficulty per part, a two-sentence brief; it never moves a box). Then one pass writes
  interpretation v(n+1) with engine `opencv-geometry+spark-labels`, stable `measures` (upsert on
  `(score_id, number, part)`, never delete), `measure_placements`, `parts` with difficulty, the score's facts
  and `ready`.
- The deliberate realistic failure: when a page's staff-to-part assignment is ambiguous (Spark's parts do
  not add up to the staves it sees, systems on one page disagree, or a page introduces parts earlier pages
  did not have), the handler parks with `ctx.needs_review(question, payload)`. Pages already read are kept
  in `interpretations.params.state`; the follow-up job (same payload plus `answer`, part names top to
  bottom as a list or comma-separated) continues from that page without paying for the earlier ones again.
- `api/app/librarian/labels.py`: prompt lifted from `label_with_spark.py` (exact text in the grounding README,
  "Exact prompts") plus difficulty and brief.
- `api/app/librarian/run.py`: `seed --pages <png...>` (a score in admin@muse.test's local library),
  `process_pages --score <id> [--answer ...]`, `show --score <id>`; `--provider meta|anthropic`.
- `api/experiments/grounding/tap_test_db.py --score <id>`: reads placements back from the database and taps
  every ground-truth bar.
- `docs/acceptance/librarian-pipeline.md` (passes on the local stack, 2026-10-27): two-page score (Goldberg
  Aria, Rachmaninoff two-piano p3); first run parks with a question about page 2 (four staves where page 1
  had two); the answer "Piano I, Piano II" resumes; score `ready` with 41 bars, parts Piano / Piano I / Piano
  II with a difficulty each; tap test 28/28 and 13/13 ALL PASS; key G major, meter 3/4, two-sentence brief,
  title and composer from the page, `flagged.bars_doubtful` = 4 (bar 17 after the repeat, two partly broken
  barlines, the wide cadenza bar 41), rehearsal mark 1 on bar 37; one `muse-spark-1.3` usage event per page
  tagged with the job id, about $0.009 to $0.011 each, `interpretations.cost_usd` their sum; reprocess gives
  v2 with the same 41 measure rows (ids unchanged) and `current_interpretation_id` moves to v2.
- Verified after the merge on 2026-10-27: page 2 parks, the answer resumes, 28/28 and 13/13 from the
  database, about $0.01 Spark per page. Its first run wrote test rows to the hosted project by mistake; CK
  approved the cleanup and it was done the same evening (score, images, usage events deleted; both spend
  counters back to 0).
- Web: `scores.status` processing → ready by Realtime; the library cover shows the meter.

## Records

From the grounding README, now in the schema (feature 001 migration):

- `interpretations`: one row per run; `version` = previous max + 1; `engine`; `status` queued | running |
  done | failed | needs_review; `params` (dpi, skew per page, thresholds, state); `summary`; `cost_usd`;
  `latency_ms`. On success `scores.current_interpretation_id` points at it.
- `interpretations.summary` is what the information box reads: `pages, systems, measures, first_measure,
  last_measure, title, composer, parts, difficulty, key_sig, meter, flagged: {pages_unreadable, bars_doubtful},
  models, log: ["Read 14 pages", ...], pages_read, question`. Counts only, never percentages.
- `measures`: identity, `unique nulls not distinct (score_id, number, part)`; `part` null = all parts;
  `label` when the printed label differs. A measure a new run does not find keeps its row and gets a
  placement with `confidence = 'low'`, `flag = 'not found in v{n}'`.
- `measure_placements`: per (interpretation, measure): `page` (1-based into `sources.page_order`), `system`,
  `box {x0, y0, x1, y1}` as fractions of the page image, `confidence` high | medium | low from geometry
  (barline width, coverage, header-zone merges) with Spark as a second opinion, `flag`, `rehearsal_mark`.
- `parts`: `name` as printed, `position`, `difficulty` 1 to 5 (UI shows one word), `storage_path`.
- `scores`: `status, progress, pages, bars, key_sig, meter, tempo_bpm, duration_sec, failure_reason`.

## Rules and decisions

- Models never place staves or bars. Spark labels; geometry measures. Spark's doubt flag is weak (it flagged
  nothing, including a spurious bar in an earlier run), so confidence comes from geometry.
- Never delete a `measures` row. Annotations point at `measures.id`.
- Counts only in the UI; difficulty is one word.
- A parked job is `done` with `result.question`; the admin's answer queues a follow-up job of the same kind
  with `payload.answer` (feature 011 owns the typed contract and the route).

## What remains (CK: close to closed)

- The deliverable named in the title, a PDF with bar numbers printed on it, does not exist as a file. What
  exists is the bar map in the database and a tappable overlay (`build_overlay.py`). Rendering numbers onto
  the page images or onto the cut strips (feature 008) is a follow-on; the barlines are already found.
- Cross-page numbering continuity is not checked (bar ids restart per page in the OMR plumbing too, 005).
- App thread asks: a route that answers a parked job; a waiting state for the score badge; nullable
  `measure_placements.page`; the information box reading the `summary` fields.
- Hosted UI check by CK.
- Geometry limits from 003 (cross-staff stems on solo-piano pages, pickup bars, deskewed frame).
