# Chopin Polonaise Op. 40 No. 1, "3b" (Ekier), one page through Convert and four engravings (2026-10-28)

Source: `api/fixtures/pdf/chopin-polonaises-ekier.pdf`, PDF page 25 (printed page 34, PWM-9386): "3b", op. 40
nr 1, second version ("Druga wersja"), Allegro con brio, bars 1 to 16 in five systems. Cut to a one-page PDF with
PyMuPDF as `api/fixtures/pdf/chopin-op40-1-p25.pdf` (gitignored, like every fixture PDF).

**The page does not start with the previous piece.** Page 25 opens directly with "3b" and Allegro con brio; the
last system of the previous version (bars 87 to 105 or so) is the bottom of PDF page 24. So Audiveris saw one
piece and wrote one movement (16 bars, 5 systems, system breaks exactly the scan's); no movement split to report.

Same pipeline, same settings as `goldberg-p1-5-gate-tuplet09/final.musicxml`: `book_box.py` on the box (one book,
no `-sheets`), 300 dpi scan, then `pipeline.py RUN --gate 0.6 --gate-tag tuplet=0.9` (A verify + B per-system
reread, effort low, 8k budget, 6 in flight), `score.py` merge, `apply_edits.py`. The only difference is the text
ground truth: none exists for this page, so an empty one (`run/text_gt_empty.json`) lets `compare.py` run; its
text F1 of 0 means nothing.

## Page 1 systems against the scan

Scan: **1-3, 4-6, 7-10, 11-13, 14-16** (one page).

| File | Renderer, input | Systems | Pages | Same as scan? |
|---|---|---|---|---|
| `A-musescore-layout.pdf` | MuseScore 4.7.5, `A-input.musicxml` (our file as written, breaks kept) | p1: 1-3, 4-6, 7-9, 10, 11-13; p2: 14-16 | 2 (Letter) | Every scan break honoured, but 7-10 does not fit the Letter page at MuseScore's staff size: bar 10 gets a line of its own, stretched, and 14-16 goes to page 2. 4 of 5 lines match, not the page. |
| `B-musescore-reflow.pdf` | MuseScore, `B-input.musicxml` (A stripped: no `<print>`, no `<defaults>`) | 1-4, 5-8, 9-11, 12-14, 15-16 | 1 (Letter) | No line matches. |
| `C-osmd.pdf` | OSMD 2.2.1 as the iPad draws it, A-input | p1: 1-2, 3-4, 5-7, 8-9; p2: 10-11, 12-13, 14-15, 16 | 2 | No line matches; 2 to 3 bars a line. |
| `D-musescore-layout-pagesize.pdf` | MuseScore, `D-input.musicxml` = A plus Audiveris's `<defaults>` and two credits | **1-3, 4-6, 7-10, 11-13, 14-16** | **1** | **Yes, exactly**, like the Goldberg D. |

Systems from MuseScore's `.mpos` (`mpos_systems.py`); C read from the image. `same_notes.py`: A, B and D inputs all
give `41529209d8c013f7`, 641 notes. D's `<defaults>`: scaling 7.112 mm / 40 tenths, page 1352 x 1793 tenths, so
the D page is 240.2 x 318.9 mm, about 13 % larger than the PDF page (212.0 x 290.3 mm): Audiveris sizes the page
from its own staff height, not the paper. Title "Polonaise Op. 40 No. 1", composer "F. Chopin". Audiveris's own 8
credits ("op. 40 M1", "* Druga wersja", "* Second version", the footnotes, "PWM-9386", "34") are not carried.

## What the transcription gets wrong (all four files, it is the content)

- **"Allegro con brio" is missing.** Audiveris did not OCR it at all (no word inter on the page reads it; its words
  are the header, footnotes and footer), and Spark's B prompt forbids tempo headings. Same root cause as the
  Goldberg tempo, see `../goldberg/README.md`, "Why the Aria's text layer underperforms".
- **Stray ">" and "<" glyphs in bars 4, 5, 6.** Spark's reread of system 2 returned the hairpins as text items
  (`{"text": ">", "x": 239, "y": 358, "bar": 4}`, `"<"` in 5, `">"` in 6), and `apply_edits.py` wrote them as
  `<words>&gt;</words>` / `<words>&lt;</words>`. Audiveris already had those hairpins as `<wedge>`s, which are kept,
  so they are drawn twice: once as a hairpin, once as a typed character. Fix: drop text items with no letter in
  `text_place.place` (or say "hairpins are not text" in the prompt).
- The *f* of bar 1 is right (Spark, snapped to Audiveris's glyph). No fingering on this page, nothing lost there.
- Flagged for review: bars 2, 4 (upper staff fills 3/2 of 3/4), 12 (Audiveris abnormal), 13, 14 (both staves short).
  Bars 13 and 14, with the double-sharp chords and the triplets across the staves, are visibly wrong in every render.
- A and B print "Music21" as the composer (the merge's `<creator>`); C hides titles; D carries "F. Chopin".
- OSMD (C) draws an end-repeat after bar 16 that is not in the file: the forward repeat at bar 9 opens a section
  whose closing repeat is on the next PDF page, and OSMD appears to close the open repeat at the end of the file
  (MuseScore does not).

## Spark (Muse Spark 1.3)

| Pass | Calls | Cost | Wall (summed) | Max output tokens | Retries | Truncated |
|---|---|---|---|---|---|---|
| A verify (11 symbols under the gate: 10 tuplets, 1 wedge) | 11 | $0.041 | 16.8 s (76.5 s) | 1845 | 0 | 0 |
| B reread (5 systems) | 5 | $0.047 | 16.1 s (60.0 s) | 2240 | 0 | 0 |
| total | 16 | **$0.088** | 32.9 s | | 0 | 0 |

Projection before the calls: 11 + 5 calls at the p1-5 rates, about $0.10, under the $0.60 stop. Every tuplet
under the 0.9 tuplet gate was a real triplet and Spark said so (all "tuplet_number '3' (high)"), so the
`--gate-tag tuplet=0.9` that saved the Goldberg run from false triplets cost 10 calls here and changed nothing:
no A edits. Audiveris skipped under the gate: 56 (29 augmentation dots, 13 wedges, 13 rests, 1 dynamic).

## Timings and sizes

| Step | Where | Wall | Output |
|---|---|---|---|
| Audiveris 5.11, one-page book | box | 24.0 s | `inputs/audiveris-p25.mxl` 11,480 |
| Mac pipeline (model, Spark A + B, merge, edits, review, Verovio render, compare) | Mac | 37.7 s (4.1 s on the cached re-run) | `inputs/ours-p25.musicxml` 247,470 |
| `A-musescore-layout.pdf` | box | 0.57 s | 63,961 |
| `B-musescore-reflow.pdf` | box | 0.55 s | 55,999 |
| `D-musescore-layout-pagesize.pdf` | box | 0.57 s | 53,508 |
| `.mpos` A / B / D | box | 0.56 / 0.52 / 0.55 s | 2,923 / 2,915 / 2,886 |
| `C-osmd.pdf` (osmd_ms 105) | Mac, headless Chrome | 2.03 s | 313,401 |
| `scan-p25.png` (150 dpi, PyMuPDF) | Mac | | 376,668 (gitignored: Ekier is a copyrighted edition) |

## Commands

```bash
# Mac (api/)
uv run python -c "import pymupdf; s=pymupdf.open('…/chopin-polonaises-ekier.pdf'); d=pymupdf.open(); \
  d.insert_pdf(s, from_page=24, to_page=24); d.save('fixtures/pdf/chopin-op40-1-p25.pdf')"
# box
python3 -I ~/omr/chopin-op40-1/scripts/book_box.py pdf/chopin-op40-1-p25.pdf ~/omr/chopin-op40-1/p25/audiveris --pages 1-1
pdftoppm -r 300 -png -f 1 -l 1 pdf/chopin-op40-1-p25.pdf p25/page300      # -> RUN/scan/page300-01.png
# Mac
uv run python experiments/omr/pipeline.py experiments/omr/out/chopin-op40-1-p25 --cap 0.60 --gate 0.6 \
  --gate-tag tuplet=0.9 --text-gt …/text_gt_empty.json --title "Chopin Polonaise Op. 40 No. 1 …"
cd experiments/engrave
python3 -I cut_measures.py chopin-op40-1/inputs/ours-p25.musicxml chopin-op40-1/A-input.musicxml 9999 --title "…"
python3 -I cut_measures.py chopin-op40-1/inputs/ours-p25.musicxml chopin-op40-1/B-input.musicxml 9999 --title "…" --strip-layout
python3 restore_defaults.py chopin-op40-1/A-input.musicxml chopin-op40-1/inputs/audiveris-p25.mxl \
  chopin-op40-1/D-input.musicxml --title "Polonaise Op. 40 No. 1" --composer "F. Chopin"
~/omr/musescore/scripts/musescore_render.sh A-musescore-layout.pdf A-input.musicxml   # box, and B, D, .mpos
./osmd_render.sh chopin-op40-1/A-input.musicxml chopin-op40-1/C-osmd.pdf
python3 -I same_notes.py chopin-op40-1/{A,B,D}-input.musicxml
python3 -I mpos_systems.py chopin-op40-1/*.mpos
```

`run/` holds the run's small files (verify, reread, edits, flags, spend, timings, run.json, the pipeline logs); the
whole run directory is `api/experiments/omr/out/chopin-op40-1-p25/` (gitignored, with `review.html`), the box copy
`~/omr/chopin-op40-1/` and `~/omr/musescore/chopin-op40-1/`.

## Paths (absolute)

- `/Users/ckjiang/Documents/muse/.claude/worktrees/agent-a6373b95fb192e74a/api/experiments/engrave/chopin-op40-1/A-musescore-layout.pdf`
- `/Users/ckjiang/Documents/muse/.claude/worktrees/agent-a6373b95fb192e74a/api/experiments/engrave/chopin-op40-1/B-musescore-reflow.pdf`
- `/Users/ckjiang/Documents/muse/.claude/worktrees/agent-a6373b95fb192e74a/api/experiments/engrave/chopin-op40-1/C-osmd.pdf`
- `/Users/ckjiang/Documents/muse/.claude/worktrees/agent-a6373b95fb192e74a/api/experiments/engrave/chopin-op40-1/D-musescore-layout-pagesize.pdf`
- `/Users/ckjiang/Documents/muse/.claude/worktrees/agent-a6373b95fb192e74a/api/experiments/engrave/chopin-op40-1/scan-p25.png`
- `/Users/ckjiang/Documents/muse/.claude/worktrees/agent-a6373b95fb192e74a/api/fixtures/pdf/chopin-op40-1-p25.pdf`
