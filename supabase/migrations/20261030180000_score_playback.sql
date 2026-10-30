-- Play the parts (014; CK 2026-10-30): a digital book's MIDI and bar map, for the browser's player.
--
-- At import of a MusicXML and at the end of Convert to Digital the API (service role, music21, no model) writes two
-- files into the `scores` bucket next to the book's other files, under the score's own folder, so the existing
-- storage policies (read = can read the score) already cover them:
--
--   {score_id}/playback/score.mid   type-1 MIDI: track 0 conductor (tempo, meter), then one track per part in score
--                                   order, named with the book's `parts.name` ("Violin I", "Cello", one "Piano")
--   {score_id}/playback/bars.json   {version, ppq, parts, quarters, bars: [{bar, at, quarters}],
--                                    tempos: [{bar, at, qpm, bpm, beat, text, marked}],
--                                    meters: [{bar, at, meter, beats, beat_quarters}]}   (at = quarter notes)
--
-- and records them here: {"midi": key, "bar_map": key, "source_id": uuid, "parts": [...], "bars": n, "made_at": ts}.
-- Null for a scanned book until it is converted. Readable with the score row (the same policies); nothing in the
-- browser writes it. Practice state (pace, mix, loop) is per device and is not stored.

alter table public.scores
  add column if not exists playback jsonb;
