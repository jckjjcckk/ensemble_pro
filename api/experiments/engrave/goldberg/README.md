# Goldberg Aria: MuseScore Studio engraving vs what the iPad shows (2026-10-28)

Question for CK: is MuseScore's engraver worth adding to the pipeline (MusicXML in, PDF/PNG/SVG out, plus
measure positions and audio)? Every file here is the Aria, bars 1 to 32, except where a name says `p1-5`.
No Meta or Claude model calls, no accounts, nothing uploaded, nothing on hosted Supabase.

## What to compare

| File | What it is |
|---|---|
| `scan-p1.png` .. `scan-p5.png` | The BGA scan (`api/fixtures/pdf/goldberg-bga.pdf`), pages 1 to 5, 150 dpi. The Aria is p1 + top of p2. |
| `musescore-opengoldberg.pdf` | Reference: the Open Goldberg edition engraved by MuseScore. |
| `musescore-ours-layout.pdf` | Our Convert output (Audiveris + Spark text layer), Aria cut, engraved by MuseScore honouring the file's own system/page breaks (MuseScore's default). |
| `musescore-ours-reflow.pdf` | The same with breaks and `<defaults>` stripped: MuseScore lays it out itself. |
| `osmd-ours.pdf` | The reflow file engraved by OSMD 2.2.1 with ScoreStage's options, 1024 px page: what the iPad shows. |
| `osmd-ours-layout.pdf` | The layout file through OSMD; identical systems, because OSMD ignores `<print>` breaks (ScoreStage does not set `newSystemFromXML`). |
| `musescore-audiveris-raw.pdf` | Raw Audiveris 5.11 output (page 1 only, bars 1 to 28), no Spark, engraved by MuseScore. |
| `osmd-opengoldberg.pdf`, `osmd-audiveris-raw.pdf` | The other two inputs through OSMD, for a four-way grid. |
| `musescore-ours-p1-5.pdf`, `osmd-ours-p1-5.pdf` | The whole p1-5 Convert output (119 bars), file as written (keeps the scan's system breaks). |
| `musescore-ours-layout.mpos`, `musescore-ours-reflow.mpos` | MuseScore's measure positions (one box per bar, page index, 1/12 spatium units); `mpos_systems.py` turns them into bars per system. |
| `musescore-opengoldberg.mp3` | MuseScore's audio export of the reference Aria (MuseScore's basic soundfont). |

The side-by-side to open: `musescore-opengoldberg.pdf` | `musescore-ours-layout.pdf` | `musescore-ours-reflow.pdf` | `osmd-ours.pdf` | `scan-p1.png`.

## Inputs

- **Reference.** opengoldbergvariations.org links only to musescore.com (account to download) and IMSLP holds only
  the PDF. MuseScore ships the Open Goldberg score (Werner Schweer, 2012, with the Kickstarter dedications) as a
  demo in its own repo: `demos/goldberg.mscz` at tag v4.7.5
  (`https://raw.githubusercontent.com/musescore/MuseScore/v4.7.5/demos/goldberg.mscz`, 152,769 bytes). MuseScore
  converted it to `inputs/ref-full.musicxml` (990 measures, 4.9 s); `cut_measures.py` kept the first 32 measures.
- **Ours.** No Convert output exists on the box for p1-5 (`~/omr/folio005/p1-5` holds only the Audiveris
  movements). The final MusicXML of the p1-5 experiment run (`score.py` after A + B, `--gate-tag tuplet=0.9`) is on
  the Mac: `/Users/ckjiang/Documents/muse/.claude/worktrees/agent-a320325d43e43534d/api/experiments/omr/out/goldberg-p1-5-gate-tuplet09/final.musicxml`,
  copied as `inputs/ours-p1-5.musicxml` (119 bars) and cut to bars 1 to 32 as `inputs/ours-aria-layout.musicxml`
  (everything kept) and `inputs/ours-aria.musicxml` (stripped, the reflow input). The in-app
  `omr_convert` writes the same shape of file (ported code); its copy lives in local Supabase storage and was not used.
- **Raw Audiveris.** `~/omr/exp-audiveris/base/goldberg-bga.mxl` (page 1 alone, 28 bars) → `inputs/audiveris-raw-p1.musicxml`.

`--strip-layout` (used for the reference, the raw Audiveris file and our reflow input) removes every `<print>`
(system/page breaks, margins), measure widths, `<credit>`s and the whole `<defaults>` block, so each engraver lays
the music out by itself at its default staff size. MuseScore 4.7's converter has no flag to ignore a file's
layout (the MusicXML import options live in the GUI preferences), hence the script. The title was replaced by a
label naming the source. The p1-5 files are the file as written.

## Layout metadata in each input (`layout_report.py`)

| | `<defaults>` | `<print>` breaks | `<credit>` |
|---|---|---|---|
| Reference (`ref-full.musicxml`, MuseScore's export of the .mscz) | scaling 6.4 mm / 40 tenths, page-layout 1312.5 x 1856.25 tenths | whole set: 464 new-system, 114 new-page; Aria: 10 new-system, 2 new-page | 63 (title page "J. S. Bach / Goldberg-Variationen / BWV 988", "ARIA", subtitle, a Kickstarter dedication on each variation's first page, variation titles) |
| Raw Audiveris p1 (`goldberg-bga.mxl`, 28 bars) | scaling 6.7733 mm, page-layout 1434 x 1783 | 5 new-system, 0 new-page | 28: "Aria con Variazioni.", "S. Bach." and 26 OCR'd fingering digits and specks |
| Audiveris p1-5, movement 1 (`~/omr/folio005/p1-5/audiveris/goldberg-bga.mvt1.mxl`, 32 bars) | same as above | 5 new-system, 1 new-page (at 29) | the same 28 |
| Ours (`final.musicxml`, 119 bars) | scaling 7 mm / 40 tenths only (music21's default), **no page-layout** | 22 new-system, 4 new-page; Aria cut: 5 new-system, 1 new-page | **0** |

Systems as written (measure ranges; P = starts a page):

- Reference, Aria: 1-4, 5-8, 9-12, 13-15, 16, 17-19 P, 20-22, 23-25, 26, 27-28, 29, 30-31 P, 32. (Bar 1 carries
  page-number 2: page 1 of the edition is the title page. The one-bar systems 16, 26, 29, 32 are as exported; I did
  not check them against the .mscz in the GUI.)
- Raw Audiveris p1 and Audiveris mvt1: 1-6, 7-12, 13-16, 17-20, 21-24, 25-28, then 29-32 P.
- Ours p1-5: 1-6, 7-12, 13-16, 17-20, 21-24, 25-28 | 29-35 P, 36-38, 39-42, 43-45, 46-48 | 49-51 P, 52-54, 55-57,
  58-60, 61-69 | 70-72 P, 73-75, 76-78, 79-81, 82-90 | 91-95 P, 96-100, 101-105, 106-109, 110-114, 115-119. Pages
  start at 29, 49, 70, 91, matching the PDF pages.
- The scan, page 1 (eyeballed, `scan-p1.png`): 1-6, 7-12, 13-16, 17-20, 21-24, 25-28. Audiveris's breaks match it
  exactly.

**Which stage drops what.** The breaks are not missing: Audiveris writes them and `score.py`'s music21 merge keeps
every `new-system` / `new-page`. The merge does drop the rest of the layout: the `<page-layout>` (music21 writes its
own `<defaults>` with scaling only) and all 28 `<credit>`s, so our file has no title and no composer and music21
fills `<creator>` with "Music21". Losing the OCR'd credits costs nothing (26 of 28 are junk; Spark owns the text
layer), but the title and composer should be written back by the merge.

**Page 1 of each rendering vs the scan (1-6, 7-12, 13-16, 17-20, 21-24, 25-28):**

| Rendering | Page 1 systems | Same as scan? |
|---|---|---|
| `musescore-ours-layout.pdf` | 1-6, 7-10, 11-12, 13-16, 17-20 (then p2: 21-24, 25-28; p3: 29-32) | Every scan break is honoured, but 7-12 does not fit MuseScore's default Letter page and staff size, so it adds a break at 11 (11-12 is stretched across a whole line) and 21-24 moves to page 2. 4 of 6 systems match, not the page. |
| `musescore-ours-reflow.pdf` | 1-6, 7-10, 11-15, 16-19, 20-23 | Only the first system matches. |
| `musescore-opengoldberg.pdf` (reflow) | 1-5, 6-10, 11-15, 16-19, 20-23 | No. |
| `musescore-audiveris-raw.pdf` (reflow) | 1-6, 7-10, 11-14, 15-18, 19-22 | Only the first system. |
| `osmd-ours.pdf` and `osmd-ours-layout.pdf` | 1-5, 6-9, 10-13, 14-16 | No; identical with and without breaks. |

MuseScore with the file's layout is the only renderer that follows the scan's lines; to match the scan's page as
well, the merge would have to keep Audiveris's `<page-layout>` and scaling (or MuseScore be given a smaller
spatium).

## Commands

Box (`ssh omr`, Ubuntu 24.04, no sudo, nothing installed system-wide):

```bash
mkdir -p ~/omr/musescore && cd ~/omr/musescore
curl -sSLO https://github.com/musescore/MuseScore/releases/download/v4.7.5/MuseScore-Studio-4.7.5.260831071-x86_64.AppImage
# sha256 a31b2da2dbcc2191bcc98beb7be5c15f2f517bedb3444def96fe3088b74d3a1e, 194,411,000 bytes, 2 s download
chmod +x MuseScore-Studio-*.AppImage && ./MuseScore-Studio-*.AppImage --appimage-extract   # squashfs-root/, 566 MB
MU_QT_QPA_PLATFORM=offscreen squashfs-root/AppRun --long-version   # Version 4.7.5; Build 3654226
MU_QT_QPA_PLATFORM=offscreen squashfs-root/AppRun -o ref/ref-full.musicxml ref/goldberg.mscz
# then, per output (api/experiments/engrave/musescore_render.sh, copied to ~/omr/musescore/scripts/):
~/omr/musescore/scripts/musescore_render.sh musescore-ours-layout.pdf ours-aria-layout.musicxml
~/omr/musescore/scripts/musescore_render.sh musescore-ours-reflow.pdf ours-aria.musicxml
```

Mac:

```bash
cd api/experiments/engrave
python3 -I cut_measures.py goldberg/inputs/ref-full.musicxml goldberg/inputs/ref-aria.musicxml 32 --title "..." --strip-layout
python3 -I cut_measures.py goldberg/inputs/ours-p1-5.musicxml goldberg/inputs/ours-aria.musicxml 32 --title "..." --strip-layout
python3 -I cut_measures.py goldberg/inputs/ours-p1-5.musicxml goldberg/inputs/ours-aria-layout.musicxml 32 --title "..."
python3 -I layout_report.py goldberg/inputs/ours-p1-5.musicxml        # defaults, credits, breaks, systems
python3 -I mpos_systems.py goldberg/musescore-ours-layout.mpos         # bars per system as MuseScore engraved them
python3 -I cut_measures.py goldberg/inputs/goldberg-bga.mxl goldberg/inputs/audiveris-raw-p1.musicxml 9999 --title "..." --strip-layout
./osmd_render.sh goldberg/inputs/ours-aria.musicxml goldberg/osmd-ours.pdf    # headless Google Chrome, no Playwright
# scans: pymupdf page.get_pixmap(dpi=150) on pages 0..4 of api/fixtures/pdf/goldberg-bga.pdf (uv run --project api)
```

`osmd_page.py` writes a self-contained page: the MusicXML inlined, OSMD from `web/node_modules`, the constructor
options copied from `web/src/app/ScoreStage.tsx` (titles off, part names and bar numbers on), then
`setPageFormat('1000x1414')`, `zoom = 1.0`, `render()`, each OSMD page printed as one 1024 x 1448 px PDF page. The
app picks the page aspect from the iPad's viewport and the zoom from the reader's scale; 1.0 and A4-like is the
neutral setting, so staff size here is OSMD's default, not a particular iPad.

## Timings and sizes

MuseScore 4.7.5 on the box (16 cores), wall clock per call, including app start:

| Output | Input | Wall | Size |
|---|---|---|---|
| `musescore-opengoldberg.pdf` (2 pages) | ref-aria, 32 bars | 0.54 s | 75,999 |
| `musescore-ours-layout.pdf` (3 pages) | ours-aria-layout, 32 bars | 0.59 s | 74,654 |
| `musescore-ours-reflow.pdf` (2 pages) | ours-aria, 32 bars | 0.56 s | 74,144 |
| `musescore-ours-p1-5.pdf` (10 pages) | ours-p1-5, 119 bars | 0.85 s | 178,580 |
| `musescore-audiveris-raw.pdf` (2 pages) | audiveris-raw-p1.musicxml, 28 bars | 0.55 s | 77,540 |
| same, straight from `goldberg-bga.mxl` | `.mxl` | 0.61 s | 85,519 (not kept) |
| `musescore-ours-layout.mpos` / `-reflow.mpos` | ours-aria-layout / ours-aria | 0.56 s / 0.54 s | 6,665 / 6,674 |
| `musescore-opengoldberg.mp3` (2:43 of audio, both halves repeated) | ref-aria | 6.77 s | 2,608,900 |
| PNG, one file per page (300 dpi default) | ref-aria / ours-aria | 10.1 s / 10.3 s | 2.9 MB + 0.9 MB per score (left on the box) |
| `ref-full.musicxml` | `goldberg.mscz`, whole set | 4.9 s (first run) | 7,840,629 |

OSMD 2.2.1 in headless Google Chrome on the Mac (`osmd_ms` = load + render inside the page under Chrome's
virtual time, so read it as indicative only; wall = two Chrome launches, one to read the DOM and one to print):

| Output | osmd_ms | Pages | Wall | Size |
|---|---|---|---|---|
| `osmd-ours.pdf` | 101 | 3 | 1.25 s | 289,327 |
| `osmd-ours-layout.pdf` | 104 | 3 | 1.28 s | 289,334 |
| `osmd-opengoldberg.pdf` | 98 | 3 | 1.39 s | 272,009 |
| `osmd-audiveris-raw.pdf` | 97 | 3 | 1.35 s | 265,772 |
| `osmd-ours-p1-5.pdf` | 236 | 10 | 1.80 s | 917,500 |

Scans: `scan-p1.png` 441,596; `-p2` 431,553; `-p3` 416,452; `-p4` 314,042; `-p5` 328,609 bytes.

The mp3 length is from `afinfo` (163 s); MuseScore plays the repeats.

## What failed, and gotchas

- `QT_QPA_PLATFORM=offscreen` is **ignored**: MuseScore 4.7 picks xcb and aborts ("no Qt platform plugin could be
  initialized", xcb needs libxcb-cursor0, which is not installed). It reads its own variable,
  **`MU_QT_QPA_PLATFORM=offscreen`** (found with `strings` on the binary). With it, no xvfb and no apt install.
  FUSE works on the box (the AppImage mounts), but the extracted `squashfs-root/AppRun` is used to skip the mount.
- `-platform offscreen` is taken as a second input file. `libjack.so.0` is missing; the AppImage's fallback is used, harmless.
- MusicXML input works as `.musicxml` and as `.mxl`.
- MuseScore prints the file's `<creator type="composer">` as the composer: ours shows "Music21" top right (music21
  writes that when the score has no composer); the raw Audiveris file shows the OCR'd "S. Bach.". Worth fixing in
  `score.py` / `omr_score` either way (write Bach, or no creator).
- Content, not engraving, visible in both renderers: our bars 29 and 30 have an empty bass staff (page 2's first
  system), and the scan's "Andante espressivo" (which raw Audiveris read) is gone, leaving only quarter = 72.
- No Playwright: headless Google Chrome (`/Applications/Google Chrome.app`) with `--print-to-pdf` and
  `--virtual-time-budget` was enough. Verovio was not needed.
- Not done: musescore.com PDF import (cloud, account; skipped by rule).

## What differs visibly (MuseScore vs OSMD, same file)

Reflowed, MuseScore fits our Aria on 1.5 pages at 4 to 6 bars per system (bars 1 to 23 on page 1), close to the
reference's own density, while OSMD at its default size needs 3 pages at 3 to 5 bars a system with the staff
drawn much larger. MuseScore's spacing is tight and even, with the two voices of each hand stacked compactly, while OSMD
spreads the same bars wide, parks the inner-voice rests far from their notes and draws the long phrase slurs of
bars 7 to 11 as large arcs above and below the system. MuseScore puts *p dolce*, *cresc.*, *mf* and *f* under the staff in the bar they belong to; OSMD also
places them by bar, but lets *cresc.* hang past the right margin at the end of a system (bar 9) and puts the *tr* of
bar 15 below the bass staff instead of between the staves.

## Paths (absolute)

Committed:
- `/Users/ckjiang/Documents/muse/.claude/worktrees/agent-a6373b95fb192e74a/api/experiments/engrave/goldberg/musescore-opengoldberg.pdf`
- `/Users/ckjiang/Documents/muse/.claude/worktrees/agent-a6373b95fb192e74a/api/experiments/engrave/goldberg/musescore-ours-layout.pdf`
- `/Users/ckjiang/Documents/muse/.claude/worktrees/agent-a6373b95fb192e74a/api/experiments/engrave/goldberg/musescore-ours-reflow.pdf`
- `/Users/ckjiang/Documents/muse/.claude/worktrees/agent-a6373b95fb192e74a/api/experiments/engrave/goldberg/musescore-audiveris-raw.pdf`
- `/Users/ckjiang/Documents/muse/.claude/worktrees/agent-a6373b95fb192e74a/api/experiments/engrave/goldberg/musescore-ours-p1-5.pdf`
- `/Users/ckjiang/Documents/muse/.claude/worktrees/agent-a6373b95fb192e74a/api/experiments/engrave/goldberg/musescore-ours-layout.mpos`, `musescore-ours-reflow.mpos`
- `/Users/ckjiang/Documents/muse/.claude/worktrees/agent-a6373b95fb192e74a/api/experiments/engrave/goldberg/osmd-ours.pdf`
- `/Users/ckjiang/Documents/muse/.claude/worktrees/agent-a6373b95fb192e74a/api/experiments/engrave/goldberg/osmd-ours-layout.pdf`
- `/Users/ckjiang/Documents/muse/.claude/worktrees/agent-a6373b95fb192e74a/api/experiments/engrave/goldberg/osmd-opengoldberg.pdf`
- `/Users/ckjiang/Documents/muse/.claude/worktrees/agent-a6373b95fb192e74a/api/experiments/engrave/goldberg/osmd-audiveris-raw.pdf`
- `/Users/ckjiang/Documents/muse/.claude/worktrees/agent-a6373b95fb192e74a/api/experiments/engrave/goldberg/osmd-ours-p1-5.pdf`
- `inputs/ref-aria.musicxml`, `inputs/ours-aria.musicxml`, `inputs/ours-aria-layout.musicxml`, `inputs/audiveris-raw-p1.musicxml`, `inputs/goldberg-bga.mxl`

On disk only (ignored by `goldberg/.gitignore`: large, or copies of files that live elsewhere):
- `/Users/ckjiang/Documents/muse/.claude/worktrees/agent-a6373b95fb192e74a/api/experiments/engrave/goldberg/scan-p1.png` .. `scan-p5.png`
- `/Users/ckjiang/Documents/muse/.claude/worktrees/agent-a6373b95fb192e74a/api/experiments/engrave/goldberg/musescore-opengoldberg.mp3`
- `/Users/ckjiang/Documents/muse/.claude/worktrees/agent-a6373b95fb192e74a/api/experiments/engrave/goldberg/inputs/ref-full.musicxml`
- `/Users/ckjiang/Documents/muse/.claude/worktrees/agent-a6373b95fb192e74a/api/experiments/engrave/goldberg/inputs/ours-p1-5.musicxml`

On the box: MuseScore stays installed at `~/omr/musescore/` (AppImage + `squashfs-root/`), renders and PNGs in
`~/omr/musescore/goldberg/`, the demo score in `~/omr/musescore/ref/goldberg.mscz`.

## Same file, three renderers (`same-file/`)

Every PDF here starts from `inputs/ours-aria-layout.musicxml` (our Convert output, bars 1-32, breaks kept),
copied as `same-file/A-input.musicxml`; only the renderer changes. `same_notes.py` hashes every measure's
content minus `<print>`: A, B and D inputs all give `ae2f5b00e83e51af`, 441 notes.

| File | Input | Page 1 systems (scan: 1-6, 7-12, 13-16, 17-20, 21-24, 25-28) | Pages | Wall |
|---|---|---|---|---|
| `A-musescore-layout.pdf` | A-input, as is | 1-6, 7-10, 11-12, 13-16, 17-20 | 3 (Letter) | 0.57 s |
| `B-musescore-reflow.pdf` | `B-input.musicxml` = A stripped (`cut_measures.py --strip-layout`: no `<print>`, no `<defaults>`) | 1-6, 7-10, 11-15, 16-19, 20-23 | 2 (Letter) | 0.56 s |
| `C-osmd.pdf` | A-input, OSMD as the iPad draws it | 1-5, 6-9, 10-13, 14-16 (from the image) | 3 | 1.38 s |

Preview of the merge fix, not part of the three: `D-musescore-layout-pagesize.pdf` from `D-input.musicxml` =
A-input plus Audiveris's `<defaults>` (scaling 6.7733 mm / 40 tenths, page 1434 x 1783 tenths, margins 80) and two
`<credit>`s, title "Aria" and composer "J. S. Bach" (`restore_defaults.py`). MuseScore then reproduces the scan
exactly: page 1 is 1-6, 7-12, 13-16, 17-20, 21-24, 25-28, page 2 is 29-32, on a 242.7 x 301.9 mm page (the
scan's size), 0.60 s. So the only thing between our file and a page-faithful MuseScore engraving is that the
`score.py` merge drops Audiveris's `<defaults>` and credits.

**E, hand patch (not pipeline output): `same-file/E-musescore-text-fixed.pdf`** from `same-file/E-input.musicxml` =
D-input with the text layer fixed by hand (`same-file/hand_patch_text.py`): the tempo moved to the head of bar 1 as
one direction, bold "Andante espressivo." plus the metronome (quarter = 72) and `<sound tempo="72"/>`; the bar 2
metronome removed; `font-style="italic"` on the six expression words (dolce, cresc. x3, dim., cresc. poco); bar 27's
"cresc." and "poco" joined into one "cresc. poco". 441 notes, untouched (the `same_notes.py` hash changes to
`c38c505683cdc6ba` only because it hashes the directions too). MuseScore draws "Andante espressivo. (♩ = 72)" above
bar 1 at the head of the piece and *dolce*, *cresc.*, *cresc. poco*, *dim.* in italics; systems unchanged
(1-6, 7-12, 13-16, 17-20, 21-24, 25-28 | 29-32), 0.57 s, 76,004 bytes.

## CK's ratings, 2026-10-28

- A: page 1 90/100, pages 2-3 60/100 (page 1 smooth even with line 2 split in two; page 2 has only 2 lines and page 3 one line; cresc./poco look typed, not Italian).
- B: presentation 95/100, format preservation 30/100 (page 2 has 3 lines evenly spread with huge gaps; idea: a conversion toggle "Reformat the page to fit digital display", auto-on, stored as metadata of the converted book).
- C: presentation 80/100 (elongated page, hands too far apart, layout wrong, but even spacing across lines is excellent: 4 + 4 + 1 lines with empty space below).
- D: 95/100 on both presentation and layout, the most accurate transcription so far.

## Why the Aria's text layer underperforms (from the run's own files)

Run: `/Users/ckjiang/Documents/muse/.claude/worktrees/agent-a320325d43e43534d/api/experiments/omr/out/goldberg-p1-5-gate-tuplet09/`
(`audiveris/goldberg-bga.mvt1.mxl`, `model.json`, `reread.json`, `edits.json`, `base.musicxml`, `final.musicxml`).
Probe: `text-layer/spark_probe.py`, 2 Spark calls, $0.031 (`text-layer/spend.json`).

### (a) "Andante espressivo. (♩ = 72.)" lost, the metronome mark on bar 2

1. **Audiveris read it, on the wrong bar.** Raw `mvt1.mxl`, measure 2:
   `<words default-y="52" relative-x="-160" font-family="serif" font-size="12" font-weight="bold">Andante espressivo. </words>`
   in the same `<direction placement="above">` as `<metronome parentheses="yes"><beat-unit>quarter</beat-unit><per-minute>72.</per-minute>`
   and `<sound tempo="72">`. The heading starts over bar 1 (the model has the word "Andante" in bar 1,
   "espressivo." in bar 2) but Audiveris anchors the sentence to a chord in bar 2 and pulls it back with
   `relative-x="-160"`.
2. **`score.py` (music21) splits it**: in `base.musicxml` measure 2 holds two directions, the `<words>` and a
   separate `<metronome>`; the `relative-x` that drew it over bar 1 survives only on the words.
3. **`apply_edits.py` deletes the words and keeps the metronome.** B replaces every Audiveris word in the bars of a
   system Spark answered; `clear_text()` removes `TextExpression`s and `Dynamic`s, not `MetronomeMark`s.
   `edits.json`: `"B-clear", "number": 2, "what": "dropped Audiveris text ['Andante espressivo.']"`. `final.musicxml`
   measure 2: `<direction placement="above"> … <metronome parentheses="yes"> … <per-minute>72</per-minute>`, with no
   offset back, so every renderer draws it over bar 2.
4. **Spark was never asked.** `REREAD_PROMPT` says "Do NOT include … tempo headings (e.g. "Allegretto")", and the
   system crop (`pad_y=4` interlines, origin y 324 px on page 1) starts below the heading line. `reread.json` p1
   sys1 answers only `[{"text": "p", …, "bar": 1}, {"text": "dolce", …, "bar": 1}]`.
5. **Spark can read it.** Probe on system 1 padded to 8 interlines with a "heading" question:
   `{"text": "Andante espressivo. (♩=72.)", "x0": 78, "y": 57, "bar": 1}`, exact, on bar 1. (Chopin p25 shows the
   other failure: Audiveris never OCR'd "Allegro con brio" at all, so only Spark could supply it.)

**Fix.** `spark_layers.py` (and `omr_spark.py` in the app): for the first system of each movement, crop with
`pad_y=8` (or up to the page top) and ask for a `heading` list (text, left edge `x0`, bar); place it by its left
edge, not its centre (`text_place.bar_at(x0)`), which also fixes Audiveris's bar-2 anchor. `apply_edits.py`: write
it as `tempo.MetronomeMark(text=…, number=72, referent=quarter)` at offset 0 of that bar (music21 then writes the
bold words and the metronome at the head of the bar, checked), and make `clear_text()` also remove Audiveris's
`MetronomeMark`s in bars Spark answered, so the old one in bar 2 cannot survive. When Spark gives no heading,
keep Audiveris's words + metronome together and move them to the bar under the words' left edge.

### (b) Every fingering digit is missing

1. **Audiveris reads some digits but never as fingering.** No `<fingering>` anywhere in `mvt1.mxl`,
   `base.musicxml` or `final.musicxml`. On page 1 the OCR'd digits mostly become page-level `<credit-words>` (26 of
   the 28 credits are digits and specks: `<credit-words … font-weight="bold">3</credit-words>`, `>2<`, `>4<`,
   `>21<`, `>4 2<` …), a few become bar text (`<words …>1 2 3</words>` bar 28, `<words …>g 4</words>` bar 23), and
   `model.json` has them as `word` inters with digit values (`(10, '3')`, `(20, '5')`, `(23, '21')` …).
2. **The merge drops the credits** (`score.py` builds a new score from the parts; music21 does not carry `<credit>`),
   and **B deletes the bar words**: `edits.json` `"dropped Audiveris text ['1 2 3']"` (bar 28), `['g 4', 'f']` (bar 23).
3. **Spark is told to skip them**: `REREAD_PROMPT`, "Do NOT include fingering digits", and `apply_edits.py` has no
   code that writes `articulations.Fingering`. So the layer was never designed to add fingering; nothing writes it.
4. **Spark can read them.** Probe, same crops plus a "fingering" question (digits, bar, staff, note index, grace):
   system 1 (bars 1-6): 16 items returned against 17 printed groups, every one in the right bar and staff, no
   invention; missed the "15" in bar 2 and merged bar 6's "2" (on the grace note) and "1" (on the A) into "21".
   System 6 (bars 25-28): 12 of 12, right bar and staff. Its x drifts
   by up to 100 on the 1000 grid (bar 1's "2" at 212 against about 110), so the bar/staff/note index is the anchor,
   not the point. The standard crop (pad 4) clips the bass "4" at the bottom of bar 27.

**Fix.** `spark_layers.py`: add a `fingering` list to the B prompt (or its own call per system), crop pad 6 so
digits below the bass staff are in frame. `apply_edits.py`: append `articulations.Fingering(d)` to the
`note_index`-th notehead of that staff (all voices by onset, chord once, grace notes counted), one per digit for a
stacked group on a chord (top digit to top note), skip and log when the index is out of range, like the ornaments;
music21 then writes `<technical><fingering>` (checked). Snap the position to Audiveris's digit `word` inters within
2 interlines when there is one. Cost: one more list in the existing 6 calls a page (output +~1k tokens), or +$0.015
a system as a separate call. Product note: fingering is editorial; a reader toggle "show fingering" is cheap once
it is in the file.

### (c) "cresc." and "poco" look typed

1. **Audiveris had the style; the B layer drops it.** Raw/base: `<words default-y="-83" font-family="serif"
   font-size="11" font-style="italic" relative-x="0">creso.</words>` (bar 29), `<words … font-style="italic" …>cresc.
   poco</words>`. Spark replaces the text (right: "creso." is OCR garbage), and `apply_edits.py` writes a bare
   `expressions.TextExpression(word)`, so `final.musicxml` has `<words>cresc.</words>`, `<words>poco</words>`,
   `<words>dolce</words>`, no `font-style`. MuseScore imports a plain `<words>` as upright staff text: hence "typed".
2. **One phrase becomes several directions.** The prompt asks "one item per word", so "cresc. poco" in bar 27 is two
   items, placed by `text_place.py` on different staves (`+'cresc.' staff 1 below at 1.5`, `+'poco' staff 2 above
   at 2.5`), and "cresc. poco a poco" later becomes four directions (`cresc.`, `poco`, `a`, `poco`).

**Fix.** `apply_edits.py`, B-text: for `kind == "words"` set `el.style.fontStyle = "italic"` (music21 writes
`<words font-style="italic">`, checked); keep tempo headings bold upright. `spark_layers.py`: ask for one item per
expression phrase ("cresc. poco a poco" is one item), and in `text_place.py` join adjacent items of one system
whose y differs by under one interline and whose gap is under 3 interlines, as a safety net. E (above) shows the
result in MuseScore.
