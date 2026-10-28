# 016 Benchmark tool: accuracy and cost per combination

Status: working (tool committed in `api/experiments/benchmark/`, first grid run 2026-10-28 night; see "The tool") | Meta models: Muse Spark 1.3 in every role under test (header, labels, recheck, text layer, closed questions); SAM 3.1 as an optional segmentation condition; Claude through the same harness for the published comparison.

## Purpose

One tool that runs a fixed set of about 10 pages through every combination that matters and reports
accuracy and cost per combination, so a night of credits answers a question instead of producing one more
strip to look at. Decided 2026-10-27 night.

## CK's rule

Credits go to iterations on ~10 pages, never 50-page runs or Claude-vs-Spark bakeoffs for now. The
benchmark is how a 10-page iteration becomes a number.

## Dimensions

| Axis | Values |
|---|---|
| engine | OpenCV geometry (003); Audiveris, homr for the OMR tiers (005) |
| Spark role | header on/off; labels by score order vs by position; recheck on/off; text layer; closed questions; judge (expected to lose) |
| effort | low (the rule), medium, high (expected worse: the grounding table) |
| resolution | native vs 150 dpi vs normalised staff spacing (Beethoven 9 found 10/16 native vs 16/16 upscaled, 003) |
| model | muse-spark-1.3, muse-spark-1.2, claude through the same harness |

Metrics: tap test (measure boxes), staves found vs header count, systems grouped, crops correct by eye or by
ground truth, verify pass rate, recheck true catches vs false alarms, OMR-NED / pitch F1 / text F1 for the
OMR tiers, $ per page, seconds per page, JSON repair and retry counts. Output: one results table plus per-page
JSON and an HTML report in the repo.

## Pages (proposal, fixed and versioned in `api/experiments/omr-bench/corpus/`)

From OMR-RESEARCH.md §4: tier A layout (our 2 tap-test pages + 8 more: Goldberg BGA x3, Rach two-piano x2,
Dvořák x2, Rach brass quintet x1, hand-verified boxes); tier B pianoform (Goldberg Aria + Var. 1 to 3 vs Open
Goldberg, CC0); tier C quartet (20 to 30 systems from OSSQ-OMR); tier D SMB subsets if HF access arrives;
tier E iPad photos of A and B pages for the SAM-dewarp condition. For the part cut: Rach 1 p1 to 5, PC3 p1
to 5, PC5 p1 to 5, Dvořák p5 to 9, Beethoven 9 p172 to 176, each with the known right answer per system
(008 tables). Engines for the OMR tiers: Audiveris 5.11, homr 0.7, SMT NeXt, Zeus 2026, Transcoda,
Spark-direct (one row, expected ~90 OMR-NED). Conditions: native / +SAM crops / +OpenCV crops / +GT crops;
raw photo / +SAM dewarp; output / +Spark correction. Split: shared contract first (corpus folders,
`ground_truth.json` per page, `run_<engine>.py page.png [--crops crops.json]`, `evaluate.py`), then one
session per engine. Risks: SMB access is manual; no CUDA on the Mac (Legato out); AGPL engines run as
separate processes only.

## Grader format

CK created a "Score Stave Extractor" in Anthropic's Managed Agents builder to borrow its grader and rubric
format; the bundle for its environment is `stave-extractor.zip` in the session scratchpad (scripts + two
5-page excerpts + README). The per-fixture ground-truth JSON that the agent never sees, scored by code, is
the workshop pattern (006).

## Reference numbers to beat or reproduce

Geometry + Spark labels $0.008 and 6.5 s per page (28/28, 13/13); part cut ~$0.02 and 10 to 30 s per page
(label $0.009 to 0.018, recheck $0.002 to 0.015); header $0.014 to 0.025; Audiveris 34 s free, A+B $0.12 and
~20 s parallel; `spend-global.json` cap $4.00.

## The tool (`api/experiments/benchmark/`, built 2026-10-28)

`uv run experiments/benchmark/run.py --grid grid.yaml --budget-meta 5 --budget-claude 5 [--dry-run] [--only task=header ...] [--rescore] [--report-only] [--retry-errors]`
from `api/`. Needs `api/.env`, the PDFs in `api/fixtures/pdf` (or `FOLIO_PDF_DIR`) and, for OMR, the `omr` ssh alias.

- **Corpus** (`corpus/manifest.yaml`, version 1): ten pages, at most five per file. Goldberg BGA p1-3, Rach 1
  Gutheil p1-3, Beethoven 9 p172-175. Geometry is frozen per page in the 150 dpi frame (`corpus/geom/`, from the
  experiment's `geom-p*.json`; Goldberg p1 from `cut.page_geometry` with system 1 merged by hand), so staff
  numbers never move. The resolution axis changes only the pixels the model sees: the page is rendered at that
  resolution, deskewed by the frozen angle and the frozen boxes scaled onto it. Headers for the label context are
  the experiment's `header.json` files, frozen (`corpus/headers/`).
- **Ground truth**: header (staff count, accepted instrument counts, per-box family) on Goldberg p1, Rach p1,
  B9 p172; labels on Rach p1-3 (Piano) and B9 p172-175 (Soprano, 008's decisions); text (005's `TEXT_GT`, bars
  1-28) and closed questions (005's 11 symbols, checked by eye) on Goldberg p1; OMR pitch on Goldberg p1 bars
  1-28 (Open Goldberg, `corpus/gt/goldberg-aria.json`). **No GT:** Goldberg p2 (the Aria GT has bars 29-32 but
  the page splits into two movements, not wired) and p3; no text or closed-question GT outside Goldberg p1; no
  OMR GT for Rach or Beethoven.
- **Tasks** use the product's prompts (`header.prompt`, `part_cut.LABEL_PROMPT` with `header.context`) or 005's
  (`reread_systems`, `verify_symbols`); one retry on unparseable or truncated JSON (both charged), like
  `ask_model`. No model task touches notes; the grid loader refuses one, refuses `max_tokens` < 8k when Spark
  is in the grid, and defaults effort to low.
- **Runner**: a call id is `task|item|model|effort|resolution`; `runs/<name>/results.json` is written after
  every call and an id with a record is never called again (API errors, which cost nothing, only with
  `--retry-errors`). Budgets are per provider over the whole run: a call starts only if spent + in flight + its
  estimate fits; the first that does not stops that provider cleanly. `spend.json` keeps every run's totals.
- **Tests** `api/tests/test_benchmark.py` (13, no network): manifest loader and its refusals, every metric,
  the JSON retry and refusal, the budget stop, resume and `--retry-errors`, the grid guards.

### First grid (2026-10-28 night, run `night-2026-10-28`)

4 tasks x 3 models (muse-spark-1.3, claude-haiku-5-5, claude-sonnet-5-5) x effort low/medium x native/150 dpi,
plus Audiveris on Goldberg p1-3 at native / 150 / 300 dpi / PDF (homr a stub): 348 calls, about 7 minutes.
**Spend: Meta $1.456, Claude $0.886.** Full table in `runs/night-2026-10-28/results.md`.

- **Labels:** 100 % of systems for Spark (both efforts, both resolutions, $0.010 a page at low), Sonnet ($0.014)
  and Haiku except low/150 dpi (2 misses; $0.001 a page).
- **Header:** box family accuracy 1.0 for Spark at low/150 dpi but staves 2/3 (on B9 it folded the two
  page-edge fakes into Flauti and Bassi); Sonnet 0.6 everywhere (it numbers B9's staves from 1, ignoring the
  fake box 1: every box off by one); Haiku 0.91 to 1.0. Spark costs $0.019 to 0.022 a header at low.
- **Text layer (Goldberg p1):** Spark low 0.88 (150 dpi) / 0.92 (native), medium native 1.00 at 2.2x the cost
  ($0.19 a page); Haiku medium 1.00 at $0.006 a page; Sonnet 0.92 flat.
- **Closed questions:** 0.82 for almost every cell (Spark low 9/11, as in 005); Sonnet low native 11/11. Almost
  every miss is one of the two eighth rests (ids 11822, 11940: models call them fingering "7"/"1" or nothing).
- **JSON:** zero first-try failures in 330 model calls (16k output budget, JSON-only system prompt).
- **Audiveris:** fed the PDF (it rasterises itself) it reproduces 005 exactly, pitch F1 0.972, onset+pitch
  0.878, 28 bars; our PyMuPDF renders lose barlines (native 27 bars, 0.908; 300 dpi 25 bars, 0.838); 150 dpi is
  refused ("interline 10 px, not reliable"). Feed Audiveris the PDF.

## Next steps

1. CK: confirm the closed-question GT for the two eighth rests (ids 11822, 11940) and the override on 11400
   (the box holds the "d" of dolce), then `--rescore` if anything changes.
2. Wire homr (`omr.run_homr`), OMR GT for Goldberg p2 (bars 29-32, two movements), text GT for p2-3.
3. Grow the corpus to the 25 part-cut pages above (Rach 1 p4-5, PC3, PC5, Dvořák) and add the recheck task.
