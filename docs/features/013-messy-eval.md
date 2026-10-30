# 013 Messy eval: rambling, mis-heard and unrecoverable speech to Muse Spark to marks

Status: experiment (2026-10-30). | Meta model: Muse Spark 1.3 only (`/v1/chat/completions`, streamed, effort
**minimal**). No speech-to-text: the transcript is typed text written to look like bad speech and bad STT.

The question: the clean text eval (`013-text-eval.md`) put prompt v4d at 99/100. How much of that holds when the
speech is what a conductor actually says, through what Voice Transcribe actually writes?

Files: `api/experiments/voice_text/messy/` — `cases.py` (the 50 cases, ground truth and the librarian's note per
case; `set.jsonl` is the same as data), `run.py` (calls, two runs, code scoring that reuses `../run.py`'s pairing
and stand-text test), `report.py` (every table below), `results/raw_r{1,2}.json` (every reply),
`results/score_r{1,2}.json` (every case scored), `spend.jsonl` (every call). Local data only; Supabase not touched;
no app code changed.

## Set-up

- **Prompt**: v4d exactly as in the clean eval's round two (`prompt_v4d.build_v4d`: the app's v4d rules + the
  confidence rule and field; the app's own `voice_prompt.py` has the same rules without the confidence field).
  Same score facts and roster: parts Violin I, Violin II, Viola, Cello, Soprano, Alto, Tenor, Bass; members Lin,
  Inès; bars 1–240; letters A–F. Two calls per case, minimal, 8k budget, 6 in parallel.
- **The set**, 50 lines, none from the clean set or `script.csv`; 40 instructions (46 expected marks) and 10
  unrecoverable:
  - **comm, poor communication (20)**: rambling with the instruction buried (2), mid-sentence changes of bar,
    part or dynamic (4), two instructions with an aside between (2), roster gaps mixed with real parts ("Trumpets
    and cellos", "Clarinets … and violas, you too") (2), negatives ("don't rush at 60", "don't breathe in 118") (2),
    implicit targets resolvable from the line (3), sarcasm ("forte at 30, that's exactly what pianissimo looks
    like") (2), nicknames ("Linny", "Benji" not in the roster, "Concertmaster") (3), dynamics without a named mark
    ("I can't hear you … that's the tune", "drowning everyone") (2).
  - **stt, poor transcription (20)**, in the style of the realtime transcripts in
    `voice_stream/results/realtime_endpointing.json` (numerals, lost punctuation, lower case): dropped first word
    (2), homophones `too`/`for teen`/`two loud`/`bah`/`pianist`/`fore` (6), merged words `cellospizz` (1), split
    number `bar 1 40` (1), mis-heard parts `Vidos`, `Autos`, `base` (3), mangled terms `attempt oh`,
    `retard and oh`, `pizza cutter`, `fermenta` (4), run-on with a non-instruction tail (1), a player's reply inside
    the transcript ("which one", "is that 50 or 15") (2).
  - **unrec, unrecoverable (10)**: 5 with ground truth **none** (sarcasm with no content, noise, cut off mid-bar,
    a cut "I'll tell you later", "louder, no, softer, I don't know") and 5 with ground truth **flag** (an
    instruction with no place, "bar 2 forty", garbled cello request, "you, yes you", "base is a piano tuna at for
    tea"). v4 has no "uncertain" field, so **flag = a mark whose known fields are right and whose confidence is
    below 0.9**, so it reaches the admin and not the stand; the unknown field accepts anything. Where the other
    outcome is also defensible it is recorded (`also`): un01 and un08 accept a low-confidence card, un02, un04 and
    un10 accept none.
  - Difficulty 1/2/3: 9/29/12. Each case's `note` says what a careful librarian would write.
- **Scoring**: as the clean eval (code, no judge): `parse_answer` + `checked_marks`, best one-to-one pairing,
  position/bars/audience/kind exact against the accepted values; a case is right when every expected mark is right
  and nothing extra stands. Stand text: lenient key words. Defensible alternatives recorded as accepted answers
  (pc06/pc07 cello or violas alone, ensemble with the section word kept, or both; pc14 Violin I or ensemble; pc20
  one mark 44–64 or two marks; pc04 cresc. at 55–56 or 56).
- **Ground-truth edits after the first look, disclosed**: three entries contradicted their own case notes and were
  tightened before the numbers below: pc01 accepted `bar_to` null (which in v4 means "to the end", against the note
  "no end bar was said"); pt02's text key `g` matched any text with the note name; pt12's key `entry` passed a text
  without "early". Before the edits: 38/40 and 40/40 instructions right, 38/40 and 40/40 with stand text.

## Results

| run | instructions right | + stand text | position | bars | audience | kind | text | unrecoverable right | all 50 | no mark | extra mark |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | **37/40** | 35/40 | 45/46 | 44/46 | 45/46 | 45/46 | 43/46 | 9/10 | 46/50 | pc16 | pt17 |
| 2 | **39/40** | 37/40 | 46/46 | 45/46 | 46/46 | 46/46 | 44/46 | 9/10 | 48/50 | – | – |

Right in both runs: 46/50 (37/40 instructions). Clean set for comparison: v4d 99/100, 96/100 with text.

| group | n | r1 right | r2 right | r1 + text | r2 + text |
|---|---|---|---|---|---|
| comm | 20 | 18 | 19 | 18 | 19 |
| stt | 20 | 19 | 20 | 17 | 18 |
| unrec | 10 | 9 | 9 | 9 | 9 |

| difficulty | n | r1 right | r2 right |
|---|---|---|---|
| 1 | 9 | 9 | 9 |
| 2 | 29 | 27 | 28 |
| 3 | 12 | 10 | 11 |

Every sub-category was right in both runs except: rambling 1/2 (pc01), dynamics without a mark 1/2 then 2/2
(pc16), run-on 0/1 then 1/1 (pt17), wrong number 1/2 (un03), and on stand text dropped word 1/2 (pt02), part name
2/3 (pt12). All 6 homophones, all 4 mangled terms, all 4 mid-sentence changes, both asides, both negatives, both
sarcasm lines (pc11 came out pp, not f), both stray player replies, "cellospizz" and "bar 1 40" = 140 were right
in both runs.

### Run-to-run agreement

- Same structured marks (position, bars, audience, kind) on **47/50** cases; differ on pc16 (none vs a mark),
  pt17 (an extra mark in run 1), un10 (bar 43 vs 40, both at 0.35–0.4). Same verdict 48/50.
- Stand text word for word on 30/50 (the rest differ in wording only: "bar 104" vs "104", "Softer" vs "Bring down").
- Confidence on the 45 paired marks: median |r1 − r2| 0.00, max 0.20, equal on 23. But **21 marks cross one of the
  three thresholds between runs** (7 at each of 0.8, 0.9, 0.95), e.g. pc14 0.85 → 0.65, pt09 0.95 → 0.85, pc15
  0.75 → 0.90. On messy input the gate decision for a given line is close to a coin toss near the threshold.

### Unrecoverable cases and false positives

| id | what | gt | run 1 | run 2 |
|---|---|---|---|---|
| un01 | "Lovely, let's never play 55 like that again." | none | none 0.9 | none 0.9 |
| un02 | "that bar again, softer" | flag (also none) | none **0.6** | none **0.6** |
| un03 | "tenors bar 2 forty accent" | flag | Tenor, bar 240, accent, **0.9** ✗ | same ✗ |
| un04 | "the cello the bar the thirty the uh fermenta no the other one" | flag (also none) | none **0.65** | none **0.6** |
| un05 | "uh violas at the um can we just the thing at the end of the" | none | none 0.9 | none 0.9 |
| un06 | "Sopranos, at bar sixty-" | none | none 0.95 | none 0.9 |
| un07 | "you, yes you, bar 88, too loud" | flag | ensemble, 88, softer, 0.6 | same, 0.6 |
| un08 | "Everyone, cut from forty to, uh, to, hmm, I'll tell you later." | none (also flag) | none 0.8 | none 0.8 |
| un09 | "Violas, louder at 70, no, softer, no, actually, I don't know, let's hear it." | none | none 0.9 | none 0.9 |
| un10 | "base is a piano tuna at for tea" | flag (also none) | Bass, bar 43, p, 0.35 | Bass, bar 40, p, 0.4 |

- **False positives on the 5 "none" cases: 0/5 in both runs** (no mark at all). Across all 10, one mark at ≥ 0.9 in
  each run (un03), none at ≥ 0.95.
- Only 2 of the 5 flag cases came back as a flagged card (un07, un10); un02 and un04 came back as none, which the
  set accepts, but they are silent: the admin never hears that something was asked for. Their none-confidence (0.6,
  0.6–0.65) is the lowest of any none in either run; every other none was 0.8–0.95.

### Confidence on messy input

| run | threshold | marks auto-applied (of 49) | of those wrong | instructions wholly auto-applied (of 40) | of those not right |
|---|---|---|---|---|---|
| 1 | ≥ 0.8 | 38 | 2 (pc01, un03) | 30 | 1 |
| 1 | ≥ 0.9 | 28 | 1 (un03) | 20 | 0 |
| 1 | ≥ 0.95 | 15 | 0 | 11 | 0 |
| 2 | ≥ 0.8 | 39 | 1 (un03) | 32 | 0 |
| 2 | ≥ 0.9 | 25 | 1 (un03) | 19 | 0 |
| 2 | ≥ 0.95 | 12 | 0 | 9 | 0 |

(Wrong = not core-right, an extra, or any mark on an unrecoverable case. Stand text not counted: pt02 "In tune high
G" at 0.85 and pt12 "Entry at bar 200" at 0.85 pass ≥ 0.8 with the wrong words.)

- **Spark knows the input is worse.** Right marks: median 0.90 (clean set: 0.95), 0.6–0.75 on 8 and 7 right marks,
  mostly STT noise (pt10 "Vidos" 0.6–0.65, pt13 "attempt oh" 0.65–0.7, pt15 "pizza cutter" 0.65) and roster
  doubts (pc13 "Benji" 0.65, pc06's trumpet card 0.6). The 0.95 tier covers only **9–11 of 40** instructions (clean:
  64/100, CK's recorded takes 11/35), and stayed clean in both runs.
- The 0.9 tier is not clean: un03 sat at exactly 0.9 twice. The flagged unrecoverable marks (un07 0.6, un10
  0.35–0.4) were well below any gate, which is what the field is for.

### Latency and cost

| run | median s | p90 s | max s | cost (50 calls) | $/call | output tokens (median) |
|---|---|---|---|---|---|---|
| 1 | 1.57 | 2.72 | 6.46 | $0.150 | $0.0030 | 274 |
| 2 | 1.47 | 2.93 | 6.03 | $0.117 | $0.0023 | 248 |

Slower and dearer than the clean set (1.19 s median, $0.0021/call for v4d): longer lines and more reasoning even at
minimal (un10 spent 617 reasoning tokens). The slow tail is the garbled and run-on lines (un10 6.5 s, pt17 4.8 s).

## The ten most instructive failures (raw output)

1. **pc01** "ok so um, what I'm hearing is, yeah, the second violins, that whole passage, let's say from thirty,
   thirty-ish, it's just too much, bring it down" (both runs) → `{"position": "range", "bar_from": 30, "bar_to":
   null, "audience": ["part:Violin II"], "kind": "dynamic", "text": "Softer from 30", …, "confidence": 0.8}` (run 2
   0.75). The buried instruction was found; but `range` with null `bar_to` means "to the end" in v4, so the card
   would span 30–240. **Prompt rule** (v4 has no wording for "from X" with no end; arguably harmless for a dynamic).
2. **pc16** "At 120 the sopranos are just drowning everyone, it's a wall of sound." (run 1) → `{"none": true,
   "confidence": 0.8}`; run 2: Soprano, bar 120, "Softer at bar 120", 0.65. A complaint with no named mark read as
   chat. **Spark reasoning**, on the edge (the two runs split).
3. **pt17** "okay second violins 80 to 84 softer and then the violas at 85 come in strong forte and everybody else
   just wait" (run 1) → the two right marks (0.9 each) plus `{"position": "bar", "bar_from": 85, "audience":
   ["part:Violin I", "part:Violin II", "part:Cello"], "kind": "text", "text": "Wait at 85", "confidence": 0.7}`. The
   v4d exclusion rule fired on a remark about who rests. **Prompt rule** (ground truth arguable: some librarians
   would pencil the rest).
4. **un03** "tenors bar 2 forty accent" (both) → `{"position": "bar", "bar_from": 240, "audience": ["part:Tenor"],
   "kind": "marking", "text": "Accent at bar 240", "confidence": 0.9}`. 240 is the likeliest reading and the last
   bar of the book, but the transcript cannot settle 2, 40 or 240 and it came in at the 0.9 gate. **Ground truth
   arguable**; the confidence is the failure.
5. **pt02** "bar 33 you're sharp on the high G" (Inès dropped; both) → ensemble, bar 33, "In tune high G at bar
   33", 0.85 / 0.75. Fields right for what the text supports; the text writes the remedy and loses "sharp". **Prompt
   rule** (stand-text wording; the clean set's m01, s01, s09 did the same) on top of **STT noise** (lost addressee).
6. **pt12** "base at 200 you're coming in early" (both) → Bass, bar 200, "Entry at bar 200", 0.85. "base" =
   basses recovered; "early" lost, so the card says nothing. **Prompt rule** (same remedy/remark pattern).
7. **un02** "that bar again, softer" (both) → `{"none": true, "confidence": 0.6}`. A real instruction with no
   place, dropped silently; accepted by the set, but a librarian would ask "which bar?". **Pipeline**: the low
   none-confidence is the only trace of it.
8. **un04** "the cello the bar the thirty the uh fermenta no the other one" (both) → `{"none": true, "confidence":
   0.65}` / 0.6. Same as 7: "cello, bar 30, something" was recoverable as a question. **STT noise too severe** for a
   mark; **pipeline** for the ask.
9. **pc14** "Concertmaster, up bow at 9." (both) → ensemble, "Concertmaster up bow at bar 9", 0.85 / 0.65.
   Accepted, but every stand gets an up bow card the admin has to re-address; v4d's roster rule ("a name not in
   the score facts → ensemble") is applied literally to a role that names the Violin I desk. **Prompt rule**.
10. **un10** "base is a piano tuna at for tea" → run 1 `Bass, bar 43, "p at 43", 0.35`, run 2 `Bass, bar 40,
    "p at bar 40", 0.4`. The right behaviour (a low card), but bar 43 out of "for tea" shows what minimal does when
    it guesses; the runs disagree on the bar. **STT noise too severe**; the confidence did its job.

## What would help most (not applied)

1. **Stand text: write the remark, not the remedy.** Add to the text rule: "keep what the speaker said is wrong
   (sharp, flat, early, late, rushing) in the text; add the fix only beside it ('Sharp on high G, bar 33')".
   Evidence: pt02 and pt12 in both runs are every stand-text miss on a produced mark here, and m01, s01, s09
   did the same in the clean set; every instance passes ≥ 0.8. It is the one failure mode that recurs across both sets and that the
   confidence does not catch.
2. **Turn a low-confidence none into an ask, and keep auto-apply at ≥ 0.95 (or strictly > 0.9).** In always-on, a
   `{"none": true}` with confidence below 0.7 should become a "did you want something written?" card with the
   quote. Evidence: un02 and un04 (4/4 runs) are the only nones below 0.7; all 10 nones on the "none" cases were
   0.8–0.95 (and 0.9–0.99 on the clean set's 30 non-instructions), so this costs no false cards here.
   For auto-apply: 0.9 let un03 through in both runs at exactly 0.9; ≥ 0.95 had 0 wrong in both runs here and on
   the clean set, but covers only a quarter of messy instructions, and 21 marks crossed a threshold between runs.
3. **Two rule edits for places and roles.** "'From X' with no end and no 'to the end' is a mark at bar X
   (position bar)" (pc01, both runs). "A role that names a desk (concertmaster, leader, principal cello) is that
   part" (pc14, both runs ensemble). Smaller, and pc01 is arguably harmless for a dynamic.

## Caveats

- I wrote the set and its ground truth knowing v4d's rules, the roster and the clean results; the STT noise is my
  imitation of Voice Transcribe, not its output. The lines are messier than the clean set, but Spark still got
  92–98% of them; real recorded speech (CK's 40 takes: 21/26 base at v4d) remains the harder and more honest test,
  because there the transcript itself is wrong in ways one cannot write in.
- 40 instructions and two runs: one case is 2.5 points. The run-to-run differences (pc16, pt17) are the kind of
  spread the clean set's repeats showed for n16 and v15.
- Three ground-truth entries were tightened after the first look (Set-up); the numbers before the edits are
  given there.

## Spend

**$0.267** of the $2 cap, 100 Spark calls in `api/experiments/voice_text/messy/spend.jsonl` (run 1 $0.150, run 2
$0.117). No speech-to-text calls.
