# 016 Benchmark tool: accuracy and cost per combination

Status: to design (the intended overnight job) | Meta models: Muse Spark 1.3 in every role under test (header, labels, recheck, text layer, closed questions); SAM 3.1 as an optional segmentation condition; Claude through the same harness for the published comparison.

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

## Next steps

1. Write the contract (corpus, ground truth, runner interface, evaluate.py) as one session.
2. First night: the part-cut dimensions on the 25 pages above, Spark only.
3. Then the OMR tiers.
