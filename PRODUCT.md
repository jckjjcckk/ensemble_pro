# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

Vite + React 19 + TypeScript, Tailwind v4, OpenSheetMusicDisplay for score rendering, supabase-js for auth, storage and realtime. Served as a PWA opened in Safari on iPad and in a browser window on Mac. A FastAPI backend (Python, music21, Meta Model API) does the heavy work; the UI never calls models directly.

## Users

Four roles share one product. The roles are confirmed for the design phase; some may be hidden or removed before the hackathon submission on Nov 4, 2026, so the shell must not depend on all four existing.

- **Section player or singer.** Holds an iPad on a stand in rehearsal, sees their own part, receives the leader's cuts and markings live, and practises the same part at home.
- **Conductor or leader.** Sees the full score, marks cuts, dynamics, bowings and spoken notes that fan out to every member's part.
- **Solo pianist.** Photographs or imports a score and practises at a digital piano (a Casio PX-S1100 connected over MIDI through the Mac). Piano concertos are the first target: the pianist plays the solo line, the app plays the orchestra.
- **Ensemble librarian or manager.** Scans or uploads scores, reorders and cleans pages, triggers processing, assigns parts to members, and keeps the library tidy.

## Product Purpose

Turn any score, photographed or imported, into clean split parts on every member's device, keep the group's markings and notes in sync live, and let the same score become a practice tool with loop, tempo, metronome, other-parts playback and listening to the player's own instrument. Success is a rehearsal where nobody holds paper and a change the leader makes reaches every stand in a second, and a practice session where the pianist never leaves the score to configure anything.

## Positioning

One score object serves the whole life of the music: scan, split, distribute, mark, rehearse, practise. Competing products stop at one step (scanning, or reading, or practising). The scan and cleanup use Meta's SAM 3.1 for page and system segmentation and Muse Spark for reading handwritten markings and writing rehearsal briefs; Muse Voice Transcribe turns spoken rehearsal notes into bar-anchored text.

## Operating Context

- **Rehearsal hall or stage.** iPad on a music stand, arm's length, often dim or under stage light, hands busy with an instrument. Landscape shows two facing pages; portrait shows one.
- **Practice room.** iPad on a piano music rest in landscape, or on a stand. The Casio sends MIDI; the app follows position and listens for notes.
- **Desk.** The librarian or conductor on a Mac, landscape only, window sometimes half-width. Scanning, reordering pages, assigning parts, reviewing processing results.
- **Document mode** is the score plus everything the group has said about it: markings, cuts, voice notes, who is on which bar.
- **Practice mode** is the same score as an instrument-facing tool: bar-range loop, tempo, metronome, other-parts playback, and listening to the player's instrument.

## Capabilities and Constraints

Confirmed for the design phase:

- Library of scores with processing states (uploaded, ordering pages, processing, ready, failed) and split parts per score.
- Scan intake: photos or PDF pages, reorder, delete, retake, then process as one ordered set.
- Document mode with part switching, annotations (pencil marking, cut, voice note, text), live presence of other members.
- Practice mode with loop, tempo, metronome, other-parts playback, and instrument listening (position following, wrong-note flags, run scoring).
- Two-page landscape and one-page portrait on iPad; landscape-only on Mac, adapting to a half-width window.
- Apple Pencil input through pointer events; large touch targets usable while holding an instrument.

Constraints and undecided facts:

- MIDI and instrument listening are their own workstream; this phase builds only the UI foundation for them and does not depend on real MIDI data.
- Whether a given PDF can be recognised digitally is not guaranteed; the UI must show processing failure and partial results honestly.
- The product name is undecided. Designs use a neutral placeholder wordmark that is easy to swap.
- Terminology: *score* (the full work), *part* (one instrument or voice extracted from it), *marking* (any annotation), *cut* (a skipped bar range), *member* (a person in an ensemble), *session* (one practice run).

## Brand Commitments

Binding tone from the owner: premium, quiet and professional. Not playful, not "creative" for its own sake, and not a raw admin panel. It should feel like a serious instrument-grade tool that a professional orchestra and a conservatory student would both trust.

## Evidence on Hand

- Public-domain MusicXML fixtures exported from the music21 corpus in `web/public/fixtures/` (a Bach SATB chorale, a Beethoven string quartet movement, a solo piano piece). These render in OpenSheetMusicDisplay and are the real content every screen shows.
- Shared mock data in `web/src/explorations/shared/` for ensembles, members, scores, parts, annotations and practice sessions.
- No testimonials, customers, logos, press or benchmarks exist. Do not invent any.

## Product Principles

1. The music is the interface. Controls recede; the score is never crowded by chrome.
2. Readable at arm's length under bad light, operable with one hand or a pencil.
3. Everything the group knows about a score travels with the score.
4. Honest about machine output: processing states, confidence and failures are visible, never hidden behind a spinner.
5. One shell serves four roles; a role switch changes what is shown, not where things are.

## Accessibility & Inclusion

Text and controls must be legible at roughly 60 cm on a stand in dim light: generous type sizes, contrast above WCAG AA, and touch targets of at least 44 pt. Keyboard operation on Mac. Motion is minimal and respects reduced-motion settings; nothing animates while a musician is reading.
