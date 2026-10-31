# Folio

An AI librarian for ensembles, on iPads. Scan or import a score and the librarian reads it: it finds every
system and bar, names the parts, cuts a part out for each player, and can convert a scanned book into digital
notation. Marks made on one stand appear on every stand live. A conductor's spoken note ("second violins, from
forty-two to forty-eight we're cutting that") becomes a proposed mark on the right stands, and the parts play back
at any pace for practice.

Built for the Meta Global AI Developer Hackathon (Oct 27 to Nov 4, 2026). The eight commits dated 2026-10-26
are setup only (repo layout, scaffold, install script, design-exploration scaffold and mock data); everything
else is hackathon work.

- Product site: https://folio.jckjjcckk.com
- Web app: https://folio-app.jckjjcckk.com (accounts are created by hand; there is no sign-up)
- iPad app: TestFlight, build 1 approved
- Support: folio@jckjjcckk.com

## Who it is for

- **A chamber group or small ensemble.** The admin (in the demo, the quartet's violist) imports the score, splits
  parts, makes cuts and speaks instructions; each player reads their own part on an iPad and receives the
  group's marks.
- **A solo player with a personal library.** A pianist imports a scanned book, converts it to digital, and
  practises with the other parts playing.

Roles live on the membership: an account can be admin of one group and a player in another.

## Meta models, and exactly where each is used

All model calls go through the API (`api/`); the iPad never calls a model. Every call is charged to a spend ledger
with a per-user and a global cap (feature 007).

| Model | Where | Effort |
|---|---|---|
| **Muse Spark 1.3** (`muse-spark-1.3`) | Page reading on import (004): labels what the geometry found (first bar number, parts per system, rehearsal marks, title, composer, difficulty, brief) | minimal, falls back to low on a doubted page |
| | Score header (instruments, staves per system), key and meter (closed question), page kinds, front-matter form (003, 004, 005) | low |
| | Part cut agent (008): reads the margin labels per system, then a closed recheck of each cut block | labels minimal (fallback low); recheck and agent turns low |
| | Convert to Digital (005): text, dynamics and tempo words per system, written only where an Audiveris glyph or a fixed vocabulary confirms them; a closed render check against MuseScore's engraving | minimal |
| | Voice instructions (013): one call per take turns the transcript into marks (kind, bars, audience, stand text, confidence) | minimal |
| **Muse Voice Transcribe 1.0** (`muse-voice-transcribe-1.0`) | Voice notes (013): the take, in DIARIZATION mode, with keywords from the book (part names, members' first names, a short music glossary) | n/a |
| **SAM 3.1** (`sam-3.1`) | Evaluated in the first experiment (003, item 0): SAM system boxes plus Spark per system against OpenCV geometry on a tap test. SAM found systems but never barlines and failed the test (10/28); geometry plus Spark labels passed (28/28). SAM is not in the shipping pipeline. | n/a |

Spark never places staves or bars and never judges or re-transcribes notes: geometry measures, Spark reads text
and answers closed questions, and checks the model cannot skip decide what is written.

## Architecture

```
iPad (React PWA inside a Capacitor shell; also the web app in Safari)
  |  sign-in, reads and writes rows under RLS, uploads to Storage, hears changes over Realtime
  v
Supabase: Auth, Postgres (RLS on every table), Storage, Realtime
  ^
  |  service key; claims durable jobs from the jobs table
FastAPI (api/): verifies the user's token, enforces budgets, runs the librarian's handlers
  |-- Meta Model API: Muse Spark 1.3, Muse Voice Transcribe 1.0
  |-- OpenCV page geometry, music21 (part split, MIDI, landmarks)
  '-- OMR box over ssh: Audiveris 5.11 (recognition), MuseScore 4.7.5 headless (engraving, render check)
Cloudflare: the web app as a Worker with static assets; the API behind a Cloudflare Tunnel
```

The iPad calls the API only to start work. Results arrive as row changes. The database is the truth and Realtime
is the notification: clients refetch on reconnect. Three data layers: source (PDF, images, MusicXML),
interpretation (bars, staves, parts, versioned), collaboration (marks, cuts, scribbles, presence). Marks point at
stable measure ids, so re-reading a page keeps everyone's marks.

## Run it locally

Requirements: Node, npm, uv, git, Docker and the Supabase CLI. Convert to Digital and engraving also need an OMR
box with Audiveris and MuseScore reachable over ssh.

```bash
supabase start                          # local Supabase in Docker; applies supabase/migrations
cp api/.env.example api/.env            # fill in (names below)
cp web/.env.example web/.env
./install.sh                            # checks tools and env, installs deps, starts web :5173 and api :8000
cd api && uv run scripts/smoke_local.py # once: creates the five demo accounts locally and checks RLS
```

Or run the two servers by hand:

```bash
cd web && npm run dev                                   # LAN-exposed on :5173
cd api && uv run uvicorn app.main:app --reload --port 8000
```

`./install.sh --check` only checks; `--stop` stops both servers.

Environment, by name only:

- `api/.env` (server secrets, never shipped): `SUPABASE_URL`, `SUPABASE_SECRET_KEY`, `LLM_PROVIDER` (`meta` or
  `anthropic`), `META_API_KEY`, `META_API_BASE_URL`, `ANTHROPIC_API_KEY` (experiments only), `PER_USER_BUDGET_USD`,
  `CORS_ORIGINS`; optional `META_MODEL`, `ANTHROPIC_MODEL`, `WORKER` (0 turns the job loop off),
  `OMR_HOST`, `OMR_ROOT`, `OMR_PARALLEL_PAGES`.
- `web/.env` (public values only): `VITE_SUPABASE_URL`, `VITE_SUPABASE_PUBLISHABLE_KEY`, `VITE_API_URL`. The same
  three names in `web/.env.local` point the dev server at the local stack; hosted and iPad builds never read it.

Tests: `cd api && uv run pytest` (offline; the model is faked at the transport) and `cd web && npm test`.
iPad build: `docs/ios.md`. Hosting: `deploy/README.md`.

## Repo layout

- `web/`: Vite + React + TypeScript app, Tailwind v4, OpenSheetMusicDisplay, Tone.js, supabase-js; `web/ios/` is the
  Capacitor shell.
- `api/`: FastAPI on Python 3.12 via uv. `app/agent/` the agent loop, `app/librarian/` the handlers (page reading,
  part cut, convert, engrave, voice, playback), `experiments/` every measured experiment with its spend ledger,
  `tests/`.
- `supabase/`: migrations (schema, RLS policies, RPCs).
- `docs/`: `features/` one file per feature with its status, numbers and decisions (index in
  `docs/features/README.md`); `agent-loop.md`, `librarian-contract.md`, `acceptance/`, `design/`,
  `submission.md`, `demo-shot-list.md`.
- `deploy/`: Cloudflare and service config.
- `PRODUCT.md`, `DESIGN.md`: product and visual rules.

## Measured results

Each number is from the feature doc named, with its sample size and date. Most are single runs on a few pages.

| What | Result | n, date | Source |
|---|---|---|---|
| Who places bars: tap every bar on a page | OpenCV geometry + Spark labels 28/28 and 13/13; Spark alone at high effort 9/28; SAM 3.1 + Spark 10/28 | 2 pages, n=1, 2026-10-27 | 003 |
| Page reading on import, effort minimal with a guard | 5-page import 35.3 s to 23.4 s; labels 42/42 across a 13-page corpus, $0.0127 a page | import n=1 before, n=2 after; corpus one run; 2026-10-30 | 004 |
| Part cut, Rachmaninoff Concerto 1, pages 1 to 5 | 9/9 decisions right, 0 questions; 93.8 s to 39.5 s after the speed pass | 4 runs 2026-10-28; speed pass 2026-10-30 | 008 |
| Label memory (Beethoven Concerto 3, piano part) | questions on two pages to 0; 7/7 systems cut | n=1 each, 2026-10-30 | 008, 006 |
| Convert to Digital, Goldberg BGA pages 1 to 5 | text F1 0.963, notes kept by MuseScore 1731/1731 (v2 run); 187.8 s to 114.7 s, $0.22 | n=1, 2026-10-28 and 2026-10-30 | 005 |
| Audiveris pitch accuracy, Goldberg Aria bars 1 to 28 | pitch F1 0.972 against the Open Goldberg ground truth | n=1, 2026-10-27 | 005 |
| Voice: CK's recorded lines | all fields right on 21/26, retakes 7/9, no mark on 23/23 non-instructions; Spark median 1.08 s, $0.0035 a line | one voice, n=1, 2026-10-30 | 013 |
| Voice: 100 messy typed instructions | 99/100 with score context (prompt v4e), 74/100 without; 0/6 false positives | n=2, 2026-10-30 | 013-v4e-eval |
| Live marks to four stands | p50 0.47 s, 0 of 20 cuts lost, missed cut recovered after a reconnect | local stack, 2026-10-28 | 012 |

## Limits, plainly

- **Scanned books.** Bar numbering and part cutting work on the tested pages; recognising the notes does not
  always. Audiveris drops notes on dense piano and orchestral pages; the librarian flags doubtful bars but does not
  fix notes. Convert to Digital is scoped to piano and chamber music, and no chamber-music PDF has been tested.
- **One voice.** The voice prompt was tuned and scored on one speaker's recordings (CK's). A second voice is the
  overfitting check and has not been recorded. A transcript sometimes drops a leading addressee ("Cello, ..."), and
  the mark then goes to the whole group. Every voice proposal waits for the admin's tap; nothing is applied
  automatically.
- **iPad only.** The native app is iPad only; the web app runs in Safari and on a Mac browser. The iPad microphone
  path has not been measured.
- **Small samples.** Most numbers above are single runs on 1 to 13 pages. Realtime latency was measured on the local
  stack, not the hosted project.
- **Not built:** always-on listening (researched in 013-always-on), MIDI listening to the player's instrument,
  piano reduction, notation editing.

## Licence and credits

No licence file has been added to this repository yet.

Folio runs alongside these tools, each under its own licence:

- [Audiveris](https://github.com/Audiveris/audiveris) (AGPL-3.0), optical music recognition, run on the OMR box.
- [MuseScore Studio](https://musescore.org) (GPL-3.0), headless engraving and the render check, run on the OMR box.
- [music21](https://web.mit.edu/music21/), [OpenSheetMusicDisplay](https://opensheetmusicdisplay.org),
  [Tone.js](https://tonejs.github.io) with samples from nbrosowsky/tonejs-instruments (MIT),
  [OpenCV](https://opencv.org), [PyMuPDF](https://pymupdf.readthedocs.io) (AGPL-3.0), [Supabase](https://supabase.com),
  [Capacitor](https://capacitorjs.com).

Test material is public domain or openly licensed: the MusicXML fixtures in `web/public/fixtures/` come from the
music21 corpus; the OMR ground truth is Open Goldberg (CC0); the scanned scores are public-domain editions from
[IMSLP](https://imslp.org), kept out of the repo.

Built by CK Jiang with Claude Code.
