# 010 Distribution: parts to players, iPad reading view

Status: prototype (MusicXML scores render on the iPad-first score screen from signed URLs; parts match players by seat name; distributing cut images or highlighted page bands is not built) | Meta model: none (the parts come from 002, 004 and 008).

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

- Reading view for page images and strips (today only MusicXML renders).
- Highlighted staff band on the original page.
- Pages take long to engrave; consider caching OSMD output per part.
- Chrome hide/show on tap in document mode not built.

## Next steps

1. Image reading view with `measure_placements` overlays (tap a bar = select a bar, as in the tap test).
2. Strip reading view for `part_images` sources.
3. Real iPad pass of `touch.md`.
