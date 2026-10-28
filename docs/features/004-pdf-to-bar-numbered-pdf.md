# 004 PDF to bar-numbered pages

Status: working (`process_pages` handler; acceptance passes on the local stack; CK says this is close to closed; signature read added 2026-10-28 night) | Meta model: Muse Spark 1.3 labels what geometry found (first measure number, parts, rehearsal marks, title, composer, difficulty, brief) and reads the key and time signature of page 1's first system (closed question).

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

## The signature read: the book's key and meter (2026-10-28 night)

CK: a book's identity in the app is musical, its key, meter and length. `bars` was already written; `key_sig`
and `meter` came from the page labels' free text ("G major") and were missing or loose for scans. Now one
closed question fills them (`api/app/librarian/signature.py`, Muse Spark 1.3):

- When: first in `process_pages`, before the page loop, once per interpretation (kept in
  `interpretations.params.state.signature`, so a resumed run never pays for it again). The score row gets
  `key_sig` and `meter` at once, so the cover shows them even while the run waits on a parts question; the
  final facts write the same values. The labels' own key and meter are no longer used for the score.
- What Spark sees: the first system of page 1, cut by the geometry (`cut.page_geometry` at the working
  resolution, `cut.cut_system` over all its staves: cleaned, the next system's ink erased, never widened),
  uploaded for audit to `{score_id}/signature/p001-s1.png`. Spark never places a staff or a bar here.
- What it is asked (JSON-only system prompt, effort low, 8000-token budget, one retry through `ask.ask_model`,
  which moved out of `part_cut.py` so both handlers share it): the key signature as "sharps" / "flats" / "none"
  and a count 0 to 7, read on non-transposing staves (clarinets, horns, trumpets and timpani ignored, cancelling
  naturals not counted); major / minor / unsure from the opening music; the time signature as digits, "common",
  "cut" or "none"; a confidence for each, "low" rather than a guess.
- Canonical storage, which the web parses: `key_sig` = `"<Tonic> <mode>"`, the tonic a capital letter with `#`
  or `-` (music21 spelling: "E- major", "F# minor", "C major"), computed from the count and the mode
  (`key_from_signature`), not from Spark's prose; `meter` = `"<num>/<den>"`, common time "4/4", cut time "2/2".
  Null when Spark says low, when the mode is unsure, when its key name contradicts its own count, when no time
  signature is printed at the start of the system, and when the call never returns JSON or page 1 has no
  system; never a guess. The reason lands in `summary.signature.why` and the log says "left blank".
- `import_musicxml` writes the same forms (music21's "f# minor" becomes "F# minor"; `canonical_key`,
  `canonical_meter`), and names parts through `part_groups` (008).
- The interpretation summary carries `key_sig`, `meter` and `signature` {read, why, crop, crop_key, cost_usd}.

Live on the local stack, page 1 only of each (2026-10-28 night, seeded fresh as one-page scores):

| Score | Truth (by eye) | Read | Signature call | Whole run |
|---|---|---|---|---|
| Rach 1 Gutheil p1 (`e8c80b5f`), 17 staves | F# minor (3 sharps), C = 4/4 | F# minor, 4/4, both high | $0.0123 | $0.0260; parked on the parts question (the 004 geometry splits the system at the dotted line into 10 + 7 staves), key and meter on the score anyway |
| Beethoven 9 p172 (`a72c18a4`, printed 168), 16 staves | G major (naturals cancel D, 1 sharp), 3/2, Andante maestoso | G major, 3/2, both high; noted the clarinets' transposed flat | $0.0113 | $0.0300; `ready`, but `bars` = 2 where the part-cut geometry finds 8 (the 004 geometry on this scan, unchanged here) |

Spend $0.056 of the $2 cap, 4 calls. The B9 page is not D major 2/2: this page opens "Seid umschlungen".

Tests `api/tests/test_signature.py`: the key and meter tables, nulls for every unsure case, the request (image,
JSON-only system prompt, 8000 budget, effort low), no JSON and a blank page, `process_pages` writing the read and
not the labels' guess, one call across a parked question, and the import's canonical forms on two fixtures.

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
