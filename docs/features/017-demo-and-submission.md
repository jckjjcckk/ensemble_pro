# 017 Demo plan and hackathon submission

Status: designed (script written; nothing recorded; not deployed) | Meta models: all three on screen: SAM 3.1 (named; optional system crops), Muse Spark 1.3 (librarian labels, part cut, voice proposals), Muse Voice Transcribe (spoken notes).

## What the judges see

Rubric: Impact 30, Use of Meta AI tooling 25, Technical depth 20, Demo 25. Stage one is pass or fail on
using Meta models. Three-minute video, public repo, new work only; stage three: the top 5 per track, judges
watch the videos live. Bonus prizes: Best Agentic ($5K, autonomy, effectiveness, practical usefulness), Best
Creative with Muse Image or Wonder ($5K), Best Open-Weight ($10K), Most Viral (post on X). Submission due
2026-11-04, 9 PM ET.

The claim (000 positioning): a mid-size model made trustworthy on a hard visual task by designing the loop;
same accuracy at a tenth of the cost; both numbers published, Claude through the same harness.

## Demo script (revised 2026-10-26, supersedes the first version)

| Time | Scene | Proves |
|---|---|---|
| 0:00 to 0:20 | A rehearsal goes wrong because parts disagree | Real problem |
| 0:20 to 0:55 | Folio imports and prepares the score (Path B photos → pages, parts, difficulty) | Intelligent automation (SAM 3.1 + Spark) |
| 0:55 to 1:25 | The agent detects an ambiguous staff, asks the admin, resolves it, continues | Distinctive Meta AI use, honest |
| 1:25 to 2:15 | Admin makes a cut and speaks an instruction; confirms the proposal; players' stands update | The wow moment (Realtime + Voice Transcribe + Spark) |
| 2:15 to 2:40 | Pianist practises the corrected passage: loop, tempo, other parts | Continuing usefulness |
| 2:40 to 3:00 | The agent's log, the finished score, the product promise, the name | Credibility and impact |

Demo fixture: Beethoven Op. 18/1 (MusicXML, Path A) for the ensemble, plus one or two scanned Goldberg pages
for the Path B and failure moments. Orchestral scores are not in the video. The one deliberate realistic
failure (ambiguous staff assignment, the agent asks, continues) is more credible than an infallible model.
First version (for the record): 0:00 the problem; 0:30 admin drops a PDF; 1:15 invite, assign parts, four
iPads light up; 1:40 rehearsal session with a cut and a spoken note; 2:20 pianist practice with the Casio;
2:50 name. Admin carries the video; pianist gets the last 30 s. Needs 2+ iPads, the Casio, ideally a small
real ensemble or UofT Faculty of Music contacts.

## Deployment (week one, not urgent)

- Web at `https://folio.jckjjcckk.com`: Cloudflare Pages, root `web`, build `npm run build`, output `dist`,
  env `VITE_*`, custom domain on CK's zone (subdomain, not a path: PWA scope, Vite base, Pages domains and
  Supabase redirects all favour a clean origin).
- API at `https://api.folio.jckjjcckk.com` through CK's named Cloudflare tunnel (`macbook_pro_m4`, inactive
  today; `zephyr server` healthy) to the Mac (Casio and OMR live there); Railway later if wanted. Set
  `CORS_ORIGINS` to the web origin, `VITE_API_URL` to the API origin, add `https://folio.jckjjcckk.com/**` to
  the Supabase redirect URLs.
- Quick tunnel for phone access meanwhile: `cloudflared tunnel --url http://localhost:5173` (random
  trycloudflare URL, allowed by `web/vite.config.ts`).
- Modal credits only if CPU OMR turns out too slow.

## Submission checklist

- README: what existed before Oct 27 (the seven setup-only commits of Oct 26: project setup, exploration
  scaffolds, mock data, install script), which Meta model does what (generated from the handler docstrings),
  how to run. The video must say the same.
- Rename the GitHub repo to Folio before the submission form (GitHub redirects the old URL; then
  `git remote set-url origin ...`).
- Build queue: Nov 2 integration, iPad testing, demo rehearsal (full run-through recorded); Nov 3 reliability,
  recording, README, submission draft (final video cut); Nov 4 final verification, submit before 9 PM ET,
  post on X.
- Public repo from day 0; push only when CK says.

## Next steps

1. Complete usable demo by Nov 1, then refine.
2. Deploy, PWA install on the iPads, record.
