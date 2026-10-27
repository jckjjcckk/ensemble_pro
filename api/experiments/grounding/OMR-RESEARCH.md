# OMR landscape and a benchmark proposal (research note, 2026-10-27)

Question from CK: where could SAM 3.1 (or another Muse model) significantly improve existing open-source
optical music recognition, and can we submit a benchmark of "existing engine, with SAM, without SAM"?
This note is research only; nothing here is built yet beyond the two probes marked as such.

## 1. The engines that are alive in 2026

| Engine | What it is | Input → output | Runs on the Mac? | Licence | Notes |
|---|---|---|---|---|---|
| **Audiveris 5.11.0** (Jul 2026, repo pushed Oct 11 2026) | Classic symbolic pipeline, Java 21 | page image / PDF → `.omr` book + MusicXML (`.mxl`) | Yes: arm64 `.dmg` on GitHub releases; headless `audiveris -batch -transcribe -export -output DIR file` | AGPL-3 | The only engine that keeps **system / staff / measure pixel bounds** (in the `.omr` XML). Legato 2 paper puts it at OMR-NED 56–86 on their sets. |
| **homr 0.7.0** (Jun 2026, repo pushed Oct 26 2026) | oemer's UNet segmentation + Polyphonic-TrOMR transformer per staff | photo / scan → MusicXML with `<!-- imgpos -->` comments | Yes: `uvx --from 'homr[cpu]' homr img` installs in 9 s (ONNX, CPU; `--coreml-encoder` on Apple Silicon) | AGPL-3 | Has `--write-staff-positions` / `--read-staff-positions`: **an injection point for external staff detection**. Pitch and rhythm only; no dynamics. No published accuracy. |
| **oemer 0.1.8** (Nov 2024, stale) | End-to-end UNet + classifiers | photo → MusicXML | Probably (onnxruntime), but unmaintained | MIT | homr is its successor; include only as a historical baseline if cheap. |
| **SMT / SMT NeXt** (PRAIG, repo pushed Sep 2026) | Encoder-decoder transformer, **one system image at a time** → `bekern` | system crop → kern | Yes with `uv sync`; HF weights `antoniorv6/smt-grandstaff`, `smt-camera-grandstaff`, `smt-string-quartets` | MIT | SER 5.1 (GrandStaff), 6.2 (camera), 1.4 (quartets) on its own test sets; collapses off-distribution (OMR-NED 92 on Transcoda's synthetic pages, 80 on Polish scans). **Needs a system segmenter in front of it.** |
| **Zeus** (ÚFAL / OmniOMR, pushed Sep 2026) | Staff and grand-staff recogniser → MusicXML (LMX) | staff / grand-staff crop → MusicXML | Yes, `pip install 'zeus @ git+https://github.com/OmniOMR/zeus.git'`, Python 3.10 | MIT code; 2024 models CC BY-SA, 2026 models CC BY-NC-SA | 2026 snapshots trained on Dolores + OLiMPiC + OmniOMR (incl. handwritten). **Also needs a staff/system segmenter in front.** |
| **Legato (v1)** (NeurIPS 2025 workshop; repo `guang-yng/legato`, pushed Sep 2026) | Llama 3.2 11B Vision encoder + ABC decoder, full page / multi-page | page → ABC | Heavy: 11B vision model, CUDA 12.4 tested; weights gated behind the Llama 3.2 licence on HF | MIT (weights), Llama licence for encoder | OMR-NED 28–58 on Legato 2's sets. Note the encoder is a Meta model. |
| **Legato 2** (arXiv 2607.05769, Jul 2026) | YOLOv8-m system detector + per-system VLM | page → symbolic + embedded text | **Not released** ("upon publication") | — | Best published numbers: OMR-NED 17–44; beats Gemini 3.1 Pro (89–94) and Audiveris by a wide margin. Its system segmenter is a fine-tuned YOLO on 1,024 pages: exactly the component SAM could replace zero-shot. |
| **Transcoda** (arXiv 2605.10835, May 2026; repo `btrkeks/transcoda`, 13 stars, AGPL-3) | 59M-param end-to-end, trained 6 h on one GPU, fixed 1485×1050 page → kern, grammar-decoded | page → kern | Should: small model, CPU-feasible | AGPL-3 | OMR-NED 18.5 synthetic, 64 on historical scans (vs Legato 44 / 87, SMT++ 92 / 80). Zero-shot by design. Worth trying first among the research models. |
| MeasureDetector (OMR-Research, Faster R-CNN, TF 1.13, Python 3.6) | measure bounding boxes | page → boxes | No (TF1 era) | MIT | Dead stack; our OpenCV geometry already does this job on the two test pages. |

Frontier VLMs as OMR engines: Legato 2 measured Gemini 3.1 Pro at OMR-NED 89–94 on every set, worse than
Audiveris. That matches our own Spark grounding result: the models read music, they do not transcribe or
locate it. Spark as a direct OMR baseline will lose; it is still worth one row in the table for the "Meta
tooling" story, and as a **corrector** it might win (see §4).

Datasets and metrics that are actually usable:

- **Sheet Music Benchmark (SMB)**, ISMIR 2025: 685 pages, 4,039 regions, kern ground truth, public-domain
  scans paired with KernScores; pianoform 469 pages, quartet, monophony. HF `PRAIG/SMB` (gated, manual
  approval). Defines **OMR-NED** = (insertions + deletions) / (N_pred + N_ref) over visual symbols, computed
  with music21 + musicdiff; the paper says it is meant as a **test set**. The baseline (SMT trained from
  scratch) scores 57 OMR-NED on pianoform, so there is room.
- **OSSQ-OMR** (arXiv 2608.10978): 116 string quartets, 24,544 system images and 98,172 staff images, scans
  from IMSLP aligned to OpenScore transcriptions (LMX, kern, ABC). Multi-part, i.e. our ensemble case. HF
  `jhlusko/ossq-omr-data`.
- **Open Goldberg Variations**: CC0 MusicXML + MuseScore source. Our Goldberg BGA scan has a clean
  symbolic ground truth for free; the first-page tap test already has hand-verified measure boxes.
- GrandStaff / Camera-GrandStaff, OLiMPiC (OpenScore Lieder, 17,945 systems), PDMX-Synth: training sets
  the research models already saw; fine for sanity checks, not for a fair benchmark.
- Metric stack: OMR-NED (musicdiff) for transcription, SER as the legacy number, and our **tap test**
  (measure-box accuracy) for layout, which none of the above measure and which is what Folio needs.

## 2. Where SAM 3.1 can and cannot help (with two probes from today)

Probe 1 (page level, done in the grounding experiment): `"musical staff"` returns exactly the six systems
on the clean page; `"line of music"` returns grand staves on the grey scan but with overlapping boxes;
`"sheet music"` / `"sheet of paper"` return the page. No prompt finds barlines.

Probe 2 (symbol level, today, Goldberg system 1 upscaled 2×): `"note head"` returned 10 boxes, all real
noteheads, out of roughly 70 (recall ≈ 15 %, precision 100 %, confidence ≈ 0.5); `"treble clef"` found the
one clef; `"fingering number"` found 12 fingerings; `"musical note"`, `"bass clef"`, `"sharp sign"`,
`"rest symbol"`, `"bar line"`, `"staff"`, `"slur"` returned nothing. So SAM is not a symbol detector for
music; the UNets in homr and the detectors in DeepScores-style work are far ahead there.

Where it plausibly beats the status quo:

1. **System / staff segmentation in front of system-level recognisers.** SMT, Zeus and Legato 2 all need
   crops; Legato 2 trained a YOLO on 1,024 hand-annotated pages for this, SMT's authors assume ground-truth
   crops, homr uses its own staff detection and lets you override it. SAM gives zero-shot system boxes with
   no training. Ablation: *SMT / Zeus / homr with (a) their own or no segmentation, (b) SAM 3.1 crops,
   (c) our OpenCV crops, (d) ground-truth crops.* The gap (b)−(a) is "what SAM adds"; (d)−(b) is "what
   SAM still misses". This is the cleanest and most defensible benchmark we can submit.
2. **Phone-photo preprocessing.** `"sheet of paper"` gives a page mask; its quadrilateral gives a
   perspective correction and background removal before any engine. Camera-GrandStaff and Camera-OSSQ show
   every engine degrades on photos (SMT 5.1 → 6.2 SER; Legato 1 33 → 58 OMR-NED on quartets; Audiveris
   65 → 75). Ablation: *engine on raw photo vs SAM-dewarped photo*. Needs real photos: CK shoots the
   fixture pages with an iPad (10–20 photos is enough), or we apply Camera-PrIMuS-style synthetic warps.
3. **Multi-piece and non-music regions.** Pages with two pieces, text blocks, or facing pages confuse
   full-page models (Transcoda, Legato). SAM masks for "sheet music" / "block of text" / "title" could
   pre-split pages. Smaller effect, harder to measure; third priority.

Where it will not help: barlines, noteheads, accidentals, rests (probe 2), and anything handwritten.

## 3. Where Muse Spark can help

1. **Post-OMR correction.** Give Spark the page image plus the engine's MusicXML (or kern) and ask for a
   corrected version, measured by OMR-NED before and after. Legato 2 showed the inverse (symbolic context
   improves VLM understanding by 3×); nobody has published "VLM fixes OMR output" numbers on SMB. Risk:
   Spark rewrites correct bars; mitigate by letting it only emit per-measure edits with a reason, and by
   accepting an edit only if it lowers a local cost. This is the experiment most likely to produce a
   headline number, and it is pure Meta tooling.
2. **Labelling** (first measure number, parts, rehearsal marks, title, tempo text): already works
   (grounding experiment). Legato 2 reports text CER as a separate metric (24.8 vs Audiveris 73.8); Spark
   on our pages read titles and Cyrillic correctly, so a text-CER row is cheap.
3. **Direct transcription baseline**: expected ≈ 90 OMR-NED like Gemini. One row, low effort, do it last.

## 4. Proposed benchmark

**Corpus (fixed, versioned in `api/experiments/omr-bench/corpus/`):**

| Tier | Pages | Ground truth | Purpose |
|---|---|---|---|
| A. Layout | our 2 pages + 8 more from the fixtures (Goldberg BGA ×3, Rach two-piano ×2, Dvořák full score ×2, Rach brass quintet ×1), hand-verified boxes | measure boxes (tap test) | what Folio needs first |
| B. Pianoform | Goldberg BGA Aria + Var. 1–3 (6–8 pages) vs Open Goldberg MusicXML (CC0) | MusicXML → kern via music21 | transcription accuracy on a real scan with clean GT |
| C. Quartet | 20–30 systems from OSSQ-OMR scans | LMX / kern | ensemble parts, the demo's Op. 18/1 case |
| D. Standard | SMB pianoform + quartet subsets (if HF access is granted in time) | kern | comparability with the literature |
| E. Photos | tiers A–B pages photographed with an iPad under room light, slight angle | same GT as A–B | the "with SAM dewarp" condition |

**Engines:** Audiveris 5.11, homr 0.7, SMT NeXt (grandstaff + camera + quartet weights), Zeus 2026, Transcoda,
and Spark-direct. Legato 1 only if a CUDA box is available (11B; not the Mac). oemer optional.

**Conditions per engine:** native / +SAM system crops / +OpenCV crops / +GT crops (tier A boxes);
raw photo / +SAM dewarp (tier E); output / +Spark correction (all tiers).

**Metrics:** OMR-NED and SER via musicdiff + music21 (SMB's own tooling), measure-box tap accuracy and
measure-count error (ours), text CER for titles and part names, wall time, $ per page.

**Output:** one results table + per-page JSON in the repo, an HTML report page, and a short write-up.
Submission angle: "A layout-first OMR benchmark on real scans and photos, with zero-shot SAM 3.1
segmentation and Muse Spark correction as plug-in stages for existing engines."

## 5. How to split it into sub-agents

Shared contract first (one session, half a day): corpus folders, `ground_truth.json` per page, a
`run_<engine>.py` interface that takes `page.png [--crops crops.json]` and writes `out/<engine>/<page>.musicxml`
plus optional `boxes.json`, and `evaluate.py` (musicdiff OMR-NED, SER, tap test, text CER) that every
engine's output goes through. Then one session per engine, each ending in a filled results row:

1. **Audiveris**: install the arm64 dmg, drive `-batch -transcribe -export -save`, parse `.omr` for
   system/measure bounds (so it also competes in tier A), run native and with pre-cropped systems.
2. **homr**: `uvx` install, native vs `--read-staff-positions` fed from SAM and from OpenCV, photos.
3. **SMT** (needs crops by construction): GT / SAM / OpenCV crops; three weight sets.
4. **Zeus** (needs staff crops): same three crop sources; 2026 snapshot.
5. **Transcoda**: full page at 1485×1050, native; then with SAM page mask / dewarp.
6. **Spark correction + Spark direct**: a corrector that takes any engine's MusicXML, scored on every
   engine's output; the direct-transcription row.
7. **Corpus + photos + GT** (can start now, blocks nobody after day one): music21 conversion of Open
   Goldberg, OSSQ-OMR download, SMB access request, iPad photos of the fixture pages.

Risks: SMB access is manual and may not arrive in time (tier D is optional); the Mac has no CUDA so Legato
is out unless Baseten/Modal credits run it; AGPL engines (Audiveris, homr, Transcoda) are fine to benchmark
and to call as separate processes, but Folio's own code should not import them.

## Sources

- Audiveris: https://github.com/Audiveris/audiveris (release 5.11.0, 2026-07-11); CLI reference
  https://audiveris.github.io/audiveris/_pages/guides/advanced/cli/
- homr: https://github.com/liebharc/homr, https://pypi.org/project/homr/ (0.7.0)
- oemer: https://github.com/BreezeWhite/oemer
- SMT: https://github.com/antoniorv6/SMT (weights antoniorv6/smt-grandstaff, smt-camera-grandstaff, smt-string-quartets)
- Zeus: https://github.com/OmniOMR/zeus
- Legato: https://arxiv.org/abs/2506.19065, https://github.com/guang-yng/legato, https://huggingface.co/guangyangmusic/legato
- Legato 2: https://arxiv.org/abs/2607.05769
- Transcoda: https://arxiv.org/abs/2605.10835, https://github.com/btrkeks/transcoda
- Sheet Music Benchmark: https://arxiv.org/abs/2506.10488, https://huggingface.co/datasets/PRAIG/SMB, https://grfia.dlsi.ua.es/smb/
- OSSQ-OMR: https://arxiv.org/abs/2608.10978, https://huggingface.co/datasets/jhlusko/ossq-omr-data
- Open Goldberg Variations (CC0): https://opengoldbergvariations.org/
- MeasureDetector: https://github.com/OMR-Research/MeasureDetector
- musicdiff (OMR-NED base): https://github.com/gregchapman-dev/musicdiff
