# IMSLP sonatas: Beethoven Op. 27 No. 2 in two editions

Two whole books for the E2E night (2026-10-31, `docs/features/018-e2e-night.md`), run whole with CK's approval.
The PDFs are public-domain IMSLP scans and are not committed (13 MB); this file is the truth table.

| file | pages | edition |
|---|---|---|
| `beethoven-op27-2-moscheles.pdf` | 18 | Moscheles' edition (Hallberger): p. 1 title, pp. 2-15 music, pp. 16-18 the publisher's catalogue |
| `beethoven-op27-2-cappi-1802.pdf` | 16 | the first edition (Cappi, Vienna 1802): p. 1 title, pp. 2-15 music, p. 16 blank |

Reference totals in the standard numbering (upbeats not counted, a repeat's closing part-bar counted once):
I. Adagio sostenuto 69, II. Allegretto 36 + Trio 24 = 60, III. Presto agitato 200; **329** in all.

## Moscheles: bars per page, provisional truth (counted by eye, E2E night)

| page | content | bars | the reading (process_pages) | note |
|---|---|---|---|---|
| 1 | title | - | - | no staff ("cover") |
| 2 | I | 19 | 19 | |
| 3 | I | 24 | 24 | |
| 4 | I, end | 26 | 23 | I = 69, as the standard |
| 5 | II Allegretto + Trio | 60 | 64 | standard numbering; my count of the printed measures did not settle at 60 (the Allegretto came to 37-38 with its upbeat, the Trio has two upbeats and two closing part-bars): **recount before using p. 5** |
| 6 | III | 21 | 21 | |
| 7 | III | 19 | 19 | |
| 8 | III | 26 | 26 | |
| 9 | III | 25 | 20 | |
| 10 | III | 21 | 17 | |
| 11 | III | 16 | 16 | |
| 12 | III | 23 | 24 | |
| 13 | III | 14 | 14 | |
| 14 | III | 17 | 19 | |
| 15 | III, end | 19 | 22 | III = 201 by this count against the standard 200: one bar too many somewhere on pp. 6-15, not found |
| 16-18 | publisher's catalogue | - | - | no staff ("back" since e67658f) |

The reading: 328 bars (the page sums drift where a system's bars are miscounted and where a bar is split over a
system break). Convert to Digital on main (Audiveris per page, e67658f): 332 bars; Audiveris counts every printed
measure, upbeats included.

## Cappi 1802: movements by page (bars per page not counted)

| pages | content | bars (standard) | the reading |
|---|---|---|---|
| 1 | title | - | - |
| 2-4 | I Adagio sostenuto | 69 | 14 (5 + 5 + 4) |
| 5 | II Allegretto + Trio | 60 | 7 |
| 6-15 | III Presto agitato | 200 | 86 |
| 16 | blank | - | - |

The first edition's engraving runs a bar over the system break on most lines and spaces the bars unevenly, so the
per-page count by eye was left for a later pass; the movement pages come from the contact sheet and the reading's
tempo landmarks (Allegretto at the reading's bar 15, the first bar of p. 5). The reading's 107 bars against 329 is
the result to beat, whatever the per-page truth turns out to be.
