# 010 Distribution: parts to players, iPad reading view

Status: prototype (a digital book's full score reads from the pages MuseScore engraved on the box, in the book's chosen layout, 2026-10-28; a single part still renders on the device with OSMD; parts match players by seat name; distributing cut images or highlighted page bands is not built) | Meta model: none (the parts come from 002, 004 and 008).

## Purpose

Every member opens the same score and sees their part: for MusicXML, OpenSheetMusicDisplay renders the part;
for scanned scores, the original page with the part's staff band highlighted, or the cut strip (008) for
big scores. Landscape = two facing pages, portrait = one page. Mac landscape only, adapting to a half-width
window.

## What exists

- Score screen (`web/src/app/ScoreDoc.tsx`, `ScoreStage.tsx`, `Ruler.tsx`, `mock/ScoreView.tsx`): OSMD renders
  a fixture or a signed-URL file; after every render the app reads `GraphicSheet.MeasureList` and stores each
  bar's box, so cuts, loops, pins, presence and cursors are positioned overlays. Nobody edits OSMD's DOM;
  `.osmd svg` is repainted from `--ink` so dark themes invert the notation. Swipe turns the spread;
  long-press (500 ms) on a bar opens the marking composer; tap selects. Margin notes on landscape at 1180 px
  and wider; document tools go icon-only below 1000 px; the screen grid is constrained to the viewport.
  Fixed: `ScoreView` crashed with "load() needs to be called before render()" when page format and zoom
  changed in the same render; it tracks the loaded instance with a ref. Cleanup sets
  `osmd.AutoResizeEnabled = false` before `clear()`.
- Engrave times: the full Op. 18/1 score 12 to 16 s, Violin I about 10 s.
- Parts: `parts` rows per score (name, position, difficulty, `storage_path`); seats match parts by name
  (`members.part`); the information box shows parts with holder and one-word difficulty; violin2 sees the
  Vn II badge.
- Display setting: Instrument or Bound token set, theme auto/light/dark (`DESIGN.md`).
- Information box (2026-10-28 night, CK: "it still looks like a website"): a book's identity leads it. An
  engraved treble staff with the key signature and the time signature (`Identity.tsx`; glyph outlines are
  VexFlow 1.2.93's Gonville, the face OSMD engraves with, extracted once into `engraving.ts`; all
  `currentColor`, so the theme's ink draws it), the key named under it ("B♭ major", the mode the signature
  cannot show), and the length in bars, plus duration ("c. 7 min") for digital books. `keysig.ts` reads
  music21's `key_sig` ("E- major", "f# minor", case-insensitive) and `meter`; an unread or invalid key or
  meter leaves the signature's place empty on the bare staff, never a guess. Pages, tempo, the read result
  and the last change moved under the (i) beside the close button. Read flags stay visible as a count line.
- Every book carries one tag, PDF or Digital, on the cover and at the head of the box, from its first
  non-split source (`pdf`/`images` = PDF, `musicxml` = Digital; `Score.book` in `data.tsx`). "MusicXML" is
  said only on Import MusicXML and Export MusicXML (a digital book's stored file, or a digital split's).
- Digital splits (008) read on the stage with only their instruments: `/score/{id}?split={source_id}` adds
  the split as a choice in the part switcher and selects it.
- **Two ways into a book (2026-10-28, CK).** Below the identity block the book page has mode buttons: **Open PDF**
  (the pages as printed) and **Open Digital** (the engraving, part by part). A book with only a `pdf`/`images`
  source shows Open PDF and, for its owner or admin once it is read, a secondary **Convert to Digital**
  (`POST /scores/{id}/convert`, an `omr_convert` job, 005; a 404 reads "Converting to Digital is not available
  yet."). While it runs the button shows the breathing ring and "Digitalising", and the book's "…" menu says
  "Digitalising in progress". When the transcription lands (a `musicxml` source with `meta.transcribed_from`, plus
  `parts` rows) the book carries both tags, PDF and Digital (`Score.kinds`), both buttons are active, Open Digital
  reads the transcription on the stage (the score's file falls back to the transcription when no part has a
  file of its own) and Export MusicXML exports it. A book imported from MusicXML shows only Open Digital.
  Split by instrument and Export stay where they were.
- **Open Digital reads engraved pages (2026-10-28 night, CK: rendered server-side by MuseScore, not on the device;
  005).** When a book has `engraving` sources, the full score on `/score/{id}` is drawn by `EngravedStage.tsx` instead
  of OSMD: the chosen layout's SVG pages as images (signed URLs, one batch per page set), fitted like the PDF reader
  (one page per screen in portrait, two facing in landscape, dark themes invert the paper), and the stage `Geo` built
  from the `.mpos` bar boxes (fractions of the page scaled onto the page's rectangle; a system is one page and one y).
  Because the geometry has the same shape OSMD's had, highlights, notes, cuts, scribbles, presence faces and Follow work
  on the pages unchanged; the pointer gestures (tap, 500 ms hold, swipe) moved to `stageGestures.ts`, shared with
  `ScoreStage`. OSMD stays the fallback: a single part, a split, or a book without pages. Verified in the browser pane
  on the Beethoven quartet imported into the local stack: 22 pages optimised for digital display, 21 as the file prints
  them, a tap on bar 4 opens its quick menu, Violin I falls back to OSMD; screenshots in the session notes.
- **Layout toggle.** The book's "…" menu carries "Preserve original formatting" (a `menuitemcheckbox`; off means
  "Optimised for digital display", said under it), for whoever may edit the book; it writes `scores.digital_layout`
  and the world reloads. A cover at the shelf's left edge now hangs its menu from the button's left edge (before, the
  menu left the viewport).
- **Open PDF** is `/score/{id}/pages` (`web/src/app/Pages.tsx`): the rendered pages `{score_id}/pages/{n}.png`
  (listed from the bucket, so pages appear as the import renders them) or a camera intake's photographs in
  `page_order`; one page per screen in portrait, facing pages in landscape with page 1 alone as a right-hand
  page, snapping spread by spread, dark themes invert the paper like the strips. The dock offers the PDF file
  itself (signed, the iPad's own viewer) and Open Digital when there is one. Verified on three repo page images
  through the temporary harness at 1024x768; not seen with a real import's pages.
- The reader is reached through the dock's Book place, and Read / Practise is a toggle in its header (001).
- **A personal book shared with a group (2026-10-28, 001).** By reference: the group reads the owner's book, its
  pages, its Digital file and its splits' rows from the owner's library; nothing is copied. On the group shelf it sits
  in "Shared with the group" with "Shared by {name}"; for anyone but the owner its page and menu offer only Open PDF
  and Open Digital. Marks are per layer (`ensemble_id` on `annotations` and `scribbles`): the owner's private marks
  stay private, the group's marks live in the group's layer and are kept when the book is unshared. The reader writes
  and filters the layer from `useStore().markGroupFor(score)`; the scribble upsert's `onConflict` gains
  `ensemble_id` (rules and contract in 001 and in `20261028200000_score_shares.sql`).
- **Every stand live (2026-10-28, build-queue item 5, details and numbers in 012).** Marks, cuts and scribbles from
  other members arrive on the open score as Realtime row changes and are drawn with a 200 ms fade; the stage never
  re-engraves for them. The header's presence faces are the real members of the group the book is read in, each with
  the bar they are on; the admin's face is filled ink; a tap on a face shows that bar (touch.md line 8). A player
  has **Follow** in the header: the spread turns with the admin's bar, and any turn of the player's own (swipe, the
  turn buttons, arrow keys, the ruler, a face, a marking) switches it off; it holds still while the quick menu,
  the scribble tools or the composer are open. Default off.
- Bound's facing-pages book view (`engraving.tsx`: `useEngraving`, `segments`, `Book`, in
  `docs/design/explorations/4.md`) is a stretch display setting after Nov 1.
- Acceptance: `docs/acceptance/touch.md` lines 3 to 8 and 12 (not yet run on the iPad).
- For scanned scores the per-part deliverable is the `part_images` source (008): one cut system image per
  "page", `storage_paths` in reading order; or the original page plus the staff boxes already in
  `measure_placements` for the highlighted band.

## Rules and decisions

- Choir feedback (2026-10-27): SATB singers keep the grand sheet; distribution for small scores = the
  original page with your staff band highlighted (we have the staff boxes); true extraction (crop + stitch
  per part) only for 10+ staff full scores.
- Player sees their part and their own notes plus admin notes addressed to them (000).
- iPad first; 44 pt targets; swipe is the page turn.
- A part export is a user-chosen selection of parts (008 contract), so the reading view must accept a strip
  that holds two voices.
- Words: Split by instrument (not cut parts), Digital (not MusicXML) as a book's kind, Reading (not
  processing). The identity block is notation, not typed text.

## Open issues

- The page reader shows pages only: no bar overlays, no markings, no swipe turn beyond native scroll-snap.
- Highlighted staff band on the original page.
- Pages take long to engrave on the device for a single part (the full score now comes engraved from the box; a
  part's own pages are the next step, 005).
- The composer line under the reader's title shows the last word of the composer ("van" for "Beethoven, Ludwig van").
- Chrome hide/show on tap in document mode not built.

## Next steps

1. `measure_placements` overlays on the page reader (tap a bar = select a bar, as in the tap test).
2. Open Digital on a converted book end to end through the UI (the engraving step runs at the end of `omr_convert`;
   seen only on an imported MusicXML so far).
3. Real iPad pass of `touch.md`, including line 8 (tap a face) and Follow between two iPads.
