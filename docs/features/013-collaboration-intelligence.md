# 013 Collaboration intelligence: voice notes to proposed marks

Status: built, push-to-talk (server, recording, tray and ghosts on 2026-10-30; eval 2026-10-29; listening mode not built) | Meta models: Muse Voice Transcribe (speech to text, diarisation) then Muse Spark 1.3 (one call per take).

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
- `api/experiments/voice/voice_eval.py`: m4a → plain PCM WAV, Voice Transcribe, one Spark call per line, scores
  (Results below). Every prompt version in `prompts.py`, scores in `results/`, every paid call in `spend.jsonl`.
- `api/app/librarian/voice_prompt.py`: the chosen prompt (`build_prompt`), score facts, and the check that refuses
  a mark (`checked_marks`); `tests/test_voice_prompt.py`.
- Job kind `transcribe_voice` (`docs/librarian-contract.md`): payload `{score_id, session_id, audio_path,
  author_id}`; writes `annotations` with `status = 'proposed'`, `audience`, `measure_from/to` by stable id,
  `body` = transcript. Agent tools (006): `score_facts` (part list, measure range, rehearsal marks),
  `propose(kind, measure_from, measure_to, audience, text, quote)` (commit: `quote` must be a verbatim span
  of the transcript, bars inside the range, audience a known part or `ensemble`, else refuse), `finish`.
- Schema support: `annotations.status proposed | live`, `audio_path`, `session_id`; `rehearsal_sessions`.

## Built: push-to-talk (2026-10-30)

- `POST /scores/{id}/voice` (`api/app/routes/voice.py`): the raw WAV body (16 kHz mono 16-bit, at most two minutes),
  `?ensemble_id=` the mark layer, `?session_id=` optional. Only the layer's leader (`can_lead_layer`: the group's
  admin, or the owner of a personal book); 402 when the budget is spent. Stores `{score}/voice/{utterance}.wav`,
  inserts a `transcribe_voice` job as `running` and runs it in the API process right after answering `202
  {job_id, utterance_id}` (the worker's stale sweep requeues it if the process dies). The job has no `score_id`, so
  a failed take never marks the book failed.
- `transcribe_voice` (`api/app/librarian/transcribe_voice.py`): score facts from the database (parts, or the group's
  seats when no parts are read; members' first names; bar range from `measures`; letters from the current
  interpretation's `measure_placements.rehearsal_mark`), keywords from them, Voice Transcribe in diarisation mode,
  one Spark call (`provider="meta"` whatever LLM_PROVIDER says), `checked_marks`, then one `annotations` row per
  audience with `status = 'proposed'` and `payload = {source: 'voice', utterance_id, mark_id, position, bar,
  bar_to}`. A letter is placed by the score's marks ("before F" = the bar before); "global" is the whole piece,
  or its first or last bar when the words say so; a landmark with no record (double bar, coda) goes to
  `result.unplaced` for the admin to place by hand. `result = {utterance_id, transcript, quotes: {mark_id: quote},
  proposed, rows, unplaced, refused, seconds, cost_usd}`. Both calls are charged (`voice`, `spark`).
- What was said stays the sender's (CK, 2026-10-30, after the audit): the raw take is deleted as soon as it is
  transcribed (a sweep removes one left by a failed job after an hour); the transcript and the quotes live only on
  the job row, which only its creator reads (`jobs_select`); an annotation carries its stand text and ids, never
  the take's other words. A retry after transcription reuses the saved transcript (no second ASR charge). The tray
  reads quotes from the job result, and from the sender's own earlier jobs by `utterance_id`.
- Real run through the handler (fake database, eval takes v02, v11, v28, v14): 2.7 to 5.8 s and $0.003 to $0.006
  a take; v02 → Cut 42–48 on Violin II; v14 → nothing; v11 and v28 lost their addressee in transcription (the
  known failure, below) and came out for the ensemble.
- Tests: `api/tests/test_transcribe_voice.py` (rows per audience, member and ensemble, letters, to the end,
  global, refusals, nothing to mark, WAV checks, the route's permissions).
- The Stand (`web/src/app/voice.ts`, `VoiceNotes.tsx`, `voice.css`, `web/src/lib/recorder.ts`): a glass "Hold to
  speak" button for whoever leads the layer on screen (Space or Enter hold on a keyboard; a tap under 400 ms only
  shows the hint). Recording is raw PCM through an AudioWorklet resampled to 16 kHz WAV (MediaRecorder on iOS gives
  m4a, which Voice Transcribe refuses), stopped at 120 s; `Info.plist` asks for the microphone. Listening lights
  the glass in Muse blue with the voice level; working drifts the multicolour wash. The tray (a sheet) holds one
  card per `mark_id`: kind, place, text, audience chips (the quickest fix), the quote, Accept / Edit / Dismiss,
  Accept all per take, "Left out: …" for refusals, "Nothing to mark", and "Tap a bar" for unplaced marks. Ghosts
  (glass, Muse-blue rim) sit over the proposed bars per system; a card tap jumps there, a ghost tap opens its card.
  Proposed rows never draw as marks; the job is watched by Realtime on its row plus a 2 s poll until it is done or
  failed (five minutes at most; the worker's two retries say "Trying again…"). Send again first asks the job, so a
  job that is still working is watched again, never doubled; a reason the job gave about the recording itself is
  shown and offers no resend.
- Accepting is one transaction (web half audit, 2026-10-30): `commit_marks` (migration 20261030120000) removes,
  changes and adds a card's rows together, as the caller, so the annotations policies decide every row; a row
  gone or not the caller's refuses the whole call. Every row it writes carries its bars in `payload.bar` /
  `bar_to`, which is what a player's Realtime copy (no joined measures) draws from: an edited cut reaches the
  stand at its new bars. A cut whose text only names its bars ("Cut 42–48") is rewritten with them. A refusal or
  no connection puts the card back from memory and says why ("Not saved. No connection. Try again."). The bar
  steppers stop at the book's last bar; an unplaced item keeps the audience it was heard with. Checked
  `api/scripts/smoke_commit_marks_local.py` (16 checks on the local stack: a batch with one bad write changes
  nothing, a player is refused, edit bars, keep one part, drop one, add a player) and in the browser (accept with
  bars 44–48 and Cello swapped for Lin; the same accept with the request failing rolls back and says so).
- Checked 2026-10-30 in the browser on the local stack with real Meta calls (the pane blocks the microphone, so
  the take was fed through a replaced `getUserMedia`): v02 → "Cut 42–48", Violin II, in about 5 s; card tap → the
  ghost at bar 42; Accept → one live row for Violin II. v21 on a string quartet → "sfz at 65" for everyone plus
  "Left out: Alto is not a part in this book"; Dismiss deletes. Not yet checked: a real microphone on the iPad
  (WKWebView's prompt, AudioWorklet from a blob URL), a player's stand receiving the accepted mark live.

## Prompt v4d (2026-10-30)

The app's prompt (`voice_prompt.py`) is now **v4d**: v4 plus three rule edits found by a text-only eval of the Spark
half (`013-text-eval.md`). (1) A start point for a later run ("next time", "tomorrow") or anything the speaker asks
to have written is a mark (v4 dropped "Start at bar 12 next time" and even "write that in" as a start point).
(2) An exclusion ("everyone else", "except") lists the other parts of the excluded part's group only (v4 spread
"everyone else" from the altos across the strings). (3) A section or name not in the score facts goes to the
ensemble with the word kept in the text (v4 turned "brass" into Bass, and "Marco" into a member the check refuses).

- Text set (130 lines written for the test, 100 instructions + 30 non-instructions, chat completions, effort
  minimal, one run each): v4c 95/100 fully right → v4d **99/100**; missed instructions 3 → 0; flow marks 2/5 →
  4/5; balance 5/7 → 7/7; roster cases 2/4 → 4/4; false positives 0 → 1 (n16, which v4c also gets wrong 2 times in 5
  on repeat; v4d 5/5); 1.19 s median, $0.0021 a call.
- CK's 40 recorded lines + 23 negatives (realtime transcripts, minimal): v4c 22/26, 7/9, 23/23 → v4d 21/26, 7/9,
  23/23. The one change is v15 "Stop the cello" (except), which repeats put at v4c 4/5 and v4d 5/5: spread, not a
  regression. Confidence ≥ 0.95 auto-applied 10 marks, none wrong.
- Latency, the always-on pipeline and the confidence gate: `013-always-on.md`. The few-shot examples are unchanged,
  and `experiments/voice/prompts.py` keeps v4 as scored and checks the app against `RULES_V4D`.

## Prompt v4e (2026-10-30)

The app's prompt is now **v4e**: v4d plus two parts of the library-of-context eval (`013-v4e-eval.md`). (a) The facts
list the book's **landmarks** with bars, and a place named from a listed one ("two after the key change", "the bar
before the double bar", "in the slow section") resolves to `bar` or `range`; a landmark not listed stays `mark`, as
before. (b) The facts list the book's **groups**, and an exclusion lists the other parts of the widest listed group
holding the excluded part (a soloist is excluded from the Orchestra); the hardcoded strings/voices pair is gone.
Part (c), a musical-terms mishearing line, is not adopted: no measured gain (v4d already read every mangle on text).

- **Groups** (`voice_prompt.derive_groups`, from the part names through the header's synonym table): Strings,
  Woodwinds, Brass, Percussion, Keyboard, Voices in score order; a book whose instruments span two sections has an
  Orchestra, and its one piano (or a part named solo) is the Soloist, in no other group. A quartet is Strings, a
  choir Voices, strings + choir the two v4d groups (so book A behaves as before).
- **Landmarks** (`scores.landmarks`, migration `20261030160000_score_landmarks.sql`; `app/librarian/landmarks.py`):
  `{kind, label, bar, bar_after, source}`, kinds key_change, meter_change, tempo, double_bar, repeat, coda, segno,
  fine, section, rehearsal; source `musicxml` or `page`. Digital books: music21 at import and on Convert to Digital
  (`landmarks.from_musicxml`, no model). Scanned books: the per-page Spark read points each printed landmark at a bar
  box, geometry gives the bar (004). A converted book's MusicXML landmarks replace the page ones. The facts say a
  boundary as "double bar between bars 150 and 151" (the eval's one v4e miss, lm15, read "double bar after bar 150"
  so "the bar before the double bar" came back 149), a tempo heading as a range to the next heading ("Andante bars
  151-210"), a coda to the end. A book with none says "Landmarks: none listed." (behaves as v4d: the clean-130 guard).
- **ASR keywords** gain a trimmed glossary of 31 musical terms (`transcribe_voice.MUSIC_TERMS`): fermata, sforzando,
  pizzicato, ritardando… The eval's term-word errors went 5 → 3 of 34 in both runs; `pizz`, `cut`, `piano`,
  `forte`, `mezzo`, `mute`, `bar`, `letter` are left out ("pizz" + "cut" split "pizzicato" into "pizz cut").

Scores, the app's own prompt builder with the eval's confidence field, facts built as `transcribe_voice.Score` builds
them, effort minimal, one run (`api/experiments/voice_text/live_v4e/`, $0.41 for 159 calls):

| set | eval v4d | eval v4e (2 runs) | app v4e (1 run) |
|---|---|---|---|
| messy100 landmark cases (20) | 0 | 19, 19 | **20** (lm15 now bar 150) |
| messy100 concerto group cases (9) | 4 | 9, 9 | **8** (g15: audiences right, "Rest at 240" kind marking, not text) |
| clean 130: instructions right (100) | 100 | 100 | **99** (f04 split into two marks at 57) |
| clean 130: with stand text | 97 | 97 | 96 |
| clean 130: false positives (30) | 0 | 0 | **0** |

`experiments/voice/prompts.py` keeps `RULES_V4D` and checks the app against `RULES_V4E` at import.

## Effort minimal in the app (2026-10-30, speed pass)

`transcribe_voice` sends its one Spark call at effort minimal on chat completions, streamed (`VOICE_EFFORT`), the
setting every voice eval ran at. The app's own call (v4e `build_prompt`, `llm.complete`) on CK's recorded lines and the
negatives (realtime transcripts, `experiments/speed_pass/voice_regress.py`, 6 in flight, one run each):

| | base lines, all five fields | retakes | negatives clean | median s | p90 s | median out tok | $ a line |
|---|---|---|---|---|---|---|---|
| Messages, low (before) | 21/26 | 7/9 | 23/23 | 1.83 | 3.50 | 426 | 0.0034 |
| chat, minimal, streamed (after) | 21/26 | 7/9 | 23/23 | 1.08 | 2.30 | 237 | 0.0035 |

Two lines swap (v23 right only at minimal, v26 only at low). `scripts/smoke_voice_local.py`, take to done on the local
stack: v02 4.6 -> 3.3 s, v28 4.3 -> 2.9 s, v14 2.4 -> 2.4 s, same proposals, FAILS 0 both times.

## Rules and decisions

- Voice instructions are proposals: the admin confirms before anything goes live. No speech error alters
  anyone's music (external review 2026-10-26).
- Admin only: only the admin can enable voice notes and only during a rehearsal session they started.
- One Spark call per note, effort low, output budget as in 006; quotes are verbatim. Prompt v4e since 2026-10-30
  (v4d earlier the same day).
- Voice Transcribe facts (000): 16-bit mono WAV at 16 or 24 kHz, at most 10 min and 32 MB, turn-level
  timestamps only, `keywords` biasing (feed the part names and rehearsal letters), diarisation, $0.18 per
  hour. Spark 1.3 audio is "not fully supported": audio goes to Voice Transcribe, not to Spark.
- Full live-agent behaviour (cuts and page turns by voice) is out of scope.
- Rehearsal brief (Spark, `brief` job) if time.

## Results (2026-10-29, eval on CK's recordings)

Set-up: 30 script lines (`v01`..`v30`, 26 marks + 4 negatives) and 10 retakes of lines 1-10 (`v01c`..`v10c`, CK
self-correcting or blurring the wording; 9 marks + 1 negative), one voice, iPhone-style m4a at about 5 s each.
Voice Transcribe in `DIARIZATION` mode with `keywords` = the 8 part names, plural seat names, Lin, Inès, "bar",
"pickup", "letter A".."letter F". Spark `muse-spark-1.3`, effort low, 8k output budget, one call per line, answer
`[{position, bar_from, bar_to, audience, kind, text, quote}, ...]` or `{"none": true}`; a mark whose quote is not a
verbatim span, whose bars are outside 1-240 or whose audience is not a known part/member/ensemble is refused and
counts as a miss. Score facts given: parts, members, bars 1-240, letters A-F (no letter-to-bar map, so `mark`
positions carry no bars). Scoring: fields exact against the CSV (audience as a set, `member` resolved to the named
member; a one-bar mark's null `bar_to` = `bar_from`; "to the end" = null or 240); `expect` exact after folding case,
dashes, punctuation and spoken numbers; "judge" = one Spark closed question (expected vs proposed text with bars and
audience: would a musician accept it); negatives = no mark produced. WER against the CSV text with spoken numbers
as digits ("forty-two" = 42, "one-twelve" = 112).

**Best prompt: v4** (rules + 8 worked examples from the CSV with the scored line and a retake's base line held
out). Run twice (v4, v4r2) to see Spark's spread.

| | base 30 (v4 / repeat) | retakes 10 (v4 / repeat) |
|---|---|---|
| WER (Voice Transcribe vs script) | 0.177 (55/310 words) | 0.686 (72/105; mostly CK's added correction words) |
| mark produced | 26/26 | 9/9 |
| position | 26/26 | 9/9 |
| bar_from / bar_to | 26/26 / 26/26 | 9/9 / 9/9 |
| audience | 23/26 | 8/9 |
| kind | 25/26 / 24/26 | 8/9 |
| all five fields | **22/26 / 21/26** | **7/9 / 7/9** |
| expect, exact text | 9/26 / 6/26 | 4/9 / 6/9 |
| expect, musician would accept (judge) | 22/26 / 23/26 | 8/9 / 7/9 |
| negatives with no mark | 4/4 | 1/1 |
| refused by the check | 0 | 0 |
| cost per line (transcribe + Spark) | $0.0034 | $0.0044 |
| seconds per line (transcribe + Spark) | 5.9 (1.5 + 4.4) | 6.5 (2.1 + 4.4) |

Every version, base set, all five fields / judge / negatives: v1 plain 9/26, 11/26, 4/4 (3 marks refused: letter
and "last page" places given as `bar` with no bar); v2 rules 16/26, 20/26, 4/4; v3 rules + few-shot 15/26, 19/26,
4/4; **v4** revised rules + few-shot 22/26, 22/26, 4/4; v5 = v4's rules without few-shot 21/26, 20/26, 4/4 at
$0.0040 a line (the examples cut Spark's reasoning, so v4 is also the cheaper one). Full table:
`api/experiments/voice/results/summary.md`; transcripts `results/transcripts.md`.

Round two (cap raised to $20 by CK), base all five fields / judge, retakes all five fields:

| version | what changed | base | judge | retakes |
|---|---|---|---|---|
| v4 / v4r2 (chosen) | rules + held-out few-shot | 22/26, 21/26 | 22/26, 23/26 | 7/9, 7/9 |
| v6 | v4 with the mishearing rule made generic (no "accept/stop" = except, no example names) | 19/26 | 24/26 | 6/9 |
| v7 | v4 + "keep negations, add nothing" in the stand text | 20/26 | 22/26 | 7/9 |
| v8 | v6's generic rules + both recognisers' transcripts (diarisation and push-to-talk) | 21/26 | 24/26 | 7/9 |
| v4 on PTT transcripts | second scoring pass, other ASR mode | 20/26 | 23/26 | 6/9 |
| v6 on PTT transcripts | second scoring pass, other ASR mode | 20/26 | 21/26 | 6/9 |

Readings: the hint v4 wrote for v15/v18 is worth about two lines (v6 loses v15 "stop the cello" = except); a second
recogniser gets most of that back without a tuned hint (v8 = v4's repeat, +$0.0003 a line for the second
transcription), so v8 is the candidate if a second voice shows v4 overfitting. The fidelity rule (v7) moved
nothing: the judge's refusals (v07 "end of 2", v17 lost "not") are in the transcript, not the prompt. On PTT
transcripts the retakes drop to 6/9 (v07c loses bar 71), so DIARIZATION stays. No version, mode or pass produced a
false positive on the 5 negatives; v11, v16, v28 (addressee absent from both transcripts) miss in every run.

Honest caveats: the v2 and v4 rules were written after reading this set's misses (their examples are made up, but
the rule topics come from these 30 lines), so 22/26 is optimistic; the retakes and a second voice are the check.
A first v2 draft quoted scored lines' answers in its rules and was thrown away unscored ($0.26 in the ledger).
Run-to-run spread at effort low is about one line in 26. The cost and time exclude the judge (eval only, $0.86 over
all runs). Spark's `input_tokens` count only the uncached part of the prompt, so cost is slightly under.

Voice Transcribe format: `afconvert -d LEI16@16000 -c 1` writes WAVE_FORMAT_EXTENSIBLE with an FLLR chunk and is
refused ("must be a mono 16-bit PCM WAV"); the same samples rewritten with a plain 44-byte PCM header pass. PUSH_TO_TALK
mode gave base WER 0.158 against DIARIZATION's 0.177 (within call-to-call noise; it heard "Fiddles" and "Altos"
where diarisation heard "Vidos" and "Autos", and wrote some numbers as words); kept DIARIZATION for the speaker
labels a long take will need. Whole eval: $3.02 of Meta spend, every call in `spend.jsonl` (transcribe $0.04, propose
$1.69, judge $1.29); round one $1.93, round two $1.09.

### Failure modes

- **Numbers misheard: none that mattered.** Every bar number in all 26 base marks and 9 retakes came out right.
  Transcript noise was doubling ("bar 112 everyone bar 112"), a stray "eight" in v13 ("go straight eight on") and
  "back at 130" for "one thirty" (a negative).
- **Part names and addressees.** The real loss. Three lines lost the addressee before Spark saw them: v11 "Lin,",
  v16 "Firsts and", v28 "Cello," appear in no transcript in either mode, with or without a second of leading
  silence (CK: worth a listen to whether they were said softly). v15 "Everyone except the cello" became "stop the
  cello" ("accept the cello" in PTT); v4 recovers it, but its rule names that mishearing (tuned). Misheard but recovered: "Autos" = altos (v04),
  "Vidos" = fiddles (v18), "Dakota" = coda (v29), "Right in a menta" = "write in a fermata" (v27), "Drums" in v03c.
  "Ing 88" (v10, "in 88") made v1 address Inès; fixed by "only when the name is clearly said". Audience misses in
  v4: v11, v16, v28 (all three are the dropped addressees), so the prompt is at the transcript's ceiling there.
- **Self-corrections (retakes).** The five explicit ones resolve right in both v4 runs: v01c "32, no, uh, 34",
  v02c "first and second, actually, no, just the second", v03c "drums… no… for the cello", v05c "letter D… no, from
  letter C", v07c "the first violin… okay, violas". v1 got v07c wrong (no mark); v2/v3 kept the first violin; v4's
  "a correction replaces only what it corrects" rule fixed it. v04c's correction changes the meaning ("I mean
  sopranos", label Alto): Spark followed the speaker, scored as an audience miss. v10c dropped "not louder" so
  "hold it back" reads as tempo (kind text, label dynamic).
- **Negatives.** No false positive in any version: v06 "from the top", v14 lunch, v20 window, v30 "bar one, here we
  go", v06c, 0/5 produced a mark in every run. The opposite failure did happen: v12's entry cue "pickup to 34,
  firsts, that's where you come in" was treated as a start point and dropped by v2 and v3; v4 names entries as marks.
- **Kind boundary.** "Harmonic on the A string" (v22) is `marking` to Spark, `text` in the CSV; v27 fermata flips
  between `marking` and `dynamic` across runs. A taxonomy question more than an error.
- **Stand text.** Exact text matches are low (6-9/26) because wording differs ("Low E (octave) at bar 203" for "Low
  E, not the octave"); the judge accepts 22-23/26. Judge refusals that are right: v07 "entry on the end of 2" (ASR
  heard "end" for "and"), v17 lost "not".

## Open issues

- Only one voice. A second voice (README `v01b.m4a`…) is the overfitting check: run v4 and v8 on it; keep v4
  unless v8 wins there.
- No long continuous take yet: a rehearsal recording needs splitting into utterances before the one-call-per-line
  step. Planned splitter: Silero VAD (or Voice Transcribe's own `ENDPOINTING`/`DIARIZATION` turns, to compare),
  each turn to Spark with the previous turn as context.
- Leading short words ("Lin,", "Cello,") vanish in transcription; if CK's audio has them, try a longer lead-in or
  name the members first in `keywords`.
- Rehearsal letters need the score's marks (`measure_placements.rehearsal_mark`, or a digital book's MusicXML
  rehearsal marks). "The key change", "the coda", "the double bar" resolve when `scores.landmarks` lists them
  (v4e); books imported or read before 2026-10-30 have none until re-imported, converted or read again. A scanned
  page's key-change label is often wrong (the bar is right) and start repeats at a system's start are missed (004).
  Untested: "everyone but the piano" in a choir-with-piano or piano-quintet book (no Orchestra group there).
  `scores.landmarks` is on the local stack only: hosted needs `supabase db push --linked` (reads and writes
  tolerate the missing column).
- Member names in the transcript must resolve to `members` (Lin, Inès).

## Next steps

1. CK on the real iPad: hold to speak, the microphone prompt, a take, accept; a second iPad as a player to see
   the mark arrive.
2. A second voice for the 30 lines; re-run `voice_eval.py run --prompt v4`.
3. Rehearsal sessions (start/end on the Stand) and `session_id` on takes; then listening mode on the same seams.
