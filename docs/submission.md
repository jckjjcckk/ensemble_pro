# Folio: submission write-up

Folio is an AI librarian for ensembles on iPads. Meta Global AI Developer Hackathon, Oct 27 to Nov 4, 2026;
entered for the main track and Best Agentic.

## The problem

A chamber group rehearses from paper. The parts disagree with the score, the cut is on three stands and not
the fourth, the agreed bowing is in someone's bag. A public-domain scan is easy to find,
but it is a picture: no bar numbers a machine can use, no parts, nowhere to keep what the group decided.

## Who we built it for

CK Jiang has played classical piano for ten years and built Folio for the rehearsal he wants: nobody holds
paper, and the leader's change reaches every stand. A cellist's feedback set two rules. A player's own marks
and the ensemble's stay separate: a fingering never appears on another stand, the leader's cut appears on all.
And repeats, bar numbering and handwriting are what AI gets wrong, so fixing a machine's mark must be as cheap
as making one. The same cellist asked to slow a passage, loop it and hear the other parts: "play the parts".

## What it does, in the demo's order

1. **Import.** A scanned PDF reads itself: OpenCV finds every staff, system and barline; Muse Spark labels
   what geometry found (first bar, parts per system, rehearsal marks, title, composer, key, meter).
2. **The librarian asks.** Splitting out a part, the agent meets a staff it cannot place, parks, and asks one
   typed question in musicians' words ("Which staves are the Piano's on page 2, line 2?"). The admin taps the
   staves; the run resumes where it stopped.
3. **Parts on every stand.** Each player opens their part, cut from the same pages: bar 112 is bar 112 for all.
4. **Convert to Digital.** Audiveris recognises the notes, Spark adds text only where a glyph confirms it,
   MuseScore engraves the result for the iPad's page.
5. **Marks, live.** A highlight or a cut made on one stand lands on every stand.
6. **The conductor speaks.** The admin holds the voice button: "Second violins, from forty-two to forty-eight
   we're cutting that." Muse Voice Transcribe writes it down, Spark proposes a cut on bars 42 to 48 for
   Violin II, a card and a blue ghost appear; the admin taps Accept and the cut is on the Violin II stand.
7. **Play the parts.** Choose the parts that sound, leave yours out, set the pace, loop.

## The agentic story

**A loop that carries the guarantees.** The librarian runs Spark as an agent (feature 006): one tool call per
turn, every result through a commit tool whose checks the model cannot skip (staff counts, label agreement,
geometry). Geometry measures; Spark reads labels and answers closed questions; Spark never places a bar or
judges a note. Asked to place every bar on a page, Spark alone got 9/28; geometry plus Spark labels got 28/28.

**Park and resume.** After three refused commits on one tool the run parks with a typed question (011),
keeping its history. The answer returns to the same reasoning as the next message: nothing is re-read or
re-charged.

**The agentic memory rule.** Cutting the piano out of a Beethoven concerto asked "which staves are the piano?"
page after page. The rule now: a handler never asks again what the book already settled. What the agent learns
("Klav." is the Piano) is kept on the book with its provenance (human or model, page, job), consulted before
asking, passed to the model for later pages, and a human answer outranks any model read. On that concerto:
questions on two pages became none, 7 of 7 systems cut (n=1, 2026-10-30).

**A confidence gate on voice, measured before it is trusted.** A proposal is refused unless its quote is
verbatim, its bars in range and its audience a known part. Spark also returns a confidence: on recorded takes
the 11 proposals at 0.95 or above were all right, on clean text 73 of 73 (2026-10-30). Push-to-talk still
waits for the admin's tap on every proposal; the gate is held for always-on listening.

**A speed pass with outputs held fixed** (2026-10-30). Effort minimal where it matched low, with a fallback to
low on a doubtful page; the part cut reads ahead and skips rechecks the memory settled; Audiveris runs page by
page in parallel. Five-page import 35.3 s to 23.4 s; part cut 93.8 s to 39.5 s with the same 9 decisions;
Convert 187.8 s to 114.7 s; voice call median 1.83 s to 1.08 s with the same marks.

## Each Meta model's role

- **Muse Spark 1.3**: page labels, score header, key and meter, part-cut labels and rechecks, Convert's text
  and render check, voice instructions. In the 2026-10-28 grid (n=1 per cell), Spark at effort low
  labelled every system's parts right at $0.0103 a page.
- **Muse Voice Transcribe 1.0**: voice notes, DIARIZATION mode, the book's part names and a music glossary as
  keywords. Word error rate 0.177 on CK's lines (2026-10-29); the glossary turned "fermenta" into "fermata".
- **SAM 3.1**: tried first for page layout. It found systems but never a barline; SAM boxes plus Spark scored
  10/28 on the tap test (2026-10-27), so geometry took the job. SAM is not in the shipping pipeline.

## What we measured

From `docs/features/*`. Small samples: most rows are one run.

| What | Result | n, date |
|---|---|---|
| Place every bar (tap test) | geometry + Spark 28/28 and 13/13; Spark alone 9/28 | 2 pages, n=1, 2026-10-27 |
| Part cut, Rachmaninoff Concerto 1 p1-5 | 9/9 right, 0 questions | 4 runs, 2026-10-28 |
| Convert, Goldberg p1-5 | text F1 0.963, $0.220, 114.7 s | n=1, 2026-10-30 |
| Audiveris notes, Goldberg Aria b1-28 | pitch F1 0.972 | n=1, 2026-10-27 |
| Voice, CK's recorded lines | 21/26 all fields right, 7/9 retakes, 23/23 non-instructions silent | one voice, n=1, 2026-10-30 |
| Voice, 100 messy typed lines | 99/100 with score context, 74/100 without | n=2, 2026-10-30 |
| Live marks, four stands | p50 0.47 s, 0 of 20 cuts lost | local stack, 2026-10-28 |
| Meta spend, all experiments | $21.80 | to 2026-10-30 |

Not yet measured: the iPad microphone, a second speaker, a chamber-music PDF through Convert, hosted Realtime.

## What's next

- **Always-on voice.** Researched, not built: the iPad streams audio through the API to Meta's realtime
  recogniser, one Spark call per spoken turn; estimated about 2.1 s median from end of speech to card (two
  stages assumed), against about 4.2 s today.
- **The IMSLP dataset run.** Dozens of public-domain PDFs to test import, part cut, Convert and metadata.
- **Metadata normalisation.** Canonical composer, work, catalogue number and movement from the header read, as
  an editable suggestion; web-search grounding only when no catalogue number is printed.
- **MIDI listening.** Follow the player's own instrument over MIDI while the other parts play.

## Team and links

- CK Jiang: product, design direction, musical judgement; built with Claude Code.
- Repo: https://github.com/jckjjcckk/folio-pad
- Product site: https://folio.jckjjcckk.com
- Web app: https://folio-app.jckjjcckk.com
- iPad: TestFlight, build 1 approved
- Support: folio@jckjjcckk.com
