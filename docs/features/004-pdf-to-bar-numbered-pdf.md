# 004 PDF to bar-numbered pages

Status: working (`process_pages` handler; acceptance passes on the local stack; CK says this is close to closed; signature read added 2026-10-28 night; on the part cut's geometry since 2026-10-28: keyboard, two-piano and both orchestral test files read themselves) | Meta model: Muse Spark 1.3 labels what geometry found (first measure number, parts, rehearsal marks, title, composer, difficulty, brief), reads the key and time signature of the first system (closed question) and the score header on the first page of music (instruments, staves per full system).

## Purpose

Scanned pages become a score with stable measure identities: every bar has an id, a page, a system and a box
on the page image, so annotations, cuts and distribution work on page coordinates with no transcription.
Reprocessing keeps every id. This is build-queue item 6's engine (Path B).

## What exists

- `api/app/librarian/process_pages.py` (job kind `process_pages`, payload `{score_id, source_id, answer?}`):
  first the signature read and the score header on the first page with music (both once per interpretation,
  below), then per page: download the PNG, `cut.page_measures` (feature 003, the part cut's geometry, the
  header's staff count driving the staff recovery; boxes as fractions, confidence from geometry),
  `labels.label_page` (one Spark call per page through `ctx.complete`, effort low, about $0.008 to $0.02 a
  page: first measure number, part names per system, rehearsal marks, doubtful bars, title, composer, key,
  meter, 1..5 difficulty per part, a two-sentence brief; it never moves a box). Then one pass writes
  interpretation v(n+1) with engine `opencv-staff-geometry+spark-labels`, stable `measures` (upsert on
  `(score_id, number, part)`, never delete), `measure_placements`, `parts` with difficulty, the score's facts
  and `ready`.
- The deliberate realistic failure: when a page's staff-to-part assignment is ambiguous (Spark names no parts
  for a system, its parts do not add up to the staves the geometry found, a page brings a part that neither
  earlier pages nor the score header have, or two names on one system match one part), the handler parks with
  `ctx.needs_review(question, payload)`. Systems on one page may differ (cut-away systems, below). Pages
  already read are kept in `interpretations.params.state`; the follow-up job (same payload plus `answer`, part
  names top to bottom as a list or comma-separated) continues from that page without paying for the earlier
  ones again.
- `api/app/librarian/labels.py`: prompt lifted from `label_with_spark.py` (exact text in the grounding README,
  "Exact prompts") plus difficulty and brief; from page 2 on the prompt lists the parts already read, so a page
  with abbreviations or no margin labels reuses their names. `read_header` (the part cut's header prompt and
  reconciliation from `header.py`) and `match_part` (the name matcher) live here too.
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
- Which page (2026-10-28, for whole PDFs from 002): the first page where the geometry finds a system, at most page 4,
  since a real PDF opens with a title page and often a blank page (Rach 1 two-piano: read on page 3, F# minor 4/4;
  page 1 gave blanks before). Pages without a system cost no call. `summary.signature.page` and the crop key
  `p{page:03}-s1.png` say which.
- What Spark sees: the first system of page 1 (or of the page above), cut by the geometry (`cut.page_geometry` at the working
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
| Beethoven 9 p172 (`a72c18a4`, printed 168), 16 staves | G major (naturals cancel D, 1 sharp), 3/2, Andante maestoso | G major, 3/2, both high; noted the clarinets' transposed flat | $0.0113 | $0.0300; `ready`, but `bars` = 2 where the part-cut geometry finds 8 (the old 004 geometry; the page has 9, and the port below reads 9) |

Spend $0.056 of the $2 cap, 4 calls. The B9 page is not D major 2/2: this page opens "Seid umschlungen".

Tests `api/tests/test_signature.py`: the key and meter tables, nulls for every unsure case, the request (image,
JSON-only system prompt, 8000 budget, effort low), no JSON and a blank page, `process_pages` writing the read and
not the labels' guess, one call across a parked question, and the import's canonical forms on two fixtures.

## Page reading on the part cut's geometry (2026-10-28)

Page reading parked within five pages on two of three real PDFs, both for geometry reasons the part cut had
already solved. `process_pages` now reads every page with `cut.page_measures` (003): page-edge shadows masked,
the working scale, staves as row-profile peaks, systems by the systemic line, the header's staff count driving
the staff recovery, system barlines by the two votes. `geometry.py` and `measures_on_page` are gone; their raster
steps live in `cut.py`. The record shape is unchanged (`measures`, `measure_placements` boxes as page fractions,
systems, `assign_parts`, the question path); `params.state.pages[n].geometry` also carries `working_px`,
`expected_staves`, `staves_before_recovery` and `recovered` per system.

- **The score header** (one Spark call, about $0.01 to $0.02, on the page the signature read used: the first with
  a system): the part cut's prompt on the numbered staff overlay, reconciled by `header.reconcile`; kept in
  `params.state.header` and `summary.header`, the overlay at `{score_id}/header/p{page:03}-overlay.png`. Its
  `expected_staves` goes to every page's geometry. A header with no JSON is left out (log: "staves are not
  recovered"); the book is never failed over it. The header's instrument names are not given to the label
  prompt: on a keyboard page with no margin label the header read takes the heading ("Aria.") for the
  instrument, and page 1 of the acceptance book then named its part "Aria" (first acceptance re-run).
- **Two geometry fixes in `cut.py`** found on these files: the systemic line is looked for at the pair's own
  staff start as well as the page median, in a window that grows with the spacing (an indented first system,
  Goldberg p1-2 and the two-piano p3, fell apart into single staves, each counting stems as barlines); and the
  barline votes' column tolerance is 4 px up to an 11 px spacing and 0.4 space above (`barline_tol`: Beethoven 9
  at 3150 px has 15-16 px spacing and one barline in nine drifted out of the 4 px window; 5 px on the 10 px
  Goldberg page let two stems meeting across the grand staff's gap vote as a barline).
- **Confidence** per bar from the part cut's barlines: medium when the closing barline does not cross every staff
  of the system, when the bar has no closing barline, when its start merged with a repeat or key strokes, or when
  it is over 2.6 times the page's median width; low under 4 spaces wide.
- **Parts, decided:** a cut-away system (resting parts left out, the two-piano and orchestral norm) is not a
  question when every name on it is a part the book already has. From page 2 on each name is matched to the
  parts read so far (`match_part`: exact ignoring case, punctuation and plurals; an abbreviation whose family has
  one entry; a shared numeral, "Flute I" in "Flauti I. II."; never a numbered name to an unnumbered part, so
  "Piano I" after "Piano" is new) and stored under the known name. A name that matches nothing is accepted when
  the header lists it (a part resting through the first pages), else it is the question. The two-piano page 4
  case turned out not to be a parts change at all: piano II plays in every system there; the old geometry missed
  both top staves of system 1 (and split it into 1 + 1 staves), and Spark labelled those "Piano I". With the
  header's 4 staves the recovery restores them and nothing is asked. Had piano II truly rested, "Piano I" on a
  2-staff system would now be read without a question, since its staves add up and the part is known.

Live on the local stack through `POST /scores/{id}/import` (the 002 route, `import_pdf` rendering at 150 dpi,
then `process_pages`), first five pages of each file (Beethoven 9: pages 172 to 176 as a five-page PDF), Spark
effort low, 8k budget. Truth counted by eye on the page images.

| File | Read without a question, before | After | Bars per page, truth | Before (old geometry) | After | Key, meter (after) | After: time, cost, calls |
|---|---|---|---|---|---|---|---|
| Rach 1 full score (B&H plates, 17 staves) | 0 of 5: parked on p1 (system split 10 + 7) | 5 of 5, `ready` | 4, 9, 9, 6, 7 = 35 | 9, 9, 6, 5, 7 | 4, 9, 9, 6, 7 = 35 | F# minor, 4/4 | 122 s, $0.117, 7 |
| Rach 1 two-piano Gutheil (p1-2 title, blank) | p3 only: parked on p4 | p3-5, `ready` | -, -, 13, 15, 12 = 40 | -, -, 13, 23, 12 | -, -, 13, 15, 12 = 40 | F# minor, 4/4 | 68 s, $0.062, 5 |
| Beethoven 9 p172-176 (16 staves, 17 on p176) | p172 only: parked on p173 (system split 8 + 6) | 5 of 5, `ready` | 9, 5, 9, 6, 5 = 34 | 2, 7, 2, 1, 2 | 9, 5, 9, 6, 5 = 34 | G major, 3/2 (the before run read D major) | 133 s, $0.117, 7 |
| Goldberg BGA (keyboard, regression check) | 5 of 5 | 5 of 5, `ready` | 28, 20, 21, 21, 29 = 119 | same | same | G major, 3/4 | 66 s, $0.067, 7 |

Before runs: the Rach 1 files from the 002 live runs earlier the same day; Beethoven 9 run once on `main` for this
table ($0.051, parked on its page 2). Spend for this work about $0.62 of the $2 cap (four after runs, the
Beethoven 9 before run, a Rach 1 full re-run after the plural fix, two acceptance runs). Keyboard and chamber read
themselves; both orchestral files read themselves too on these pages, more than CK's bar asked. Recovery fired on
two-piano p4 (2 staves) and on Beethoven 9 p173 (4) and p174 (1). Doubtful bars: Rach 1 full 5, Beethoven 9 13
(mostly "closing barline does not cross every staff": the resting staves of a choir page carry faint barlines),
two-piano 3, Goldberg 3.

Acceptance (`docs/acceptance/librarian-pipeline.md`) re-run on the new geometry: page 2 parks ("Spark reads Piano
I, Piano II there, which earlier pages did not have (they had Piano)"), the answer resumes, 41 bars, parts Piano /
Piano I / Piano II, tap test 28/28 and 13/13 ALL PASS, G major 3/4, rehearsal mark 1 on bar 37. Two differences:
`flagged.bars_doubtful` is 2 (bar 17 after the repeat, the wide cadenza bar 41; the two partly broken barlines
now cross every staff within a px), and a run makes two calls before the pages (signature, header), so
`usage_events` has pages + 2 rows.

Tests: `api/tests/test_process_pages.py` (the page record and its flags, the indented system, the barline
tolerance on a drifting line, cut-away systems, names kept across pages, a header-listed part, the questions
that remain, the matcher, the header count recovering a staff inside `process_pages`, the question without a
header, no header call before the first music); `test_signature.py` and `test_import_pdf.py` script the header
call.

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
- Geometry limits from 003 (cross-staff stems on solo-piano pages, pickup bars, deskewed frame, thin bowed
  Breitkopf scans).
- The header is read once per book; a book whose instrumentation changes between movements reads later
  movements against the first header (003 next steps: a per-page header call).
- Orchestral names: Spark's names on page 1 become the book's parts (English or as printed, it varies by run);
  a later abbreviation that fits two parts of one family ("Tromb." with tenor and bass trombones) is a question.
