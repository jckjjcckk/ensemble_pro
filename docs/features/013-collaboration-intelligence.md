# 013 Collaboration intelligence: voice notes to proposed marks

Status: designed, fixture ready (30-line ground truth; no recordings yet; no handler) | Meta models: Muse Voice Transcribe (speech to text, diarisation) then Muse Spark 1.3 (one call or a short agent run that decides position, audience and kind).

## Purpose

During a rehearsal session the admin speaks ("Second violins, from forty-two to forty-eight we're cutting
that") and the right stands get a proposed mark the admin confirms with one tap. Build-queue item 7 (Oct 31).
Done means: "Second violins, start at 34, skip 42 to 48" becomes a confirmed cut on the violin II stand.

## What exists

- `api/fixtures/voice/script.csv`: 30 lines, each labelled with `position` (bar | range | mark | global |
  none), `bar_from`, `bar_to`, `audience` (ensemble | part:<seat name> | member; several joined with `;`),
  `kind` (cut | dynamic | marking | text | breath | bowing | none), `expect` (the one-line annotation the stand
  should show, or none). Includes negatives (v06 "Let's take it from the top", v14 lunch, v20 window, v30
  "bar one, here we go") that must produce no annotation, a two-part line (v21: breath at 64 for A and T,
  sfz at 65 for all), named members (v11 Lin, v22 Inès), pickups (v12), rehearsal letters (v05, v19, v25),
  "to the end" ranges (v16). Parts: Violin I, Violin II, Viola, Cello (Hart House) and Soprano, Alto, Tenor,
  Bass (choir).
- `api/fixtures/voice/README.md`: recording instructions (one file per line, `v01.m4a`..., iPhone Voice Memos;
  said the way a conductor says it mid-rehearsal; a second pass by a different voice as `v01b.m4a` to tell
  whether the model keys on words or on voice; audio gitignored). CK records.
- Planned: `scripts/voice_eval.py` scores Voice Transcribe + Spark against the CSV.
- Job kind `transcribe_voice` (`docs/librarian-contract.md`): payload `{score_id, session_id, audio_path,
  author_id}`; writes `annotations` with `status = 'proposed'`, `audience`, `measure_from/to` by stable id,
  `body` = transcript. Agent tools (006): `score_facts` (part list, measure range, rehearsal marks),
  `propose(kind, measure_from, measure_to, audience, text, quote)` (commit: `quote` must be a verbatim span
  of the transcript, bars inside the range, audience a known part or `ensemble`, else refuse), `finish`.
- Schema support: `annotations.status proposed | live`, `audio_path`, `session_id`; `rehearsal_sessions`.

## Rules and decisions

- Voice instructions are proposals: the admin confirms before anything goes live. No speech error alters
  anyone's music (external review 2026-10-26).
- Admin only: only the admin can enable voice notes and only during a rehearsal session they started.
- One Spark call per note, effort low, output budget as in 006; quotes are verbatim.
- Voice Transcribe facts (000): 16-bit mono WAV at 16 or 24 kHz, at most 10 min and 32 MB, turn-level
  timestamps only, `keywords` biasing (feed the part names and rehearsal letters), diarisation, $0.18 per
  hour. Spark 1.3 audio is "not fully supported": audio goes to Voice Transcribe, not to Spark.
- Full live-agent behaviour (cuts and page turns by voice) is out of scope.
- Rehearsal brief (Spark, `brief` job) if time.

## Open issues

- No recordings yet; ffmpeg not installed on the Mac (only when audio work starts); conversion from `.m4a`
  to 16 kHz mono WAV needed before upload.
- Rehearsal letters need the score's marks (`measure_placements.rehearsal_mark`); "the last page", "the key
  change", "the coda" need score facts that MusicXML has and scans may not.
- Member names in the transcript must resolve to `members` (Lin, Inès).

## Next steps

1. CK records the 30 lines (and the second voice).
2. `voice_eval.py`: transcribe, propose, score position / audience / kind / expect against the CSV.
3. `transcribe_voice` handler on the agent loop; confirm UI on the admin iPad; live push to the stands.
