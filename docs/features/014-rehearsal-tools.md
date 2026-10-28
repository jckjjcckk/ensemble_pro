# 014 Rehearsal tools: slow down, loop, play other parts, mix volumes

Status: idea (the practice screen exists as a mock; no playback engine) | Meta model: none for playback (Spark may later rate trouble spots; MIDI listening is a stretch).

## Purpose

From the cellist's feedback: what a player wants from the score in a rehearsal or practice room is to slow a
passage down, loop it, hear the other parts, and mix their volumes. Build-queue item 8 (Nov 1): practice mode,
minimal. Done means: the pianist account loops the corrected passage at 80 %.

## What exists

- `web/src/app/Practice.tsx` with mock state: Violin I, loop 178 to 190, tempo 120 of 132 (91 %), metronome
  on, other parts on, listening "following" / "lost", trouble-spot heat under the ruler, four-session
  history. Loop bracket on the ruler mirrored as a tint in the score. Tempo is the biggest number on screen.
  Controls operable with one hand (dock 52 to 72 pt). `docs/acceptance/touch.md` lines 9 and 10.
- Path A scores carry tempo and duration (`scores.tempo_bpm`, `duration_sec`); MusicXML is the input a
  synth needs. For scanned scores playback needs OMR output (005), which is why OMR sits behind practice mode.

## Decisions and open questions

- Other-parts playback engine: MuseScore headless audio vs music21 MIDI + a browser synth. Pick whichever
  works first on Nov 1.
- Mix volumes = per-part gain on the synth; "play other parts" = mute my part.
- Casio PX-S1100 over USB MIDI through the Mac as a sound source in the video, not in the code; MIDI
  listening (`mido`) is a stretch after Nov 1. Hardware for practice mode around day 5: Casio over USB, two
  iPads on the same wifi.
- Same score object as rehearsal: loop and tempo are per-device practice state, not marks (012).

## Next steps

1. Nov 1: select bars, loop, tempo, hear other parts, from the Op. 18/1 MusicXML.
2. Volume mix per part; metronome.
