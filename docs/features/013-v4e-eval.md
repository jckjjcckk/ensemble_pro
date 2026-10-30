# 013 v4e eval: a library of score context for the Spark half

Status: experiment (2026-10-30). | Meta models: Muse Spark 1.3 (`/v1/chat/completions`, streamed, effort minimal);
Muse Voice Transcribe 1.0 realtime (ENDPOINTING) for the keywords part.

Question (CK): how much does giving Spark a "library" of context help the voice-note prompt? Live v4d against v4e =
v4d plus (a) score landmarks with bars, (b) the book's groups, (c) a musical-terms mishearing line; then the one part
only speech can measure, a music glossary in the ASR `keywords`.

Files: `api/experiments/voice_text/messy100/` — `prompts.py` (v4d = the app's `build_prompt` + the confidence field;
v4e built from it by three asserted string edits; `ScoreFactsE`), `cases.py` (the 100 cases, both fixture books;
`set.jsonl` is the same as data), `run.py` (calls, code scoring), `report.py` (the tables below), `clean130.py` (guard
on the clean set), `asr.py` (keywords part), `results/` (every raw reply and score), `spend.jsonl` (every call).
Local data only; Supabase not touched; nothing in `api/app` or `web/src` changed.

## Set-up

- **v4d** is exactly the app prompt (`app.librarian.voice_prompt.build_prompt`) with the always-on confidence rule
  and field added as `voice_stream.spark_lat` v4c does. (It differs from the text eval's v4d builder only in the
  header line "Rules:" vs "Rules (examples here are made up; …):".)
- **v4e** = v4d plus, and nothing else (examples unchanged):
  - (a) `Landmarks:` line in the facts and, at the end of the position rule: when the facts list a landmark with its
    bars, a place named from it resolves to bars and is "bar" or "range"; a landmark not listed stays "mark".
  - (b) `Groups:` line in the facts; the exclusion rule lists the other parts of the widest listed group holding X
    (or the group the speaker names), a soloist alone in its group is excluded from the Orchestra, and a group the
    speaker names is every part listed in it. The hardcoded strings/voices lists are gone from the rule.
  - (c) in the mishearing rule: fermenta/fermata, pizza cutter/pizzicato, retard and oh/ritardando, attempt oh/a
    tempo, spores and oh/sforzando, arc oh/arco, stuck auto/staccato, the visi/divisi, lay gato/legato, coal leg
    no/col legno; "a word that sounds like a musical term is that term".
- **Fixture books.** A = the eval's book (V1, V2, Va, Vc, S, A, T, B; Lin, Inès; bars 1–240; letters A–F) with
  made-up landmarks: **segno 17; double bar after 64; key change at 97 (E-flat major); Adagio (the slow section)
  121–160; Tempo primo 161; To Coda 200; coda 221–240**; groups Strings (V1, V2, Va, Vc), Voices (S, A, T, B).
  B = a piano concerto: Piano + Flute, Oboe, Clarinet, Bassoon, Horn, Trumpet, Timpani, Violin I, Violin II, Viola,
  Cello, Double Bass; Mei, Tomás; bars 1–312; letters A–K; landmarks **key change 75 (F major); double bar after 150;
  Andante (the slow section) 151–210; Allegro (Tempo I) 211; cadenza 268; coda 281–312**; groups Soloist (Piano),
  Orchestra (the other 12), Woodwinds, Brass, Strings (with Double Bass). v4d gets the same parts, members, bars and
  letters, and no landmarks or groups (what the app sends today).
- **Set**: 100 new lines (not the clean 130, not script.csv, not the other agent's 50): terms 25 (12 with a pair
  named in (c), 12 with mangles (c) does not name, e.g. "crash endo", "tenure toe", "con sore dino", "pits", "fur
  mata", "ritter dando", "down bough"; 1 part mangle; several also mangle a part or name: "Chelos and Violets",
  "Second violence", "In-ezz", "timp knee"), landmarks 20 (14 book A, 6 book B), groups 15 (6 A, 9 B), rambling /
  self-correcting / buried 20, dropped addressee or stray player reply 10, unrecoverable 10 (6 truth none; 4 "none
  or an uncertain mark"). Difficulty 1/2/3: 12/62/26. Book A 75, B 25.
- **Ground truth** is what the book means: landmarks resolved to bars, groups to their parts (so v4d, which has
  neither, is scored on what the conductor meant, and the landmark/group cases measure exactly what (a)/(b) add).
  Both answers accepted where two are defensible ("two after the key change" 98 or 99; "from the coda" bar or range;
  pizz/arco at two places as one mark or two; "everyone except the oboe" with or without the piano; a reply
  addressed to two parts as one mark or two). Dropped addressee: truth is ensemble (what the text supports).
- **Scoring**: the text eval's code (`voice_text.run`: app `parse_answer` + `checked_marks` against the case's book,
  best one-to-one pairing, position/bars/audience/kind exact, lenient stand-text keys). Right = every expected mark
  core-right and nothing extra. Two runs per prompt per case, effort minimal, 8k budget, 6 in parallel: 400 calls.

## Results: text set

| run | cases right | + stand text | field position | field bars | field audience | field kind | field text | field core | false positives (none-only) | missed (no mark) | median s | p90 s | cost | $/call | out tok |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| v4d_r1 | 74/100 | 74/100 | 77/98 | 77/98 | 91/98 | 98/98 | 98/98 | 71/98 | 0/6 | 0 | 1.38 | 2.35 | $0.284 | $0.0028 | 307 |
| v4d_r2 | 74/100 | 74/100 | 78/99 | 78/99 | 91/99 | 99/99 | 99/99 | 71/99 | 0/6 | 0 | 1.35 | 2.29 | $0.214 | $0.0021 | 315 |
| v4e_r1 | 99/100 | 99/100 | 98/98 | 97/98 | 98/98 | 98/98 | 98/98 | 97/98 | 0/6 | 0 | 1.20 | 2.23 | $0.346 | $0.0035 | 263 |
| v4e_r2 | 99/100 | 99/100 | 97/97 | 96/97 | 97/97 | 97/97 | 97/97 | 96/97 | 0/6 | 0 | 1.23 | 2.02 | $0.243 | $0.0024 | 269 |

(Fields over the expected marks of each run; "false positives" over the 6 truth-none cases; the 4 "none or mark"
cases are right either way and listed below.)

| category | n | v4d_r1 | v4d_r2 | v4e_r1 | v4e_r2 |
|---|---|---|---|---|---|
| terms | 25 | 25 | 25 | 25 | 25 |
| landmark | 20 | 0 | 0 | 19 | 19 |
| group | 15 | 10 | 10 | 15 | 15 |
| ramble | 20 | 19 | 19 | 20 | 20 |
| addressee | 10 | 10 | 10 | 10 | 10 |
| unrecoverable | 10 | 10 | 10 | 10 | 10 |

| difficulty | n | v4d_r1 | v4d_r2 | v4e_r1 | v4e_r2 |
|---|---|---|---|---|---|
| 1 | 12 | 7 | 8 | 12 | 12 |
| 2 | 62 | 49 | 48 | 61 | 61 |
| 3 | 26 | 18 | 18 | 26 | 26 |

| book | n | v4d_r1 | v4d_r2 | v4e_r1 | v4e_r2 |
|---|---|---|---|---|---|
| A | 75 | 61 | 61 | 75 | 75 |
| B | 25 | 13 | 13 | 24 | 24 |

| term cases | n | v4d_r1 | v4d_r2 | v4e_r1 | v4e_r2 |
|---|---|---|---|---|---|
| listed | 12 | 12 | 12 | 12 | 12 |
| unlisted | 12 | 12 | 12 | 12 | 12 |
| part | 1 | 1 | 1 | 1 | 1 |

Landmark cases where the answer is wrong only by being left unplaced (position mark, null bars, audience and kind right): v4d_r1 19/20, v4d_r2 19/20, v4e_r1 0/20, v4e_r2 0/20

So v4d's landmark answers are nearly all *safe*: right audience and kind, `position: mark`, which the app returns in
`result.unplaced` for the admin to put on a bar by hand. v4e places them. The one v4d landmark case that is not
safe is lm16 ("Strings, two after the key change, pizz." in the concerto: v4d put it on the ensemble, the piano
included).

### Run-to-run agreement

| prompt | same right/wrong | identical marks (fields) | right both runs | flips |
|---|---|---|---|---|
| v4d | 98/100 | 92/100 | 73 | g07, g13 |
| v4e | 100/100 | 98/100 | 99 | none |

v4d's flips are both concerto exclusions: g07 "Everyone except the piano" (r1: winds, brass and timpani only, the
strings dropped; r2 right) and g13 "Everyone except the oboe" (r2: Flute, Clarinet, Bassoon only).

### Where v4e helped

- **Landmarks (a): 0/20 → 19/20 both runs.** e.g. lm01 "two after the key change" → bar 99; lm02 "the bar before the
  double bar" → 64; lm04 "in the slow section" → range 121–160; lm11 "From the To Coda sign we jump straight to the
  coda" → cut 201–220; lm07 "three bars before the coda" → 218; lm18 "Mei, at the cadenza" → 268.
- **Concerto groups (b): book B group cases 4/9 → 9/9 (both runs)**, plus r19 ("the whole orchestra, not you Mei"). v4d,
  with no groups listed: "Orchestra" / "Woodwinds" / "Everybody but the soloist" → `ensemble` (the roster rule: a
  section not in the facts is the ensemble), so the soloist gets the orchestra's mf, dim. and sub. p; "Brass and
  timpani … accent" → ensemble; the exclusions above are unstable. Book A groups were already 6/6 for both (the
  hardcoded strings/voices groups match book A).
- **Terms (c): no measurable effect on text.** v4d was already 25/25, listed and unlisted mangles alike ("crash
  endo" → cresc., "tenure toe" → ten., "pits" → pizz., "fur mata", "down bough", "Second violence"). The current
  rule ("a word that sounds like a part … is that part") plus Spark's own knowledge already covers it.
- Rambling, addressee and unrecoverable: equal (one ramble case is r19, a group case at heart).

### Where v4e hurt

v4e better than v4d (right in more runs): 26 cases ['lm01', 'lm02', 'lm03', 'lm04', 'lm05', 'lm06', 'lm07', 'lm08', 'lm09', 'lm10', 'lm11', 'lm12', 'lm13', 'lm14', 'lm16', 'lm17', 'lm18', 'lm19', 'lm20', 'g07', 'g08', 'g09', 'g11', 'g12', 'g13', 'r19']

v4e worse than v4d: 0 cases []

wrong in some run for both: ['lm15']

- lm15 v4d_r1: `[{"position": "mark", "bar_from": null, "bar_to": null, "audience": ["part:Piano"], "kind": "text", "text": "rit. bar before double bar", "quote": "Piano, the bar before the double bar, ritardando, take your time.", "confidence": 0.9}]`
- lm15 v4e_r1: `[{"position": "bar", "bar_from": 149, "bar_to": 149, "audience": ["part:Piano"], "kind": "text", "text": "rit. at bar 149", "quote": "Piano, the bar before the double bar, ritardando, take your time.", "confidence": 0.95}]`
- lm15 v4e_r2: `[{"position": "bar", "bar_from": 149, "bar_to": 149, "audience": ["part:Piano"], "kind": "text", "text": "rit. at bar 149", "quote": "Piano, the bar before the double bar, ritardando, take your time.", "confidence": 0.95}]`

- **lm15 is the only v4e miss and it is v4e's only kind of new error: a confident off-by-one resolution.** With
  "double bar after bar 150" listed, "the bar before the double bar" came back bar 149 at 0.95 both runs (book A's
  identical phrasing, "double bar after bar 64", resolved to 64). The fix is in the fact's wording, not the rule:
  render a double bar as "double bar between bars 150 and 151" (or "at the end of bar 150"). Not re-run.
- No case is worse for v4e than v4d. Unrecoverable: no false positive on the 6 truth-none cases for either prompt;
  u02 "bar forty or fourteen" became a bar-14 mark at 0.45–0.55 for both (below any gate).

### Unrecoverable cases

| id | truth | said | v4d_r1 | v4d_r2 | v4e_r1 | v4e_r2 |
|---|---|---|---|---|---|---|
| u01 | none or mark | uh the the thing at the um you know there softer | none 0.85 | none 0.9 | none 0.85 | none 0.6 |
| u02 | none or mark | Violas bar forty or fourteen whatever, piano | bar 14 Viola "p at bar 14" 0.55 | bar 14 Viola "p at bar 14" 0.5 | bar 14 Viola "p at bar 14" 0.45 | bar 14 Viola "p at bar 14" 0.55 |
| u03 | none | and, bar, the, and | none 0.95 | none 0.95 | none 0.95 | none 0.95 |
| u04 | none | Cellos, at bar, um. | none 0.95 | none 0.95 | none 0.95 | none 0.95 |
| u05 | none | Everyone, the bar before the double bar, no wait, there are two double bars in my score, never mind. | none 0.9 | none 0.95 | none 0.95 | none 0.95 |
| u06 | none | Sopranos, can you, no, forget it, let's just sing. | none 0.95 | none 0.95 | none 0.95 | none 0.95 |
| u07 | none or mark | Bar eighty, the, the, the firsts, lighter, the other one. | bar 80 Violin I "lighter at 80" 0.65 | bar 80 Violin I "lighter at bar 80" 0.75 | bar 80 Violin I "Lighter at bar 80" 0.7 | bar 80 Violin I "lighter at bar 80" 0.85 |
| u08 | none or mark | Somebody's flat at bar fifty, I don't know who. | none 0.9 | none 0.9 | none 0.9 | none 0.9 |
| u09 | none | Piano, the, the cadenza thing, we'll talk about it later. | none 0.9 | none 0.9 | none 0.9 | none 0.9 |
| u10 | none | Violins, there, the bit, you know the bit, do the thing we said. | none 0.9 | none 0.95 | none 0.9 | none 0.9 |

### Confidence (both runs pooled)

**v4d**

| group (2 runs pooled) | n | min | median | max | values |
|---|---|---|---|---|---|
| right marks | 142 | 0.5 | 0.9 | 0.97 | 0.5: 1, 0.55: 1, 0.65: 1, 0.7: 4, 0.75: 10, 0.8: 4, 0.82: 1, 0.85: 16, 0.88: 1, 0.9: 34, 0.92: 5, 0.95: 59, 0.97: 5 |
| wrong marks | 55 | 0.7 | 0.9 | 0.95 | 0.7: 2, 0.8: 3, 0.85: 14, 0.9: 25, 0.95: 11 |

| threshold | marks auto-applied | of those wrong | precision | cases wholly auto-applied | of those not fully right |
|---|---|---|---|---|---|
| ≥ 0.8 | 178/197 | 53 | 0.702 | 167/200 | 51 |
| ≥ 0.9 | 139/197 | 36 | 0.741 | 131/200 | 36 |
| ≥ 0.95 | 75/197 | 11 | 0.853 | 73/200 | 11 |

**v4e**

| group (2 runs pooled) | n | min | median | max | values |
|---|---|---|---|---|---|
| right marks | 193 | 0.45 | 0.95 | 0.98 | 0.45: 1, 0.55: 1, 0.7: 2, 0.85: 20, 0.88: 2, 0.9: 41, 0.92: 5, 0.95: 113, 0.96: 1, 0.97: 5, 0.98: 2 |
| wrong marks | 2 | 0.95 | 0.95 | 0.95 | 0.95: 2 |

| threshold | marks auto-applied | of those wrong | precision | cases wholly auto-applied | of those not fully right |
|---|---|---|---|---|---|
| ≥ 0.8 | 191/195 | 2 | 0.990 | 180/200 | 2 |
| ≥ 0.9 | 169/195 | 2 | 0.988 | 158/200 | 2 |
| ≥ 0.95 | 123/195 | 2 | 0.984 | 118/200 | 2 |

v4d's "wrong" marks are almost all the safe unplaced landmark marks (0.85–0.95), so its precision column overstates
the risk of a wrong *bar*: an unplaced mark cannot be auto-applied anywhere. v4e's two wrong marks at ≥ 0.95 are
lm15's 149 (both runs); at 0.95 v4e auto-applies 118/200 cases against v4d's 73.

### Guard: the clean 130-case set

`clean130.py`, one run each, minimal, book A's facts with groups and **no landmarks** (that set's truth puts every
landmark at `mark`): v4d 100/100 instructions right, 97 with stand text, 0/30 false positives; v4e 100/100, 97, 0/30.
The new rule text costs nothing where it cannot help. (The text eval's own v4d run was 99/100 with n16 a false
positive; here n16 was none for both.)

### Latency and cost

| prompt | input tok (mean) | cached (mean) | median s | p90 s (r1 / r2) | $/call | 200 calls |
|---|---|---|---|---|---|---|
| v4d | 1,895 | 1,091 | 1.36 | 2.35 / 2.29 | $0.0025 | $0.498 |
| v4e | 2,225 | 879 | 1.20 | 2.23 / 2.02 | $0.0029 | $0.589 |

v4e adds about 330 input tokens (landmarks, groups, the three rule lines; book B's facts are the long ones) and is
not slower (fewer output tokens: 266 vs 311 mean).

### Stand-text misses (lenient keys)

None in any run, after one key fix in the set (t07 "divisi" did not match the short key "div").

## Results: speech, music glossary in the ASR keywords

**Meta's documented limit: none.** The schemas page (`keywords`: "array of string", "Terms to bias recognition toward
… Biasing does not guarantee an exact spelling"), the speech-to-text guide and the transcribe reference (fetched
2026-10-30) give no maximum count or length. 66 keywords were accepted on every handshake (no error event, close
1000 on all 160 streams).

- **Today's keywords**: `transcribe_voice.Score.keywords()` for the eval book, 28: parts, bases, plurals, firsts,
  seconds, Lin, Inès, bar, pickup, letter A–F.
- **+ glossary** (40, 38 new): pizzicato, pizz, arco, fermata, ritardando, ritard, a tempo, sforzando, subito,
  crescendo, diminuendo, staccato, legato, tenuto, marcato, accent, sordino, mute, divisi, tutti, pickup, downbeat,
  double bar, coda, segno, key change, vibrato, harmonic, up bow, down bow, breath mark, cut, letter, bar, repeat,
  forte, piano, fortissimo, pianissimo, mezzo. 66 in all.
- CK's 40 recorded lines (`api/fixtures/voice/audio/wav`), realtime ENDPOINTING with `realtime.py` (80 ms frames,
  real-time pace, 0.3 s before, 2.5 s after), **each keyword set run twice** to see the recogniser's own spread.
  WER with the eval's `textnorm.wer`; term words = reference tokens from the glossary less those today's list
  already has (bar, letter, pickup) and function words, scored on the alignment (34 in the set).
  Then every transcript through v4d once (minimal), scored as the recorded eval (`voice_eval.score_line`).

| keywords | run | WER | term-word errors | v4d all fields, base 26 | retakes 9 | negatives 5 |
|---|---|---|---|---|---|---|
| today (28) | 1 | 110/415 = 0.265 | 5/34 | 21 | 6 | 5/5 |
| today (28) | 2 | 112/415 = 0.270 | 5/34 | 22 | 7 | 5/5 |
| + glossary (66) | 1 | 109/415 = 0.263 | **3/34** | 22 | 7 | 5/5 |
| + glossary (66) | 2 | 112/415 = 0.270 | **3/34** | 22 | 7 | 5/5 |

Runs of the same keywords differ on 5 of 40 lines each, so overall WER and all-fields are noise-level equal. The
term words move consistently, both runs:

- **Fixed by the glossary**: v27 "fermenta" → "fermata" (today run 2 even gave "write Inès Frmenta"), v21 "sforzato"
  → "sforzando". Also v04 "autos" → "Altos" once.
- **Not fixed**: v25 "retard" (for ritard) and v01c "piano" (a word lost in a self-correction) in all four runs.
- **Worse with the glossary**: **v15** "Stop the cello, bar 50, pizzicato" → "stop the cello, bar 50, **pizz cut**"
  in both glossary runs (today: "pizzicato" once, "pits cuto" once). The short keywords `pizz` and `cut` pulled the
  word apart. v08 "bar one twelve … one sixteen" (glossary run 1) is number formatting the WER normaliser does not
  fold, not a recognition error (the marks were right).
- Did better words reach the marks? Barely: the only all-fields change attributable to the glossary is v27
  (today run 2 lost the fermata line; both glossary runs got it). v4d already read "fermenta" and "sforzato" right
  on text, so the ASR fix mostly duplicates what Spark does anyway.

## Recommendation

- **(a) landmarks: adopt** — the one large win (0/20 → 19/20 placed, and placed marks can be auto-applied, 118 vs 73
  cases at 0.95). Write a double bar as "between bars N and N+1" to avoid lm15's off-by-one. It needs a data source
  the app does not have yet: today the DB keeps rehearsal letters per bar (`measure_placements.rehearsal_mark`) and
  one score-level `key_sig`; key changes, double bars, tempo headings, segno and coda would come from the
  interpretation's MusicXML via music21 (`KeySignature`, `Barline('light-light')`, `MetronomeMark`/tempo text,
  `Segno`/`Coda`). Until it does, the rule with an empty list behaves as v4d (clean-130 guard). The letter-to-bar
  map the app already has could be listed the same way at no cost (not tested here).
- **(b) groups from the book: adopt** — needed as soon as a book is not strings + choir: v4d sends the soloist the
  orchestra's marks. Book A unchanged. Groups need deriving from part names (an instrument-family table).
- **(c) musical-terms line: optional, no measured gain** — v4d already gets every mangle on text (25/25), and it
  cost nothing on either set. Keep it if CK wants belt and braces; it is 4 lines of prompt.
- **ASR glossary: adopt a trimmed one** — it fixes the term words the recogniser actually mangles (fermata,
  sforzando: term errors 5 → 3 of 34 in both runs) with no WER cost and no limit to respect, but drop the short or
  common words that split real ones (`pizz`, `cut`; probably `piano`, `bar`, `letter`, `mute`, which today's list or
  context already covers). Small set (34 term words, one voice): treat as directional.

## Proposed diff (not applied)

`api/app/librarian/voice_prompt.py`:

```diff
@@ class ScoreFacts
     bar_last: int = 240
     rehearsal_marks: list[str] = field(default_factory=lambda: list("ABCDEF"))
+    landmarks: list[str] = field(default_factory=list)      # "key change at bar 97 (E-flat major)", "double bar between bars 64 and 65"
+    groups: list[tuple[str, list[str]]] = field(default_factory=list)   # ("Strings", ["Violin I", ...])

     def as_text(self) -> str:
-        return (f"Parts: {', '.join(self.parts) or 'none named'}.\n"
+        out = (f"Parts: {', '.join(self.parts) or 'none named'}.\n"
                 f"Members (players addressed by name): {', '.join(self.members) or 'none'}.\n"
                 f"Bars: {self.bar_first} to {self.bar_last}.\n"
                 f"Rehearsal letters: {', '.join(self.rehearsal_marks) or 'none'}.")
+        out += "\nLandmarks: " + ("; ".join(self.landmarks) if self.landmarks else "none listed") + "."
+        if self.groups:
+            out += "\nGroups: " + " ".join(f"{g}: {', '.join(ps)}." for g, ps in self.groups)
+        return out
@@ RULES, position
-  null, name the landmark in text); "global" for the whole piece or its very beginning or end (bars null).
+  null, name the landmark in text); "global" for the whole piece or its very beginning or end (bars null). When the score facts list a
+  landmark with its bars, a place named from it resolves to bars ("two after the key change", "the bar
+  before the double bar", "from the coda", "in the slow section"): use "bar" or "range"; a landmark the
+  facts do not list stays "mark".
@@ RULES, audience
-  "all but X"), list every other part of X's group only, never parts of the other group (strings: Violin I,
-  Violin II, Viola, Cello; voices: Soprano, Alto, Tenor, Bass). A player addressed by name is
+  "all but X"), list every other part of the widest group in the score facts that holds X (or of the group the
+  speaker names: "strings except the cellos"), never parts of another group; a soloist alone in its group
+  is excluded from the Orchestra ("everyone but the piano" = every Orchestra part). A group the speaker
+  names ("the strings", "the orchestra") is every part listed in it. A player addressed by name is
@@ RULES, mishearing (optional, (c))
-  part may be "except". Numbers are usually right. A section or a name that is not in the score facts (e.g.
+  part may be "except". Musical terms are misheard too: "fermenta" = fermata, "pizza cutter" =
+  pizzicato, "retard and oh" = ritardando, "attempt oh" = a tempo, "spores and oh" = sforzando, "arc oh" =
+  arco, "stuck auto" = staccato, "the visi" = divisi, "lay gato" = legato, "coal leg no" = col legno; a word
+  that sounds like a musical term is that term. Numbers are usually right. A section or a name that is not in the score facts (e.g.
```

`api/app/librarian/transcribe_voice.py` (`Score`): fill `landmarks` from the interpretation's MusicXML and `groups`
from the part names, and in `keywords()` append a trimmed glossary:

```diff
+MUSIC_TERMS = ["pizzicato", "arco", "fermata", "ritardando", "ritard", "a tempo", "sforzando", "subito",
+               "crescendo", "diminuendo", "staccato", "legato", "tenuto", "marcato", "accent", "sordino", "divisi",
+               "tutti", "downbeat", "double bar", "coda", "segno", "key change", "vibrato", "harmonic", "up bow",
+               "down bow", "breath mark", "repeat", "fortissimo", "pianissimo"]
@@ def keywords
-        out += list(self.members) + ["bar", "pickup"] + [f"letter {c}" for c in self.letters]
+        out += list(self.members) + ["bar", "pickup"] + [f"letter {c}" for c in self.letters] + MUSIC_TERMS
```

Applying needs `RULES_V4D` in `api/experiments/voice/prompts.py` brought in step (it asserts equality with the app's
rules at import), the always-on prompt the same, and tests for the new facts lines.

## Caveats

- I wrote the cases, the landmarks and the truth knowing both prompts; v4d's landmark and concerto losses are by
  construction (it is not given the facts). Read the landmark/group numbers as "what the facts buy", and the
  terms/ramble/addressee/unrecoverable numbers (equal) as the honest comparison of the rule text.
- The (b) wording names "Orchestra" and a soloist; it was tested on one concerto layout only.
- Two runs per prompt; ASR two runs per keyword set, one voice, 34 term words.

## Spend

**$1.924** of the $3 cap, 980 logged calls in `api/experiments/voice_text/messy100/spend.jsonl`: v4d 200 calls
$0.498, v4e 200 calls $0.589, clean-130 guard $0.483 (v4d $0.197, v4e $0.285), ASR 160 realtime streams $0.074,
v4d on the four transcript sets 160 calls $0.281.
