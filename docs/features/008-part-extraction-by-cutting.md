# 008 Part extraction by cutting, no OMR

Status: prototype (experiment pipeline works on 6 scores; `part_cut` handler merged on main, runs end to end on the local stack with Spark on Rach 1 pages 1 to 5 (2026-10-28, see "Live runs"); migration applied locally, not hosted; the multi-part contract below is implemented in the handler with the two routes, run on Beethoven 9 pages 172 to 176, 2026-10-28 evening; the same route splits a Digital book's MusicXML by
instrument with music21, no model, about a second, 2026-10-28 night) | Meta model: Muse Spark 1.3 (labels the target staves per system on a numbered overlay, re-reads each crop alone; reads the header, feature 003). SAM 3.1 not used.

## Purpose

For a soloist or a choir singing from a full score, skip OMR: recognise which staves on each system are the
requested part, crop them, clean the neighbours' ink out, stack them into a strip per page. CK's question
(2026-10-28 morning): "extract the piano sheet from the grand sheet of Rachmaninov piano concerto no 1, I
want only piano." Choir feedback (2026-10-27): SATB singers keep the grand sheet; separate parts only pay
off when the voice sits inside a 10+ staff full score, so small scores distribute the original page with
the part's band highlighted (feature 010) and true extraction is for big scores.

## The contract (CK, 2026-10-28)

**A part export is a selection of parts chosen by the user, not a single instrument.** A soprano can export
soprano alone or soprano and alto together. The payload takes a list of instruments; the chosen staves of
each system are kept together in score order and cleaned as one block; one strip per page. When the chosen
set skips a staff in the middle (soprano and tenor without alto) each contiguous run is cut as its own block
and the blocks are stacked vertically into one strip image per system with a small gap (CK: "stack them").

Implemented (2026-10-28 evening): the payload takes `instruments: [...]` (`instrument: "..."` still accepted
as a one-element list); per system the union of the chosen staves is split into contiguous runs, each run
is cleaned and verified as its own block, the recheck asks per block and must name one of the block's
instruments (or "chorus" for a block of voices), the strip is the blocks stacked with a white gap of 1.5
staff spaces, the header count check expects the summed staff count. Slug = the instruments' slugs joined
with `+` (`soprano+alto`), keys stay `{score_id}/parts/{slug}/p{page:03}-s{k}.png`.

Routes (`api/app/routes/scores.py`, `api/app/routes/jobs.py`):

- `POST /scores/{id}/parts` body `{instruments: [string], pages?: [int]}`, owner or ensemble admin, budget
  checked; refuses an empty list (400) and a score with neither a `pdf`/`images` source nor an imported
  `musicxml` source (400). A PDF book (a `pdf`/`images` source) gets a `part_cut` job `{score_id, instruments,
  pages?}` and the queued row back. A Digital book gets the split below, finished inside the request.
- `POST /jobs/{id}/answer` body = the answer payload (`{staves: [...] | "absent"}` or `{blocks: [[...], ...] |
  "absent"}`), only for a job that is `done` with `result.question` set and whose score the caller may edit
  (409 otherwise, 409 when already answered, 404 unknown); inserts a job of the same kind with the parked
  job's payload plus `answer`, `resume_from` and the question's `interpretation_id`, returns the new row.

## Split by instrument for a Digital book (`api/app/librarian/part_split.py`, 2026-10-28 night)

CK: every book is tagged "PDF" or "Digital" (Digital = imported MusicXML), and "Split by instrument" is one action
for both; for a Digital book it is trivial and instant, no model. Same route, same payload:

- The route sees no `pdf`/`images` source and an imported `musicxml` source (one whose `meta` has no
  `split_from`). The names must be the score's `parts.name` rows, else 400 with the parts named in the detail
  string: `Not in this score: Flute. The parts are Violin I, Violin II, Viola, Cello.` (`pages` is ignored).
- It inserts a `part_split` job as `running` (attempts 1, `locked_at` now), runs the handler in the request
  through the worker's own `run_one` and returns the row, `done` with `result = {source_id, instruments,
  storage_path, bytes, seconds, note}`. If the process died mid-split, the stale sweep would queue the row again
  for the worker. No usage event, no spend.
- The handler loads the stored MusicXML with music21, keeps the chosen parts in score order (`instruments` in the
  result is score order, whatever the payload's order), every staff of a part (a piano on two staves is one part
  "Piano", with a brace; an original bracket survives when two or more of its parts do), renames a one-staff part
  to the app's name ("Violoncello" prints as "Cello", the first "Violin" as "Violin I"), and writes a new MusicXML
  to `{score_id}/parts/{slug}.musicxml` (slug as the part cut's: `violin-i+cello`). A `sources` row of kind
  `musicxml` records it: `storage_paths = [key]`, `meta = {instruments, split_from: <source id>, slug}`. The same
  selection again replaces the file and updates that row. Measure numbers are the source's. No `parts` row is
  written (the web reads splits from `sources`; a joined label in `parts` would become a selectable name).
- Names: `import_musicxml.part_groups` is the one place that groups music21 parts into the app's parts (PartStaff
  pairs from one `<part>` with `<staves>2`, and `part_names`' two-"Piano"-parts rule); the import writes
  `parts.name` from it and the split accepts exactly those names. No schema change: `sources.kind` already
  admits `musicxml`.

Live on the local stack (Beethoven Op. 18 No. 1 i, score `b4fe666c`, 313 bars, four parts), through the route
with FastAPI's TestClient as the ensemble admin: Viola + Violin II returned `done` in 1.08 s (handler 0.76 s,
747 KB, written as Violin II, Viola with 313 measures each on re-read); Cello alone 0.52 s (345 KB); Violin I +
Flute 400 with the four names; through `run.py part_split`, Violin I + Cello 0.78 s (845 KB). Zero usage events.
Not checked: how OSMD renders the written files in the reading view (web thread).

Tests `api/tests/test_part_split.py` (fixtures in `web/public/fixtures/`): the names the grouping gives for the
quartet, the Chopin piano and the Bach chorale; score order, 313 measures and the title kept; the piano's two
staves and brace; the chorale bracket over S + T and none over A alone; unknown names; the handler's upload,
content type, row and re-use; the route's `done` row, its 400 detail, a PDF book still queuing `part_cut`, and a
book whose only MusicXML is itself a split refused.

## Pipeline (`api/experiments/grounding/`, run from `api/` with `uv run experiments/grounding/<script>.py`)

| Step | Script | Model | What |
|---|---|---|---|
| 0 | `score_header.py` | Spark, effort low | page 1 overlay → instruments in score order, staves, clefs (003) |
| 1 | `piano_cut_geometry.py` | none | rasterise at 150 dpi, deskew, staves, systems, system barlines, staff recovery from the header, numbered overlay (003) |
| 2 | `piano_cut_label.py` | Spark, effort low, `complete_json` (8000 tokens, one retry) | one call per page: which staff numbers are the wanted instrument per system, every other staff's instrument, playing / resting / absent; prompt carries the score order and the by-order guess (full system) or "decide from labels/clefs/brace, answer absent" (short system) |
| 3 | `piano_cut_build.py` + `piano_cut_clean.py` | none | crop the named staves per system, clean-and-extend, geometric verify, stack into `part-p<NN>.png` and `strip.png`, `piano-cut.html`, `results.json` |
| 4 | `piano_cut_recheck.py` | Spark, effort low, `complete_json` 4000 tokens, one retry | Spark sees each crop alone and names the instrument; disagreement → NEEDS REVIEW |

`--score <pdf stem>` / `PIANO_CUT_SCORE=` (default Rach 1 Gutheil writes to `out/piano-cut/`, others to
`out/piano-cut/<stem>/`); `--instrument "..."` / `PIANO_CUT_INSTRUMENT=` on every script (default "Piano
(solo)"; other instruments write to `out/piano-cut/<stem>/<instrument-slug>/`; pages, geometry, overlays,
`header.json` and `spend.json` stay in the score folder). The matcher (`piano_cut_label.match_instrument`:
synonym table + numeral) prefers a voice-family header entry for a voice name, then a label whose first word
is the name, no single-letter synonyms (the first Alto run cut the alto trombone, "Tromboni Alto e Tenore",
$0.11 wasted). Nothing piano-specific is left in the label or recheck prompt; the class names inside
`piano_cut_clean.py` are documented as "the target".

## The cut and the clean-and-extend pass (`CLEAN.md`)

Rule: crops are cleaned and extended, never widened. Per system: the band runs from 4 px (half a space)
below the bottom line of the staff above to 4 px above the top line of the staff below (else the adjacent
system's edge staff, else 12 spaces); full left margin, system right edge + 2 spaces. Known barline columns
(+-4 px) that run dark from the band edge to the target's outer line are masked for the analysis only.
Components: dilate 7x3, 8-connected, bbox and area on real ink. Classes: TARGET (overlaps the target region,
outer lines +-1 space), NEIGHBOUR (reaches the band edge or within 1 space of the neighbour's outer line),
BOTH (kept, logged); specks under 4 px outside the target erased. Gap components go to the nearer **ink**
(vertically in their own columns, or horizontally on their own rows within 1.5 spaces, the next word of a
text line), ties to the target. Deviation from the brief: not "nearer staff line" (the 8va on Rach 1 p. 2 s2
sits 3 px under the timpani and 50 px above the piano; "a tempo" 17 px under, 27 px above). Erase NEIGHBOUR
(white over the dilated mask + 1 px), fit the crop to the kept ink + 3 px, never narrower than the staves +
1 space. Flags `edge_ink_top` / `edge_ink_bottom` (informational). Kernel and reaches tuned on 150 dpi.

Verifier: `bar_count` by re-detecting barlines inside the crop gave false alarms on dense piano systems
(p. 3 s1: 6 vs 5, p. 4 s1: 5 vs 3, p. 4 s2: 4 vs 3); replaced by `barlines_present` (each system barline x
must have a vertical dark run through the block, cover at least 0.9) plus `staves_in_crop` (= the expected
count) and `brace_or_bracket` (informational, skipped for single staves). Geometry cannot catch a wrong
instrument (a violin pair also has two staves, a brace and the same bars; p. 43 has both piano staves in
treble clef), only a wrong box, so the Spark recheck is mandatory.

**Bar-aware cleanup (2026-10-27 late, the three leaks: Rach 1 p. 3 s1 Vn I hairpin; PC3 p. 3 s2 Horn II
ledger notes with `sf` and slurs; PC3 p. 5 s2 a neighbour's `sf`).** Barline x positions split the staves'
x range into bars (barline columns +-5 px belong to no bar; bar 1 starts at the staves' left end so clef and
key are bar 1's ink). Own ink per bar inside the target's staff region with the staff lines removed (runs
of at least 1.5 spaces, +-1 row), counted in staff-space units: rests-only bars measure 0.0 to 1.3 sp² on 18
systems (PC3 all 0.0 to 0.3), the sparsest playing bar 7.0, clef and key alone 4.0. **Floor: 1.25 sp² per
staff** (2.5 for a piano). A quarter rest keeps its ink (8.6) and counts as playing. Components over resting
bars only (not touching the staff lines within 2 px, not reaching the neighbour) are the neighbour's and
erased, except a component that continues a kept text line (next word within 2.5 spaces; chains propagate:
"Allegro con brio" over PC3 p. 1 bars 1 to 2). Pieces of kept components: a TARGET or BOTH component's ink
minus the vertical barline runs (at least 5 spaces tall at a barline column) is re-joined; a floating piece
(no ink inside the staff rows) over resting bars only is erased; a piece with ink inside the staff rows is
never touched (clef tails, ledger chords on their stems, the sagging line of a bowed staff; the staff
region's edge rows are traced per column, since the Breitkopf bottom line sags 1 to 6 px and two earlier
drafts cut it). Result on 18 systems: 3 crops changed (the three leaks gone), 15 pixel-identical, verify
17/17 as before. Limits: a bar holding only a whole note in a space measures below the floor; tempo text
over a resting bar mid-system is lost; marks of the neighbour over bars where the target plays are still
decided by distance (PC5 p. 2 "Ped." and release star).

## Results

Rach 1 Gutheil 1919, pages 1, 2, 7, 15, 16, 43 (`REPORT.md`, 2026-10-27, $0.103 of a $1.50 cap, 13 calls):

| Page | Why | Staves | Systems (bars) | Spark: piano staves | Correct | Verify | Label s / $ | Recheck s / $ |
|---|---|---|---|---|---|---|---|---|
| 1 | full names in the margin | 17 | 1 (4) | 11, 12 playing | yes | pass | 6.4 / 0.0089 | 3.8 / 0.0021 |
| 2 | "Pno." abbreviations, piano top of system 1 | 24 | 2 (4, 5) | 1, 2 and 18, 19 | yes | pass, pass | 9.2 / 0.0107 | 5.7 / 0.0051; 3.2 / 0.0022 |
| 7 | abbreviations, busy piano | 17 | 1 (4) | 11, 12 | yes | pass | 4.8 / 0.0086 | 6.2 / 0.0056 |
| 15 | no labels, piano all rests | 17 | 1 (5) | 11, 12 resting | yes | pass | 11.6 / 0.0155 | 3.9 / 0.0047 |
| 16 | tutti, cut-away, piano not printed | 22 | 2 (6, 4) | s1 absent; s2 18, 19 | half: s2 is Vn I/II | geometry pass, **recheck "violins"** → NEEDS REVIEW | 11.7 / 0.0151 | 8.4 / 0.0066 |
| 43 | no labels, both staves treble, virtuosic | 17 | 1 (4) | 11, 12 | yes | pass | 18.4 / 0.0150 | 2.8 / 0.0030 |

Works as a two-call loop with a review state. 5 of 6 pages right; the miss is the cut-away tutti page where
Spark picks the braced Vn I/II pair by score position ("between brass and strings"); a $0.005 recheck of the
crop alone catches it. 3 of 6 answers were malformed JSON (`}-math]`, `]} apron,`), repaired by the parser.
~$0.02 and 10 to 30 s per page; a 92-page score about $1.60 and under an hour serially. Plain crops lost the
top of the 8va on p. 1 and a triplet "3", p. 7's high slurs touched the edge (fixed by the clean pass).
Rach 1 p. 1 to 5 later: 8/8 systems, identical staves and erased/kept counts across the hardening rerun.

Generalisation (`GENERALISE.md`, pages 1 to 5, $0.2287: Rach 2 $0.0713, PC3 $0.0819, PC5 $0.0755; 15 label
calls $0.166 at $0.009 to 0.018 and 5.7 to 14.2 s; 23 rechecks $0.063 at $0.002 to 0.005 and 2.2 to 5.5 s):

| Score | Crops | Correct | Verify | Recheck | Notes |
|---|---|---|---|---|---|
| Rach 2 (IMSLP 03631, 1240x1754, skew +-0.3°) | 9 | 9/9 | 9/9 pass | 9/9 "Piano"/"P-no" | every staff found; wind hairpins under the staff above leak into 4 crops (p2 s2, p3 s1, p3 s2, p5 s2) |
| Beethoven PC3 (Breitkopf, 1425x1875) | 7 | 6/7 | 1 FAIL staves_in_crop (p5 s2 [21]: geometry missed the piano treble; crop correct by luck, flagged) | 7/7 "piano"/"Klavier" | piano rests all five pages; p4 lost to truncated JSON (1502 tokens, before the 8k budget); p3 s2 Horn II ledger leak; p2 s2 thin brace not detected |
| Beethoven PC5 (Breitkopf) | 7 | 7/7 | 7/7 pass | 7/7 "Piano"/"Pfte." | cadenza page grouped right (2, 13, 2); tutti p4 and p5 "absent", no crop; p4 geometry found 14 of 24; p3 s3 Cor. II `sf` leak; page number and plate "B. 69." kept (harmless) |

Score: 23 crops shipped, 23 the piano, 3 neighbour-ink leaks, 1 flagged, 1 page lost. Spark right on 14/15
parseable pages, 28/28 systems where geometry was right. After hardening (`HARDEN.md`, PC3 p1 to 5 and Rach
1 p1 to 5, $0.243): PC3 9 crops, 9 piano, 9 pass, 9 recheck "piano"; both recovered staves real; p4 came back
whole at 1349 tokens with the 8000 budget; one retry on Rach 1 p1 ($0.009 wasted); stray-token repair on 2
of 10 pages. Rach 2 / PC3 / PC5 first 5 pages after the clean pass: 23/24 systems right, every wrong pick
caught by the recheck, ~$0.02 a page.

Any instrument (`GENERAL.md`, 2026-10-27 night, $0.777: headers $0.062 (3), labels $0.40 (32 calls incl.
retries and the wasted Alto run), rechecks $0.31 (41 calls incl. 3 wasted at 2048 tokens)):

| Score | Instrument | Pages | Correct by eye | Verify / recheck | Notes |
|---|---|---|---|---|---|
| PC5 | Violin I | 1 to 5 | 9 of 9 systems boxed right; p4 s2 crop holds Vn I + Vn II (Vn II unboxed, band ran on) | p4 s2 FAIL (barlines, recheck "Violin I & II") → needs_review | p2 "Ped." and release star above (distance rule); p3 s3 "f arco" of the staff below |
| Dvořák 9 | Flute I | 5 to 9 (5 = first music page, book p. 183; 6 to 9 no labels) | yes on every system (shared Fl. I/II staff is the answer) | p6 recheck "Violin I" (ff chords), p7 s2 "Trumpet" ("a2"), p8 s2 barlines_present FAIL (one barline not re-found); 3 of 9 rechecks ran out at 2048 tokens → 4000 + retry | p9 s1 oboe slurs under the flute (both play) |
| Dvořák 9 | Piano (solo) | 5 to 8 | negative test passes: header lists no piano, absent on all 6 systems, no crop | n/a | $0.038 |
| Beethoven 9 | Soprano | 172 to 176 (book 168 to 172, first chorus pages) | yes on every page ("Seyd umschlungen", "Kuss der ganzen Welt!", "Brüder, überm Sternenzelt", "ein lieber Vater wohnen") | p174, p176 recheck "Alto" (false alarms) → needs_review; p176 needed `--reparse` (`responsibility=0` stray token) | lyrics partly erased; grey scan specks painted white |
| Beethoven 9 | Alto | 172 to 176 | p173 crop holds Alto + Tenor (tenor unboxed); others yes | p173 recheck "Alto and Tenor" (right); p174 barlines + "Viola", p175 "Tenor" (false alarms) → needs_review | soprano's lyrics above leak |

Score: 28 crops shipped; 26 are the wanted staff and nothing else is boxed in (PC5 p4 s2 and Beethoven 9 Alto
p173 hold a second, unboxed staff, both flagged by the recheck). Spark's labelling right on every system where
geometry was right (56/56 incl. absent). The recheck is the weak model step on unlabelled pages: 7 false
alarms (Dvořák p6, p7; Beethoven 9 S p174, p176, A p174, p175) against 2 true catches.

**CK judged the soprano strip usable as it stands (2026-10-28).**

Known choir defects (2026-10-28 morning): a lyric line is half erased (the gap between S and A holds the
soprano's lyrics and the alto's noteheads; nearest-ink splits the line word by word, "Seyd _schlungen _li
o_nen!"; the whole-note blind spot makes semibreve bars count as resting so syllables under them go to the
neighbour); page-edge shadows counted as staves (003); soprano/alto C-clef confusion in the recheck (4 times);
native resolution finds 10/16 staves vs 16/16 upscaled (003).

**Choir defects fixed (2026-10-28, branch `worktree-agent-a4cf8156a80b2ad8b`, $0.63: 22 labels, 28 rechecks,
1 header, 3 wasted retries; `out/piano-cut/beethoven-sym9-fullscore-imslp46254/choir-before-after.html`, the
earlier run kept in `before/`).** Three rules, in the experiment and in `cut.py` (`tests/test_cut.py`):

1. *Lyrics, the text-line rule* (`piano_cut_clean.text_lines`, `clean_crop(voice=, voice_above=)`;
   `piano_cut_build.voice_flags` reads the families from the header through the names Spark gave the staves).
   A text line is a chain of word-sized components (0.5 to 2.6 spaces tall, under 20 wide, fill at least 0.15)
   whose rows overlap, up to 30 spaces apart (syllables sit a bar or more apart), plus the hyphens and extenders
   between its words. Under a vocal staff the band from its bottom line to the midpoint of the gap below is its
   own: a text line with a word there is kept whole; a text line under the staff with no word there is the staff
   below's and erased whole; a text line with a word in the upper half of the gap above a vocal neighbour is that
   neighbour's lyrics, erased whole. Words on text lines never go to the rest rule. A word glued to neighbour
   ink by a scratch (p175 "Brü", a hairline runs from the word to the alto's staff) is carved out on the line's
   rows (baseline-bounded, 3x3 join). Two groupings were tried: chaining by row overlap ("overlap", kept) and
   clustering by bottom row within one space ("baseline", `--text-mode baseline`); on the five soprano pages
   both kept the same words, and overlap is order-aware (a word on another baseline cannot join a line through
   a tolerance), so it is the default. Applied to voice staves only: the band-below-is-own premise is false
   for orchestral staves (Rach 1 p2 "a tempo" under the timpani belongs to the piano below), so single-staff
   orchestral instruments keep the nearest-ink and rest rules, which is also what keeps the 17 Rach 1 / PC3
   regression crops pixel-identical.
2. *Page-edge shadows* (`mask_page_edges`, before anything else): a side has a shadow when the run of pixels
   darker than paper minus 100 from that edge is at least 8 px in 90 % of its columns; the masked run follows
   each column through the blurred rim (paper minus 40, at most 40 px past the core) plus 2 px, capped near the
   band's median thickness so a systemic line touching the band is not swallowed. Header 18 became 16 (one
   call; Spark listed "Violoncello e Bassi." twice for the unboxed bottom staves and `score_header.reconcile`
   drops a consecutive duplicate without boxes; `--reconcile` re-runs that on the saved answer). Geometry
   16/16 on p172 to 175 and 17/17 on p176, one system per page (p173 and p176 were split before).
3. *Resolution* (`render_dpi`, `working_scale`, `prepare_page`): the page renders at the scan's own resolution
   when it is one embedded raster under 150 dpi (B9: 1513x1920, no invented pixels), and the geometry upscales
   by an integer when the staff spacing is under `SPACING_MIN` = 6 px. Measured: B9 native spacing is 7.0 to
   8.0, the same as the tuned 150-dpi scans (Rach 1 7.25, PC3 7.25 to 7.5, Dvořák 6.25), so a spacing threshold
   alone could never have separated them, and the native 10/16 was not resolution at all: the shadow bands lock
   the skew estimate to 0.0 (p172 is -0.4°, p176 -0.8°) and the thin lines then miss the row profile. With the
   shadows masked, native finds 13 to 15 of 16 and recovery completes every page, with a new hole-filling pass
   (two staves two pitches apart, the hole searched at 3 of 12 strip votes, not capped by the header count:
   p173 Viola, p176 Violin II). Crops are now 1.2 to 1.4k px wide (the scan's real pixels) instead of 3k.

Per page after (S / A / T): p172 S and A rest, T "Seyd umschlungen Millionen" (unchanged); p173 S "Seyd um_
_schlungen Mil_ _ _li_o_nen! die_ _sen" complete (before: "Seyd _schlungen _li o_nen! die_sen"), A alone with
the soprano's "um_ Mil_" above gone and no right-edge black band (before: A + unboxed T), T complete (before:
A + T pair); p174 S "Kuss der FF gan_ _zen Welt!" (before: "der gan_ _"); p175 S "Brü_ _der ü_bern Ster_ _
_nen_zelt" (before: "Brü_ _ _der _bern Ster_ _nen_"); p176 S "muss ein lie_ _ _ber Va_ _ _ter woh_nen."
(before: "ein lie_ _ber Va _ter woh"), T "Va _ter" as before. Every crop holds the right staff and nothing
else by eye; geometry verify passes on 14 of 15 (T p173: the system's final barline at x 1208 does not cover
0.9 of the thin single staff in the crop, present by eye); the recheck still mistakes the C clefs (soprano
clef read as "Alto", alto clef as "Viola", tenor clef as "Viola"): 11 of 15 crops are flagged needs_review by
the recheck alone (before: 5 of 10 S and A crops). Left: the grey gutter
texture next to the masked band (cols 50 to 110 at native) is not uniform enough for the mask and shows as a
faint strip at the crop's left edge; the recheck needs the header's clefs; the bar-aware rest rule is still
not ported to `cut.py`; `part_cut.py` must pass `voice` / `voice_above` to `cut_system` from the header
family (defaults keep the old behaviour).

## The job handler (`api/app/librarian/part_cut.py`, drafted 2026-10-27 on branch `worktree-agent-a4b9692edf1cec344`, commit 6c1885d; merged into main 2026-10-28 as 2524caf with 7f827d8)

- Kind `part_cut`, payload `{score_id, instruments: [str] (or instrument: str), interpretation_id?, pages?: [int],
  answer?, resume_from?, max_cost_usd? (2.0)}`. Runs on the agent loop (006): one model call per turn plus one
  inside `read_header`, one inside `read_page` (labels on the overlay; several instruments are asked in one
  call, `wanted: [{instrument, staves, status}]` per system), one per block inside `commit_system` (recheck,
  4000-token budget).
- `api/app/librarian/cut.py`: the geometry, overlay, clean-and-extend crop and verify ported from the
  experiment (no model). Since 2026-10-28 night also the header-driven staff recovery (003): `load_page`
  passes the header's `expected_staves` to `page_geometry` on every page read after `read_header`, and page 1
  is read again with it (the first read, before the header exists, only serves the overlay the header call
  sees); the header's families set the lyric rule's `voice` / `voice_above` per block (`voice_flags`: the
  block's instruments through the header entry's family, else the name; the staff above by score order when
  the system is full, else the header entry printed above the block's first instrument, or the last entry of
  the header when the block opens a system under a full one); the commit records `voices` per block with the
  lyric lines kept or erased.
- Recheck, closed since 2026-10-28 late (CK: the open "which instrument is this block?" asked about three
  questions in five choir pages, a lone C-clef staff being ambiguous between alto and tenor). `recheck_claim`
  builds the claim from what we already have: the page labels say which wanted part the block's staves are,
  the header entry gives the part's printed name, staff count and clefs. Spark is asked "according to the
  header and the labels this block is the CORO Soprano: 1 staff in the soprano clef; does this crop look like
  that? yes/no, staves seen, clefs seen, label seen, one line why". A no refuses the commit (three in a row
  park the question as before); a yes whose `clefs_seen` contradicts the header refuses too (`clefs_fit`:
  nothing seen, an unknown spelling or a generic "C clef" against a C-clef header passes; an instrument's
  seen clef must be one of the header's; for a voice any C clef or the treble passes against a C-clef or
  treble header, since the C clefs are exactly what Spark confuses and the labels plus the header already
  name the voice, so only a bass clef on a soprano, alto or tenor staff, or a C or treble clef on a bass
  voice, contradicts). The guards before the model call are unchanged (count, labels, geometry verify). The
  commit records `rechecks: [{block, verdict yes|no|clef, matches, staves_seen, clefs_seen, label_seen,
  why}]`. A geometric C-clef reader as a tie-break was tried and dropped (003, "Clef reading by geometry").
  Measured (2026-10-28 late, $0.17): the Soprano-alone run on the local Beethoven 9 chorus score (pages 172
  to 176) had parked three times with the open question, every time on the soprano block alone ("Coro Alto"
  from the C clef on p. 174 and 176, "Coro Tenore" on p. 175); with the closed check it ran to `done` with 0
  questions, 3 systems cut, $0.132 (the three rechecks answered yes, clefs seen "soprano"; this run's label
  step called pages 173 and 175 absent where the earlier run had found staff 12, a label-step variance, not
  the recheck's). Replayed over the experiment harness's five soprano crops (`out/piano-cut/beethoven-sym9
  .../soprano`, $0.037): the open recheck had flagged 2 of 5 ("Alto" on p. 174 and 176), the closed one
  refuses 0 of 5, clefs seen "soprano" on every crop. When the header lists the choir as one entry ("CORO.",
  4 staves, clefs S A T B, as the live header read it) the voice's clef comes from that entry (`chorus_clef`).
- Tools: `read_header` (once, first), `list_pages`, `read_page(page)` (geometry + proposal, overlay uploaded
  to `{score_id}/parts/{slug}/overlay-p{page:03}.png`), `commit_system(page, system, staves | blocks |
  "absent")` (commit: staves exist in the system, total count matches the header's sum over the chosen
  instruments, the union is split into contiguous blocks, crop verify and the closed Spark recheck per block
  against that block's own header entry), `finish` (commit: refuses while any
  page or system is uncommitted). `max_turns = 8 + 6 x pages` (choir pages have up to 4 systems),
  `max_refusals = 3`.
- Vocal pairs: in choral writing the barlines stop at each staff and do not cross the lyric gap, so a
  two-staff block never passes `barlines_present` over its full span; when `staves_in_crop` passes and every
  staff of the block has its barlines on its own, the block passes (`verify.barlines_present.per_staff`).
- Three refusals park the run with the typed Question payload `{kind: "choose_staves", page, system,
  instrument ("Soprano + Alto"), instruments: [...], interpretation_id, proposal (union or "absent"),
  blocks: [{staves, instruments}], staves_per_instrument, last_attempt, feedback, staff_boxes: [{index,
  y_top, y_bottom, x0, x1}], image_key, allowed: {staves, blocks, absent: true}, answer_format}`. The
  answer `{staves: [...] | "absent"}` or `{blocks: [[...], ...] | "absent"}` is applied as a successful
  commit: no recheck, no count or verify refusal either (011: the admin's words are final, and the geometry
  may have missed a staff); the run resumes with `resume_from` = the job that asked. State in
  `jobs.result.agent`.
- Outputs: strips at `{score_id}/parts/{slug}/p{page:03}-s{k}.png`; a `sources` row of kind `part_images`
  (`storage_paths` = strips in reading order, `meta` = `instrument` (joined label), `instruments` (list),
  slug, parent source, interpretation, per-system `staves`, `blocks`, key and bars; migration
  `20261028090000_part_images_source.sql`, applied locally, **not hosted**); an `interpretations` row, engine
  `part-cut-agent`, summary with counts and log, the page-intake placements copied under it (same measure
  ids); `parts` upsert named by the joined label with `storage_path` = first strip.
- Tests `api/tests/test_part_cut.py` (PIL-drawn pages, scripted model): happy path three pages, refusal then
  correct retry, escalation to needs_review then resume, absent page and finish refuses uncommitted, header
  from the overlay, matcher table, two blocks cut separately and stacked (gap measured, one recheck per
  block, a wrong recheck on one block refuses the commit), adjacent instruments as one block, a vocal pair
  through the per-staff barline fallback, absent for every chosen instrument, question and answer with
  blocks, admin answer against the header count, payload forms. `api/tests/test_routes.py`: the two routes
  through FastAPI's TestClient with the fake database. 50 passed with the loop tests (2026-10-28 evening).

### Live runs on the local stack (2026-10-28, Rach 1 Gutheil pages 1 to 5, Muse Spark 1.3, effort low)

Seeded with `uv run -m app.librarian.run seed --pages p01..p05.png`, run with
`uv run -m app.librarian.run part_cut --score <id> --payload '{"instrument": "Piano", "pages": [1,2,3,4,5]}'`.
The expected decisions are the experiment's: p1 s1 [11,12]; p2 [1,2] and [18,19]; p3 [6,7] and absent; p4 [7,8]
and [17,18]; p5 [3,4] and [13,14].

| Run | Header | Refused commits | Outcome | Cost |
|---|---|---|---|---|
| 1, before the header port | empty (old prompt, 2k budget, 3 JSON failures) | 5, the recheck caught every wrong guess | parked `needs_review` on p3 s2 after a streak of 3; resumed with `{"staves": "absent"}`, finished `done`, all 9 decisions right | $0.13 |
| 2, header ported (9a5c39e) | 15 instruments, 17 staves, first try | 2 | `done`, all 9 right | $0.13 |
| 3, with require/retry, before the JSON-only system prompt | same | 0 | `done`, but p2 s1 committed absent instead of [1,2] because the labels skipped it; led to the `absent` guard | $0.11 |
| 4, JSON-only system prompt and `absent` guard | same | 0 | `done`, all 9 right, no question asked | $0.10 |

What the runs proved: the loop's refusal reset works in practice (two refusals, four good commits, three
refusals, park); the resume path applies the admin's answer and continues; the derived `sources` row (kind
`part_images`, 8 crops in reading order, `meta.instrument`) and the `interpretations` row (engine
`part-cut-agent`, done) are written. Fixes that came out of the runs: the in-tool header, label and recheck
calls get their own JSON-only system prompt (the agent's "one tool per turn" prompt made Spark answer a label
request with a pretend tool call); a model commit of `absent` is refused unless the page labels say absent.

### Live runs: Beethoven 9 pages 172 to 176, two instruments (2026-10-28 evening, Muse Spark 1.3, effort low)

Seeded from the IMSLP 46254 PDF at 150 dpi (pymupdf, grey, 3153 x 4000). Expected from the single-part runs:
S 13 / A 14 / T 15 on p. 172 s1, p. 176 s4; S 12 / A 13 / T 14 on p. 175 s1; p. 173 and p. 174 depend on the
geometry (see below). `uv run -m app.librarian.run part_cut --score <id> --payload '{"instruments":
["Soprano", "Alto"], "pages": [1,2,3,4,5]}'`, answers through `--payload '{..., "resume_from": <job>,
"answer": {"blocks": [[13], [15]]}}'` (the shape `POST /jobs/{id}/answer` queues).

| Run | Outcome | Cost (usage_events) |
|---|---|---|
| S+A 1 | paused at the turn limit: every commit with staves raised `KeyError: 'pass'` (the refusal message walked the `clean` stats dict, which has no `pass`; latent since the draft, never hit on Rach 1 because verify never failed there) | $0.158 |
| S+A 2 | p. 172 s1 [13, 14] committed as one block (barlines per staff: a choir's barlines do not cross the lyric gap, so the whole-span check fails on every vocal pair; fallback added); parked on p. 173 s2 where the geometry found 8 of 15 staves and the labels could only offer the alto's box | $0.125 |
| S+A 2 resumed with `{"staves": [6]}` | `done`: 5 systems cut, 6 absent, 1 question; p. 174 [10, 11] and p. 175 [12, 13], p. 176 [13, 14] right; one recheck false alarm ("alto and tenor trombones") retried through | $0.116 |
| S+T 1 | labels right on p. 172 ([13, 15], the stacked case); parked: the recheck on the soprano block alone said Oboe, viola, Organ (a resting staff whose margin shows only the "O" of CORO) | $0.076 |
| S+T 1 resumed `{"blocks": [[13], [15]]}` | p. 172 stacked strip written; p. 173 absent x3 (geometry); p. 174 [10, 11]; p. 175 labels right ([12, 14]), parked: recheck on the soprano block said "Tenor" three times (soprano C-clef) | $0.117 |
| resumed `{"blocks": [[12], [14]]}` | p. 175 stacked; p. 176 labels right ([13, 15]), parked again on the soprano block, "Tenor" | $0.056 |
| resumed `{"blocks": [[13], [15]]}` | `done`: 4 systems cut, 7 absent, 3 questions; derived source written | $0.012 |
| S+T 2, with the recheck accepting any instrument of the export (tried, then reverted) | labels right ([13, 15]); the recheck refused the soprano block as "Viola", the model tried [16] ("Choir Basses", refused), then committed **[14, 15]** (alto + tenor, one staff off) and the loosened recheck let it through on "Tenor"; parked on p. 173 s2 (geometry) | $0.153 |

Decisions that came out of the runs: the recheck stays per block and must name the block's own instrument (or
"chorus" for voices); accepting any instrument of the export was tried on S+T run 2 and shipped a wrong strip, so
the strict rule stays and asks the admin instead (3 questions in 5 pages on the soprano's C-clef, which Spark
reads as "Tenor" on every unlabelled system; an open issue below). New guard, no model call: a block must agree
with the labels, the instruments whose proposed staves it touches must account for all of its staves (`[14, 15]`
against a proposal S 13 / T 15 is refused for the stray 14); a block that shares no labelled staff goes to verify
and the recheck as before. Also: 4000-token budget for the recheck (two truncations at 2048), `max_turns = 8 + 6
x pages`, the admin's answer skips the count and verify refusals as well as the recheck. Total Meta spend of the
evening: $0.80 over 134 calls (usage_events). The strips (looked at by eye): p. 172, 175, 176 of S+A are clean two-staff blocks, the soprano's
lyrics kept and the alto's partly erased; the stacked S+T strips on the same pages are two clean single staves with
a white hairline between them, readable for the notes, the lyrics half erased on both and the "CORO" margin label
split across the blocks. p. 173 and p. 174 are wrong on both exports: the geometry misses the neighbours, so the
band runs to the page edge and the strip holds half the system (p. 173 holds Vn to Cb; p. 174 holds S A T B
and the basses) and on p. 173 the soprano has no box at all. That is the staff recovery the experiment had
and `cut.py` lacks (003).

### Live runs: Beethoven 9, after the recovery port (2026-10-28 night, Muse Spark 1.3, effort low)

Same local score (150-dpi renders, 3153 x 4000), branch `worktree-agent-adcd9e203eadda81c`. The header came back
16 staves first try with the voices clefed right (CORO Soprano soprano, Alto alto, Tenore tenor, Basso bass;
"Alto e Tenore Tromboni" tenor). Geometry per page, the same on both exports: p172 16/16 found; p173 12 found,
4 recovered (9 Vn I, 10 Vn II, 14 Tenore, 16 Vc/Cb) = 16/16; p174 15 found, 1 recovered (9 Vn I) = 16/16; p175
16/16; p176 17/17 (Vc and Cb apart); one system per page, 8 / 5 / 9 / 6 / 5 bars. Soprano = staff 12, Alto = 13
everywhere (13 and 14 on p176). `voice` true on every block, `voice_above` false (the viola is above the soprano).

| Run | Outcome | Questions / refusals | Cost (usage_events) |
|---|---|---|---|
| S+A | p172 [12, 13] committed; parked on p173: the pair fails `barlines_present` over its span (expected, choir barlines) and the per-staff fallback failed too, because the soprano's fifth barline covers 0.83 of the staff at 1 px tolerance (the scan's barlines drift a px or two over a staff at 150 dpi; 1.0 at 2 px). Fix: the verify tolerance scales with the spacing (`max(1, round(sp / 8))`: 1 px on the tuned scans, 2 on B9). | 3 refusals, 1 question | $0.056 |
| S+A resumed `{"staves": [12, 13]}` (what the run would have committed) | `done`: 5 of 5 systems cut as [12, 13], p174 to p176 committed first try, every recheck accepted | 0 | $0.053 |
| S | this header call read every choir clef as "treble" (Spark varies between calls; the S+A run read them right), so the recheck context said treble and could not help. p172 [12] committed ("Coro Soprano", low); p173 [12] committed as "chorus" (accepted for a voice block); parked on p174: "alto solo", (one `absent` attempt, refused by the labels), "Alto Solo", "Tenore Solo", "Coro Alto" | 5 refusals, 1 question | $0.166 |
| S resumed `{"staves": [12]}` x3 (p174, p175, p176) | parked on p175 ("Coro Tenore" x3) and p176 ("Coro Tenore", "Coro Alto" x2), then `done`: 5 of 5 systems cut as [12] | 6 refusals, 2 questions | $0.095 |

Total of the night's runs: $0.370 over 65 calls (S+A $0.109, S $0.261). The labels were right on all 10
systems and the geometry on all 10; the single-staff soprano recheck is the one weak step left (the C clef read
as alto or tenor on 3 of 5 pages; the pair passes because the recheck says "Soprano" or "chorus" for it).

Strips by eye (S): p172 the resting staff; p173 "Seyd um_schlungen Mil_li_o_nen! die_sen", p174 "Kuss der
FF gan_zen Welt!", p175 "Brü_der ü_bern Ster_nen_zelt", p176 "muss ein lie_ber Va_ter woh_nen." all complete,
each strip the soprano staff alone with the alto's noteheads and words gone, no page-edge band.

Strips by eye (S+A): p172 both voices rest, clean; p173 S "Seyd um_schlungen Mil_li_o_nen! die_sen" complete,
A has no text on the page; p174 S "Kuss der FF gan_zen Welt!" complete, A "Kuss der FF"; p175 S "Brü_der ü_bern
Ster_nen_zelt" complete, A "ü_bern ... muss"; p176 S "muss ein lie_ber Va_ter woh_nen." complete. Every strip
is the whole S+A pair and nothing else: the page-edge bands are gone and p173 and p174 are whole systems (the
earlier runs held half the page there). Left: the grey gutter strip at the far left of each crop, and the "CORO"
margin label cut to "R O." on p172.

## The book's label memory (2026-10-30, migration `20261030140000_label_memory.sql`)

CK cut the piano out of the Beethoven Piano Concerto 3 (Breitkopf: "Klavier" on page 1, "Klav." after) and was asked
"which staves are the piano?" on every page. Reproduced on the local stack (PC3 test pages 1 to 4, score
`f00ff3d7`): parked on p. 2 s2 ([19, 20]), answered [19, 20], parked again on p. 3 s2 ([17, 18]). Why:

- The refusals were the closed recheck doubting a correct crop for reasons that are not the instrument ("three
  staves" from a sliver of the staff above, "sf notes from the staff above intrude at the top edge") while it read
  the label right every time (`label_seen` "Klav.", clefs treble and bass). The handler stored `label_seen` and
  never used it.
- Nothing carried a decision forward. The admin's answer committed that one system (`recheck=False`) and became a
  sentence in the agent's history; the next page ran the same recheck, refused three times, and asked again.
- The book's first reading (`process_pages`, 004) had read the header with "Klavier" and its abbreviation "Klav.";
  `read_header` read page 1 again with its own Spark call, and the header's abbreviations only reached the prompt
  text, never a check. `header.family("Klav.")` was None ("klav" was not in the piano synonyms).

The rule now (006, "Agentic memory rule"): what a book's earlier reads and the admin's answers established is
remembered and applied to later pages and later jobs.

- **Store**: `scores.label_memory` (jsonb, default `{}`), written by the API only. `{entries: {<norm label>: {label,
  part, source: "human" | "model", origin: "answer" | "header" | "header-abbreviation" | "page", page, staves,
  job_id, at}}, updated_at}`. Keys are the label normalised (`label_memory.norm`: lower case, no dots, commas or
  brackets). A human entry is never overwritten by a model read; a human answer overwrites anything; a model read
  never moves a model entry to another part. Writes merge with the row as it is (another job may have learned
  meanwhile); a missing column (hosted before the migration) never fails the job, and the job's state keeps a copy
  (`scratch.label_memory`) so a resumed run keeps what it learned.
- **Resolve**: the same key first, then the same instrument by the header's synonym table ("Pfte." is "Pianoforte";
  "klav" added to the piano synonyms) or as an abbreviation (first word a prefix of at least three letters), numerals
  agreeing ("Vl. I" is not "Violine II"). Two matching entries for different parts leave the label unresolved.
- **Seeded** by `process_pages` from its header (each printed name and abbreviation as the part the reading named:
  "Klavier" and "Klav." are "Piano"), and by `part_cut.read_header` from the header it uses. `read_header` now takes
  the book's header from the current interpretation (`params.state.header`, when it has the staff count) instead
  of reading page 1 again (004: the header is read once per book); a book never read that way still reads page 1.
- **Read per page**: the label call also returns every printed margin label with its staff numbers
  (`margin_labels: [{text, staves}]` per system; Spark reads labels, geometry placed the staves). A wanted
  instrument whose label resolves through the memory is `remembered` on that system when the page's proposal
  agrees; a system the proposal left empty is filled from the label (source model); when the two reads disagree
  nothing is remembered (`label_conflicts`) and the usual checks decide. The prompt carries the known labels ("In
  this book, "Klav." is Piano (confirmed by the user on page 2)").
- **Commit**: a block the memory settled from a human answer is committed with no recheck call (verdict
  `remembered`; count, labels and geometry checks still run). A block settled by the model's memory still gets the
  recheck; a no or a clef refusal whose `label_seen` resolves to the block's instrument is accepted (verdict
  `label`): two reads agree on the printed label and the book knows what it is. A label the memory does not know
  settles nothing, so a genuinely new label still asks.
- **Learn**: a commit that passed every recheck with a yes remembers the margin labels on its staves (source model,
  origin page, never a label the synonym table gives to another instrument); the admin's answer remembers the margin
  labels on the chosen staves, else the label the refused recheck saw on that very block (source human, origin
  answer). The answer message to the agent says what was remembered. The `choose_staves` payload carries
  `known_labels` and `margin_labels`; the interpretation summary counts `settled_by_memory`.

Live (2026-10-30, local stack, PC3 pages 1 to 4, Muse Spark 1.3, effort low): before, parked on p. 2 s2 and,
after the answer, again on p. 3 s2 ($0.14 for the two runs to the second question; the page reading before them $0.12); after, a fresh run went to
`done` with 7 of 7 systems cut and 0 questions, $0.138, 87 s, no header call (taken from the book's reading). The
labels were read on every system ("Klavier" on p. 1, "Klav." after); p. 2 s2 and p. 3 s2 were accepted on the
label (the recheck doubted the crop as before), the other five passed the recheck. Same staves as the answered
run. Tests: `tests/test_label_memory.py` (normalisation, seed, provenance, ambiguity, the row) and five handler
cases in `tests/test_part_cut.py` (the header seed settles "Klavier" then "Klav." with no question; a bare first
page asks once and the answer settles "Klav." on page 2 with no recheck; a new label still asks; a disagreeing page
is not settled; the book's header is reused). 284 passed.

Not done: `process_pages` does not consult the memory for its own parts question (its admin answers are part names
without the printed labels); a page with no margin labels at all is not settled by the memory (by-order still
proposes full systems); the web's Choose the staves dialog does not show what was remembered.

## On the iPad (web, 2026-10-28 night)

The action is called **Split by instrument** everywhere in the app (never "cut parts": *cut* is the bar-range
marking). `web/src/app/Parts.tsx` holds the picker, the job rows, the staff question and the finished splits,
all in the information box. A PDF book's flow is unchanged apart from the words: the instruments the first
page names (or typed names), `POST /scores/{id}/parts` with `{instruments}`, the strip opens at `?view=strips`.
A digital book (source kind `musicxml`) lists its own `parts` rows, posts the same route, and expects a done
job with `result {source_id, instruments, storage_path}` plus a new `sources` row of kind `musicxml` with
`meta.instruments` and `meta.slug` (the API side is another agent's work, not verified from the browser).
`data.tsx` treats `part_images` sources and `musicxml` sources with `meta.instruments`/`meta.slug` as splits;
digital splits open in the reader with only their instruments (`/score/{id}?split={source_id}`, OSMD part
visibility on the book's own file) and export their own file as MusicXML.

## Open issues

- Geometry on the Beethoven 9 choir pages: fixed 2026-10-28 night (recovery ported, the gutter `x0` fix,
  003); see "Live runs: Beethoven 9, after the recovery port" for the counts.
- Recheck false alarms on unlabelled pages: the prompt now carries the header's clefs and the chorus
  context; the geometric C-clef tie-break was tried and dropped (003). Still open: trusting by-order labels
  when the system is full, or a glyph-level clef reader.
- The grey gutter strip (cols 148 to 257 at 150 dpi) is still in every crop's left edge, faint; the bar-aware
  rest rule is still not ported to `cut.py`.
- Cross-page continuity; bar numbers on the strip (barlines already found, 004); "absent" as a first-class
  answer in the UI (011); orchestral cues for a concerto soloist (adjacent staves at reduced size).
- Spark JSON: malformed on about half the page calls at low effort; stray-token repair (`}-math]`,
  `word=digits`) and one retry stay; a bracket-closing repair for truncation was planned before the 8k budget
  made it rare.
- Apply the migrations to the hosted project when CK says (the routes are wired): `20261028090000_part_images_source`
  and `20261030140000_label_memory` (without the latter the cut runs, but remembers nothing between jobs).
- Decision pending from CK: whether item 6 becomes "intake + part cut" with OMR only behind practice mode.

## Files and output dirs

`out/piano-cut/` (gitignored): `REPORT.md`, `CLEAN.md`, `GENERALISE.md`, `HARDEN.md`, `GENERAL.md`,
`pages/`, `geom-p*.json`, `overlay-p*.png`, `label-p*.json` (prompt, raw text, parsed, cost, retries),
`crop-p*-s*.png`, `recheck-p*-s*.json`, `highlight-p*.png`, `part-p*.png`, `strip.png`, `results.json`,
`spend.json`, `spend-global.json`, `piano-cut.html` (side by side, data URIs, 2.4 MB), `clean-compare.html`,
`clean-debug-*.png`, `clean-preview-*.png`, `header.json`. Per score: `rach2-fullscore-imslp03631/`,
`beethoven-pc3-fullscore-imslp977417/`, `beethoven-pc5-fullscore-imslp977419/` (+ `violin-i/`),
`dvorak9-fullscore-simrock-1894/` (+ `flute-i/`, a first run on pages 6 to 10 parked in `extra-p10/`),
`beethoven-sym9-fullscore-imslp46254/` (`soprano/`, `alto/`). A bundle for Anthropic's Managed Agents
builder ("Score Stave Extractor", for its grader format, feature 016) sits in the scratchpad as
`stave-extractor.zip` (scripts + two 5-page excerpts + README).
