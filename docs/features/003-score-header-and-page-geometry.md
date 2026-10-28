# 003 Score header and page geometry

Status: working (experiment scripts on 6 scores; ported to `api/app/librarian/cut.py`, one geometry for page reading (004) and the part cut (008) since 2026-10-28; `geometry.py` deleted) | Meta model: Muse Spark 1.3 reads the score header (part cut and page reading); the geometry itself uses none.

## Purpose

Find every staff, system and barline on a scanned page with OpenCV, and have Spark read page 1 once to list
the instruments in score order with their staves and clefs. Every page-level feature (004 bar numbering,
008 part cut, 005 OMR insertion points) sits on this. Models never place staves or bars.

## Why geometry and not SAM or Spark (item 0 verdict, 2026-10-27)

Tap test: tap the centre of every ground-truth measure; the smallest box under the tap must carry the right
number; every box hit exactly once; one wrong tap is a fail. Pages: Goldberg BGA p1 (clean, 28 bars) and
Rachmaninoff two-piano Gutheil p3 (noisy, 13 bars). `api/experiments/grounding/README.md`.

| Engine | Goldberg (28) | Rachmaninoff (13) | Latency | Cost per page |
|---|---|---|---|---|
| Spark 1.3 whole page, effort low | 23/28 fail | 13/13 pass (lucky) | 16 s / 11 s | $0.019 / $0.013 |
| Spark 1.3 whole page, medium | 9/28 fail | 2/13 fail | 22 s / 28 s | $0.022 / $0.030 |
| Spark 1.3 whole page, high | 9/28 fail | 1/13 fail | 36 s / 27 s | $0.034 / $0.025 |
| SAM 3.1 system boxes, Spark per system, low | 10/28 fail | 1/13 fail | 49 s / 27 s | $0.043 / $0.031 |
| OpenCV geometry (`fallback_cv.py`) | 28/28 pass | 13/13 pass | 0.03 s / 0.02 s | $0 |
| OpenCV + Spark labels (`label_with_spark.py`) | 28/28 pass | 13/13 pass | 6.4 s / 6.5 s | $0.008 / $0.008 |

Spark drifts: it merges a bar and every later number is off by one; at higher effort boxes slide across
systems. SAM only ever found systems ("musical staff" on the clean page, confidence ~0.75) or the page; it
never sees a barline. Symbol-level probe (Goldberg system 1 at 2x): "note head" 10 of ~70 (recall ~15 %,
precision 100 %), "treble clef" 1, "fingering number" 12, everything else nothing. Experiment spend about
$0.35. SAM is optional (system crops) and stays in the demo only as a named Meta model if wanted.

## What the geometry does

`fallback_cv.py` (piano pages, 2 to 4 staves; it was the app's `geometry.py` / `measures_on_page` for page
reading until 2026-10-28, see "One geometry" below):
binarise (Otsu OR adaptive mean, because grey scans print staff lines lighter than Otsu's threshold), estimate
skew by maximising row-projection energy (-0.5° on the Rachmaninoff page), staff lines as rows with long
runs, group in fives, grand staves when a vertical line crosses the gap away from the left edge, systems by
the left systemic line, barline = column whose vertical dark run covers at least 92 % of every grand staff in
the system; clusters in the header zone (12 staff spaces) merge into the system start. Known limits: a
cross-staff stem on a solo-piano grand staff reads as a barline; pickup bars narrower than the header zone
are swallowed; boxes are in the deskewed frame (up to 4 px off at the corners of a 0.5° page); staves with no
barline crossing (percussion, text-only) do not join a system.

`piano_cut_geometry.py` and `api/app/librarian/cut.py` (orchestral pages, 13 to 25 staves). Four changes
over `fallback_cv.py`, made on Rach 1 Gutheil 1919:

1. Staff lines as row-profile peaks (3-row smoothing, 3-px non-maximum suppression), not merged runs: the
   1919 scan smears timpani lines over six rows and adjacent lines touch.
2. Five lines found by stepping from the first line at the global spacing blended with the spacing seen so
   far, skipping extra candidates (a long slur adds a row on p. 43); spacing varies 7.0 to 7.5 px.
3. Systems by the left systemic line in a window around the page-median staff x0; staff x0 = first column
   where 3 or more of the staff's rows carry a long run, so margin labels and the timpani cue staff ("Fis, A,
   H") no longer drag x0 into the margin. Gap-based fallback (split at over 2.5x the median gap) exists, never
   needed.
4. System barlines by two votes: a column must cover at least 90 % of each staff's five-line span for at
   least 60 % of the staves and cross the gap between adjacent staves for at least 30 % of the pairs (a tutti
   chord's stems passed the first test alone, p. 1 bar 3). Barlines drift 6 px over the page, so a +-4 px
   window, one-column clusters dropped.

Bar counts matched the page on every Rach 1 system (p. 1: 4; p. 2: 4, 5; p. 7: 4; p. 15: 5; p. 16: 6, 4;
p. 43: 4). Geometry is under a second per page, free. Pixel thresholds assume ~150 dpi (page 1200 to 1450 px
wide). Systems were never mis-grouped on 15 pages of Rach 2, PC3, PC5, including 2-staff cadenza systems and
24 to 25 staff pages.

### One geometry for page reading and the part cut (2026-10-28)

004 read pages with `geometry.py` (the `fallback_cv.py` port) and parked on geometry the part cut had already
solved: Rach 1 full score p1 split at the dotted line into 10 + 7 staves, the two-piano p4 lost two staves and
split its first system, Beethoven 9 p172 counted 2 bars. `process_pages` now calls `cut.page_measures(png,
expected_staves)`, which turns `page_geometry` into 004's page record (measures with boxes as page fractions,
confidence from the barlines: closing barline crossing every staff, open end, header-zone merge, narrow, wide).
`geometry.py` is deleted; `binarise`, `estimate_skew`, `rotate` and `vertical_cover` moved into `cut.py`. The
page reading run reads the score header once (the part cut's prompt and `reconcile`, `labels.read_header`) and
passes its count to every page.

Two fixes the 004 files needed, both in `cut.py` and shared with the part cut:

- `group_systems` looks for the systemic line at the pair's own staff start as well as the page median, in a
  window of max(8, sp) left and max(15, 2 sp) right. An indented first system (Goldberg p1-2 "Aria" and "Var. 1",
  the two-piano p3 title page) starts far right of the median and fell apart into single staves, each counting
  its stems as barlines (14 "bars" on one staff).
- `barline_tol(sp)`: the barline votes' column window is 4 px up to an 11 px spacing and 0.4 space above. At the
  150-dpi render Beethoven 9 has 15-16 px spacing and its barlines drift; at 4 px one barline in nine on p172
  lost its staff votes (9 of 16, under the 60 %), at 6 px it is found. 5 px on Goldberg (9.75 px) made two stems
  meeting across a grand staff's gap a barline, hence the 0.4.

Geometry against the truth counted by eye, 18 pages at the import route's 150 dpi (bars per page):

| Pages | Truth | `geometry.py` | `cut.py` before the fixes | `cut.py` now |
|---|---|---|---|---|
| Rach 1 full p1-5 (17 staves, 7.2 px) | 4, 9, 9, 6, 7 | 9, 9, 6, 5, 7 | 4, 9, 9, 6, 7 | 4, 9, 9, 6, 7 |
| Rach 1 two-piano p3-5 (4 staves, 10-11 px) | 13, 15, 12 | 13, 23, 12 | 55, 11, 12 (p3 indent; p4 2 staves short) | 13, 15, 12 (p4 with the header's 4) |
| Goldberg BGA p1-5 (2 staves, 10 px) | 28, 20, 21, 21, 29 | 28, 20, 21, 21, 29 | 42, 51, 41, 43, 29 (indents) | 28, 20, 21, 21, 29 |
| Beethoven 9 p172-176 (16-17 staves, 15.5 px) | 9, 5, 9, 6, 5 | 2, 7, 2, 1, 2 | 8, 5, 9, 6, 5 (with the header's 16) | 9, 5, 9, 6, 5 |

Staves: 16/16 on every Beethoven 9 page with the header's count (17 on p176, cellos and basses on two staves),
17/17 on Rach 1 p1 in one system, 4 per system on two-piano p4 after recovery. 0.03 to 0.3 s a page.

## Score header (`score_header.py`, 2026-10-27 evening)

One Spark 1.3 call (effort low) on the first music page's numbered overlay. Returns instruments in score
order with label, abbreviations, the yellow box numbers each occupies, staves per instrument, clef per staff,
family, key, time, tempo, section headings. Writes `header.json` with `expected_staves` and a `validation`
block (geometry's system-1 count vs the header's total, `boxes_in_order`). Reconciliation: Spark's first
Rach 1 answer said 21 staves (two each for the Cl, Fg and Cor pairs that share a staff); anchoring the count
to the box numbers (every box 1..N exactly once, staves = len(boxes), the said value kept as `staves_said`)
gives 17 = geometry. PC3: 13 = 13 first time. Beethoven 9: the four unlabelled choir staves were named "CORO
Soprano / Alto / Tenore / Basso" from the clefs (family voice), which the matcher needs. Header calls cost
$0.014 to 0.025, 12 to 24 s. The header is read once per score; a score whose instrumentation changes
between movements needs the optional per-page header call, not wired.

In the app handler (feature 008) `read_header` uses a shorter prompt: instruments in order, staves each,
clefs, key, time.

## Staff recovery (HARDEN.md)

For every system with fewer staves than `expected_staves`, `find_staves_strips` re-searches the system's
vertical extent in 12 column strips. The Breitkopf staves that were lost are bowed (each line smears over 6 to
8 rows across the page, a 35-row plateau instead of five peaks) but straight inside a ~110 px strip. Each
strip votes for 5 (or 4 of 5) peaks at the known spacing +-35 %; clusters with 4 or more strips are a staff
(lines = medians, a missing line interpolated), forced into the short system, re-indexed, marked `recovered`,
drawn orange. The header count is a maximum: cut-away systems stay short when nothing is found. Recovery
runs only when `header.json` exists.

Ported to the app (2026-10-28 night): `cut.page_geometry(png, expected_staves=)` runs `recover_staves` (the
strip search and the hole filling, same thresholds) when any system is short of the count; the geom carries
`expected_staves`, `staves_before_recovery` and `recovered`, recovered staves are orange on the overlay. The
part-cut handler passes the header's count on every page read after `read_header` and re-reads page 1 with it.
On the app's 150-dpi renders of Beethoven 9 (3153 x 4000, spacing 15 to 16): p172 16/16 found; p173 12 found,
4 recovered (Vn I 4/12 strips, Vn II 6/12, Tenore 4/12, Vc/Cb 9/12) = 16/16; p174 15 found, 1 recovered (Vn I
8/12) = 16/16; p175 16/16; p176 17/17; one system per page. Regression at 150 dpi: Rach 1 p1 to 5 geometry
identical with and without the count; PC3 p1 to 5 identical without, and with the count only the two HARDEN.md
staves come back (p4 s2 5/12, p5 s2 7/12). Tests: `tests/test_cut.py` (a bowed staff on a synthetic page; seven
staves against a header of six, the hole filled).

| score | page | before | after | recovered |
|---|---|---|---|---|
| PC3 | 4 | 11, 8 | 11, 9 | s2 Vcll. u. K.-B. (5/12 strips) |
| PC3 | 5 | 13, 12 | 13, 13 | s2 Klav. treble (7/12 strips) |
| Rach 1 | 1 to 5 | unchanged | unchanged | none; 13 cut-away short systems searched, no false recoveries |

Later runs: PC5 p1 Cb recovered; PC5 p4 3 recovered (of 10 missed); Dvořák p6 and p9 2 each, all correct;
Beethoven 9 p174 6 recovered (16/16 after).

## Page preparation (2026-10-28, from the Beethoven 9 choir defects in 008)

`prepare_page` in `piano_cut_geometry.py` and `cut.py`, before skew and staves: `mask_page_edges` masks the
dark book-scan shadows touching a page edge (run of pixels darker than paper minus 100, at least 8 px in 90 %
of the edge's columns, followed per column through the blurred rim); `working_scale` upscales by an integer when
the staff spacing is under `SPACING_MIN` = 6 px; `render_dpi` renders a page that is one embedded raster under
150 dpi at its own resolution. Beethoven 9 now runs at native 1513x1920 (spacing 7.0 to 8.0, inside the tuned
band): the earlier native 10/16 was the shadows locking the skew estimate to 0.0, not the resolution; with the
shadows masked the five pages find 13 to 15 staves and recovery completes them (16, 16, 16, 16, 17), the header
reads 16 (was 18), one system per page. Recovery gained hole filling (`recover_staves`): two staves about two
pitches apart are searched at 3 of 12 strip votes, not capped by the header count. Regression: Rach 1 p1 to 5
and PC3 p1 to 5 geometry and crops pixel-identical. The "drop a staff whose x range is the whole page" idea was
not needed once the bands are masked.

**The gutter at 150 dpi (2026-10-28 night).** The app renders Beethoven 9 at 150 dpi (3153 px wide, every pixel
interpolated), not at the scan's resolution as the experiment does. With the left shadow masked, the grey gutter
texture next to it (cols 148 to 257, not uniform enough for the mask) binarises to a full-height ink strip 110
px wide, wider than the 78-px opening kernel, so it counted as a "long run" on every row and `find_staves` put
every staff's `x0` at 147: the systemic-line search then looked at the gutter instead of the bracket at x 1030,
found no line, and p172, p174 and p176 came out as 8 to 10 one-staff systems (p173 and p175, gutter on the
right, were fine). `staff_extent` now takes `x0`/`x1` from the longest group of long-run columns (groups closer
than 8 spaces are one); nothing changes on the tuned scans. The strip itself is still in every crop's left edge
(the band starts at x 0), faint grey.

**Clef reading by geometry: tried, not cheap here (2026-10-28 night).** The idea was to read the C clef's line
from its shape (a thick vertical bar plus curls centred on the line) as a tie-break when the recheck names the
wrong voice. On the Schott Beethoven 9 the chorus bracket and the opening barline are drawn over the staff lines
right of `x0` (the staff lines run under the bracket), so the first thick vertical bar on every chorus staff,
the bass included, is the bracket, not a clef, and a slur from the staff above crosses the clef zone on p172;
the soprano clef's own bar is engraved from the top line down past the staff, taller than its curls. Dropped;
a glyph-level reader (components right of the bracket, the curls' centroid) is the next attempt if wanted.

## What still breaks

- Staff detection drops staves on thin-lined, bowed Breitkopf scans (never on Rach 1 or Rach 2): PC3 p4 s2
  Vcl, PC3 p5 s2 piano treble (the one miss that reached the piano itself; verify caught it), PC5 p1
  Contrabasso, PC5 p4 ten staves (whole wind block of s1, timpani and strings of s2; 14 of 24 found). 13
  missed over 4 pages before recovery. The row profile (long-run dark fraction, threshold 0.2 of page width,
  local-max radius 3) does not yield five candidates at the expected spacing. The strip search was tuned on
  two scans; the PC5 p4 miss was not re-run.
- Beethoven 9 scan resolution: embedded page image 1513x1920 px, PDF page 1505x1920 pt, so the 150-dpi
  render upscales x2.08 to 3153x4000 px (spacing 13 to 16.25 px). At native 72 dpi (spacing 7.0 to 7.75 px)
  `find_staves` finds only **10 of 16** staves on p172 (1-px lines too faint for the 0.2 threshold); at 150
  dpi **16/16 on p172, 12/16 on p173 before recovery, 12/16 on p174 (16/16 after), 16/16 on p175 and p176**.
  Not tuned.
- Page-edge shadows as staves: the dark book-edge band at the top and bottom of every Beethoven 9 page
  passes `find_staves` (a 5-line fit on the shadow's rows, page-wide) → a fake staff 1 and a fake last staff
  on p172 to 176. Spark's header called them "False detection - top/bottom page edge, no staff" but counted
  them, so `expected_staves` = 18 and recovery on p173 pulled 7 extra staves into a 12-staff system. Fix: drop
  a staff whose lines are darker or wider than the page's music or whose x range is the whole page. Not done.
- Fl and Ob staves split off as 1-staff systems on Beethoven 9 p176 (systemic line broken at the top). Not seen
  at the import route's 150-dpi render on 2026-10-28: one 17-staff system.
- Brace detection (informational) missed the thin Breitkopf brace once (PC3 p2 s2); skipped for single staves.

## Files and outputs

Scripts in `api/experiments/grounding/` (run from `api/` with `uv run experiments/grounding/<script>.py`,
PEP 723 inline deps): `fallback_cv.py`, `piano_cut_geometry.py`, `score_header.py`, `build_overlay.py`,
`grade.py`, `ground_truth.json`, `common.py` (`--score <pdf stem>` / `PIANO_CUT_SCORE=`, `--instrument`).
Outputs (gitignored except the item-0 JSON/HTML): `out/cv-*.json`, `out/final-*.{json,html,png}`,
`out/piano-cut[/<stem>]/pages/p<NN>.png` (150 dpi), `geom-p<NN>.json`, `overlay-p<NN>.png` (what Spark
sees), `header.json`. In the app: `cut.py` (`page_geometry(expected_staves=)`, `page_measures` for 004,
`barline_tol`,
`recover_staves`, `staff_extent`, `overlay_png`, `cut_system`). Unmerged branch `claude/grounding-experiment-e8ae10` (commit 0700c49): 14 more
pages through geometry + Spark labels and `build_gallery.py` → `out/gallery.html`.

## Next steps

1. Drop page-edge "staves"; tune staff detection for thin bowed scans (PC5 p4) and 1-px lines.
2. Per-page header call when instrumentation changes between movements.
3. Keep every threshold documented against the 150 dpi assumption; a resolution normalisation step
   (target staff spacing ~7 px) would remove the Beethoven 9 special case. `barline_tol` and the spacing-scaled
   systemic-line window are the two places 004's files needed so far (10-11 px keyboard pages, 15-16 px
   Beethoven 9); a downscale was not chosen because the part cut's crops come from the working page.
