# 013 Always-on listening: research and experiments

Status: research (2026-10-30). Nothing built, nothing in `api/app` or `web/src` changed. | Meta models: Muse Voice
Transcribe realtime (`muse-voice-transcribe-1.0`, ENDPOINTING), Muse Spark 1.3 (chat completions, effort minimal).

The question: the leader's iPad listens for the whole rehearsal (app always in the foreground). It splits speech into
utterances, sends each one to Voice Transcribe and then Spark, and turns an instruction into a card, or applies it
directly, only when confidence is high. Rejections are silent. Push-to-talk today takes 2.7 to 4.5 s per take. This
note says what Meta offers, what was measured and what to build.

Scripts: `api/experiments/voice_stream/` (`realtime.py`, `spark_lat.py`, `gen_audio.py`, `chunk.py`,
`stream_eval.py`, `analyze.py`). Raw results are in `results/`, and every paid call is in `spend.jsonl`. Audio
(synthetic negatives, piano, the long stream, the Silero model) is in `audio/`, which is gitignored. Data: CK's 40
eval takes (`api/fixtures/voice/audio/wav/`) and local synthetic audio only. Nothing touched Supabase.

## Answer in one paragraph

Meta has a documented realtime WebSocket. Its ENDPOINTING mode works well as the chunker. It emits a finished turn
0.57 s after the speaker stops (median; p90 0.64 s). It returned no turns on piano, and its WER is slightly better
than the batch endpoint the app uses today. It gives no confidence values of any kind. On the Spark side, effort
**minimal** cuts Spark from 2.6 to 3.0 s down to 1.3 to 1.7 s at the same accuracy. Messages refuses minimal, so this
needs `/v1/chat/completions`. A shorter prompt, a smaller output cap, acting on the first JSON object and starting on
the ASR partial each save 0.1 s or less, or nothing. The proposed pipeline takes about **2.1 s from end of speech to
the card** (p90 about 2.8 s). Today's ASR plus Spark alone takes about 4.2 s. A `confidence` field added to v4 costs
nothing in accuracy. It never fired on a non-instruction, but it separates right from wrong marks only weakly; at 0.95
or higher, 11 of 35 instructions would auto-apply, all 11 right. Expected cost is $0.32 to $0.57 an hour at standard
prices, or about $0.20 an hour with the contributor switch on, which makes Spark about 3.5x slower.

## Q1. Streaming Voice Transcribe

### What Meta documents (fetched 2026-10-30)

A streaming mode exists and is documented:

- Endpoint `wss://api.meta.ai/v1/asr/realtime`, a WebSocket. Source: https://dev.meta.ai/docs/api-reference/voice/realtime.
  An optional `sessionId` query parameter is used for log correlation. The HTTP `Authorization` header is not read.
  The key goes in the first JSON text frame, which must arrive within 10 s:
  `{"authorization": {"accessToken": "Bearer <key>"}, "audioEncoding": "PCM_24KHZ" | "PCM_16KHZ", "model": "muse-voice-transcribe-1.0", "mode": "PUSH_TO_TALK" | "ENDPOINTING" | "DIARIZATION", "partialMode": "CUMULATIVE" | "DELTA", "emitAudioProgress": bool, "keywords": [...], "languageBias": [...]}`
  (field list from https://dev.meta.ai/docs/api-reference/voice/schemas). The ack is the only frame without a
  `type` and carries `sessionId`.
- Audio is sent as binary frames of signed 16-bit little-endian mono PCM. 24 kHz is native; 16 kHz is resampled on
  the server. Meta's example uses 80 ms frames sent at real-time pace. `{"type": "endStream"}` flushes the stream;
  read on until close code 1000. Close codes: 1008 means a bad request or a pacing-policy failure, 1011 means a
  backend failure or "Max session duration reached", 1013 means rate limited.
- Server events: `transcript {transcript, final, audioProcessedMs}` (partials; in CUMULATIVE mode each one is the
  whole hypothesis so far), `speechStart {turnId}`, `speechEnd {turnId}`,
  `speechComplete {turnId, transcript}` (the final, post-processed text of one turn), `speaker {label}`
  (DIARIZATION only), `audioProgress`, `error {message, sessionId, errorType?, errorCode?, errorParam?}`.
  Source: https://dev.meta.ai/docs/speech-to-text and the schemas page.
- Modes: PUSH_TO_TALK (you mark the end; completion is `final: true`), ENDPOINTING (the server finds turn
  boundaries), DIARIZATION (turns plus speakers, "not tuned for low-latency voice commands"). The mode is fixed for
  the session.
- Limits: a session lasts at most 60 min with no resume token. Audio must be sent at roughly real time and no more
  than 5 s ahead; during silence the client must send PCM silence. A stream that stops sending without `endStream`
  is closed. A tenant may run 256 concurrent streams and 16,000 streams an hour. Price is $0.18 per hour of audio
  processed, the same as the file endpoint, billed in whole seconds rounded down. Contributor mode is "not
  available for Muse Voice Transcribe" (https://dev.meta.ai/docs/pricing-rate-limits).
- **Confidence: none.** The speech-to-text page says confidence scores are not provided, and no schema has a
  score, probability or confidence field. There are no word timestamps (turn-level `startMs`/`endMs` only), no VAD
  or endpointing tuning parameters (silence length, eagerness), and no data-sharing field.
- The file endpoint can also stream: `Accept: text/event-stream` on `POST /v1/asr/transcribe` "returns the realtime
  event stream" (https://dev.meta.ai/docs/api-reference/voice/transcribe). Not tested here; it does not help a live
  microphone.

### Measured

Minimal client: `realtime.py`. It sends PCM_16KHZ in 80 ms frames at real-time pace, with 0.3 s of silence before
each clip and 2.5 s after, and the eval's keywords. Wall clock and audio clock are aligned at the first frame.
Handshake took 0.26 to 0.52 s (one cold connect took 1.1 s).

Five lines, every mode:

| line | batch DIARIZATION s (today, mean of 2) | batch PTT s | rt PTT first partial after onset s | rt PTT final after endStream s | rt ENDP first partial after speechStart s | rt ENDP speechComplete after turn end s | rt DIAR speechComplete after turn end s | WER batch DIAR | WER rt PTT | WER rt ENDP | WER rt DIAR |
|---|---|---|---|---|---|---|---|---|---|---|---|
| v02 | 2.51 | 2.10 | 1.17 | 0.13 | 1.48 | 0.57 / 0.65 | 0.66 / 0.65 | 3/13 | 3/13 | 3/13 | 3/13 |
| v08 | 1.52 | 1.86 | 1.09 | 0.16 | 1.56 | 0.54 | 0.62 | 1/7 | 4/7 | 4/7 | 1/7 |
| v11 | 1.79 | 1.59 | 0.79 | 0.26 | 1.08 | 0.57 | 0.61 | 2/14 | 2/14 | 2/14 | 2/14 |
| v15 | 1.52 | 1.37 | 1.08 | 0.12 | 1.53 | 0.55 | 0.65 | 2/7 | 2/7 | 2/7 | 2/7 |
| v21 | 2.17 | 1.95 | 1.01 | 0.15 | 1.36 | 0.56 / 0.53 | 0.62 | 3/11 | 1/11 | 1/11 | 2/11 |

(v08 counts 4/7 in realtime only because it wrote "one twelve" as words; textnorm reads that as "1 12".)

All 58 clips (40 eval takes, 15 synthetic speech negatives, 3 music clips) in ENDPOINTING mode:

| | batch DIARIZATION (eval, 2026-10-29) | realtime ENDPOINTING (2026-10-30) |
|---|---|---|
| WER, base 30 | 0.177 (55/310) | **0.148** (46/310) |
| WER, retakes 10 | 0.686 (72/105) | 0.667 (70/105) |
| speechComplete after the server's turn end | n/a | **0.57 s** median, p90 0.64, max 0.67 |
| first partial after speechStart | n/a | 1.35 s median |
| turns on piano / instrument (n16, n17, n18) | n/a | 0 / 0 / 0 |
| eval takes split into more than one turn | n/a | 6/40 (v01, v02, v04c, v07c, v09c, v21) |

Readings:

- **Endpointing is usable as the chunker, and it is fast.** The final turn text arrives about 0.57 s after the
  speaker stops, with very little spread. That timing is the server's own silence rule; it cannot be tuned.
- **Partials do not help.** In 62/62 turns the final words had already appeared as a partial, but that partial
  came 0.02 s (median) before `speechComplete`. The endpointer releases the last partial and the final together,
  so starting Spark on the partial gains nothing.
- Realtime PUSH_TO_TALK is just as quick once the client knows speech has ended: the final arrives 0.12 to 0.26 s
  after `endStream`. With a client VAD cut-off of 500 ms, that totals about 0.65 s, no better than ENDPOINTING. It
  would also need a session per utterance or a socket kept warm.
- Realtime DIARIZATION took 0.61 to 0.66 s, about 0.06 s slower than ENDPOINTING, and adds speaker labels. Every
  clip has one speaker, so whether labels could keep only the leader's voice is untested.
- The dropped addressees are not caused by the batch endpoint. Realtime also loses "Lin," (v11), "Firsts" (v16) and
  "Cello," (v28). v14 "that's lunch" came back as "that's Lin"; Spark still answered none.

## Q2. Latency budget and what cuts Spark time

Today's pipeline, per take: stop recording, upload the WAV, insert the job, batch DIARIZATION, Spark (Messages,
effort low, 8k output budget), insert the rows, then Realtime or the 2 s poll to the tray.

| stage | measured here | source |
|---|---|---|
| batch DIARIZATION (upload to answer) | 1.5 to 2.5 s (5 lines, mean 1.9) | `modes_five.json` |
| Spark, app prompt, Messages, low | 2.58 s median, p90 5.09 | `spark_latency.json` |
| overhead (route, Storage, job row, insert, Realtime/poll) | not measured (no hosted DB); about 0.5 to 1 s by subtraction | 013 doc: handler run 2.7 to 5.8 s, browser about 5 s |

Spark variants on the same five lines (realtime transcripts), 10 calls each:

| variant | median s | p90 s | s to first complete JSON object | input tok | output tok (incl. reasoning) | all 5 fields | $/call |
|---|---|---|---|---|---|---|---|
| today: app prompt, Messages, low | 2.58 | 5.09 | (arrives whole) | 1638 | 653 | 8/10 | 0.0041 |
| v4 held-out, Messages, low | 3.07 | 6.49 | (arrives whole) | 1650 | 695 | 8/10 | 0.0043 |
| v4, chat, streamed, low | 2.99 | 4.15 | 2.83 | 1651 | 851 | 8/10 | 0.0036 |
| **v4, chat, streamed, minimal** | **1.69** | **2.35** | 1.61 | 1651 | 385 | 8/10 | 0.0036 |
| app prompt, chat, streamed, minimal | 1.81 | 2.38 | 1.69 | 1638 | 385 | 8/10 | 0.0034 |
| v4sc (condensed rules, 4 examples), chat, low | 3.81 | 6.08 | 3.74 | 1264 | 951 | 6/10 | 0.0054 |
| v4sc, chat, minimal | 1.92 | 2.65 | 1.86 | 1264 | 459 | 6/10 | 0.0031 |
| v4sc, chat, minimal, contributor | 5.96 | 9.40 | 5.78 | 1264 | 416 | 7/10 | 0.0002 |

(The two misses in every v4 row are v11: the addressee is missing from the transcript.)

Over the whole set (40 eval takes plus 23 negatives, realtime ENDPOINTING transcripts, chat, streamed, 6 parallel):

| prompt, effort | base 26 all fields | retakes 9 all fields | negatives with no mark | median s | p90 s | $/call |
|---|---|---|---|---|---|---|
| v4, minimal | 22/26 | 6/9 | 22/23 (n09 "can I have an A" became a tuning mark) | 1.14 | 1.95 | 0.0024 |
| **v4c (v4 + confidence), minimal** | **22/26** | **7/9** | **23/23** | 1.29 | 1.95 | 0.0025 |
| v4c, low | 22/26 | 7/9 | 23/23 | 1.98 | 3.56 | 0.0037 |

The eval's v4 on batch DIARIZATION transcripts (2026-10-29) scored 22/26 and 7/9. Realtime ASR with effort minimal
matches it.

Findings:

- **Reasoning tokens set Spark's latency; prompt length barely matters.** Effort minimal halves the output tokens
  (about 850 to 385) and takes off about 1.3 s. The condensed prompt (-23 % input) was not faster. It reasoned
  more and was less accurate (6/10), so v4's wording stays.
- **Messages refuses `minimal`.** The reply is `HTTP 400 unsupported output_config.effort value minimal`.
  `/v1/chat/completions` with `reasoning_effort: "minimal"` works. Meta's reasoning page lists
  none/minimal/low/medium/high/xhigh/max; "none" returns 400 on Spark (https://dev.meta.ai/docs/reasoning).
- **Streaming Spark output saves about 0.08 s.** On Messages the text came in one piece after a `redacted_thinking`
  block, so streaming changed nothing. Chat completions streams real deltas, but the answer is one short JSON
  object that follows the reasoning, so the first complete object lands 0.05 to 0.1 s before the end. Streaming is
  worth having for the chat path, not as a speed-up.
- **A smaller output cap did nothing** (v4, low, 1024: same times, in the first run). Reasoning counts against the
  cap, so a cap below about 1k risks an empty answer (000).
- **Contributor mode is about 3.5x slower** (median 6 s) and 20x cheaper.
- Prompt caching hit on some calls (`cached_tokens` up to 1.6k). The production prompt has a fixed prefix (score
  facts, rules, examples, then the transcript), so caching applies. The eval's held-out examples break the prefix.

Recommended pipeline and expected latency from end of speech:

| stage | expected |
|---|---|
| ENDPOINTING `speechComplete` after the voice stops | 0.57 s (p90 0.64) |
| relay hop browser to API to Meta (LAN or tunnel) | about 0.05 s (assumed) |
| Spark v4c, chat, minimal, streamed | 1.3 s median (p90 2.0; 1.7 single-file) |
| check, insert proposed rows, Realtime to the tray | about 0.2 s (assumed; no 2 s poll needed for a live socket) |
| **end of speech to card** | **about 2.1 s median, about 2.8 s p90** |

Today the time from tapping Stop to the card is about 4.2 s for ASR and Spark alone (1.9 + 2.6) plus overhead.

## Q3. The confidence gate

Signals that exist:

- ASR: none. There is no confidence, no logprobs and no word timing. Spark logprobs are refused too:
  `logprobs cannot be true when reasoning_effort is minimal ... logprobs is not supported with reasoning`, and
  reasoning cannot be turned off.
- Spark's answer: `{"none": true}`, the deterministic `checked_marks` refusals (quote not verbatim, bars outside
  the book, unknown audience), and a `confidence` field. v4 has no such field. **v4c** adds one per mark and on
  `{"none": true, "confidence": x}`: one rule line plus one schema field. It cost nothing in accuracy (table
  above).
- A cheap text gate before Spark (regex of numbers, part names, seat nicknames, members, about 60 musical words;
  `analyze.GATE_WORDS`).

Negatives (23): CK's 5 recorded (v06, v06c, v14, v20, v30) and 15 **synthetic** lines in macOS `say` voices (Daniel,
Samantha, Karen, Moira, Fred, Tessa, Rishi), converted with afconvert to 16 kHz plain PCM. They are counting in (n01,
n02, n15), "from the top" said casually (n03, n04), start points with a bar or letter (n10 "Where were we? Bar
forty?", n12 "letter B, off we go", n14 "Again from bar twelve"), chat and logistics (n05, n06, n08, n11, n13),
praise (n07) and tuning (n09). The other 3 are music: two 12 s cuts of the MuseScore Goldberg render (a sampled
piano) and music21's `test_audio.wav`. The music produced no transcript, so Spark was never called on it.

v4c, minimal; tiers by the mark's confidence:

| threshold | instructions with a card (recall, of 35) | cards on non-instructions (of 23) | card precision | cards fully right | auto-apply precision |
|---|---|---|---|---|---|
| any (checked) | 35/35 | 0 | 1.00 | 29/35 | 0.83 |
| 0.70 | 33/35 | 0 | 1.00 | 28/33 | 0.85 |
| 0.85 | 30/35 | 0 | 1.00 | 26/30 | 0.87 |
| 0.90 | 21/35 | 0 | 1.00 | 20/21 | 0.95 |
| **0.95** | **11/35** | 0 | 1.00 | **11/11** | **1.00** |

v4c at effort low gave nearly the same table: at 0.95, 10/35 auto-applied and 10/10 right.

- **Propose tier: no threshold is needed.** Spark's own `{"none": true}` plus `checked_marks` rejected all 23
  negatives in both v4c runs, and every non-instruction scored "none" at 0.95 to 0.99. All 35 instructions got a
  card. The one false positive in this work came from v4 without the field (n09, one run of three).
- **Auto-apply tier: confidence is a weak signal.** Wrong marks sat at 0.65 to 0.90 (v11 0.65, v22 0.75, v04c,
  v10c and v28 0.85, v16 0.9), while right ones spread from 0.65 to 0.95. Only the 0.95 bucket was clean: 11/11 in
  one run and 10/10 in the other, about 30 % of instructions. Adding a rule ("an ensemble mark auto-applies only if
  the quote says everyone, all or tutti; never auto-apply a cut") made it no cleaner: 7/7 at 0.95, 15/16 at 0.9.
  These are small numbers from one voice. Treat auto-apply at 0.95 or higher as plausible, not proven.
- **The text gate** passed 34/35 instructions. It lost v27 because ASR heard "fermata" as "fermenta". It stopped
  14 of 23 non-instructions before Spark (all counting, chat and "from the top"). The ones it let through were the
  start points with numbers, praise, v14 and v30, and Spark rejected all of them. It saves money, not mistakes.

## Q4. Client-side chunking

The test file is `long.wav`, 146 s: 12 eval takes (including the retakes v03c and v07c with hesitations), 5
negatives (2 of CK's, 3 synthetic), two 12 s piano cuts and the instrument clip, with gaps of 0.5 to 5 s and room
noise at about -62 dBFS. There are 17 spoken lines in all. Silero VAD v5 ran as onnx (onnxruntime 1 thread; model
from the `silero-vad` 5.1.2 wheel on PyPI, `silero_vad.onnx` 2.3 MB). The energy gate uses 32 ms RMS frames, 12 dB
over a tracked floor. Both use the same hysteresis segmenter (minimum speech 250 ms, 100 ms pad). Meta's ENDPOINTING
turns of the same file are scored the same way.

| chunker | silence cut-off | segments | lines found (of 17) | extra pieces (splits) | segments joining 2 lines | segments on music only (music s sent) | end decided after speech end, median / p90 s | audio s sent (of 146) |
|---|---|---|---|---|---|---|---|---|
| Silero | 300 ms | 27 | 17 | 10 | 0 | 0 (0) | 0.33 / 0.43 | 71 |
| energy | 300 ms | 29 | 17 | 9 | 0 | 3 (34) | 0.31 / 0.37 | 109 |
| Silero | 500 ms | 23 | 17 | 6 | 0 | 0 (0) | 0.52 / 0.62 | 71 |
| energy | 500 ms | 26 | 17 | 6 | 0 | 3 (34) | 0.50 / 0.56 | 109 |
| Silero | 700 ms | 23 | 17 | 6 | 0 | 0 (0.1) | 0.71 / 0.84 | 73 |
| energy | 700 ms | 25 | 17 | 5 | 0 | 3 (35) | 0.70 / 0.76 | 111 |
| Silero | 1000 ms | 18 | 17 | 3 | 2 | 0 (0.1) | 1.05 / 2.57 | 76 |
| energy | 1000 ms | 15 | 17 | 2 | 5 | 1 (35) | 1.03 / 8.92 | 119 |
| **Meta ENDPOINTING** | (server) | 22 | 17 | 5 | 0 | 0 (0) | 0.44 / 0.61 (to `speechComplete`) | 73 |

- The energy gate sends almost all of the piano (about 34 of 36 s). Silero and Meta's endpointer send none of it.
- **No silence cut-off separates pauses inside an utterance from gaps between utterances.** CK's own pauses inside
  a line (v21 "bar 64 … altos and tenors", v12 "… nobody else", v07c's correction, v02's repeated "49") measured
  0.8 to 1.4 s. The gaps between lines in this file were 0.75 to 5.3 s, and in a rehearsal they can be shorter
  still. Every chunker splits lines; past 700 ms the chunkers start joining lines and the end lags.
- Added latency is the silence cut-off itself, plus about 0.03 s for Silero and about 0.15 s for the PTT final.
  Meta's endpointer behaves like a cut-off of about 450 to 600 ms with Silero-grade music rejection.
- Silero costs 0.12 ms of CPU per 32 ms frame on this Mac. On the web it would be onnxruntime-web (wasm, a few MB)
  in an AudioWorklet or worker. That is feasible, but it is not needed if Meta does the endpointing.

So a split has to be repaired after the chunker. Spark was run on Meta's 22 turns of `long.wav` (v4c, minimal):

| strategy | 12 instruction lines, all fields | 5 spoken negatives, no mark | marks on music |
|---|---|---|---|
| each turn alone | 10/12 | 5/5 | 0 |
| join with the previous turn if gap ≤ 2 s; latest reading wins | 10/12 | 5/5 | 0 |
| **rolling group: a turn within 1 s of the last joins its group (up to 3 turns); the group is re-read at each turn; a mark belongs to the turn its quote sits in** | **12/12** | 5/5 | 0 |

Turn by turn, v21 "bar 64" lost its bar and v07c lost its correction to violas. The rolling group fixes both: one
Spark call per turn, as before, but a card can change up to 1 s later when the next turn joins. This was one run on
12 lines. It is the right shape, not yet a proven number.

## Q5. Settings note: "Help Meta improve their models" and the price per hour

- The switch maps to Spark's contributor variant, `muse-spark-1.3-contributor` (or `-1.2-contributor`), at $0.10
  input, $0.002 cached and $0.20 output per 1M tokens against $1.25 / $0.15 / $4.25 standard. The terms say content
  "may be used to train future Meta models". Voice Transcribe has no contributor mode, so the switch changes only
  the Spark half. Contributor runs at 150 RPM per team (enough: about 2 calls a minute per leader) and was 3.5x
  slower here (6 s median). Suggested label: "Help Meta improve their models. Cheaper; voice notes take about
  5 s longer."
- Measured cost per call: v4c minimal $0.00254 mean (1,762 input tokens, 593 of them cached, 233 output tokens);
  contributor $0.00018. Realtime ASR streamed for the whole hour costs $0.18 an hour. The protocol requires audio
  (or PCM silence) at real-time pace, and silence is billed.
- Assumptions: 1.3 turns per utterance (22 turns for 17 lines in `long.wav`), one Spark call per turn (the rolling
  group re-reads but adds no calls), and **half of all utterances not instructions** (a guess; no rehearsal
  recording exists). The text gate stops 61 % of those before Spark.

| | 60 utterances/h | 120 utterances/h |
|---|---|---|
| ASR, realtime, whole hour | $0.18 | $0.18 |
| Spark standard, no gate (78 / 156 calls) | $0.20 | $0.40 |
| Spark standard, text gate (54 / 108 calls) | $0.14 | $0.27 |
| Spark contributor, text gate | $0.01 | $0.02 |
| **total, standard, no gate** | **$0.38/h** | **$0.58/h** |
| **total, standard, text gate** | **$0.32/h** | **$0.45/h** |
| **total, contributor, text gate** | **$0.19/h** | **$0.20/h** |

A three-hour rehearsal costs about $1 to $1.75 standard, or about $0.60 contributor. Streaming only what Silero
calls speech would bring ASR down to about $0.03 an hour (10 min of speech), at the price of a session per
utterance or a warm socket fed silence. That saves about $0.15 an hour and is not worth it for v1.

## Recommended architecture

In words, one listening session:

1. The leader turns Listening on (Stand, admin only, inside a rehearsal session). The page takes a Screen Wake Lock
   and keeps the existing AudioWorklet running, but posts 80 ms frames of 16 kHz PCM over a WebSocket to the API
   (`/scores/{id}/listen`; first frame = the Supabase token, `ensemble_id`, `session_id`). It does not build a WAV.
2. The API checks `can_lead_layer` and the budget, builds the score facts and keywords (as `transcribe_voice`
   does), and opens `wss://api.meta.ai/v1/asr/realtime` in ENDPOINTING mode with the key in the handshake frame.
   The key never reaches the browser; Meta documents no ephemeral tokens. The API relays frames at the pace they
   arrive, sends silence if the browser stalls, and opens a second Meta session before the 60-minute limit, cutting
   over at a `speechComplete`.
3. Meta → `speechStart`, partials (ignored, or shown as a faint "hearing…" glow), `speechEnd`, then
   `speechComplete {turnId, transcript}` about 0.57 s after the voice stops. Music produces no turns.
4. On each `speechComplete`, the API puts the turn in the current group (or starts a new one if more than 1 s has
   passed since the last turn ended, or the group has 3 turns). It optionally runs the text gate. It calls Spark on
   the whole group's text: v4c, `/v1/chat/completions`, `reasoning_effort: "minimal"`, streamed, 8k budget,
   `muse-spark-1.3` or `-contributor` per the switch.
5. Spark → `[marks with confidence]` or `{"none": true}`. `checked_marks`, `place` and `audiences` run as today.
   "None", a refusal or an unplaceable mark is logged on the session's job row and **shown nowhere**.
6. Each surviving mark is written as `annotations` with `status = 'proposed'` (tray card plus ghost via the existing
   Realtime subscription). If a group is re-read, the API replaces that group's earlier proposed rows, matched by
   `payload.group_id`, so the card updates in place. Once the group is closed (1 s with no new turn), a mark with
   confidence ≥ 0.95 that passed every check may go `live` directly, if CK wants that tier, with an Undo on the
   card. Everything else waits for Accept.
7. Charges: ASR per minute streamed (`voice`), Spark per call (`spark`), on the session's job. Listening stops on
   toggle, on session end or when the budget runs out. The socket closes with `endStream`, then close.

## Proven, assumed, not tested

| proven here (numbers above) | assumed | not tested |
|---|---|---|
| realtime WebSocket exists; protocol and fields as quoted | relay hop about 0.05 s; insert plus Realtime about 0.2 s | a real iPad mic at rehearsal distance with instruments playing |
| ENDPOINTING final 0.57 s after the turn ends; 0 turns on piano | half of utterances are non-instructions; 60 to 120 per hour | a second voice (still the overfitting check for v4) |
| realtime WER 0.148 vs batch 0.177 (base 30) | the rolling group generalises beyond 12 lines | choir singing (lyrics would produce turns; Spark should say none) |
| no confidence or logprobs from ASR or Spark | auto-apply ≥ 0.95 stays clean at scale (seen 21/21 across two runs) | several speakers; DIARIZATION labels to keep only the leader |
| minimal effort: Spark 1.3 to 1.7 s, same accuracy as low | | the WebSocket through the Cloudflare tunnel and Safari; session rollover at 60 min |
| v4c: 22/26 + 7/9, 23/23 negatives; cards never on a negative | | the SSE variant of the file endpoint |
| shorter prompt, output cap, partial-first and streaming-first-object do not help | | |
| contributor about 3.5x slower, 20x cheaper | | |

## Build estimate

| piece | size |
|---|---|
| API: `/scores/{id}/listen` WebSocket relay to Meta realtime (auth frame, pacing, silence fill, 60 min rollover, budget per minute) | 1 day |
| API: grouping, Spark on chat completions with `reasoning_effort` (a `chat` path in `llm.py`), v4c in `voice_prompt.py` with tests, row replace by `group_id`, silent rejections | 0.75 day |
| Web: Listening toggle and indicator on the Stand, AudioWorklet frames to a WebSocket, Wake Lock, reconnect; cards update in place (tray already exists) | 1 day |
| Settings: contributor switch (per ensemble or per user), price note | 0.25 day |
| Optional auto-apply tier with Undo | 0.5 day |
| Checks on the iPad: a real rehearsal take (5 min, CK plus playing), second voice, tunnel | CK, 1 session |

About 3 to 3.5 agent days, plus CK's iPad session.

## Spend

This task's Meta spend is **$1.07** of the $5 cap, over 435 calls in `api/experiments/voice_stream/spend.jsonl`:
ASR (batch and realtime, 90 sessions) $0.045, Spark latency variants $0.365, full-set runs $0.476, stream
evaluation $0.171, probes $0.011. The two chat probes are logged at an estimated $0.0015.
