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

## MuseScore drops notes in six bars (A, B, D): the merge's voice numbers, not the music

CK spotted it in bar 16: A, B and D show an empty bass staff, C (OSMD) has the six bass octaves. The four
renderings do come from the same notes (`same_notes.py`: A, B, D inputs identical, bar 16's staff 2 included),
and the bass is in the file:

```
bar 16 (A-input.musicxml, divisions 10080, 3/4 = 30240):
  voice 1 staff 1: 7 chords = 30240         <backup>30240</backup>
  <forward>15120</forward> voice 2 staff 1: D4+D5, C#4+C#5 16ths   <backup>20160</backup>
  <forward>25200</forward> voice 3 staff 1: C#5, B4 16ths          <backup>30240</backup>
  voice 4 staff 2: E2+E3, C#2+C#3, F#2+F#3, B1+B2, E2+E3, E1+E2 eighths = 30240
  <note default-x="13"><pitch><step>E</step><octave>2</octave></pitch><duration>5040</duration>
        <voice>4</voice><type>eighth</type><stem>up</stem><staff>2</staff>
```

Every voice adds up to the bar, every note has its `<staff>`, every duration divides `divisions`. What breaks is
the voice numbering. Audiveris numbers per staff (raw `audiveris-p25.mxl`: voices 1-3 on staff 1, 5-6 on staff 2;
bar 16's bass is voice 5). `score.py`'s music21 merge re-exports the score and **music21 renumbers voices per
measure across both staves**: bar 16 becomes 1, 2, 3 upper and 4 lower, bar 1 is 1 upper and 2 lower. Over the
page, voice 2 is the bass in bars 1, 3, 6, 8, 11, 12 (115 notes on staff 2) and an upper voice in 9, 10, 13, 14,
16 (18 notes). MuseScore's importer ties each voice number to one staff for the whole part, so in bar 16 it
files voice 2 under the bass staff as cross-staff chords (`<staffMove>-1</staffMove>` in `A-musescore-layout.mscx`,
staff 2, bar 16) and loses voices 3 and 4: the measure keeps 23 of 37 notes. No warning: the import log holds only
the usual libjack lines.

`musescore_kept.py` (pitched notes in the input vs `<Note>`s in MuseScore's .mscx), A-input: **628 notes, 586
kept; short in bars 2 (25 → 20), 4 (29 → 24), 10 (44 → 40), 13 (39 → 32), 14 (57 → 50), 16 (37 → 23)**. B and D
carry the same voices. OSMD assigns voices per staff and draws everything, which is why C looks right in bar 16.
`same_notes.py` cannot catch this: it hashes the inputs, not what the engraver kept.

The end-repeat: **not in the file and not in the scan.** A-input's only repeats are the backward repeat closing
bar 8 and the forward repeat opening bar 9; bar 16 has no `<barline>`, and the scan's bar 16 ends in a plain
single barline (the section continues on the next page). OSMD draws an end-repeat after bar 16 to close the open
forward repeat; MuseScore, correctly, does not. The scan's two grace notes in bar 16 (before the D natural and
the A) are missing everywhere: Audiveris did not read them.

**Fix** (stage: the music21 merge, `score.py` here and the same `sc.write("musicxml")` in the app's
`omr_convert.py`; `apply_edits.py` writes through music21 again, so it needs the same pass): after writing,
renumber voices per staff, staff 1 voices 1-4 and staff 2 voices 5-8, as `../renumber_voices.py` does (each
voice of a measure goes to the staff holding most of its notes; a cross-staff note keeps its `<staff>`). A test:
across the part, no voice number may appear on two staves except as a minority cross-staff note.

**A2, hand patch:** `A2-musescore-layout-bar16fixed.pdf` from `A2-input.musicxml` = A-input through
`renumber_voices.py` (228 notes renumbered, nothing else; notes identical, the hash changes because voice numbers
are hashed). MuseScore keeps **628 of 628** notes; bar 16 has its bass, bars 2 and 4 their full bass, bars 10, 13,
14 their inner voices. Systems as A (p1: 1-3, 4-6, 7-9, 10, 11-13; p2: 14-16), 0.56 s.

The Goldberg set has the same defect: `../goldberg/same-file/D-input.musicxml` loses 23 of 414 notes in MuseScore
(bars 1, 4, 5, 6, 7, 9, 19, 29, 30, 32; bars 29 and 30 lose their whole bass line, which the Goldberg README had
put down to content), and keeps 414 of 414 after `renumber_voices.py`.

**F, the fix in the merge (2026-10-28):** `F-input.musicxml` = A-input through the app's `musicxml_fix`
(`../fix_inputs.py`: voices per staff, Audiveris's `<defaults>`, title "Polonaise Op. 40 No. 1" and composer
"F. Chopin" written into the credits). MuseScore keeps **628 of 628**, systems **1-3, 4-6, 7-10, 11-13, 14-16** on
one 240.2 x 318.9 mm page, as D and the scan; no "Music21". `G-input.musicxml` (music21 re-write, then the pass):
the same, 628 of 628, same systems.

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
- OSMD (C) draws an end-repeat after bar 16 that is neither in the file nor in the scan (see above).

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
- `/Users/ckjiang/Documents/muse/.claude/worktrees/agent-a6373b95fb192e74a/api/experiments/engrave/chopin-op40-1/A2-musescore-layout-bar16fixed.pdf` (hand patch: voices renumbered per staff)
- `/Users/ckjiang/Documents/muse/.claude/worktrees/agent-a6373b95fb192e74a/api/experiments/engrave/chopin-op40-1/scan-p25.png`
- `/Users/ckjiang/Documents/muse/.claude/worktrees/agent-a6373b95fb192e74a/api/fixtures/pdf/chopin-op40-1-p25.pdf`
