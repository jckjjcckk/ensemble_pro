# Folio R3 design (CK, 2026-10-28)

Source: the Design canvas "Folio — Current Design" (https://claude.ai/artifact/6kyfBseE6dspJDPjvSZDTW).
Each `*.dc.html` is one artboard, self-contained HTML with inline styles; `canvas.json` lists titles and sizes.
Palette: paper #F3EFE6 / card #FBF9F4 / ink #1C1A16 / muted #6B665C / rule #E2DCCD, #CFC8B8; dark ground #141311,
surface #1E1C18 / #26241F; group blue #5B86C8; ask #D8A62B; failed #B5392E. Type: EB Garamond (display, book
titles, numbers), Inter (UI), Noto Music (clefs, accidentals). Sizes: 834x1194 portrait, 1194x834 landscape.

## Added 2026-10-28 night: when the reader is unsure (owner only)

`F_BookUnread` (book sheet with the amber "key could not be read" banner → Details), `F_Details` (title, composer,
key picker with the guess outlined in amber, time signature grid, cover clef, speed + marking, bar numbering),
`F_Parts` (blocking question "which parts are on page N": same as earlier pages / what the reader found / something
else, with a labelled page thumbnail, Later, Confirm and keep reading), `F_Staves` (choose the staves for a part in
one system; "isn't on this page" = absent), `F_CheckBar` (doubtful bars list with reasons, scan above digital for the
chosen bar, "Wrong, use the scan here" / "Looks right"), `F_Unreadable` (stand placeholder for a page with no staves:
Rescan page N / Show the scan as is). Rules: questions are owner-only and interruptible; the reader never rewrites
music, a rejected bar shows the scan instead.
