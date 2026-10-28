# Goldberg Aria: MuseScore Studio engraving vs what the iPad shows (2026-10-28)

Question for CK: is MuseScore's engraver worth adding to the pipeline (MusicXML in, PDF/PNG/SVG out, plus
measure positions and audio)? Every file here is the Aria, bars 1 to 32, except where a name says `p1-5`.
No Meta or Claude model calls, no accounts, nothing uploaded, nothing on hosted Supabase.

## What to compare

| File | What it is |
|---|---|
| `scan-p1.png` .. `scan-p5.png` | The BGA scan (`api/fixtures/pdf/goldberg-bga.pdf`), pages 1 to 5, 150 dpi. The Aria is p1 + top of p2. |
| `musescore-opengoldberg.pdf` | Reference: the Open Goldberg edition engraved by MuseScore. |
| `musescore-ours.pdf` | Our Convert output (Audiveris + Spark text layer), Aria cut, engraved by MuseScore. |
| `osmd-ours.pdf` | The same file engraved by OSMD 2.2.1 with ScoreStage's options, 1024 px page: what the iPad shows. |
| `musescore-audiveris-raw.pdf` | Raw Audiveris 5.11 output (page 1 only, bars 1 to 28), no Spark, engraved by MuseScore. |
| `osmd-opengoldberg.pdf`, `osmd-audiveris-raw.pdf` | The other two inputs through OSMD, for a four-way grid. |
| `musescore-ours-p1-5.pdf`, `osmd-ours-p1-5.pdf` | The whole p1-5 Convert output (119 bars), file as written (keeps the scan's system breaks). |
| `musescore-ours.mpos` | MuseScore's measure positions for `musescore-ours` (one box per bar, page index, 1/12 spatium units). |
| `musescore-opengoldberg.mp3` | MuseScore's audio export of the reference Aria (MuseScore's basic soundfont). |

The side-by-side to open: `musescore-opengoldberg.pdf` | `musescore-ours.pdf` | `osmd-ours.pdf` | `scan-p1.png`.

## Inputs

- **Reference.** opengoldbergvariations.org links only to musescore.com (account to download) and IMSLP holds only
  the PDF. MuseScore ships the Open Goldberg score (Werner Schweer, 2012, with the Kickstarter dedications) as a
  demo in its own repo: `demos/goldberg.mscz` at tag v4.7.5
  (`https://raw.githubusercontent.com/musescore/MuseScore/v4.7.5/demos/goldberg.mscz`, 152,769 bytes). MuseScore
  converted it to `inputs/ref-full.musicxml` (990 measures, 4.9 s); `cut_measures.py` kept the first 32 measures.
- **Ours.** No Convert output exists on the box for p1-5 (`~/omr/folio005/p1-5` holds only the Audiveris
  movements). The final MusicXML of the p1-5 experiment run (`score.py` after A + B, `--gate-tag tuplet=0.9`) is on
  the Mac: `/Users/ckjiang/Documents/muse/.claude/worktrees/agent-a320325d43e43534d/api/experiments/omr/out/goldberg-p1-5-gate-tuplet09/final.musicxml`,
  copied as `inputs/ours-p1-5.musicxml` (119 bars) and cut to bars 1 to 32 as `inputs/ours-aria.musicxml`. The in-app
  `omr_convert` writes the same shape of file (ported code); its copy lives in local Supabase storage and was not used.
- **Raw Audiveris.** `~/omr/exp-audiveris/base/goldberg-bga.mxl` (page 1 alone, 28 bars) → `inputs/audiveris-raw-p1.musicxml`.

All three Aria inputs were cut with `--strip-layout`: system/page breaks, margins, measure widths and credits
removed, so each engraver lays the music out by itself (ours otherwise carries the scan's line breaks from
Audiveris). The title was replaced by a label naming the source. The p1-5 files are the file as written.

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
~/omr/musescore/scripts/musescore_render.sh musescore-ours.pdf ours-aria.musicxml
```

Mac:

```bash
cd api/experiments/engrave
python3 -I cut_measures.py goldberg/inputs/ref-full.musicxml goldberg/inputs/ref-aria.musicxml 32 --title "..." --strip-layout
python3 -I cut_measures.py goldberg/inputs/ours-p1-5.musicxml goldberg/inputs/ours-aria.musicxml 32 --title "..." --strip-layout
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
| `musescore-opengoldberg.pdf` (2 pages) | ref-aria, 32 bars | 0.63 s | 70,103 |
| `musescore-ours.pdf` (2 pages) | ours-aria, 32 bars | 0.59 s | 74,144 |
| `musescore-ours-p1-5.pdf` (10 pages) | ours-p1-5, 119 bars | 0.85 s | 178,580 |
| `musescore-audiveris-raw.pdf` (2 pages) | audiveris-raw-p1.musicxml, 28 bars | 0.57 s | 78,518 |
| same, straight from `goldberg-bga.mxl` | `.mxl` | 0.61 s | 85,519 (not kept) |
| `musescore-ours.mpos` | ours-aria | 0.54 s | 6,674 |
| `musescore-opengoldberg.mp3` (2:43 of audio, both halves repeated) | ref-aria | 6.77 s | 2,608,900 |
| PNG, one file per page (300 dpi default) | ref-aria / ours-aria | 10.1 s / 10.3 s | 2.9 MB + 0.9 MB per score (left on the box) |
| `ref-full.musicxml` | `goldberg.mscz`, whole set | 4.9 s (first run) | 7,840,629 |

OSMD 2.2.1 in headless Google Chrome on the Mac (`osmd_ms` = load + render inside the page under Chrome's
virtual time, so read it as indicative only; wall = two Chrome launches, one to read the DOM and one to print):

| Output | osmd_ms | Pages | Wall | Size |
|---|---|---|---|---|
| `osmd-ours.pdf` | 116 | 3 | 2.23 s | 289,327 |
| `osmd-opengoldberg.pdf` | 98 | 3 | 1.24 s | 272,009 |
| `osmd-audiveris-raw.pdf` | 98 | 3 | 1.28 s | 265,772 |
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

MuseScore fits our Aria on 1.5 pages at 4 to 6 bars per system (bars 1 to 23 on page 1), close to the
reference's own density, while OSMD at its default size needs 3 pages at 3 to 5 bars a system with the staff
drawn much larger. MuseScore's spacing is tight and even, with the two voices of each hand stacked compactly, while OSMD
spreads the same bars wide, parks the inner-voice rests far from their notes and draws the long phrase slurs of
bars 7 to 11 as large arcs above and below the system. MuseScore puts *p dolce*, *cresc.*, *mf* and *f* under the staff in the bar they belong to; OSMD also
places them by bar, but lets *cresc.* hang past the right margin at the end of a system (bar 9) and puts the *tr* of
bar 15 below the bass staff instead of between the staves.

## Paths (absolute)

Committed:
- `/Users/ckjiang/Documents/muse/.claude/worktrees/agent-a6373b95fb192e74a/api/experiments/engrave/goldberg/musescore-opengoldberg.pdf`
- `/Users/ckjiang/Documents/muse/.claude/worktrees/agent-a6373b95fb192e74a/api/experiments/engrave/goldberg/musescore-ours.pdf`
- `/Users/ckjiang/Documents/muse/.claude/worktrees/agent-a6373b95fb192e74a/api/experiments/engrave/goldberg/musescore-audiveris-raw.pdf`
- `/Users/ckjiang/Documents/muse/.claude/worktrees/agent-a6373b95fb192e74a/api/experiments/engrave/goldberg/musescore-ours-p1-5.pdf`
- `/Users/ckjiang/Documents/muse/.claude/worktrees/agent-a6373b95fb192e74a/api/experiments/engrave/goldberg/musescore-ours.mpos`
- `/Users/ckjiang/Documents/muse/.claude/worktrees/agent-a6373b95fb192e74a/api/experiments/engrave/goldberg/osmd-ours.pdf`
- `/Users/ckjiang/Documents/muse/.claude/worktrees/agent-a6373b95fb192e74a/api/experiments/engrave/goldberg/osmd-opengoldberg.pdf`
- `/Users/ckjiang/Documents/muse/.claude/worktrees/agent-a6373b95fb192e74a/api/experiments/engrave/goldberg/osmd-audiveris-raw.pdf`
- `/Users/ckjiang/Documents/muse/.claude/worktrees/agent-a6373b95fb192e74a/api/experiments/engrave/goldberg/osmd-ours-p1-5.pdf`
- `inputs/ref-aria.musicxml`, `inputs/ours-aria.musicxml`, `inputs/audiveris-raw-p1.musicxml`, `inputs/goldberg-bga.mxl`

On disk only (ignored by `goldberg/.gitignore`: large, or copies of files that live elsewhere):
- `/Users/ckjiang/Documents/muse/.claude/worktrees/agent-a6373b95fb192e74a/api/experiments/engrave/goldberg/scan-p1.png` .. `scan-p5.png`
- `/Users/ckjiang/Documents/muse/.claude/worktrees/agent-a6373b95fb192e74a/api/experiments/engrave/goldberg/musescore-opengoldberg.mp3`
- `/Users/ckjiang/Documents/muse/.claude/worktrees/agent-a6373b95fb192e74a/api/experiments/engrave/goldberg/inputs/ref-full.musicxml`
- `/Users/ckjiang/Documents/muse/.claude/worktrees/agent-a6373b95fb192e74a/api/experiments/engrave/goldberg/inputs/ours-p1-5.musicxml`

On the box: MuseScore stays installed at `~/omr/musescore/` (AppImage + `squashfs-root/`), renders and PNGs in
`~/omr/musescore/goldberg/`, the demo score in `~/omr/musescore/ref/goldberg.mscz`.
