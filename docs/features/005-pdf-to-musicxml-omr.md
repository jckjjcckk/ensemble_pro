# 005 PDF to MusicXML (OMR on the Ryzen Ubuntu box)

Status: prototype (experiments on the box; nothing in `api/app`; OMR is optional enrichment, never a prerequisite) | Meta model: Muse Spark 1.3 reads the text layer and answers closed questions about low-grade symbols. Spark never touches notes.

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

Plumbing to fix before measuring more: run pages as one book (Audiveris exports every movement of a
multi-movement book to the same `mvtnull.mxl`, captured through a FIFO, `scripts/fifo_reader.py`; Opus
export crashes); multi-movement export collides; bar ids restart per Audiveris page (continuation pages get
an offset, `omr_model.py --page-offsets`); text placed per bar, not by x; the 0.6 grade gate misses a
fingering-as-tuplet.

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

## The box

The OMR engines run on CK's Ryzen Ubuntu box, reached as ssh alias `omr` (CK's `~/.ssh/config`; LAN host,
key `id_ed25519_omr`, ControlMaster on). Layout on the box: `~/omr/exp-audiveris/` (Audiveris 5.11, batch
`audiveris -batch -transcribe -export -output DIR file`, Java 21, `TESSDATA_PREFIX` set; `p1-3/book3b/` for
the three-page book), `~/omr/exp-homr/` (homr 0.7 in `~/omr/homr/.venv`, eval tools in `~/omr/eval/.venv`),
`~/omr/smoke/` (page PNGs and system crops). Shell runners (`run_sys.sh`, `run_rach.sh`, `run_loop.sh`,
`run_judge2.sh`) are copied under `out/omr-judge/homr/`; every box artefact is copied to a `box/` folder
next to its report. Rendering (Verovio, resvg) happens on the Mac. Spark is called from the box through
`scripts/spark.py` (Anthropic SDK against Meta, like `app/llm.py`, with a spend cap in `spend.json`).

## Files

`api/experiments/grounding/out/omr-judge/audiveris/`: `REPORT.md`, `base/` (goldberg-bga.mxl, model.json,
compare-base.json), `scripts/` (apply_edits, build_review, compare, crops, fifo_reader, flagged_table, ly_gt,
merge_pages, omr_model, render, reread_systems, retranscribe_bars, review_flags, slice_pages, spark,
verify_symbols), `gt/`, `crops/`, `spend.json`, `goldberg-p1-3/` (RUN.md, review.html, run.json, box/ with
final-mvt{1,2,3}.musicxml, final-p{1,2,3}.musicxml, merged.musicxml (69 bars), flags, verify, reread, logs).
`out/omr-judge/homr/`: REPORT.md, the scripts (arbitrate, cut_pianos, stack_parts, tokens_to_events,
events_to_xml, judge_bars, judge_score, eval_bars, ...), `box/`. The whole `out/omr-judge/` is gitignored.
Landscape of engines: `api/experiments/grounding/OMR-RESEARCH.md` (feature 016).

## Next steps

1. Fix the plumbing list above, then measure Var. 1 to 3 (6 to 8 pages) against Open Goldberg.
2. Decide whether OMR runs as a job kind (`omr`, optional, fills the same `measures`) or stays an experiment
   until practice mode (014) needs notes.
3. Keep Audiveris as a separate process (AGPL): Folio's code never imports it.
