# 000 Foundations: product, architecture, decisions

Status: shipped (decisions) | Meta models: all three are named per feature; this file names none itself.

Not a feature. The context every feature file assumes: what Folio is, the architecture, the Meta API facts,
the product decisions CK made on 2026-10-26 and 2026-10-27, the design exploration record, the fixtures, and
the working agreement. Read once; feature files link here by number.

## What Folio is

An AI librarian and practice tool for musicians, built for the Meta Global AI Developer Hackathon
(Oct 27 to Nov 4, 2026). Public repo: https://github.com/jckjjcckk/folio-pad. Local folder `~/Documents/muse`.
Product name **Folio** (decided 2026-10-26). "Muse" stays as the folder name only. Tagline direction:
"One score for the whole ensemble." No "Pro" suffix (reads as a pricing tier). GitHub repo stays
`ensemble_pro` unless renamed before the submission form (CK's to-do). Domain is a post-hackathon concern.

One score object serves the whole life of the music: scan or import, split into parts, distribute to every
member's iPad, keep markings and cuts in sync live, and practise from the same score with loop, tempo,
metronome, other-parts playback and listening to the player's instrument over MIDI.

Two modes: **document mode** (score plus everything the group said about it) and **practice mode** (score as
an instrument-facing tool). Product truth in the Impeccable format: `PRODUCT.md`. Visual truth: `DESIGN.md`.

### Hackathon facts that shape decisions

- Must use Meta models via the Meta Model API: SAM 3.1, Muse Spark, Muse Voice Transcribe (Muse Image, Muse
  Wonder optional). Stage one is pass or fail on this.
- Rubric: Impact 30, Use of Meta AI tooling 25, Technical depth 20, Demo 25. Three-minute demo video. Public
  repo, new work only. Submission due 2026-11-04, 9 PM ET.
- Banned categories included the original ZephyrFit idea (sports coaches), hence this pivot.
- Bonus prizes: Best Agentic ($5K), Best Creative with Muse Image or Wonder ($5K), Best Open-Weight ($10K).
- The participant guide is `docs_offline/hackathon-guide.md`. No grace period for setup: the Oct 26 commits
  are setup-only and the README and video must say so.

## Roles, accounts, library (decided 2026-10-26)

- Two roles per ensemble: **admin** and **player**. No separate conductor, leader or librarian personas.
  Admin creates the room, adds members, assigns parts, decides whose notes go to whom, sees every version;
  later also assigns credit. Player sees their part and their own notes, admin notes addressed to them.
- Role lives on the **membership**, not the account. An account can be admin of one ensemble and player in
  another.
- Every account has a **personal library** (GoodNotes model). Joining an ensemble is like joining a shared
  notebook. The solo pianist persona is just a personal account. The four personas of the design phase
  (player, leader, pianist, librarian) are use cases, not roles.
- Demo accounts: 1 admin (leader, plays viola in the Op. 18/1 quartet) + 4 personal accounts: pianist (solo,
  library only), violin I, violin II, cello.
- The role switcher in the explorations is mock-only; the product has a context switcher: My library / each
  ensemble.
- Library: context first, then a grid of score covers grouped in folders named by the admin or user. Cover
  shows title and one status badge. Tap a cover opens an information box (state, your part, who holds what,
  difficulty, pages unreadable) with "Open score". No list rows.
- Sync model: no offline/live transport split. Supabase Realtime always on. Admin starts and ends a
  **rehearsal session**; only during a session do live pushes (cuts, page jumps) interrupt players. Outside a
  session changes sync quietly.
- Recognition confidence: expose page and bar flags only (a quiet pencil-style margin mark; tap offers
  "re-read this bar" or "open the original photo"). The information box shows counts only ("2 pages
  unreadable, 5 bars doubtful"). No percentages, no per-note heat. Difficulty is one word per part.

### iPad first (binding for every coding agent)

Design for touch on iPad in Safari before anything else; Mac is secondary. Rules (in PRODUCT.md and
DESIGN.md): 44 pt minimum targets, no hover-only state, no right-click, no keyboard-only path (no ⌘K as
primary), swipe is primary for page turns, chrome shows/hides on tap with a visible handle, long-press on a
bar to annotate, every screen tested on the iPad before done. `docs/acceptance/touch.md` is run by CK.

## Architecture (decided)

```
iPad / Mac browser  --(React PWA)-->  Supabase  <--(service key)--  FastAPI on the Mac / Railway
        |                              auth, Postgres, Storage,          Meta API (SAM, Spark, Voice)
        |                              Realtime                          Anthropic API (experiments)
        +-------- POST /process, /annotate ... --------------------->   music21, OMR (Audiveris, homr)
```

- Supabase owns sign-in, database, file storage and realtime fan-out. Shared state and the pipe.
- FastAPI is a worker that holds all secrets, verifies the user's Supabase token, enforces the whitelist and
  budget, calls models and music tools, writes results back. Every model call goes through it.
- React web app (not Flutter, not React Native, not Capacitor for now) opened in Safari on iPad and
  installed as a PWA from the deployed HTTPS URL. On Mac, a browser window.
- The iPad calls FastAPI only to start a job. Uploads go straight to Storage, results arrive as row changes.

Why (so nobody relitigates): React web over Flutter is CK's preference, AI models write it best, and the
music rendering libraries (OpenSheetMusicDisplay, Verovio) are browser libraries anyway; React Native would
run them in a WebView regardless. PWA now, Capacitor later only if an App Store link matters (feature 015).
FastAPI over Django: Supabase already does auth, ORM and admin; the backend is ~10 async endpoints doing
heavy things (Django Ninja on Supabase Postgres is the acceptable variant). Hosted Supabase over self-hosted:
free tier, RLS on every table, nothing to run. Hosting: develop and demo on the Mac (Casio plugs in there,
iPads on the same wifi); web to Cloudflare Pages, FastAPI to Railway or CK's server behind a Cloudflare
Tunnel (Workers cannot run FastAPI: PyTorch, music21). Meta's API is drop-in compatible with the Anthropic
SDK (same client, different base URL), so experimenting with Claude first and switching to Spark costs
nothing; SAM 3.1 and Voice Transcribe have no Claude equivalent and go through Meta from day one.

Three data layers (external review, 2026-10-26): **source** (PDF, images, MusicXML), **interpretation**
(recognised measures, staves, parts, confidence flags, versioned), **collaboration** (annotations, cuts,
members, sessions). Annotations reference a stable measure id, never an interpretation row, so reprocessing
page 4 keeps everyone's markings; unmatched measures are flagged, never silently dropped. OMR is never a
prerequisite: Path A (MusicXML) gives full functionality at once; Path B (PDF or photo) keeps the original
pages as what people read, with geometry and Spark adding structure. Durable jobs in the database; Realtime
is notification, the database is truth (clients keep an `updated_at` cursor and refetch on reconnect).

## Meta API facts

Verified 2026-10-26:

- Base URL `https://api.meta.ai/v1`. Responses, Chat Completions and Messages formats all accepted. Bearer key.
- `muse-spark-1.3`: text, image, video, audio, PDF in; text out; 1M context. Up to 50 images per request,
  50 MB each. Returns coordinates on a normalised 0 to 1000 grid when asked. Default `reasoning.effort` is
  `high` and burned 232 to 442 output tokens to say "ok": set `minimal` or `low` for cheap calls.
- Prices per 1M tokens: Spark standard $1.25 in / $4.25 out; contributor mode (Meta trains on data) $0.10 /
  $0.20. SAM 3.1 $0.0025 per image, $0.20 per 1,000 video frames. Voice Transcribe $0.18 per audio hour.
- SAM 3.1 via `POST /v1/responses`, model `sam-3.1`, `input_text` noun phrase + `input_image` (URL or base64
  data URL). Box and point prompts as tokens in the text. Output is a token grammar with per-object box and
  mask; parse with Meta's `meta-sam-parser`. `metadata.include_confidence: "true"` adds scores. Video up to
  15,000 frames, 16 objects.
- Voice Transcribe: diarisation, no word timestamps.
- Docs: https://dev.meta.ai/docs/overview, /docs/models, /docs/sam/segmenting, /docs/image-understanding,
  /docs/pricing-rate-limits.

Survey 2026-10-27 (subagent, dev.meta.ai/docs): models muse-spark-1.3/1.2/1.1 ($1.25/$4.25, cached $0.15;
contributor $0.10/$0.20, 150 RPM), muse-wonder-1.0 (preview, $4/$20), muse-image-1.0 (generation and editing,
$0.01/image, no mask inpainting), muse-voice-transcribe-1.0 ($0.18/h), sam-3.1 ($2.50/1k images), web search
grounding ($2.50/1k). No TTS, no music or audio generation, no video generation, no embeddings, no batch
endpoint, no server-side code execution. **Spark 1.3 audio is "not fully supported": use 1.2 for audio
prompts.** Voice Transcribe file endpoint: 16-bit mono WAV at 16/24 kHz, at most 10 min and 32 MB,
turn-level timestamps only, `keywords` biasing, diarisation. Prompt caching automatic on the prefix (~88 %
off), optional `prompt_cache_key` / `prompt_cache_retention: "24h"`. `tool_choice`: auto everywhere,
`any`/`none` on Messages, no named tool. Structured output constrained to schema (no recursion, 10 levels).
Reasoning cannot be turned off. Credits reportedly $150 per participant. Spark Open / Glimmer are weights
only, not on the API. Meta-only demo moments, ranked: SAM 3.1 text-prompt masks; SAM video tracking; video
plus soundtrack into Spark in one call; grounded points and counts from Spark; one key for Spark, SAM, Voice.

Through the Anthropic SDK (`api/app/llm.py`): the Meta base URL loses its `/v1` for the SDK;
`output_config.effort` works on Meta and cuts Spark's reasoning tokens about 4x; Spark needs `max_tokens`
at least 1024 or it answers nothing; loop turns need 2048 or more (feature 006). Messages-style `tools=[...]`
works on Meta (verified 2026-10-27). Both providers answered a probe on 2026-10-27 (Opus 5.5 $0.00015, Spark
$0.0003 to 0.001).

## Working agreement (decided 2026-10-26)

CK owns the validation pass: writes acceptance standards, tests on real devices, makes musical and product
judgments. Claude does the coding. One acceptance file per module in `docs/acceptance/`, written by CK or
drafted by Claude and edited by CK: what done means as pass/fail lines, which fixture, what to open, what to
expect. Claude builds to it; CK runs `./install.sh`, tests on iPad, marks pass/fail; Claude fixes.

Starting thresholds Claude proposed, CK to adjust: OMR on the Goldberg Aria at least 95 % note accuracy
against the CC0 ground truth; a cut propagating to a second iPad in under 1 s; a ten-page scan processed in
under 3 min.

Only CK can: accounts and secrets; musical judgment (OMR "good enough", reduction playability, brief
quality, difficulty ratings); physical testing (stand, pencil, Casio, bad photos); product calls (roles to
cut, name, demo scene, when to stop). CK is product direction and judge: put musical judgement to CK
plainly, never hand them repetitive work.

## Design exploration record (built and judged 2026-10-26)

Five Opus agents each built one direction (about 250 to 325k tokens, 25 to 30 min each) from
`docs/design/explorations/README.md`, on shared mock data and an OSMD wrapper. All five type-checked and
built. Each wrote its contract in `docs/design/explorations/N.md`.

| # | Direction | Scene | What stood out |
|---|---|---|---|
| 1 | Reading room | Light, paper, no persistent chrome, serif + grotesk | Notes in a true outer margin level with their bar; edge bars on tap, hide after 4.5 s |
| 2 | Pit | Dark only, amber state, blue = someone else | One bar ruler shared by document and practice modes |
| 3 | Console | Mac-first, 3 panes + ⌘K, Inter | Track lane as table of contents; densest |
| 4 | Bound | Ecru/graphite/oxblood, EB Garamond + Schibsted Grotesk | Part tabs on the page edge; facing spreads; OSMD rendered off-screen and copied into page frames (`engraving.tsx`) |
| 5 | Instrument | Graphite dock, Archivo + Martian Mono, practice-first | Loop bracket on a ruler mirrored in the score; "following"/"lost" is the whole listening UI; tempo is the biggest number |

Shared technique all five converged on: read OSMD's `GraphicSheet.MeasureList` after every render, store
each bar's box, draw cuts, loops, pins, presence and cursors as positioned overlays. Nobody edits OSMD's DOM.

Verdict (CK, 2026-10-26; CK's written numbering swapped 3 and 4, folder numbers used here): **/5 Instrument
is the base.** /4 Bound: steal the serif typography and ecru palette as a second token set and the
facing-pages view as a display setting; not a second layout. /1: liked the fonts, difficulty notation and
layout; too much text; steal the margin-note placement. /2: same text problem; drop the timeline. /3:
rejected ("Cloudflare dashboard"); only the idea of processing truth, reduced to one badge. Themes are
design tokens only. One layout, never two. 1 to 3 archived in `docs_offline/explorations-archive/`; contact
sheets for 4 and 5 in `docs/design/explorations/sheets/`, full shots in `shots/` (gitignored, decided
2026-10-27). Fixes after the agents finished: `3/screens/Document.tsx` infinite update loop (palette commands
depended on `startAdd`); `shared/ScoreView.tsx` sets `osmd.AutoResizeEnabled = false` before `clear()` since
OSMD never removes its resize listener. Known from the explorations: the full quartet score takes 12 to 16 s
to engrave, Violin I about 10 s. Stitch plan artifact: https://claude.ai/artifact/Ab6TV66AnbqdXXnCWrG94v
(CK's ticks in its database, collection `plan`, doc `stitch`).

## Fixtures and test material

Plan (2026-10-26):

| Work | Tests | Edition | Notes |
|---|---|---|---|
| Bach, Goldberg Variations | pianist, practice mode, **OMR ground truth** | Bach-Gesellschaft | CC0 MusicXML exists (Open Goldberg). Start with Aria + Var. 1 to 3 |
| Rachmaninoff, Piano Concerto No. 1 (1917 rev.) | concerto mode: Casio plays solo, app plays orchestra | two-piano reduction, Gutheil 1920, not the full score | 4 staves, tractable OMR; dense solo writing breaks OMR first |
| Dvořák, Symphony No. 9 | librarian: part splitting, transposing instruments; rewrite to one piano (parked) | Simrock 1894 full score, II. Largo | Stress test, noisy OMR |

PDFs in `api/fixtures/pdf/` (gitignored): `goldberg-bga.pdf` (IMSLP06984, OMR ground truth),
`goldberg-peters-urtext.pdf` (IMSLP29193), `goldberg-schmid-1741-colour.pdf` (IMSLP712788, 100 MB
showpiece), `rach1-fullscore-gutheil-1919.pdf` (IMSLP24804, 92 pp.), `rach1-fullscore-muzyka.pdf`
(IMSLP62070, 145 pp.), `rach1-fullscore-scriptorium-2026-typeset.pdf` (IMSLP1035035, 116 pp., CC BY-SA 4.0,
credit editor Juddson Demers), `rach1-brass-quintet-arr.pdf` (IMSLP907959, ignore),
`rach1-two-piano-gutheil-1919.pdf` (IMSLP112913, 46 pp., concerto-practice and reduction-diff target),
`dvorak9-fullscore-simrock-1894.pdf` (IMSLP405834, 80 pp., low resolution, stress test), and later
`rach2-fullscore-imslp03631.pdf`, `beethoven-pc3-fullscore-imslp977417.pdf`,
`beethoven-pc5-fullscore-imslp977419.pdf` (Breitkopf), `beethoven-sym9-fullscore-imslp46254.pdf`.
MusicXML in `web/public/fixtures/`: Beethoven Op. 18/1 mv 1 (313 bars), Bach BWV 66.6, Chopin Mazurka Op. 6/2.
Rasterised experiment pages in `api/experiments/grounding/pages/`.

## Other decisions (2026-10-26 brainstorm, external review)

- **IMSLP.** Terms checked: no written ban on automated access, no download API, downloads pass a disclaimer
  wait page, scrapers have been blocked, content is public domain in Canada only. An in-app browser with
  download interception is not possible in a Safari PWA. Verified with curl: the final file URL serves the
  PDF with no cookie and no wait; the index link does not resolve server-side (JS redirect). Build: "Import
  from IMSLP" opens imslp.org in Safari with a one-line instruction; "Paste link" reads the clipboard on tap,
  accepts a direct PDF URL, queues processing; the API reads work metadata from the `IMSLPnnnnn-PMLPnnnnn`
  ids in the filename. Fallback: download in Safari, import from Files. True in-app browser only with
  Capacitor (feature 015). Feature 002.
- **Copyright.** One-line "you are responsible for having the right to use this score" at import; demo uses
  public-domain IMSLP material only; no redistribution (scores stay in a private bucket per ensemble).
- **Classical classification** (stretch after Nov 1): normalise composer, work, catalogue number, key,
  instrumentation, movement; Spark proposes from the title page, user confirms; filter by instrument.
- **Rewrite to one piano: out of the hackathon** (external review). Scope if ever: music21 mechanical
  reduction (collapse, drop doublings, range filter, two staves) + Spark review of unplayable bars, from
  clean MusicXML only, Dvořák Largo first 30 bars; the published Rachmaninoff two-piano reduction as few-shot
  examples and as the test set (reduce the full score, diff against the reduction). CK's idea of training a
  reduction model on ~10 symphony/reduction pairs is parked: too small to train, the Meta API has no
  fine-tuning, an open-weight Llama fine-tune on MusicXML tokens is the eventual route.
- **Agentic framing.** A, build fully: the librarian is an agent at intake, stops to ask the admin only when
  it cannot proceed, and the information box shows a short log ("Read 14 pages. Re-read bar 112 twice. Pages
  4 and 7 need a photo. Assigned 4 parts."). Never a chat window. B, one slice: a spoken note during a
  session becomes a proposed annotation the admin confirms (feature 013). Full live-agent behaviour (cuts and
  page turns by voice) is out of scope.
- **Cut from the hackathon:** piano reduction, general orchestral OMR (one narrow fixture made excellent
  instead), MIDI listening (stretch), in-app notation editing. Kept and protected: the intelligent librarian
  with visible work, live ensemble annotations, voice-to-score with confirmation, minimal practice mode.
- **Positioning (CK, 2026-10-27):** "a mid-size model made trustworthy on a hard visual task by designing the
  loop" and "same accuracy at a tenth of the cost". No rigged benchmark: run Claude through the same harness
  and publish both numbers.
- Stretch, only after Nov 1 with a stable demo: book/facing-pages view (/4 engraving); MIDI listening via the
  Casio (`mido`); classical classification; Spark Open on Baseten for a cheap text task (Best Open-Weight).
