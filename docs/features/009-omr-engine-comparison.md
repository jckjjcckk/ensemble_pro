# 009 OMR engine comparison and rating matrix

Status: working (CK's ratings recorded; the measured verdict is in 005) | Meta model: none in the ratings (Spark's roles are measured in 005; SAM probes in 003).

## Purpose

Decide which OMR engine, if any, Folio builds on, with CK's musical judgement on rendered output and
measured numbers against ground truth.

## CK's ratings (2026-10-28, `api/fixtures/omr/rating-matrix.csv`)

0 to 100 per criterion; overall out of 100, 5 means unusable. Pairs rendered from the OMR-box smoke outputs
(`out/omr-rating/omr-rating.html`, gitignored). The Audiveris smoke run had broken OCR (no `TESSDATA_PREFIX`).

| page | engine | bars | clef/key/time | pitch | rhythm | voices/staves | ornaments/artic. | dynamics/text | overall | notes |
|---|---|---|---|---|---|---|---|---|---|---|
| goldberg-bga-p01 | audiveris | 80 | 100 | 50 | 70 | 65 | 10 | 10 | 0 | No fingering; sometimes missing or wrong text |
| goldberg-bga-p01 | homr | 100 | 66 | 60 | 80 | 50 | 20 | 0 | 5 | Wrong time; missing ornaments; does not connect the 16th notes |
| goldberg-bga-p01 | transcoda | 70 | 100 | 30 | 30 | 20 | 0 | 0 | -5 | Completely crazy page layout |
| goldberg-bga-p01-sys1 | smt | | | | | | | | | Verovio crashed |
| rach1-2pf-gutheil-p03 | audiveris | 100 | 100 | 20 | 0 | 60 | 0 | 60 | -5 | "It recognized piano I and piano II and did a correct split, but the dense piano I is compl[etely wrong; **note truncated in screenshot**]" |
| rach1-2pf-gutheil-p03 | homr | 90 | 95 | 60 | 40 | 70 | 40 | 0 | 5 | "Treat piano I and piano II as sequential not parallel" |

The Rach Audiveris note is truncated in the CSV; CK can complete it.

## Measured verdict (details in 005)

Audiveris with Tesseract: pitch F1 0.97, full-bar 0.84 on the Goldberg Aria. Spark text layer F1 0.31 → 1.00
at $0.08/page. Spark closed questions 9/11. Spark judging or re-transcribing notes: always worse (judge 55 %,
re-transcribe drops pitch to 0.84). homr: pitch 0.943 alone, all gains deterministic, time signature never
read. Engine: **Audiveris with `TESSDATA_PREFIX`**. homr studied and rejected for now.

## Engines surveyed (`api/experiments/grounding/OMR-RESEARCH.md`, 2026-10-27)

| Engine | What | Runs on the Mac | Licence | Note |
|---|---|---|---|---|
| Audiveris 5.11.0 | symbolic pipeline, Java 21, keeps system/staff/measure pixel bounds | yes (arm64 dmg; headless batch) | AGPL-3 | the one engine with bounds |
| homr 0.7.0 | oemer UNet + Polyphonic-TrOMR per staff | yes (`uvx --from 'homr[cpu]' homr`) | AGPL-3 | `--read-staff-positions` injection point; no dynamics |
| oemer 0.1.8 | end-to-end UNet | probably, unmaintained | MIT | historical baseline only |
| SMT / SMT NeXt | transformer, one system image at a time → kern | yes; HF weights grandstaff / camera / quartets | MIT | SER 5.1 / 6.2 / 1.4 on its own sets; collapses off-distribution; needs a segmenter |
| Zeus (OmniOMR) | staff / grand-staff → MusicXML | yes, Python 3.10 | MIT code, CC BY-NC-SA 2026 models | needs a segmenter |
| Legato v1 | Llama 3.2 11B Vision → ABC, full page | heavy, CUDA | MIT weights, Llama licence | encoder is a Meta model; OMR-NED 28 to 58 |
| Legato 2 | YOLOv8-m system detector + per-system VLM | not released | - | best published, OMR-NED 17 to 44; beats Gemini 3.1 Pro (89 to 94) and Audiveris |
| Transcoda | 59M end-to-end, fixed 1485x1050 page → kern | should | AGPL-3 | OMR-NED 18.5 synthetic, 64 historical |
| MeasureDetector | Faster R-CNN, TF 1.13 | no | MIT | dead stack; our geometry does this |

Frontier VLMs as OMR engines lose to Audiveris (Gemini 3.1 Pro OMR-NED 89 to 94 in Legato 2's tables),
matching our grounding result: the models read music, they do not transcribe or locate it. Datasets:
Sheet Music Benchmark (SMB, 685 pages, kern, gated), OSSQ-OMR (116 quartets, 24,544 system images), Open
Goldberg (CC0), GrandStaff / OLiMPiC / PDMX-Synth (training sets). Metrics: OMR-NED (musicdiff), SER, our
tap test. Where SAM could help: system segmentation in front of SMT / Zeus / homr, phone-photo dewarp
("sheet of paper" mask), splitting multi-piece pages; not barlines, noteheads or anything handwritten.
The benchmark proposal from this note lives on as feature 016.

## Files

`api/fixtures/omr/README.md`, `rating-matrix.csv` (committed); `out/omr-rating/omr-rating.html`,
`out/omr-judge/` (gitignored); `OMR-RESEARCH.md` (committed).

## Next steps

1. CK completes the truncated Rach note if it matters.
2. Re-rate Audiveris output with OCR working, and the Goldberg p1-3 `review.html`, when 005's plumbing is
   fixed.
