# 013 Text eval: transcript text to Muse Spark to marks

Status: experiment (2026-10-30; v4d fix and re-run the same day, below; v4d is now the app prompt). | Meta model: Muse Spark 1.3 only
(`/v1/chat/completions`, streamed). No speech-to-text: the transcript is typed text.

The question: with the speech half taken out, how well does the v4c prompt at effort **minimal** (the always-on
recommendation, `013-always-on.md`) turn what a conductor says into the right mark, and how much is Spark's
`confidence` worth as an auto-apply gate?

Files: `api/experiments/voice_text/` — `cases.py` (the set and its ground truth; `set.jsonl` is the same as data),
`run.py` (calls and code scoring), `report.py` (the tables below), `results/raw_<effort>.json` (every reply),
`results/score_<effort>.json` (every case scored), `spend.jsonl` (every call). Local data only; Supabase not touched.

## Set-up

- **Set**: 130 lines written for this test, none taken from `script.csv`: 100 instructions (110 expected marks) and
  30 non-instructions. Categories: dynamics 9, articulation 8, tempo 8, cuts and jumps 8, bowing and breathing 8,
  balance 7, rehearsal-flow marks 5, rehearsal letters 6, relative references 6, numbers as words 4, named members 6,
  multi-instruction 10, hedged speech 6, speech-to-text noise 9; non-instructions 30 (counting in, "from the top"
  said casually, start points with a bar or letter, logistics, questions naming a part or a mark, jokes with "cut",
  talking about an instruction without giving it). Difficulty: 34 easy, 49 medium, 17 hard (instructions).
- **Score facts** as the eval: parts Violin I, Violin II, Viola, Cello, Soprano, Alto, Tenor, Bass; members Lin,
  Inès; bars 1–240; letters A–F with no letter-to-bar map. So letters, "the bar before C", "two after the key change",
  the double bar and the coda are `position: mark` with null bars (the fixture cannot resolve them); "two bars after
  bar forty" is arithmetic and expects bar 42.
- **Prompt**: v4c exactly as in the always-on run (`voice_stream.spark_lat.build("v4c", …)`): v4 rules, the eval's
  first eight worked examples (nothing to hold out, so they equal the app's `EXAMPLES`), the confidence rule and
  field. One call per case, `reasoning_effort` minimal, then the same at low; 8k output budget, 6 in parallel.
- **Scoring (code, no judge)**: the reply goes through the app's `parse_answer` and `checked_marks` (a refused mark
  is a miss). Expected marks are paired one-to-one with produced ones (best assignment). Fields exact: position,
  bars (`bar_from` and `bar_to`; a one-bar mark's null `bar_to` = `bar_from`; "to the end" = null or 240), audience
  as a set, kind. A case is **right** when every expected mark has all four right and nothing extra was produced.
  Ground truth is strict on the v4 rules and accepts more than one value only where the taxonomy is open (slur:
  bowing or marking; balance: dynamic or text; "the last bar": global or bar 240; "after 60 jump to 72": 60/61 to
  71/72) or an answer can be split two ways (one mark covering two places for one audience, as v4 says, or two
  marks; "Inès and the violas": one mark or two). **Stand text** is a lenient match: the case's key words (with
  pizz./cresc./rit./f/p… folded) must appear; misses are listed for CK below.
- **Roster gaps and lost addressees** (l04 "brass", m06 "Marco", s01 and s08 with the addressee dropped as ASR
  does): the ground truth is what the text supports inside the roster (ensemble, or the part still named), with the
  speaker's intended audience recorded in `cases.py`.

## Results

| effort | cases fully right | + stand text | field position | field bars | field audience | field kind | field text | field core | false positives | false negatives | median s | p90 s | cost | $/call | out tok |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| minimal | 95/100 | 92/100 | 107/110 | 107/110 | 105/110 | 107/110 | 103/110 | 105/110 | 0/30 | 3/100 | 1.23 | 2.31 | $0.266 | $0.0020 | 224 |
| low | 94/100 | 91/100 | 107/110 | 107/110 | 104/110 | 107/110 | 103/110 | 104/110 | 0/30 | 3/100 | 1.86 | 3.19 | $0.406 | $0.0031 | 476 |

(Fields are counted over the 110 expected marks; "core" = position, bars, audience and kind all right. Cost and
latency are per call, all 130 cases.)

Per category (right = cases fully right; bars/aud/kind counted over expected marks):

| category | n | min right | min +text | min bars/aud/kind | low right | low +text | low bars/aud/kind |
|---|---|---|---|---|---|---|---|
| dynamics | 9 | 9 | 9 | 9/9/9 of 9 | 9 | 9 | 9/9/9 of 9 |
| articulation | 8 | 8 | 8 | 8/8/8 of 8 | 8 | 8 | 8/8/8 of 8 |
| tempo | 8 | 8 | 8 | 8/8/8 of 8 | 8 | 8 | 8/8/8 of 8 |
| cut | 8 | 8 | 8 | 8/8/8 of 8 | 8 | 8 | 8/8/8 of 8 |
| bowing_breath | 8 | 8 | 8 | 8/8/8 of 8 | 8 | 8 | 8/8/8 of 8 |
| balance | 7 | 5 | 5 | 8/6/8 of 8 | 5 | 5 | 8/6/8 of 8 |
| flow | 5 | 2 | 2 | 2/2/2 of 5 | 3 | 3 | 3/3/3 of 5 |
| letter | 6 | 6 | 6 | 6/6/6 of 6 | 6 | 6 | 6/6/6 of 6 |
| relative | 6 | 6 | 6 | 6/6/6 of 6 | 6 | 6 | 6/6/6 of 6 |
| words | 4 | 4 | 4 | 4/4/4 of 4 | 4 | 4 | 4/4/4 of 4 |
| member | 6 | 6 | 5 | 7/7/7 of 7 | 5 | 4 | 6/6/6 of 7 |
| multi | 10 | 10 | 10 | 18/18/18 of 18 | 10 | 10 | 18/18/18 of 18 |
| hedged | 6 | 6 | 6 | 6/6/6 of 6 | 6 | 6 | 6/6/6 of 6 |
| stt_noise | 9 | 9 | 7 | 9/9/9 of 9 | 8 | 6 | 9/8/9 of 9 |

| difficulty | n | minimal right | low right |
|---|---|---|---|
| easy | 34 | 34 | 34 |
| medium | 49 | 47 | 47 |
| hard | 17 | 14 | 13 |

| audience (first answer) | n | minimal right | low right |
|---|---|---|---|
| everyone | 33 | 29 | 29 |
| part(s) | 60 | 59 | 58 |
| named member | 7 | 7 | 7 |

### Non-instructions and misses

- **False positives: 0/30 at both efforts.** Every non-instruction came back `{"none": true}` with confidence 0.9–0.99,
  including the traps: "Should we cut bars 42 to 48? Let me think about it", "Last week we had the cellos pizz at 30,
  that's still fine", the viola joke with "cut", "If I say cut, I mean stop playing", "Is the fermata at the end in
  your parts", "Okay, go back to the pickup of 30", "Where were we, bar sixty-two?".
- **False negatives: 3/100 at each effort**, and they are the same rule: future start points. Minimal missed f01 "Next
  time we start at bar twelve, write that in", f02 "For tomorrow, we'll begin at letter D, put a mark there" and f03
  "Start at bar 12 next time"; low got f02 and missed f01, f03 (and lost m06 to the check, below). Each was a confident
  none (0.8–0.95), so in always-on they would vanish silently. Even an explicit "write that in" did not override v4's
  "telling the players where to start playing … is not a mark".
- **Refused by `checked_marks`**: one, low's m06 `member:Marco` (not a member). Minimal put Marco's mark on the
  ensemble at 0.6, which is the right card for the admin to re-address.

### Multi-instruction

| effort | multi right | marks produced per case (answer 0 = first listed) |
|---|---|---|
| minimal | 10/10 | mu01: 2 mark(s), answer 0, mu02: 2 mark(s), answer 0, mu03: 2 mark(s), answer 0, mu04: 2 mark(s), answer 0, mu05: 2 mark(s), answer 0, mu06: 2 mark(s), answer 0, mu07: 2 mark(s), answer 1, mu08: 2 mark(s), answer 0, mu09: 1 mark(s), answer 0, mu10: 1 mark(s), answer 0 |
| low | 10/10 | mu01: 2 mark(s), answer 0, mu02: 2 mark(s), answer 0, mu03: 2 mark(s), answer 0, mu04: 2 mark(s), answer 0, mu05: 2 mark(s), answer 0, mu06: 2 mark(s), answer 0, mu07: 2 mark(s), answer 1, mu08: 2 mark(s), answer 0, mu09: 1 mark(s), answer 0, mu10: 1 mark(s), answer 0 |

All ten right at both efforts, and Spark made the same split choices both times: different audiences or different
kinds → separate marks (mu01–mu08, including "cut 20 to 24, and at 25 start piano"); one audience and one kind at two
places → one mark covering them (mu09 pizz 30 / arco 34 as range 30–34; mu10 cresc 60–64 / sub. p 65 as 60–65; t04 rit
88 / a tempo 90 as 88–90), as the v4 rule says. "Seconds … and Lin, you too" and "Inès and the violas" came out as one
mark per audience. Note the one-mark-for-two-places answer puts both instructions on one card spanning 30–34: the
ghost covers bars where nothing changes.

### Confidence

**minimal**

| group | n | min | median | max | values (value: count) |
|---|---|---|---|---|---|
| right marks | 105 | 0.6 | 0.95 | 0.98 | 0.6: 1, 0.65: 1, 0.7: 2, 0.75: 1, 0.8: 2, 0.85: 6, 0.9: 17, 0.92: 1, 0.93: 1, 0.95: 63, 0.97: 6, 0.98: 4 |
| wrong marks | 2 | 0.65 | 0.775 | 0.9 | 0.65: 1, 0.9: 1 |
| marks on non-instructions | 0 |  |  |  |  |
| none on non-instructions (none-confidence) | 30 | 0.9 | 0.95 | 0.99 | 0.9: 2, 0.95: 20, 0.98: 5, 0.99: 3 |
| none on instructions (missed; none-confidence) | 3 | 0.9 | 0.9 | 0.95 | 0.9: 2, 0.95: 1 |

| threshold | marks auto-applied | of those wrong | precision | instructions wholly auto-applied | of those not fully right |
|---|---|---|---|---|---|
| ≥ 0.8 | 101/107 | 1 | 0.990 | 91/100 | 1 |
| ≥ 0.9 | 93/107 | 1 | 0.989 | 83/100 | 1 |
| ≥ 0.95 | 73/107 | 0 | 1.000 | 64/100 | 0 |

**low**

| group | n | min | median | max | values (value: count) |
|---|---|---|---|---|---|
| right marks | 104 | 0.7 | 0.95 | 0.99 | 0.7: 2, 0.8: 3, 0.85: 3, 0.9: 15, 0.92: 1, 0.95: 57, 0.97: 5, 0.98: 16, 0.99: 2 |
| wrong marks | 3 | 0.65 | 0.85 | 0.88 | 0.65: 1, 0.85: 1, 0.88: 1 |
| marks on non-instructions | 0 |  |  |  |  |
| none on non-instructions (none-confidence) | 30 | 0.9 | 0.96 | 0.99 | 0.9: 3, 0.95: 12, 0.97: 1, 0.98: 5, 0.99: 9 |
| none on instructions (missed; none-confidence) | 2 | 0.8 | 0.875 | 0.95 | 0.8: 1, 0.95: 1 |

| threshold | marks auto-applied | of those wrong | precision | instructions wholly auto-applied | of those not fully right |
|---|---|---|---|---|---|
| ≥ 0.8 | 104/107 | 2 | 0.981 | 94/100 | 2 |
| ≥ 0.9 | 96/107 | 0 | 1.000 | 86/100 | 0 |
| ≥ 0.95 | 80/107 | 0 | 1.000 | 71/100 | 0 |

"Marks auto-applied" counts every checked mark at or above the threshold, on instructions and non-instructions alike;
"wrong" is a mark not fully right on position, bars, audience and kind (stand text not counted). On clean text the
0.95 tier is clean in both runs (73 and 80 marks, none wrong) and covers about two thirds of instructions, against
11/35 on CK's recorded takes. The 0.9 tier lets through l03's "everyone else" mark at minimal. The wrong marks sit at
0.65–0.9, but so do 30 right ones; the signal is still one-sided (low confidence does not mean wrong). The stand-text
inversions below (s09 0.65, s01 0.7) did get low confidence, which is useful: Spark seems to know when it is
rewriting what was said.

Cases scored differently by minimal and low: f02 (minimal wrong, low right), m06 (minimal right, low wrong), s05 (minimal right, low wrong).

### Stand text disagreements (for CK)

The lenient key match passed 103/110 marks at each effort. Every miss, with what Spark wrote:

| effort | id | said | reference | Spark's stand text |
|---|---|---|---|---|
| minimal | l04 | Too much brass at sixty. | Less brass at 60 | Softer at bar 60 |
| minimal | m01 | Lin, bar 64, you're sharp on the F. | F is sharp, bar 64 | Lower F at bar 64 |
| minimal | s01 | bar fifteen is flat, listen to the viola there. | Flat at 15, tune to viola | In tune at bar 15, listen to Viola |
| minimal | s09 | Lynn, bar eighty, you're late. | Late at 80 | On time at bar 80 |
| low | l04 | Too much brass at sixty. | Less brass at 60 | softer at bar 60 |
| low | m01 | Lin, bar 64, you're sharp on the F. | F is sharp, bar 64 | F in tune at bar 64 |
| low | s01 | bar fifteen is flat, listen to the viola there. | Flat at 15, tune to viola | Listen to viola at bar 15 |
| low | s09 | Lynn, bar eighty, you're late. | Late at 80 | Entry at bar 80 |

The structured fields of all but l04 are right. The pattern: Spark writes the **remedy**, not the remark ("you're
late" → "On time at bar 80"; "is flat" → "In tune at bar 15"; "sharp on the F" → "Lower F"). "Lower F" is what a
player would pencil; "In tune" and "On time" lose the information. CK's call whether remedy wording is wanted.

## The ten most instructive failures (raw output)

1. **f03 "Start at bar 12 next time."** (minimal and low) → `{"none": true, "confidence": 0.95}`. A future start
   point read as a start point now; a confident silent miss.
2. **f01 "Next time we start at bar twelve, write that in."** (minimal and low) → `{"none": true, "confidence": 0.9}`
   (low 0.8). An explicit "write that in" loses to the start-point rule.
3. **f02 "For tomorrow, we'll begin at letter D, put a mark there."** (minimal) → `{"none": true, "confidence": 0.9}`.
   Low got it right (mark, ensemble, "Start at letter D"): the case is on the edge.
4. **l04 "Too much brass at sixty."** (both) → `[{"position": "bar", "bar_from": 60, "bar_to": 60, "audience":
   ["part:Bass"], "kind": "dynamic", "text": "Softer at bar 60", "quote": "Too much brass at sixty.", "confidence":
   0.65}]`. The mishearing rule ("a word that sounds like a part … is that part") turns a section the book does not
   have into the nearest-sounding part, and drops "brass" from the text.
5. **l03 "Bring out the altos at bar 12, everyone else lighter."** (both) → Alto "Bring out at bar 12" (0.9), right;
   and "Lighter at bar 12" for `["part:Violin I", "part:Violin II", "part:Viola", "part:Cello", "part:Soprano",
   "part:Tenor", "part:Bass"]` (0.9). v4 says an exclusion means the other parts *of its group* (S, T, B); Spark took
   "everyone else" literally across the whole book. In a book with only one group the two readings agree.
6. **s05 "accept the basses, bar 120, forte."** (low) → audience `["part:Violin I", "part:Violin II", "part:Viola",
   "part:Cello", "part:Soprano", "part:Alto", "part:Tenor"]`, 0.88. "accept" = except was recovered; the group scope
   was not. Minimal answered S, A, T (right). Same weakness as 5.
7. **m06 "Marco, bar 20, softer."** (low) → `["member:Marco"]`, 0.85, refused by the check, so no card. Minimal gave
   ensemble at 0.6 (right). A name outside the roster should fall to ensemble with the name kept in the text.
8. **s09 "Lynn, bar eighty, you're late."** (minimal) → `member:Lin` (right: "Lynn" resolved), text "On time at bar
   80", confidence 0.65. Low wrote "Entry at bar 80". Fields right, text inverted.
9. **s01 "bar fifteen is flat, listen to the viola there."** (addressee dropped as ASR does; minimal) → ensemble
   (all the text allows), text "In tune at bar 15, listen to Viola", 0.7. Right by the text, wrong by intent (Lin);
   the low confidence is the useful part.
10. **m01 "Lin, bar 64, you're sharp on the F."** (minimal) → `member:Lin`, "Lower F at bar 64", 0.9 (low: "F in tune
    at bar 64", 0.85). Remedy wording; probably acceptable, listed so CK can say.

## Readings

- **On clean text the second half is not the bottleneck.** 95/100 cases fully right at minimal (94 at low), every
  easy case right, 0 false positives on 30 non-instructions, all ten multi-instruction lines right, numbers as words,
  hedges, self-corrections inside numbers ("ninety, nine, sorry, nineteen"), "bar to" = 2, "for tea" = 40, "right in
  a fermenta" = fermata, "Chelos", "Violets", "Lynn" all recovered. The recorded eval's misses (22/26) were mostly
  the transcript (dropped addressees), and this run agrees: the losses left are prompt rules, not reading.
- **Minimal is as accurate as low** (95 vs 94, the three disagreements split both ways) at 1.23 s against 1.86 s
  median, 2.31 vs 3.19 s p90, and $0.0020 against $0.0031 a call. Keep minimal.
- **Two prompt weaknesses, both rule wording**: (1) the start-point rule swallows rehearsal-flow marks ("next time",
  "tomorrow", even "write that in"); (2) roster scope: the mishearing rule maps an unknown section to a sound-alike
  part ("brass" → Bass) or an unknown name to a member the check refuses, and "everyone else" is read across the
  whole book instead of the excluded part's group. Suggested fixes (not run): add to the first rule "A start point
  for a later run ('next time', 'tomorrow') or anything the speaker asks to be written or marked is a mark"; add to
  the mishearing rule "A section or name that is not in the score facts and does not sound like one is not a part:
  use ensemble and keep the word in the text"; and say "everyone else" means the other parts of the named part's
  group.
- **Confidence**: the 0.95 auto-apply tier was clean here (0 wrong of 73 at minimal, 0 of 80 at low) and is the same
  answer as the recorded run's 21/21; 0.9 let one wrong mark through at minimal. Confident none (0.9–0.95) on the
  three missed flow marks means the gate cannot rescue a rule-level miss.


## Round two: v4d (the two fixes), re-run (2026-10-30)

CK: "fix and re-run". `api/experiments/voice_text/prompt_v4d.py` = v4c with three rule edits (wording below; the
new examples avoid this set's words: no "brass", no "Marco"). All 130 cases at effort minimal (`run.py call minimal
v4d`), then CK's 40 recorded lines and the 23 negatives on their realtime ENDPOINTING transcripts (`regress.py`,
scored exactly as `voice_stream.spark_lat full`), then 5 repeats per prompt of every case that changed
(`repeat.py`). The diff to `api/app/librarian/voice_prompt.py` is at the end of this section (applied after this run).

### Text set, v4c vs v4d (minimal, one run each)

| | v4c | v4d |
|---|---|---|
| cases fully right (of 100) | 95 | **99** |
| + stand text | 92 | 96 |
| fields position / bars / audience / kind (of 110) | 107 / 107 / 105 / 107 | **110 / 110 / 110 / 110** |
| false positives (of 30) | 0 | 1 (n16) |
| false negatives | 3 (f01, f02, f03) | 0 |
| flow marks (of 5) | 2 | 4 (f04 split in two) |
| balance (of 7) | 5 | **7** |
| roster cases l03, l04, m06, s05 | 2 of 4 | **4 of 4** |
| marks ≥ 0.8 auto-applied / wrong | 101 / 1 | 109 / 2 |
| marks ≥ 0.9 auto-applied / wrong | 93 / 1 | 101 / 2 |
| marks ≥ 0.95 auto-applied / wrong | 73 / 0 | 81 / 1 (f04's duplicate) |
| median / p90 s | 1.23 / 2.31 | 1.19 / 1.96 |
| cost (130 calls) | $0.266 | $0.268 |

What the fixes did, raw: f01, f03 → `{"position": "bar", "bar_from": 12, "bar_to": 12, "audience": ["ensemble"],
"kind": "text", "text": "Start here next time", …, "confidence": 0.95}`; f02 → mark, "Start here next time at D";
l03 "everyone else" → `["part:Soprano", "part:Tenor", "part:Bass"]`; l04 → ensemble, "Brass softer at 60", 0.85
(was `part:Bass` at 0.65); m06 → ensemble, "Marco softer at 20", 0.9; s05 → S, A, T.

**Got worse (single run):**

- **n16** "Last week we had the cellos pizz at 30, that's still fine." → `[{"position": "bar", "bar_from": 30,
  "bar_to": 30, "audience": ["part:Cello"], "kind": "marking", "text": "pizz. at bar 30", "quote": "Last week we had
  the cellos pizz at 30, that's still fine.", "confidence": 0.9}]` (v4c: none, 0.9).
- **f04** "From 57 next time, and keep it light." → two marks for one audience at one bar: `"Start here next time at
  bar 57"` (0.95) and `"Keep it light at bar 57"` (0.9). Both are in the right place, but v4 asks for one mark per
  audience, so it counts as an extra. That extra is the one "wrong" mark at ≥ 0.95.

**Repeats (5 calls per prompt, minimal, `results/repeats.json`)** show both are noise, not the fix:

| case | v4c right | v4d right |
|---|---|---|
| n16 (non-instruction) | **3/5** (2 false positives) | 5/5 |
| f04 | 5/5 | 5/5 |
| v15 "Stop the cello, bar 50, pizzicato" (recorded, below) | 4/5 | 5/5 |

n16 is a weak spot of v4c too: its first run's none was luck.

### Real speech regression: CK's 40 recorded lines + 23 negatives (realtime transcripts, minimal)

| prompt | base 26 all fields | retakes 9 all fields | negatives no mark | marks ≥ 0.9 (wrong) | marks ≥ 0.95 (wrong) | median s | p90 s | $/call |
|---|---|---|---|---|---|---|---|---|
| v4c (2026-10-30, `voice_stream/results/full_v4c_minimal.json`) | 22/26 | 7/9 | 23/23 | 22 (1 wrong) | 11 (0 wrong) | 1.29 | 1.98 | $0.0025 |
| v4d (`voice_text/results/full_v4d_minimal.json`) | 21/26 | 7/9 | 23/23 | 22 (0 wrong) | 10 (0 wrong) | 1.25 | 2.28 | $0.0018 |

The one line that changed: **v15** "Stop the cello, bar 50, pizzicato," → `[{"position": "bar", "bar_from": 50,
"bar_to": 50, "audience": ["part:Cello"], "kind": "marking", "text": "pizz. at bar 50", "quote": "Stop the cello, bar
50, pizzicato,", "confidence": 0.88}]`: "stop" was not read as "except". In the repeats v4d got it 5/5 and v4c 4/5,
so this is the known spread (about one line in 26 a run), not a regression. No new false positive on real negatives;
the other 34 instructions scored the same.

### Verdict

v4d fixes all three flow misses and all four roster cases, and loses nothing that repeats confirm. Recommend it
replace v4 in the app (with the confidence field, i.e. as v4c→v4d, when the always-on path is built; for
push-to-talk today, the same three rule edits apply to v4). Caveat: the set that motivated the fixes is the set that
scored them; the real-speech run is the independent check, and it held.

### Diff for `api/app/librarian/voice_prompt.py` (applied 2026-10-30, CK: "apply and commit")

```diff
@@ RULES
-  is a mark at that bar. Telling a part where it comes in (its entry) is a mark.
+  is a mark at that bar. Telling a part where it comes in (its entry) is a mark. A start point for a later run ("next time",
+  "tomorrow", "after the break") is a mark at that place (text "Start here next time"), and so is anything the
+  speaker asks to have written or marked.
@@
-  Violin II, fiddles = both violin parts. When the speaker excludes a part, list every other part of its group
-  (strings: Violin I, Violin II, Viola, Cello; voices: Soprano, Alto, Tenor, Bass). A player addressed by name is
+  Violin II, fiddles = both violin parts. When the speaker excludes a part ("everyone except X", "everyone else",
+  "all but X"), list every other part of X's group only, never parts of the other group (strings: Violin I,
+  Violin II, Viola, Cello; voices: Soprano, Alto, Tenor, Bass). A player addressed by name is
@@
-  part may be "except". Numbers are usually right."""
+  part may be "except". Numbers are usually right. A section or a name that is not in the score facts (e.g.
+  "the winds", "percussion", a player not in Members) is not a part or member: use "ensemble" and keep that word in
+  the text ("Winds softer at 12"), never the nearest-sounding part."""
```

Applying it also needs `RULES_V4` in `api/experiments/voice/prompts.py` brought in step (it asserts equality with
the app's rules at import) and a test in `tests/test_voice_prompt.py` for the new wording.

## Caveats

- I wrote the set and its ground truth knowing the v4 rules and the fixture's roster, and the sentences are clean,
  well-formed conductor speech; real transcripts are messier (the recorded eval's WER was 0.15–0.18). Read 95/100 as
  the ceiling of the text half, not the pipeline's accuracy.
- One run per effort. The always-on runs saw about one line in 26 of run-to-run spread; here minimal and low
  disagreed on 3/130.
- The stand-text match is lenient key words, not a judge: it can pass a text that misses a nuance (e.g. "cresc. into
  47" for "a little more, like a crescendo") and it flagged "senza vibr." until `vibr` was folded.
- Latency is with 6 calls in parallel from this Mac; the always-on run measured 1.29 s median for v4c minimal on the
  recorded set, in line with 1.23 s here.

## Spend

**$1.118** of the $3 cap, 475 Spark calls in `api/experiments/voice_text/spend.jsonl`: round one $0.672 (v4c minimal
$0.266, low $0.406), round two $0.446 (v4d text set $0.268, recorded regression $0.098, repeats $0.080). No
speech-to-text calls (the regression reuses voice_stream's saved realtime transcripts).
