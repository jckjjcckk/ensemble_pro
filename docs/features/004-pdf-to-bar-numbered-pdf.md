# 004 PDF to bar-numbered pages

Status: working (`process_pages` handler; acceptance passes on the local stack; pages read in two waves since 2026-10-30, 110.9 s to 46.4 s for five pages; CK says this is close to closed; signature read added 2026-10-28 night; on the part cut's geometry since 2026-10-28: keyboard, two-piano and both orchestral test files read themselves) | Meta model: Muse Spark 1.3 labels what geometry found (first measure number, parts, rehearsal marks, title, composer, difficulty, brief), reads the key and time signature of the first system (closed question) and the score header on the first page of music (instruments, staves per full system).

## Purpose

Scanned pages become a score with stable measure identities: every bar has an id, a page, a system and a box
on the page image, so annotations, cuts and distribution work on page coordinates with no transcription.
Reprocessing keeps every id. This is build-queue item 6's engine (Path B).

## What exists

- `api/app/librarian/process_pages.py` (job kind `process_pages`, payload `{score_id, source_id, answer?}`):
  first the signature read and the score header on the first page with music (both once per interpretation,
  asked at the same time, below), then the pages in two waves (below; per page: download the PNG, `cut.page_measures` (feature 003, the part cut's geometry, the
  header's staff count driving the staff recovery; boxes as fractions, confidence from geometry),
  `labels.label_page` (one Spark call per page through `ctx.complete`, effort low, about $0.008 to $0.02 a
  page: first measure number, part names per system, rehearsal marks, doubtful bars, title, composer, key,
  meter, 1..5 difficulty per part, a two-sentence brief; it never moves a box), the parts assigned in page
  order after the wave. Then one pass writes
  interpretation v(n+1) with engine `opencv-staff-geometry+spark-labels`, stable `measures` (upsert on
  `(score_id, number, part)`, never delete), `measure_placements`, `parts` with difficulty, the score's facts
  and `ready`.
- The deliberate realistic failure: when a page's staff-to-part assignment is ambiguous (Spark names no parts
  for a system, its parts do not add up to the staves the geometry found, a page brings a part that neither
  earlier pages nor the score header have, or two names on one system match one part), the handler parks with
  `ctx.needs_review(question, payload)`. Systems on one page may differ (cut-away systems, below). Every
  page read is kept in `interpretations.params.state`, the pages after the question too; the follow-up job
  (same payload plus `answer`, part names top to bottom as a list or comma-separated) continues from that page
  without paying for any page again.
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

## Printed landmarks for voice notes (2026-10-30, 013 prompt v4e)

The per-page Spark read (`labels.py`, item 8) also names what is printed on the page that marks a place: tempo words
and metronome marks, key and time signature changes, double bars, repeats, segno, coda, To Coda, Fine, D.C./D.S.,
section titles. Each is pointed at a provisional bar box exactly as rehearsal letters are; Spark is told not to
count or number bars. `process_pages` gives each box its bar from the geometry count (`landmarks_at_bars`; a double
bar or an end repeat is the boundary after its box) and writes `scores.landmarks` with source `page` (013). A
landmark whose box Spark leaves null, points off the page, or that sits over a box Spark itself doubts is dropped
and logged ("Page 3: landmark 'rit.' left out (no box)"), never guessed. A converted book's MusicXML landmarks
replace the page ones.

Eval (`api/experiments/landmarks_page/`, Muse Spark 1.3, effort low; Goldberg BGA pp. 2-3, Chopin op. 26/1 pp. 14-16;
20 printed landmarks counted by eye; $0.155 for 10 calls):

| page | printed | r1 found | r1 invented | r2 found | r2 invented |
|---|---|---|---|---|---|
| Goldberg BGA p. 2 (end of Aria, Var. 1) | 4 | 4 | 1 (start repeat, box 19) | 4 | 0 |
| Goldberg BGA p. 3 (Var. 1, Var. 2) | 5 | 5 | 0 | 3 (start repeat, 2/4 missed) | 0 |
| Chopin op. 26/1 p. 14 (ritenuto x2, end repeat, Fine, key change) | 5 | 4 (end repeat missed; key "3 flats" for 5) | 0 | 4 + end repeat named a double bar ("4 flats") | 0 |
| Chopin p. 15 (start repeat, meno mosso, ritenuto, end repeat) | 4 | 3 (start repeat pointed at no box, dropped) | 0 | 3 (same) | 0 |
| Chopin p. 16 (start repeat, ritenuto) | 2 | 2 | 0 | 2 | 0 |
| **total** | **20** | **18** | **1** | **16 (+1)** | **0** |

r1 invented a start repeat; the prompt was tightened once (only what is printed: a repeat sign is two dots beside a
double barline, never inferred; count the new key's flats; one barline can carry two landmarks) and r2 invented
none. Known weak spots: a key change's label (the bar is right), a start repeat at a system's start, and geometry
errors carry over (Chopin p. 14 has a key-signature-only box after the last bar; p. 15's last system is one box for
three bars, so its end repeat lands two bars early).

## Reading the pages in two waves (2026-10-30)

A five-page PDF took 110.9 s at bfac5d9, almost all of it seven Spark calls awaited one after another: the
signature read (6.8 s), the header read (12.9 s), then a label call per page (13.8 to 23.1 s; the landmarks
added on 2026-10-30 lengthened the answers to 1,900 to 3,200 output tokens). Geometry, downloads and the
database writes between calls were about 0.4 s a page. No prompt changed; only the waiting did.

- **Signature and header at once.** Both closed questions look at the first page where the geometry finds a
  system and neither reads the other's answer, so they go out together (`asyncio.gather`). A page with no
  system costs neither a call, as before; the log keeps the signature line first, then the header's.
- **Wave one:** the first page with music, alone. Its parts name the book, and every later page's label prompt
  lists them ("Parts already read on earlier pages"). Its parts are assigned before the second wave, so a
  question on the first page parks before any other page is paid for.
- **Wave two:** every remaining page at once, at most `CONCURRENCY` = 4 label calls in flight (a semaphore;
  Meta allows 150 requests a minute, and the investigation's three-at-once run drew no 429). Each page is told
  the first page's parts. A page read is stored `pending` in `params.state.pages` with `save_state()` as it
  lands, its cost added and the progress note counting pages read.
- **Assignment in page order** (`assign_in_order`): after the wave, `assign_parts` runs over the pending pages
  1..n, each against the parts of the pages before it, exactly as the page-by-page loop did, up to the first
  page not read. The log's page lines stay in page order. The one difference from a page-by-page run: page
  3's label prompt lists page 1's parts, not page 1's and page 2's, so a part that first appears on page 2 is
  not named to Spark on page 3 (the matcher still files "Vl. I" under page 2's "Violin I"). On a keyboard or
  chamber book, where the first page has every part, the prompts are byte-identical.
- **A question on page k** parks on the first ambiguous page in order. The later pages stay read and pending;
  the answer's follow-up assigns them with no new call.
- **A failed call** (label_page raises on a malformed answer) loses none of the other pages: they are saved,
  the pages before the gap are assigned, and the attempt then fails. The interpretation records
  `params.job_id`; the worker's retry of the same job (`attempts > 1`, no answer) resumes that interpretation
  ("Attempt 2: 4 pages already read are kept") and reads only the missing page. Before, a retry started a new
  interpretation and paid for every page again.

Measured on the local stack, Goldberg BGA pp. 1-5 (`api/fixtures/pdf/goldberg-bga-p1-5.pdf`, 119 bars), the
real handlers (`import_pdf`, then `process_pages`), Muse Spark 1.3 at effort low, every request and answer
recorded:

| Run | Wall time | Signature + header | Page 1 | Pages 2-5 | Calls | Spend |
|---|---|---|---|---|---|---|
| bfac5d9, page by page | 110.9 s | 20.1 s (in series) | 13.8 s | 75.9 s (in series) | 7 | $0.093 |
| two waves | 46.4 s | 12.9 s (at once) | 12.7 s | 19.5 s (four at once) | 7 | $0.073 |

Per book the first-page reads go from about 20 s to about 13 s (the longer of the two). Pages after the first
share four slots instead of waiting in line, so by the same call times a ten-page PDF should read in 70 to 80 s
rather than 2.5 to 3 minutes, and a 40-page one in about 3 minutes rather than 9 (estimates, not measured:
the experiment budget is 3-5 pages a file). Spend is unchanged per call.

Same output: the seven requests of the parallel run hashed identically to the page-by-page run's (model,
system, messages, budget), so every prompt was byte-identical. Replaying the page-by-page run's recorded
answers through the new code, and the parallel run's answers through bfac5d9, gave identical page records,
119 placements (boxes, confidence, flags, rehearsal marks), 22 and 24 landmarks, parts, summary and log; the
only differences were the label memory's timestamps. Between the two live runs the geometry was identical
(28, 20, 21, 21, 29 bars, the 003 truth) and Spark's free text varied as it does run to run (briefs,
difficulty, 22 against 24 landmarks; the header said 12 staves for the piano once; the staff recovery
then searched every two-staff system and found nothing to add, so the bars did not move).

Tests: `api/tests/test_page_waves.py` (pages 2-5 in flight together and finishing out of order, assigned in
page order with "Vl. I" filed under page 2's Violin I; the bound; a question on page 3 of 5 keeping pages 2, 4
and 5 and the answer assigning 4 and 5 with no call; a failed page 3 losing nothing and the retry reading only
it; a retry of another job starting a new reading; the signature and header calls in flight together).

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
- `scores`: `status, progress, pages, bars, key_sig, meter, tempo_bpm, duration_sec, failure_reason`, `landmarks`
  (013 v4e, migration `20261030160000`, local stack only until `supabase db push --linked`).

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
