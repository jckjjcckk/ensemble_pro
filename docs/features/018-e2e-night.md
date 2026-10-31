# 018 E2E night: every book through the real chain

Status: run 2026-10-31 (night), main eacc5bf → see the commits below | Meta models: Muse Spark 1.3 (page reading,
part cut, convert passes, voice proposals), Muse Voice Transcribe 1.0 (voice notes). SAM 3.1 is not on this path.

## How it was run

The chain as the iPad uses it: hosted Supabase (the test project), the Mac dev API (`WORKER=0`, reached through the
tunnel) and yoga's stable worker (0fca589, `WORKER_CONCURRENCY=2`), which claims every job and runs the OMR box.
Voice runs in-process on the API that receives it, so voice ran on main.

Everything was driven as admin1@muse.test, exactly as the client does it (`web/src/lib/api.ts`, `data.tsx`): the row,
the upload and the source under RLS with admin1's token, then the API call. Sessions came from the service role
(`generate_link` + `verify`), never a password or the sign-in screen. The demo group "Hart House Quartet" was made the
same way: admin1 admin, test1 Violin I, test2 Cello (muse2@muse.test does not exist; test2 was used).

Harness: `api/experiments/e2e_night/` (`book.py` import, wait, answer, cut, convert, check, delete; `voice.py`;
`live_index.py`; `realtime_listen.mjs`; `setup_group.py`; `local_job.py`). Results per book in `results/*.json`,
every model call in `spend.jsonl` (copied from `usage_events`, by event id, under the book its job worked on).

**Fixes on main, verified before yoga moves.** Reading, cutting, converting and importing run on yoga, which stays at
0fca589. `local_job.py` runs one such job on main's code in this process against the same hosted project: the row
goes in `running` (claim_job takes only `queued`) with the payload the API would give it, and `worker.run_one` runs
it here, the box reached over ssh. The first three local runs went to Claude by mistake (the Mac's `api/.env` says
`LLM_PROVIDER=anthropic`; yoga says `meta`): $4.00 of Claude, two Goldberg cuts and one Moscheles convert. The runner
now forces `meta`, and every result below that says "main, local" is the Spark run unless it says Claude.

## Headline

| Book | Pages | Read: s, $ | Bars (truth) | Split: questions | Convert | Voice | Result |
|---|---|---|---|---|---|---|---|
| Op. 18/1 mvt 1 (MusicXML, group) | 13 | 35.0 s, $0 | 313 | Digital split 3 s, 0 | - | 2 lines, players see their marks | pass |
| PC3 p1-4 (group) | 4 | 98.4 s, $0.165 | 70 (56) | Violine I 2 (yoga) → 0 on main; Klavier pair 0 | 286 s, $0.314: 70 bars, 60 parts | cello mark hidden from the cellist | bugs fixed / open |
| PC5 p1-4 (group) | 4 | 148 s + 1 parts question, $0.202 | 28 (25) | Pianoforte 0; Violino I + Violoncello 5 (yoga) → 1 on main | failed (Audiveris NPE p4) | Violino I mark hidden | bugs fixed / open |
| Sym 9 p3-6 (group) | 4 | 121 s, $0.097 | 28 | Violoncello 1; Violoni + Vc 2 | failed (1826 scan) | - | open |
| Rach 2 p1-4 (group) | 4 | 71.5 s, $0.072 | 34 (34) | Piano 0; Violini I + Violoncelli 0 | 184 s, $0.177: 30 bars, 29 parts | - | convert wrong |
| Chopin polonaises p4-7 | 4 | 36.9 s, $0.053 | 70 | Piano 0, 105 s | 135 s, $0.181: 70 bars, 1 track | bar 22 right; bar 112 refused (book ends at 70) | pass |
| Goldberg p1-5 | 5 | 53.8 s, $0.067 | 119 (119) | "Aria": a question on every line (yoga) → 0 on main | 161 s, $0.231: 119 bars | - | bugs fixed |
| Moscheles Op. 27/2 | 18 | 106 s, $0.150 | 328 (329) | Pianoforte 0, 592 s, $0.434 | failed (yoga) → 296 s, $0.631, 332 bars on main | - | bug fixed |
| Cappi 1802 Op. 27/2 | 16 | 113 s, $0.172 | **107** (329) | Pianoforte 3, 63 systems, $0.549 | failed (yoga; p. 16 blank sent) → failed on main too (Audiveris staves) | 2 lines right | reading wrong |
| Clara Schumann Lied (.mxl) | 2 | failed ×3 (yoga) → 13 s on main | 41 | - | - | - | bug fixed |

Truth for the four test PDFs is `docs_offline/benchmark.md` and the fixture docs; for the sonatas,
`api/fixtures/imslp/README.md` (counted by eye tonight).

## Per book

Times are wall clock from the request to the row's last state; cost is the job's `usage_events`.

### Op. 18 No. 1, first movement (MusicXML, the demo fixture, Hart House Quartet)

| Step | Time | Cost | Result |
|---|---|---|---|
| import (MusicXML) | 35.0 s | $0 | ready: 313 bars, parts Violin I, Violin II, Viola, Cello; 4 MIDI tracks; bar map 313/313 |
| split Cello; Violin I + Cello (twice) | 3.2 / 3.0 / 3.3 s | $0 | `part_split` done at once, no model |
| voice v03 "Cellos, bar twelve, up bow" | 7.0 s | $0.0034 | bowing, bar 12, part Cello; accepted; test2 (Cello) reads it, test1 does not |
| voice v12 "Pickup to thirty-four, firsts" | 7.6 s | $0.0043 | text, bars 33-34, part Violin I; accepted; test1 reads it, test2 does not |
| delete | 0.9 s | - | 204; every child row gone (cascade); the Storage files stay (no cleanup) |
| re-import (op18b) | 39.4 s | $0 | ready again |

### PC3 p1-4 (Breitkopf full score, group)

| Step | Time | Cost | Questions | Result |
|---|---|---|---|---|
| import + reading | 98.4 s | $0.165 | 0 | 70 bars (truth 56: the cadenza and split systems over-count; printed numbers ignored) |
| split Violine I (yoga) | 2 questions | $0.084 | 2 | 7 systems; both questions from the crop check failing on a bowed staff → f880fc1 |
| split Violine I (main, local, Spark) | 43.1 s | $0.085 | 0 | 7 systems |
| split Klavier oben + unten | 87.5 s | $0.175 | 0 | 7 systems |
| convert (yoga) | 285.8 s | $0.314 | - | 70 bars, **60 parts** (Audiveris reads each page's condensed system as new parts; the per-page run fell back to the whole book); 58 MIDI tracks; MusicXML landmarks replaced the page ones with key changes that are not there |
| voice v03 "Cellos, bar twelve, up bow" | 7.4 s | $0.0037 | - | bar 12 right, audience part "Violoncello and Double Bass": **test2, seated Cello, cannot read it** |
| voice v01 "Everyone, bar thirty-four, piano" | 7.3 s | $0.0038 | - | p at 34, everyone; both players read it |
| Realtime (two channels, node supabase-js, 231 events) | - | - | - | every job, score, interpretation, parts and sources change arrived, including the answer-resume inserts; two events within one millisecond can arrive out of order |

### PC5 p1-4 (group)

| Step | Time | Cost | Questions | Result |
|---|---|---|---|---|
| import + reading | 147.7 s + answer + 4.3 s | $0.202 | 1 (parts on p. 4) | the answer "…, Timpani in Es, B, …" became two parts, "Timpani in Es" and "B" → 9e88fa0 |
| split Pianoforte | 41.0 s | $0.058 | 0 | 7 systems |
| split Violino I + Violoncello (yoga) | 5 questions | $0.201 | 5 | 6 systems; three questions because a two-instrument split never learned the shared cello staff's label → cc4b30d (+ Breitkopf cello abbreviations) |
| split Violino I + Violoncello (main, local, Spark) | 79.7 s + 7.5 s | $0.107 | 1 | 6 systems; the one question is p. 4 line 2, where the geometry finds 8 of the 11 staves (Viol. II, Viola and the cellos missed, the known p. 4 staff miss): Violino I answered, the cello is not on offer |
| convert (yoga) | 62.8 s | $0.0009 | - | failed: Audiveris NullPointerException on p. 4 |
| voice v18 "Fiddles, bar seven, down bow" | 7.0 s | $0.0039 | - | heard as "firsts": Violino I only (ASR); **test1, seated Violin I, cannot read "Violino I"** |
| voice v26 "Seconds, bar fifty-five…" | 8.5 s | $0.0051 | - | refused, rightly: bar 55 is not in this 28-bar book |

### Beethoven 9, p3-6 (the 1826 scan, group)

| Step | Time | Cost | Questions | Result |
|---|---|---|---|---|
| import + reading | 121.1 s | $0.097 | 0 | 28 bars |
| split Violoncello | 1 question | $0.083 | 1 | 4 systems |
| split Violoni + Violoncello | 2 questions | $0.179 | 2 | 4 systems |
| convert (yoga) | 55.0 s | $0.0056 | - | failed: Audiveris cannot read the 1826 scan |

### Rachmaninoff 2, p1-4 (group)

| Step | Time | Cost | Questions | Result |
|---|---|---|---|---|
| import + reading | 71.5 s | $0.072 | 0 | 34 bars = truth |
| split Piano | 42.5 s | $0.050 | 0 | 7 systems |
| split Violini I + Violoncelli | 159.5 s | $0.159 | 0 | 7 systems |
| convert (yoga) | 184.4 s | $0.177 | - | 30 bars of 34, 29 parts; the bar map lacks bars 31-34 (the book's bars come from the reading, the playback from the transcription) |

### Chopin polonaises (Ekier), p4-7

| Step | Time | Cost | Result |
|---|---|---|---|
| import + reading | 36.9 s | $0.053 | 70 bars (counts from p. 4 run one off the printed numbers: printed numbers are not read) |
| split Piano | 104.6 s | $0.117 | 20 systems, 0 questions |
| convert (yoga) | 134.5 s | $0.181 | 70 bars, 1 MIDI track, bar map complete, 11 landmarks |
| voice v24 / v08 | 7.5 / 6.7 s | $0.008 | bar 22 right; "bar 112" refused (the book ends at 70) |

### Goldberg Variations (BGA), p1-5

| Step | Time | Cost | Questions | Result |
|---|---|---|---|---|
| import + reading | 53.8 s | $0.067 | 0 | 119 bars = truth; the picker offers "Aria" (the header read the title as the instrument) |
| split "Aria" (yoga) | 41 s, then 11 s a line | $0.06 | 3 (stopped) | a question on every line: the header entry "Aria." was never matched to "Aria" (one staff expected), and the admin's two-staff answer did not hold for the next line |
| split "Aria" (main, local, Claude) | 150 s | $1.68 Claude | 0 | paused after 50+ turns with nothing cut, no question: the agent stopped calling tools after the count refusal |
| split "Aria" (main + both fixes, local, Claude) | 176.6 s | $1.44 Claude | 0 | 30 systems cut |
| split "Aria" (main + both fixes, local, Spark) | 133.2 s | $0.165 | 0 | 30 systems cut (2a88828) |
| convert (yoga) | 161.3 s | $0.231 | - | 119 bars, 1 track, bar map 119/119, 20 MusicXML landmarks (benchmark 2.10: 114.7 s, $0.220 alone on the box) |

### Moscheles, Op. 27 No. 2 (18 pages, whole)

| Step | Time | Cost | Questions | Result |
|---|---|---|---|---|
| import + reading | 105.7 s | $0.150 | 0 | 328 bars (329): p. 4 three short, p. 9 five, p. 10 four short; p. 12, 14, 15 over |
| split Pianoforte (yoga) | 591.7 s | $0.434 | 0 | 81 systems |
| convert (yoga) | 242.8 s | $0.004 | - | failed: "could not read this PDF" (pp. 16-18 catalogue sent to Audiveris; p. 13 TimSort crash) |
| convert (main, local, Claude passes) | 257.4 s | $0.89 Claude | - | pages 2-15 read, 16-18 "back", 332 bars, playback 1 track; bar map lacks bar 117 of 333 measure rows (e67658f's message quotes this run's cost; the Spark run is the one below) |
| convert (main, local, Spark) | 296.2 s | $0.631 | - | the same: pages 2-15 (p. 13 read on the legacy-sort retry), 16-18 "back", 332 bars, one track over 332 bars; Audiveris 165 s of the box's 191 s (five pages at once while the Cappi convert ran beside it) |
| voice | - | - | - | (not run on this book) |

### Cappi 1802 (16 pages, whole)

| Step | Time | Cost | Questions | Result |
|---|---|---|---|---|
| import + reading | 113.2 s | $0.172 | 0 | **107 bars of 329** ("ready"): the first edition runs bars over the system breaks and the reading counts a few bars a page |
| voice v24 / v01 | 6.7 / 7.2 s | $0.008 | - | bars 22 and 34, everyone; accepted and dismissed through commit_marks |
| split Pianoforte (yoga) | 415 s to the first question, 139 s after the last answer | $0.549 | 3 | 63 systems. p. 8 line 1: the crop check missed a barline on the lower staff (answered [1, 2]); p. 12: the geometry took line 4's grand staff for two one-staff systems, asked twice ("line 4" [7], "line 5" [8]) |
| convert (yoga) | 342.6 s | $0.005 | - | failed, "could not read this PDF": pages 2-16 sent, p. 16 blank |
| convert (main, local, Spark) | 976.1 s | $0.005 | - | failed after both box runs: p. 16 stayed out ("back"), every page read, but Audiveris saw three staves on some pages and two or four on others, so neither the stitched book ("movement 4 has 3 staves, movement 1 had 2") nor the whole-book run lined up; 16 minutes to a failure |

### Clara Schumann, Op. 12 No. 4 (compressed .mxl)

| Step | Time | Result |
|---|---|---|
| import (yoga) | 62.4 s | failed three times: UnicodeDecodeError, the zip handed to music21 as text → 9b44938 |
| the same job on main (local) | 13.3 s | ready: parts Voice and Piano (the grand staff one part), 41 bars, 2 MIDI tracks, bar map 41/41, 9 landmarks; engraving "offline" from the Mac (MuseScore runs on yoga) |

## Across the books

- **409 naming the live job**: a second Split of the same parts and a second Convert, while the first was queued or
  running, got 409 `{message, job_id, kind, status}` naming it, on every book (`duplicate.names_live_job`).
- **One live job (`jobs_one_live`)**: a second `omr_convert` row for a book with one running, inserted with the
  service role past the route, was refused by Postgres (23505).
- **commit_marks**: accept (p_update with bars and `live`) and dismiss (p_remove) worked on every card; dismissed rows
  are gone.
- **Landmarks and label memory**: every PDF book has page landmarks after reading (1 on Sym 9 to 27 on the Goldberg) and label memory (2 entries
  from the header, more after a split); a converted book's MusicXML landmarks replace the page ones.
- **Delete and re-import**: delete cascades every child row; Storage files are left behind.
- **Hosted backfill**: 8 hosted books, all Digital, made before 2026-10-30, have neither landmarks nor
  playback. `api/scripts/backfill_landmarks_playback.py` (music21, no model; dry run by default, `--apply`, `--owner`)
  found the same 8 on 2026-10-31: ck@muse.test 5 (the benchmark's Goldberg and Rach pages), admin@muse.test 2 (the
  Hart House Chamber Players quartet and chorale), piano@muse.test 1 (the Mazurka); 2 of the 8 print no landmark (the
  homr Rach page, the chorale), so only their playback would change. None belongs to admin1, test1 or muse2 (no such
  account); the apply for them wrote nothing. Left for CK: `--apply --owner admin@muse.test` (and ck@, piano@).

## Bugs fixed (main, not pushed)

| Commit | Bug | Where it runs |
|---|---|---|
| f880fc1 | 008 a bowed staff's barlines fail the crop check: PC3 Violine I asked twice (→ 0 on main, Spark) | yoga |
| 9e88fa0 | 004/011 a part name with a comma ("Timpani in Es, B") became two parts | yoga (+ web) |
| cc4b30d | 008 a two-instrument split never learned the shared staff's label: PC5 asked 5 times (→ 1 on main, Spark) | yoga |
| 9b44938 | 002 an imported .mxl crashed the import | yoga |
| e67658f | 005 trailing catalogue pages and a page Java refuses to sort failed a whole convert (Moscheles → 332 bars on main) | yoga (the box script ships with the job) |
| 2a88828 | 008 an instrument the synonyms do not know never found its own header entry, and the admin's staff count did not hold for the next line (Goldberg "Aria": a question on every line → 0) | yoga |

## Open

- **Seat names are not part names (for CK).** RLS shows a part mark when `audience_part = my_part(...)`, the member's
  seat, exactly; the stand matches seat to part by exact name too (`Stand.tsx` `parts.find(p => p.name ===
  persona.instrument)`). A PDF book's parts carry the printed names ("Violoncello and Double Bass", "Violino I"),
  the group's seats say "Cello", "Violin I": tonight the cellist and the first violin could not read the marks meant
  for them on PC3 and PC5 (on Op. 18, whose parts are named like the seats, both could). A fix needs one equivalence in
  three places (the policy, the stand's default part, the marks' part lookup), or a seat-to-part map per book; the
  voice handler alone cannot fix it without breaking the stand. The demo's Op. 18 path is not affected.
- **Orchestral convert**: PC3 60 parts and 70 bars (56), Rach 2 29 parts and 30 bars (34) with the last four bars
  missing from the bar map; the MusicXML landmarks then replace the reading's with wrong key changes.
- **Audiveris refuses whole PDFs**: PC5 (NPE on p. 4), Sym 9 (the 1826 scan), Cappi 1802 (staff counts that change
  from page to page, so neither box run lines up, and the failure comes after 16 minutes). One failed page fails the
  convert; dropping the page (it would be `pages_unreadable`) is a product choice.
- **Bar counts**: printed bar numbers are not read; split bars at system breaks and cadenzas over- or under-count
  (PC3 +14, PC5 +3, Moscheles -1 overall with errors of 3-5 a page, Cappi 107 of 329, reported "ready").
- **A cut can end with nothing cut and no question** (`paused`, seen once on Claude): the iPad shows a finished split
  with no part.
- **A parked question replays the transcript of whichever model wrote it**: resuming yoga's Spark transcript on
  another provider was refused (400 on `redacted_thinking`); a key or provider change strands parked questions.
- **Moscheles Digital**: 333 measure rows, 332 bars in the bar map (bar 117 missing); 332 vs the standard 329
  (Audiveris counts the upbeats).
- Goldberg: the label memory learns variation titles ("Var. 2. (a 1 Clav.)") as the Aria's labels.
- Page-read time and cost above the benchmark on orchestral pages (PC3 24.6 s and $0.041 a page vs 7.4 s corpus).
- The Lied's bar-1 tempo in the bar map is 74 where the score's sound tempo is 80.

## Not verifiable tonight

- Anything on the iPad screen itself: the simulator stayed signed in as admin1 and untouched.
- The fixes on yoga's path, on yoga: yoga stays at 0fca589; each was run on main locally instead (see above).
- Engraving from the local runner (MuseScore lives on yoga; the Mac's call failed), so a local convert's render check
  could not run and its "to check" count is inflated.
- Players' stands receiving marks live (RLS reads were checked as test1/test2; no second device).

## Spend

Ledger `api/experiments/e2e_night/spend.jsonl`: every `usage_events` row of admin1 since 09:20 UTC (1,411 calls),
under the book its job worked on.

| | Meta (Spark + VT) | Claude |
|---|---|---|
| PC3 | 0.830 | |
| Moscheles | 1.228 | 0.894 (local runner) |
| Cappi | 0.740 | |
| Goldberg | 0.560 | 3.110 (local runner) |
| PC5 | 0.519 | |
| Rach 2 | 0.458 | |
| Chopin | 0.359 | |
| Sym 9 | 0.282 | |
| Op. 18 | 0.008 | |
| **Total** | **4.982** of the $12 cap (VT 0.004) | **4.004**, by mistake |
