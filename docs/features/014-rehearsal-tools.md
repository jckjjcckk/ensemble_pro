# 014 Rehearsal tools: play the parts

Status: working on the local stack (2026-10-30), digital books only; the practice mock is retired (2026-10-30); not yet on an iPad | Meta model: none (music21
writes the MIDI, the browser synthesises; Spark may later rate trouble spots; MIDI listening is a stretch).

## Purpose

From the cellist's feedback: what a player wants from the score in a rehearsal or practice room is to slow a passage
down, loop it, hear the other parts and mix their volumes. Build-queue item 8. CK specified it on 2026-10-30 as a
musician's workflow, sold as **play the parts**, not "practice mode": choose which parts sound (several at once),
leave your own part out, set a pace, press play, hear one bar counted in in the score's meter, then the music; loop a
passage. The point: a PDF converted to Digital (005) can now be played part by part.

## The engine decision

**music21 MIDI on the API + a browser synth (Tone.js), no server audio.** Chosen over MuseScore headless audio because:
the pace, the mix and the parts must change while it plays (a rendered file cannot), the MIDI is ~37 KB for the whole
Op. 18/1 movement against megabytes of audio per mix, music21 is already in the import and convert path (no box, no
ssh, ~2 s), and nothing new runs on the server per play. No MIDI listening, no Casio in the code.

## What is built

API (`api/app/librarian/playback.py`, no model):

- `write_step` runs at the end of `import_musicxml` (after the landmarks) and of `omr_convert` (after the `musicxml`
  source row is written). Best effort: a book whose MIDI fails is still ready; the reason is in the job result as
  `playback: {ok, reason}`.
- `{score_id}/playback/score.mid`: type-1 MIDI. Track 0 is music21's conductor track (tempo, meter); then one track per
  part in score order, the track name = the book's `parts.name` (`part_groups`: "Violin I", "Cello", one "Piano" with
  both staves in one track). Ties joined per staff, grace notes left out, dynamics realised as velocities. Repeats are
  **not** expanded: bar N has one place in time, so playback can start at any bar.
- `{score_id}/playback/bars.json`:
  `{version, ppq, parts, quarters, bars: [{bar, at, quarters}], tempos: [{bar, at, qpm, bpm, beat, text, marked}],
  meters: [{bar, at, meter, beats, beat_quarters}]}`, `at` in quarter notes from the start. One entry per measure
  number in printed order (a number printed twice keeps its first place; Chopin's fixture has three bar 0s). A bar
  lasts until the next one starts. `qpm` is quarters per minute; `bpm`/`beat` the printed mark (dotted quarter = 60 is
  qpm 90). No printed mark: one entry at 120 with `marked: false`. `count_in(map, bar)`: one bar of the meter in force.
- `scores.playback` jsonb (migration `20261030180000_score_playback.sql`): `{midi, bar_map, source_id, parts, bars,
  made_at}`. **Applied to the local stack only; hosted needs `supabase db push --linked` when CK says.** No new route:
  the browser reads both files from Storage through the existing score policies.
- Tests `api/tests/test_playback.py` (18): on the three fixtures and the Goldberg Aria, track count = part count with
  the book's names, every measure in the bar map in order, count-in beats = meter numerator for every bar; the quartet
  (313 bars, 3/4, 132, no invented tempo word), the piano as one track, the chorale's pickup, a made-up 3/4 → 6/8
  score with a tempo change; the import stores and records both files; a failing build leaves the book ready.
  `test_omr_convert` checks the convert records them. Suite 308 → 326.

Web:

- `web/src/app/player.ts`: loads both files (`@tonejs/midi`), and `PartsPlayer` on Tone.js 15 (dynamic import, its own
  ~340 KB chunk, fetched when the panel opens so Play can resume audio inside the tap). Schedules one pass on Tone's
  transport in ticks: the count-in clicks (first beat higher) in the start bar's meter, then the chosen bars shifted
  after it. Transport tempo = printed tempo × pace, so a pace change lands at once (within a beat) and score tempo
  changes still apply. Loop = transport loop from the range start (after the count-in) to its end, so the count-in
  sounds once. A part that is off skips its notes at trigger time; each part has its own gain. Without a loop the
  pass stops at the range end (or the last bar). iOS: `navigator.audioSession.type = 'playback'` where it exists.
- Samples under `web/public/sounds/` (4.4 MB, loaded on the first play, only the instruments the book needs): piano
  (12 notes A1–C7, every 6 semitones) and strings (cello C2, G2, D3 + violin G3, E4, C5, G5, E6), MP3 from the npm
  packages `tonejs-instrument-{piano,cello,violin}-mp3` 1.1.x (MIT per their package.json; the samples come from
  nbrosowsky/tonejs-instruments). Keyboards sound as piano; strings, voices, winds and brass as sustained strings.
- `web/src/app/PlayParts.tsx` + `play.css`: the panel at the foot of the Stand, opened from the "…" menu ("Play the
  parts", a checkbox item) or by **Loop from here** on a bar (which now opens the player on that passage, the
  passage's length kept, else 4 bars, looping, instead of going to the practice mock). Graphite instrument surface in
  both themes: the bar ruler on top (tap two bars to choose a passage, drag the bracket ends to change it, "Whole
  piece" to clear; the playhead rides it), Play/Stop (64 px), the bar and count-in beats, the pace −/+ in 5 % steps
  (30–150 %, default 80 %, the largest number) with "♩ = 106 of 132", Loop and Count-in toggles, and a lane per part
  (on/off, volume). The device's own part (the reader's seat in the group) starts off. On the pages: the passage as a
  wash, the playing bar outlined in the page's own ink (light, dimmed and inverted pages), and the spread follows the
  playing bar. Pace, mix, loop and passage are this device's (`localStorage` `folio.play:{score_id}`), never a mark.
  A scanned book's panel says "Convert to Digital to play it"; a digital book imported before today says to import
  the MusicXML again.

## Verified (local stack, 2026-10-30)

- Op. 18/1 re-imported through the real `import_musicxml` handler on the local stack: 4 tracks, 313 bars, 36.9 KB MIDI,
  2.1 s; `scores.playback` recorded.
- In the in-app browser (1194×834 and 834×1194, light and dark, signed in as the local test pianist): Violin I off,
  80 % (transport 105.6 qpm = 132 × 0.8), bars 19–26 chosen by two taps on the ruler: count-in then 19 → 26 and back to
  19 with no second count-in; 8 bars in 13.5 s (1.69 s a bar, expected 1.70); Violin I's notes skipped (80) while the
  other three sounded; + to 85 % changed the tempo to 112.2 at once; Loop off stops after bar 26; Loop from here on bar
  7 gave 7–14 looping. AudioContext `running`; no console errors. Screenshots in the session scratchpad.

## Not verified

- Real iPad Safari: the audio unlock in the tap, the silent switch (`audioSession`), sample decoding memory, touch on
  the sliders. Device audio latency (the bar highlight does not compensate output latency). The Capacitor shell.
- What it sounds like: checked by the transport, the scheduled notes and the AudioContext, not by ear (the pane was
  hidden, so its rAF and timers were throttled; bar timing there was jittery, the average was right).
- Convert to Digital end to end with a real PDF (the step is covered by `test_omr_convert`; no live convert was run).
- Hosted: the migration is not pushed, and hosted digital books imported before today have no playback until reimported.

## Decisions

- Digital books only; the PDF stays the truth for reading, the transcription is what plays.
- Same score object as rehearsal: loop, pace and mix are per-device practice state, not marks (012).
- The practice mock (`Practice.tsx`, its styles and mock state) is retired (2026-10-30) and the Read | Practise
  toggle with it: the player is a panel on the Stand, not a second mode, so it has one door, the "…" menu (plus Loop
  from here on a bar). An old `/practice` link falls to the Shelf.

## Next steps

1. iPad pass: play, loop, mute, pace on the device and in the Capacitor shell; ear check of the samples.
2. A metronome during playback (only the count-in clicks today); repeats played as written (today once, as printed).
3. Push the migration to hosted and reimport the hosted demo books (CK).
