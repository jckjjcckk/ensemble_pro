# Demo video: shot list (3:00)

Built from the demo script in `docs/features/017-demo-and-submission.md` and build-queue items 9 to 11 (Nov 2
integration and rehearsal run-through, Nov 3 recording and final cut, Nov 4 verification and submission before
9 PM ET). The order follows the script: the problem, the librarian at work, the question it has to ask, the
wow moment (a cut and a spoken instruction reaching the stands), play the parts, the close.

Markers: **[2 iPads]** needs two signed-in devices in frame or cut together; **[mic]** needs the real iPad
microphone, recorded live, not dubbed.

Devices: **iPad A** is the admin's (CK's iPad Pro 13, signed in as Ada, admin of Hart House, plays viola).
**iPad B** is a player's (signed in as Noor, Violin II). The pianist's shots use iPad A signed in to the pianist's
personal library, or a third account if a device is free.

Books:

- **Goldberg** (Bach-Gesellschaft, IMSLP06984): a 5-page cut starting at the first music page, from
  `api/fixtures/pdf/goldberg-bga.pdf`. Imported live in shot 3, plus a copy imported and converted beforehand.
- **Concerto** for the question: Beethoven Piano Concerto 3 test pages 1 to 4 (`beethoven-pc3-fullscore-imslp977417.pdf`)
  or Rachmaninoff Concerto 1 pages 1 to 5. Which book asks reliably must be settled in the Nov 2 rehearsal run
  (the label memory now settles labels the header names, so a question is not guaranteed).
- **Op. 18/1**: Beethoven, String Quartet Op. 18 No. 1, first movement, MusicXML
  (`web/public/fixtures/beethoven-op18no1-mv1.musicxml`, 313 bars), in Hart House with all four parts assigned.

## Shots

| # | Time | Dur | On screen | Said (one line) | Device | Book | Fallback |
|---|---|---|---|---|---|---|---|
| 1 | 0:00 | 0:12 | Paper parts on four stands; a cut pencilled on three parts and not the fourth; a page turn fumbled | "In a rehearsal, the parts never quite agree." | Camera, no iPad | Printed Op. 18/1 parts | Stills of the stands with the line as a caption |
| 2 | 0:12 | 0:06 | The Shelf on iPad A, the book covers, the wordmark | "Folio is a librarian for the whole ensemble, on iPads." | iPad A | Shelf | None needed |
| 3 | 0:18 | 0:12 | Import a PDF from Files; the card's blue rope runs while the librarian reads | "Drop in a scan, and the librarian reads it." | iPad A | Goldberg, 5 pages | Cut the wait (a 5-page import took 23.4 s in testing); if it stalls, use the copy imported beforehand |
| 4 | 0:30 | 0:12 | Book sheet: key, meter and length; Open PDF; tap a bar and it is selected, with its number | "It finds every bar and names it. Muse Spark reads the labels, geometry does the measuring." | iPad A | Goldberg | Same shots on the copy imported beforehand |
| 5 | 0:42 | 0:13 | Convert to Digital, then Open Digital: the scan beside the engraved pages | "Convert to Digital turns the scan into notation you can play." | iPad A | Goldberg, converted beforehand | Show only the result (Convert of 5 pages took 114.7 s in testing; never run it live) |
| 6 | 0:55 | 0:13 | Split by instrument; the rope turns yellow; the question with the numbered staves and "Why am I asked?" | "When it can't tell, it stops and asks, in a musician's words." | iPad A | Concerto | A split started before recording and left parked: the question waits until answered |
| 7 | 1:08 | 0:14 | The admin taps the staves; "Resuming"; later pages go through without a question; the part strip on the Stand | "It remembers the answer for the rest of the book." | iPad A | Concerto | Cut to the finished part strip if the resume is slow |
| 8 | 1:22 | 0:15 | Op. 18/1 on both stands, presence faces; the admin draws a cut and it lands on the Violin II stand | "A cut made on one stand reaches every stand." | **[2 iPads]** A and B | Op. 18/1 | Retake; if Realtime misbehaves, the Mac browser signed in as Noor as the second stand |
| 9 | 1:37 | 0:10 | The admin holds the voice button: strands gather into one string while speaking | "Second violins, from forty-two to forty-eight we're cutting that." | **[mic]** iPad A | Op. 18/1 | Retake in a quieter room; then the proposal from a take recorded before the shoot (proposals wait in the tray until accepted) |
| 10 | 1:47 | 0:10 | The proposal card and the blue ghost over bars 42 to 48 for Violin II; Accept | "Muse Voice Transcribe writes it down, Spark proposes the mark, the admin confirms." | **[mic]** iPad A | Op. 18/1 | As shot 9 |
| 11 | 1:57 | 0:10 | The cut on the Violin II stand; the cello stand unchanged | "It lands only on the stands it was meant for." | **[2 iPads]** B, then A as cello or a third device | Op. 18/1 | Show the Violin II stand alone, then the cello part opened on iPad A |
| 12 | 2:07 | 0:25 | Play the parts from the Stand's "…" menu: Violin II left out, pace 80 %, one bar counted in, a loop over a passage | "Then practise: leave your part out, slow it down, loop it." | iPad B, sound on | Op. 18/1 | Record on the web app in a Mac browser; the iPad shell's sound fix is verified on the simulator only |
| 13 | 2:32 | 0:16 | The book sheet of the concerto: its parts and state; then a card naming the three Meta models and what each did | "Spark reads and asks, Voice Transcribe listens. SAM 3.1 was tried first and geometry won the tap test." | iPad A, then title card | Concerto | Title card alone |
| 14 | 2:48 | 0:12 | End card: Folio, folio.jckjjcckk.com, TestFlight, the repo | "Folio. One score for the whole ensemble." | Title card | None | None needed |

Total: 3:00.

## Props and setup checklist

- [ ] Accounts: Ada (admin, Viola), Lin (Violin I), Noor (Violin II), Inès (Cello) in Hart House, and the pianist's
      personal account. CK signs every device in; budgets reset and the demo group seeded on the hosted project.
- [ ] Books imported beforehand: Op. 18/1 MusicXML imported fresh into Hart House, so it has its landmarks and
      playback files (books imported before 2026-10-30 have no landmarks), all four parts assigned; the Goldberg
      copy imported and converted to Digital; the concerto split started and left parked on its question (shot 6
      fallback); one successful voice take left as a proposal (shot 9 fallback).
- [ ] The concerto book that asks confirmed in the Nov 2 rehearsal run.
- [ ] A clean 5-page Goldberg PDF in Files on iPad A for shot 3.
- [ ] yoga's stable API on main, checked with a test import before the shoot.
- [ ] Mac awake, on power, on the same network.
- [ ] Both iPads on the current build from main, charged, Do Not Disturb on, volume up, same network.
- [ ] Quiet room for shots 9 and 10; the real-iPad mic tested once before the shoot.
- [ ] Printed Op. 18/1 parts and four stands for shot 1.
- [ ] Screen recording on each iPad; a full run-through recorded on Nov 2 as the safety cut.
