# 005 PDF to MusicXML (OMR on the Ryzen Ubuntu box)

Status: working on the local stack (Convert to Digital: `POST /scores/{id}/convert`, job `omr_convert`; engraved pages in two layouts by MuseScore on the box, `engrave.py`, 2026-10-28); experiments on the box in `api/experiments/omr/` | Meta model: Muse Spark 1.3 reads the text layer and answers closed questions about low-grade symbols. Spark never touches notes.

## Purpose

Turn a scanned page into MusicXML for playback (feature 014) and for the OMR accuracy number. The engine is
Audiveris; Spark adds what the symbolic engine cannot read (text, dynamics, words) and verifies what it is
unsure about. The product's bar map stays on the OpenCV geometry (003, 004).

## Verdict (measured 2026-10-27, Goldberg Aria p1, bars 1 to 28, vs Open Goldberg ground truth)

| | Number |
|---|---|
| Audiveris alone, pitch F1 | **0.972** |
| Audiveris alone, onset+pitch | 0.878 |
| Audiveris alone, full (onset+pitch+duration) | **0.838** (0.844 with Spark verify) |
| Spark text layer, text F1 | **0.31 → 1.00**, $0.08 / page, 6 calls, 81 s |
| Spark closed questions on low-grade symbols (A) | **9/11 right**, 11 calls, $0.04, 44 s |
| Spark judging notes (homr judge) | precision 0.45, recall 0.62 (55 %), $0.016 and 17 s per bar |
| Spark re-transcribing abnormal bars (C) | pitch F1 **drops to 0.837**, full 0.738; harmful |
| A + B together | full 0.844, text 1.00, ornaments P/R/F1 0.48/0.83/0.61, **$0.12 and 125 s** (~20 s parallel) |
| Audiveris alone, CPU | 34 s per page, $0 |

The smoke run CK rated (feature 009) had broken OCR; with `TESSDATA_PREFIX` set the title, composer and
tempo are read (fingering digits become garbage words). Spark's re-transcribed bars all "add up to 3/4",
which is why a plausibility judge must not pick them. Per flagged bar, pitch tp/pred/gold, Spark vs
Audiveris: m3 1/7/7 vs 5/5/7; m7 11/21/20 vs 20/21/20; m25 1/11/8 vs 6/6/8. Effort medium on m7 spent 8000
output tokens and returned nothing. Spend $0.50 of $2.00, 39 calls.

**Rules:** models never place staves or bars; Spark reads text and answers closed questions only; Spark never
judges or re-transcribes notes; effort low; output budget at least 8k tokens (effort low still spends 2 to
7k output tokens reasoning; runs capped at 3 to 4k truncated).

## Audiveris (5.11, the engine)

`api/experiments/grounding/out/omr-judge/audiveris/REPORT.md`. Data model (`.omr` = zip of XML):
`sheet#1.xml` is a 2547x3246 px frame (= pdftoppm 300 dpi within 1 px), so crops come straight from the
scan. Per system, `<stack left right expected duration excess>` = measure x-bounds plus Audiveris's own
rhythm check; `<measure abnormal="true">` is the flag. Every symbol is an inter with `shape`, `grade`,
`ctx-grade`, `bounds`, `pitch`, `staff` (1822 on the Aria: 349 heads, 26 rests, 8 ornaments, 10 dynamics, 1
tuplet, OCR words). `abnormal` is a good review signal: 8 bars flagged (2, 3, 7, 13, 14, 16, 23, 25), every
one has an error; five bars with 1 to 8 wrong events go unflagged (19, 24, 26, 27, 28). Grade under 0.6
marks confusables: the only tuplet (0.36) is the *e* of "dolce", the m7 fermata (0.23) is fingering "45",
"sf" (0.38) is really *mf*.

Insertion points: measure/system/staff bounds taken as-is (Spark never moves a box); pitch taken as-is;
rhythm in dense bars flagged with `abnormal` + `excess` (no per-measure re-run or parameter override in the
CLI, so no agentic retry); low-grade confusables → A, Spark verifies (crop with red box, closed question,
deterministic MusicXML edit); text, dynamics, words → B, Spark re-reads per system (boxed, numbered bars)
and replaces Audiveris's words; ornaments → B lists them per bar with a notehead index (recall up, precision
down; placement right about half the time, counting only the melody voice helps, F1 0.55 → 0.61); abnormal
bars → C re-transcribe: harmful.

Failure cases: A called the real *p* of "p dolce" (grade 0.51) a letter and dropped it (B restores it); the
m21 eighth rest was called fingering "1" (rests are never edited). B hallucinates ornaments where grace notes
and slurs are (bars 7, 13, 25). Four system calls reported 52 to 82 input tokens (image cached?), so cost is a
lower bound.

Recommendation: yes, this week, for structure, text and review flags; not for notes. Run Audiveris (34 s a
page, free), take bounds, pitch and rhythm as-is, show `abnormal` bars as needs review, let Spark verify
low-grade symbols (A) and own the text layer (B) for about $0.12 and 20 s a page. The story: a mid-size model
made trustworthy by asking it only closed questions the symbolic engine cannot answer.

### Goldberg pages 1 to 3 end to end (`goldberg-p1-3/RUN.md`)

Audiveris as one book over sheets 1 to 3 with `TESSDATA_PREFIX` → A grade-gated verifier (symbols graded
under 0.6) → B per-system text + ornament re-read (ornaments written only when placement is unambiguous:
single voice, no grace notes, bar not abnormal) → review flags (`abnormal` + durations-add-up check).

| Page | Content | Bars | Audiveris | Spark calls | Spark cost | Spark time (A + B) | Abnormal | Rhythm flags | Text items | Ornaments written / skipped |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Aria 1 to 28 | 28 | 37.4 s | 17 | $0.121 | 49 + 76 s | 8 | 7 | 12 in 10 bars | 7 / 18 |
| 2 | Aria 29 to 32, Var. 1 1 to 16 | 20 | 38.5 s | 17 | $0.103 | 36 + 70 s | 2 | 4 | 16 in 10 bars | 5 / 0 |
| 3 | Var. 1 17 to 32, Var. 2 1 to 5 | 21 | 35.8 s | 9 | $0.061 | 16 + 49 s | 3 | 5 | 16 in 12 bars | 1 / 2 |
| total | 69 bars, 3 movements | 69 | 77 s as one book | 43 | **$0.285** | 296 s (~25 s parallel) | 13 | 16 | 44 | 13 / 20 |

Aria check (32 bars): Audiveris alone pitch F1 0.977, onset+pitch 0.892, full 0.859, ornaments 7/18, text F1
0.27; after A+B full 0.864, ornaments 11/18 at precision 0.69, text recall 12/12 (precision 0.71 only because
the page-1 text ground truth stops at bar 28). Rendered with Verovio 6.3 on the Mac in a subprocess, SVG to
PNG via resvg (`scripts/render.py`); `review.html`.

The p1-3 plumbing (exports caught through a FIFO, per-page bar offsets, text per bar, a fixed 0.6 gate) is
replaced by the committed scripts in `api/experiments/omr/` (next section).

### Plumbing fixed, Goldberg pages 1 to 5 (2026-10-28, `api/experiments/omr/`)

- **One book, one file per movement, no collision.** The `mvtnull` name comes from the CLI: with `-sheets` it
  hands `export` a fresh score list instead of the book's, so `Score.getId()` (the index in the book's list)
  is null for every movement (read in the 5.11 bytecode, `CLI$ProcessingTask`; the opus export dies on the
  same duplicate name). `book_box.py` cuts the page set into its own PDF (pdfseparate + pdfunite, same stem)
  and never passes `-sheets`: one `-transcribe -export` writes `goldberg-bga.mvt1..4.mxl`, the time
  signature and key carry across pages, and the 5-page cap is structural. Rewriting `book.xml` into a single
  movement was tried and rejected (the export duplicated the first page of each sheet and lost Var. 2's 2/4).
  Careful: `-export` on a saved book without `-sheets` transcribes every remaining sheet of the PDF.
- **Continuous bar ids.** `measure_map.py` gives every stack the 004 shape: key `page.system.bar`, global
  `number` (+1 per printed bar over the page set, voltas included), `box` as page fractions, plus `movement`
  and `movement_bar` (= the ordinal in that movement's export). `score.py` merges the movement files onto
  the global numbers (counts must match, spanners carried) into one `base.musicxml`; edits, flags, text and
  crop labels all use those numbers.
- **Text by position.** Spark returns each word's centre on its 0 to 1000 grid over the system crop.
  `text_place.py` maps it to page pixels, snaps it to an Audiveris text glyph within 8 interlines (OCR words
  that are not digits, dynamics symbols: Audiveris knows where the ink is, Spark knows what it says), anchors
  a dynamic to the first notehead at or right of its ink (an *f* whose ink starts left of the barline belongs
  to the next bar), else takes the bar whose x range holds the point; staff by the nearer staff band, ties
  to the upper staff. Spark's bar label is only a cross-check; when it disagrees with an unconfirmed x the
  bar is flagged for review.
- **Gate knob.** `audiveris_model.py --gate 0.6 --gate-tag tuplet=0.9`; `model.json` records `gate_skipped`
  (what the gate let through unasked). Answers are cached per inter, so moving the gate pays only for the
  newly admitted symbols.

The BGA PDF's page 4 is a second scan of page 3 (Var. 1 bars 17 to 32, Var. 2 bars 1 to 5); the run keeps it
(five pages as given). Audiveris reads it as a continuation of Var. 2 in the carried 2/4, so 15 of its 21
bars are abnormal: a real hazard of carrying the time signature, and a good review-flag test.

| Page | Content (global bars) | Bars | Abnormal | Rhythm flags | Flagged | Text items | Ornaments written / skipped |
|---|---|---|---|---|---|---|---|
| 1 | Aria 1 to 28 (1-28) | 28 | 8 | 7 | 9 | 12 in 10 bars | 6 / 22 |
| 2 | Aria 29 to 32, Var. 1 1 to 16 (29-48) | 20 | 2 | 4 | 4 | 16 in 10 bars | 4 / 0 |
| 3 | Var. 1 17 to 32, Var. 2 1 to 5 (49-69) | 21 | 3 | 5 | 5 | 16 in 12 bars | 1 / 1 |
| 4 | duplicate scan of page 3 (70-90) | 21 | 15 | 15 | 16 | 16 in 12 bars | 1 / 1 |
| 5 | Var. 2 6 to 32 with voltas (91-119) | 29 | 4 | 1 | 4 | 10 in 10 bars | 0 / 4 |
| total | 119 bars, 4 Audiveris movements | 119 | 32 | 32 | 38 | 70 | 12 / 28 |

Against p1-3: pages 1 to 3 give the same 69 bars (28, 20, 21) and the same abnormal and rhythm counts.
Audiveris 91 s for the 5-page book (77 s for 3). Spark 60 calls, **$0.389** ($0.078 a page, p1-3 $0.095),
34 + 61 s wall with 6 calls in parallel (501 s summed), largest reply 3.3k output tokens, none truncated.
Text, with a typed ground truth for all five pages (`goldberg_bga_text_gt.json`, 70 words) and dots
ignored: Audiveris alone F1 0.44; final **0.986** strict (69/70; P = R), 1.00 within a bar. On bars 1 to 69,
same metric: p1-3 (per-bar labels) 1.00, this run 0.977, the one miss a *cresc.* (bar 18) whose ink Spark
put 100 px right and Audiveris never found, so nothing confirmed it (flagged). Placement methods on the same
Spark answers: Spark's x alone 0.929, x refined by geometry 0.986, Spark's bar label 1.00. Aria notes
unchanged (pitch 0.977, onset+pitch 0.892, full 0.859 → 0.864); ornaments 9/18 at precision 0.60 (p1-3
11/18 at 0.69; Spark's ornament answers vary run to run). Gate at 0.6: 30 asked, 202 skipped, among them
three tuplets at 0.65, 0.74, 0.76, all false (fingering, letters); the first two bars were un-tupleted anyway
by a lower-graded tuplet in the same bar, bar 67 kept a false triplet. `--gate-tag tuplet=0.9`: 3 more calls
($0.013), all three called letters or nothing, no tuplet left in the final file. Total spend $0.403.

## Convert to Digital, in the app (2026-10-28, `omr_convert`)

CK's direction: a PDF book gets a second version of itself, scoped for now to piano and chamber music. The book
shows PDF and Digital and two mode buttons, Open PDF and Open Digital; Digital is a transcription with flagged
bars and the PDF stays the truth. The interaction is Split by instrument's: one action, a busy state, a result row.

**Route.** `POST /scores/{id}/convert`, body optional `{pages?: [int]}` (1-based PDF pages; the whole PDF when
omitted). 402 over budget, 404 no such score, 403 not owner or admin, 400 "This book has no PDF to convert" (no
`pdf` source) or "A transcription of this book is already in progress" (an `omr_convert` job queued or running).
Returns the job row: `kind = 'omr_convert'`, `status = 'queued'`, `max_attempts = 1` (a retry would pay for Spark
again), `payload = {score_id, source_id, pages?}` and **`jobs.score_id` null**: the worker marks a failed job's
score `failed` and `ctx.progress` moves the score's meter, and neither may touch a ready PDF book. The browser
finds the job with `.eq('kind', 'omr_convert').eq('payload->>score_id', id)`; RLS lets the creator read it
(`created_by = auth.uid()`), other admins of the ensemble do not see the busy state. While it runs, the handler
refreshes `jobs.locked_at` every minute, so the worker's 15-minute stale sweep never re-queues a long book.

**Handler** (`api/app/librarian/omr_convert.py`, helpers `omr_box.py`, `omr_book.py`, `omr_spark.py`,
`omr_score.py`; the experiment code ported, not imported):

1. Ships the stored PDF (the first `.pdf` key of the `pdf` source) to the box over ssh (`OMR_HOST`, default the
   `omr` alias; `~/omr/folio/<job id>/`, removed afterwards unless `OMR_KEEP=1`), runs `omr_box.py` there:
   Audiveris on the PDF itself (a page subset cut with pdfseparate/pdfunite), one book, no `-sheets`; `pdftoppm -r
   300 -gray` for the crops; one tar back. At most 40 pages (`MAX_PAGES`, refused on the box before Audiveris
   starts). Box unreachable (ssh exit 255, or the probe fails): the job fails with `result.reason` "The
   transcription engine is offline" (the row's `error` reads "EngineOffline: The transcription engine is offline"),
   before any model call, no charge. Audiveris failing, no bars, or bars that do not line up also fail before Spark.
2. `omr_book` builds the bar map (global numbers, Audiveris's boxes, the gate at 0.6); `omr_score.merge` puts the
   movements on it. A part the export left a bar out of is lined up by Audiveris's own measure numbers and gets a
   whole-bar rest, flagged (Rach 1 two-piano p3-5: Piano II lacked bars 17 and 19, 38 measures against 40 stacks).
3. Spark: the closed questions (A) and the text and dynamics re-read per system (B), 6 calls in flight, effort
   low, 8k budget, JSON-only system prompt, one retry, every call through `ctx.charge`; allowance
   `max_cost_usd` (default $0.20 a page), past it the rest keep Audiveris's reading. Two changes from the
   experiment: B no longer asks for ornaments (precision 0.60, so nothing is attached to notes by the model;
   Audiveris's ornaments stay), and an unconfirmed Spark point whose own bar label names another bar of the
   system takes the label's bar (the open question of the p1-5 run, decided: all four such cases in the p1-5 and
   p1-3 runs were the label's bar). Rest, dot, ornament and wedge verdicts are never edits; a doubtful one flags
   the bar.
4. Writes `{score_id}/digital/score.musicxml` and one `sources` row, kind `musicxml`, `storage_paths` that key,
   `meta = {transcribed_from, engine: "audiveris-5.11+spark", flags: {bars_doubtful, pages_unreadable},
   flagged_bars: [{number, page (PDF page), key, box (page fractions), reasons}], pages, parts}`; never
   `instruments`, `slug` or `split_from` (the web's `isSplit`). A re-run replaces the file and updates the row.
   The file is read back through the import's own `book_facts` (extracted from `import_musicxml.py` with
   `write_parts` and `write_measures`; the import's behaviour unchanged): `measures` upserted; `parts` written as
   the import writes them when the book has none, else the book's own names kept (positionally, when the counts
   agree, and written into the file) and only `storage_path` set to the digital file, difficulty untouched; OCR'd
   names tidied otherwise ("Piano 11." → "Piano II"). Facts only where empty: key, meter, bars (and pages for a
   whole PDF); never tempo or length (the Goldberg Aria, which prints no tempo, came back as quarter = 72). The
   score's `status`, `progress` and `current_interpretation_id` are not touched; no interpretation row.
5. Result: `{source_id, instruments, bars, flagged_bars (numbers), seconds, cost_usd, pages, pages_unreadable,
   spark_calls, spark_skipped, edits, timings: {box_s, audiveris_s, render_s, upload_s, pull_s, spark_s,
   write_s}}`.

Consequence for the web: `parts.storage_path` now points at the digital file, so `firstPath` in `data.tsx` gives a
converted PDF book a `fixture` and ScoreDoc opens the notation (before, a PDF book said "The pages have not been
read yet"). Open PDF and Open Digital, and the job's busy state, are web work still to do.

**Live, local stack, 2026-10-28** (`api/tests/test_omr_convert.py` covers the same with a stubbed box and model):

| Book | Pages | Bars | Parts (import path) | Wall | Box (Audiveris, render) | Spark | Flagged |
|---|---|---|---|---|---|---|---|
| Goldberg BGA | 1-3 | 69 | Piano (2 staves), 69 measures | 115.7 s | 65.0 s (56.9, 5.6) | 43 calls, 49.7 s, $0.185 | 24 |
| same, re-run (label rule) | 1-3 | 69 | same, same source row | 114.2 s | 67.3 s (59.0, 5.6) | 43 calls, 45.7 s, $0.154 | 22 |
| Rach 1, two pianos (Gutheil) | 3-5 | 40 | Piano I, Piano II (4 staves), 40 measures | 140.7 s | 91.1 s (85.0, 4.9) | 34 calls, 48.3 s, $0.183 | 32 |

Re-run on Goldberg bars 1 to 69: text F1 strict **1.00** (44/44; the first run 0.932, its three misses the
label rule now fixes), Aria notes identical to the experiment (pitch 0.977, onset+pitch 0.892, full 0.864),
ornaments 7/18 at precision 0.88 (Audiveris's own). Key from the digital file: Goldberg "E minor" (music21's mode
analysis on a G major signature: a scanned book gets its key from 004's signature read first, and that is never
overwritten), Rach "F# minor" (right). Both files render in Verovio. Spend $0.52 of the $3 Meta cap; the first
Rach attempt failed at the merge before any call (no charge), which is how the missing-bar case was found. No
Beethoven quartet PDF exists in `api/fixtures/pdf/` or on the box, so chamber music beyond two pianos is untested.

**How long for a 10-page PDF.** Per page, end to end: 38 s (Goldberg, sparse) to 47 s (Rach, dense). Audiveris
20 to 28 s a page in one book (JVM start included once), the scans 2 s, Spark 15 to 16 s a page with 6 calls in
flight, transfer and writing a few seconds. A 10-page book: Audiveris 3.5 to 5 min, Spark about 2.5 min, about
**6.5 to 8 minutes** in all, Spark about $0.50 to $0.60. Audiveris and Spark run one after the other (Spark needs
Audiveris's boxes); more calls in flight is the cheap lever on the Spark half.

## homr (0.7, studied and rejected for now)

`out/omr-judge/homr/REPORT.md`. Pipeline: autocrop, resize, CLAHE → segnet UNet → boxes → `detect_staff` →
RapidOCR title → brace detection → `MultiStaff` → one dewarped crop per staff → TrOMR encoder+decoder (ONNX)
→ symbols → `generate_xml`. Facts: the time signature numerator is never read (median of per-bar duration
sums, so one bad system makes the Aria 4/4); both staves of a grand staff run on one clock; no `<beam>`; no
text or dynamics; 0.7 writes no `imgpos` comments; `--read-staff-positions` makes every line a single staff.

| Variant | pitch | onset | pitch+beat+dur | perfect bars | time sig | beams | OMR-NED |
|---|---|---|---|---|---|---|---|
| homr alone | 0.943 | 0.460 | 0.434 | 5/28 | 4/4 wrong | 0 | 0.745 |
| + Spark time signature ($0.005, 6.5 s) | 0.943 | 0.460 | 0.434 | 5/28 | 3/4 | 0 | 0.743 |
| + per-staff clocks, clip, beams | 0.895 (0.921 before clipping) | 0.698 | 0.670 | 7/28 | 3/4 | 56 | 0.636 |
| + system-crop retry, bar-length arbitration | 0.897 | 0.713 | 0.691 | 7/28 | 3/4 | 56 | 0.638 |
| system crops only | 0.883 | 0.664 | 0.623 | 4/28 | 3/4 | 53 | 0.657 |

All gains deterministic (geometry crops and stacking, per-staff clocks, beams from the time signature, a
free bar-length check: precision 1.00, recall 0.86; 18 of 28 bars flagged, all wrong; 3 wrong bars pass).
Spark as per-bar judge: precision 0.45, recall 0.62, do not ship (needs 6000 max_tokens or reasoning eats
the reply). Rach two-piano p3: homr alone gives 1 part with 41 sequential measures; six geometry crops
stacked give 2 parts x 13 bars, 7/13 flagged; 40 s CPU. Per page: 8 s staff detection + 15 s decoder (CPU),
retry crops +30 s. Grace notes: homr keeps 16 trills, drops all 26. Spent $0.26 of $2. Verdict: not as a
Spark loop and not this week as a transcription feature.

## Engraving (2026-10-28, MuseScore headless on the box)

MuseScore Studio 4.7.5 runs headless on the box (`~/omr/musescore/`, the extracted AppImage, no install;
`MU_QT_QPA_PLATFORM=offscreen ~/omr/musescore/scripts/musescore_render.sh out.(pdf|mpos|mscx) in.musicxml`, about
0.6 s a page; plain `QT_QPA_PLATFORM` is ignored). Engraving our file there found two defects in what the merge
writes, both fixed in `api/app/librarian/musicxml_fix.py`, a post-write pass on the bytes that `omr_convert`'s
`write_musicxml` and the experiments' `score.py` and `apply_edits.py` all run:

- **Voice numbers.** music21 renumbers voices per bar across both staves, so voice 2 is the bass in one bar and
  an upper voice in the next; MuseScore binds a voice to one staff per part and silently drops the rest. Now every
  staff gets its own numbers (staff 1 voices 1-4, staff 2 voices 5-8; each voice of a bar goes to the staff with
  most of its notes, a cross-staff note keeps its own `<staff>`). Notes kept by MuseScore (`musescore_kept.py`):
  Goldberg Aria **391 → 414 of 414**, Chopin Op. 40/1 page **586 → 628 of 628** (bar 16's bass, the inner voices
  of 2, 4, 10, 13, 14).
- **Layout metadata.** The merge builds a new score, so Audiveris's `<defaults>` (page size, margins, scaling) and
  every `<credit>` were lost, and music21 wrote "Music21" as the composer. Now the first movement file's
  `<defaults>` and its title and composer credits (the first two credits with real text; OCR'd fingering digits
  and specks dropped) are carried, the book's title and composer written into them (else the credits' own text),
  and an empty or "Music21" creator removed. `<print new-system/new-page>` were already kept. With the scan's
  page size MuseScore reproduces the scan's systems exactly: Goldberg p1 1-6, 7-12, 13-16, 17-20, 21-24, 25-28,
  p2 29-32; Chopin 1-3, 4-6, 7-10, 11-13, 14-16 on one page (before: Letter, extra breaks, a second page).

The fixed files and their renders: `api/experiments/engrave/goldberg/same-file/F-*` and
`api/experiments/engrave/chopin-op40-1/F-*` (`fix_inputs.py`; `G-input.musicxml` is the same after a music21
re-write, same counts and systems). Tests: `api/tests/test_musicxml_fix.py`.

### The engraving step, in the app (2026-10-28 night, `engrave.py`)

CK's decision: digital books are rendered server-side by MuseScore, not on the device. Every book's own notation (the
import's file, or the transcription; never a split) is engraved twice at the end of `import_musicxml` and of
`omr_convert` (`engrave_step`, best effort: the book is ready either way, and the reader falls back to OSMD on the
device when no pages exist), and again on demand as job kind `engrave` (`run.py engrave --score`). The box runs one
MuseScore job file per layout (`-j`: SVG pages plus the `.mpos` measure positions in one run, `-S style.mss` for the
display layout), about 4.5 s a layout for the Beethoven quartet (22 pages) over ssh, 9.9 s for both.

| Layout | The file MuseScore gets | Style | What CK sees |
|---|---|---|---|
| `display` (default), "Optimised for digital display" | a copy with every `<print>` system and page break dropped and `<defaults>` set to an iPad page, 3:4 portrait, 210 x 280 mm, 12/14 mm margins, the file's own `<scaling>` kept (music21's 7 mm / 40 tenths when absent), `<system-layout>` and `<staff-layout>` defaults dropped | `enableVerticalSpread` 0, `lastSystemFillLimit` 0, `pageTwosided` 0 | systems at their natural distance; a short last page keeps its empty space at the bottom (Goldberg p2: system gaps 2530/2360 units instead of 3890/3720 stretched); the quartet reflows to 22 pages of 3 systems (2 under the title) |
| `original`, "Preserve original formatting" | the file as it stands | none | the scan's page size and systems for a transcription (`musicxml_fix` carries them); the editor's page for an import (the quartet: Letter, 21 pages, vertically justified, as the file says nothing) |

Style keys tested on the box (`.mss` is the `<Style>` block of an `.mscx`; the template files under
`squashfs-root/share/mscore4portable-4.7/templates/` list every key): `enableVerticalSpread` is the switch;
`maxSystemDistance = minSystemDistance` on top of it packs every page to the minimum (tighter than the natural
distance, rejected); page size keys in the style are ignored when the file carries `<defaults>`, which is why the
display copy rewrites the file. `MU_QT_QPA_PLATFORM` and `QT_QPA_PLATFORM` must both be `offscreen` (one alone aborts).

`.mpos` units are twelve times the SVG's user units (the SVG is written at 1200 dpi): the first bar's `x / 12` is the
first staff line's x, a system's `y / 12` the staff's top. Each element is one measure in file order, `id` the ordinal,
`page` 0-based. `bar_boxes` joins ordinal i to the i-th measure number of the file's first part (`measures.number`) and
writes `[number, page (1-based), x, y, w, h]` as fractions of its page; an ordinal past the numbers, a page without an
SVG, or a number engraved twice is skipped. The box spans the whole system height (every staff of the system).

Storage: `{score_id}/digital/{layout}/p{nnn}.svg` and one `sources` row of kind `engraving` per layout
(`storage_paths` the pages in order, `page_count`, `page_order`, `meta = {layout, source_id, engine "musescore-4.7.5",
page_mm, bars, engraved_at}`); a re-run replaces the files and updates the row. The chosen layout is
`scores.digital_layout` (default `display`), migration `20261028230000_engraved_layouts.sql` (local only, CK pushes).
Failures are plain sentences in `result.engraving.reason` ("The engraving engine is offline", "... crashed on this
file", "... wrote no pages for this file", "A compressed .mxl cannot be engraved yet"); `ENGRAVE=off` in the
environment skips the box (the test suite's default, `tests/conftest.py`). Tests: `api/tests/test_engrave.py` (the
display copy, the measure numbers, the real Goldberg `.mpos` to boxes, the step and the job against a fake box, the
import's step, the ssh exit 255 rule). The reader side is in 010.

## The box

The OMR engines run on CK's Ryzen Ubuntu box, reached as ssh alias `omr` (CK's `~/.ssh/config`; LAN host,
key `id_ed25519_omr`, ControlMaster on). Layout on the box: `~/omr/exp-audiveris/` (Audiveris 5.11, batch
`audiveris -batch -transcribe -export -output DIR file`, Java 21, `TESSDATA_PREFIX` set; `p1-3/book3b/` for
the three-page book), `~/omr/exp-homr/` (homr 0.7 in `~/omr/homr/.venv`, eval tools in `~/omr/eval/.venv`),
`~/omr/smoke/` (page PNGs and system crops). Shell runners (`run_sys.sh`, `run_rach.sh`, `run_loop.sh`,
`run_judge2.sh`) are copied under `out/omr-judge/homr/`; every box artefact is copied to a `box/` folder
next to its report. Rendering (Verovio, resvg) happens on the Mac. Spark is called from the box through
`scripts/spark.py` (Anthropic SDK against Meta, like `app/llm.py`, with a spend cap in `spend.json`).
The p1-5 run uses `~/omr/folio005/` (`scripts/book_box.py`, `p1-5/audiveris/`); everything after
Audiveris, Spark included, runs on the Mac with `api/.env`.

## Files

`api/experiments/grounding/out/omr-judge/audiveris/`: `REPORT.md`, `base/` (goldberg-bga.mxl, model.json,
compare-base.json), `scripts/` (apply_edits, build_review, compare, crops, fifo_reader, flagged_table, ly_gt,
merge_pages, omr_model, render, reread_systems, retranscribe_bars, review_flags, slice_pages, spark,
verify_symbols), `gt/`, `crops/`, `spend.json`, `goldberg-p1-3/` (RUN.md, review.html, run.json, box/ with
final-mvt{1,2,3}.musicxml, final-p{1,2,3}.musicxml, merged.musicxml (69 bars), flags, verify, reread, logs).
`out/omr-judge/homr/`: REPORT.md, the scripts (arbitrate, cut_pianos, stack_parts, tokens_to_events,
events_to_xml, judge_bars, judge_score, eval_bars, ...), `box/`. The whole `out/omr-judge/` is gitignored.
Landscape of engines: `api/experiments/grounding/OMR-RESEARCH.md` (feature 016).

Committed plumbing, `api/experiments/omr/`: `book_box.py` (box: page set → one book → one export per
movement), `audiveris_model.py` (bar map, inters, grade gate), `measure_map.py`, `text_place.py`,
`spark_layers.py` (A verify, B reread, cached, parallel), `score.py`, `apply_edits.py`, `review.py` (flags,
page slices), `render.py`, `compare.py`, `build_review.py`, `pipeline.py` (the Mac side end to end),
`goldberg_bga_text_gt.json`; tests in `api/tests/test_omr_plumbing.py`. Runs land in
`api/experiments/omr/out/` (gitignored): `goldberg-p1-5/` (model, verify, reread, edits, flags,
compare-*.json, base/final.musicxml, slices, render, review.html) and `goldberg-p1-5-gate-tuplet09/`.

In the app: `api/app/librarian/omr_convert.py` (handler, `SshBox`), `omr_box.py` (box side, stdlib, copied over
per run), `omr_book.py` (bar map and gate), `omr_spark.py` (crops, prompts, placement, the two passes),
`omr_score.py` (merge, edits, flags), `musicxml_fix.py` (voices per staff, page layout and credits), `engrave.py`
(MuseScore over ssh, the two layouts, `.mpos` to bar boxes, the `engraving` sources); `api/app/routes/convert.py`;
tests `api/tests/test_omr_convert.py`, `api/tests/test_musicxml_fix.py`, `api/tests/test_engrave.py`.

## Next steps

1. Web: the Convert to Digital action on a PDF book, the busy state from the job row (found by
   `payload->>score_id`), the Digital tag next to PDF once a `transcribed_from` source exists, Open PDF / Open
   Digital, and the flagged bars (`meta.flagged_bars` has page and box for an overlay on the PDF).
2. A chamber-music run: no Beethoven quartet PDF is in the corpus; a string quartet or piano trio, 5 pages.
3. Notes ground truth for Var. 1 and 2 (Open Goldberg) so the note F1 covers more than the Aria; a page-level
   duplicate check (page 4 of the BGA PDF repeats page 3).
4. Keep Audiveris as a separate process (AGPL): Folio's code never imports it; MuseScore (GPLv3) likewise, a
   process over ssh.
5. Engraving: a single part's pages (today a part falls back to OSMD on the device); `.mxl` input (unzip before the
   box); a player's own layout choice (the toggle writes the book, so only an owner or admin sees it); the
   per-book `bars` list rides in `sources.meta` and is loaded with the library (about 12 KB a layout).
