# Voice-note ground truth

Recordings of rehearsal instructions, each labelled with what the librarian should make of it. The audio goes
through Muse Voice Transcribe, then one Spark call decides **position** (which bar or bars, a rehearsal mark, or
global), **audience** (everyone, one part, or one person) and **content** (kind and text). The labels in
`script.csv` are the answer key; `scripts/voice_eval.py` (to come) scores a run against them.

## Recording

- One file per line of `script.csv`, named by its `id` (`v01.m4a`, …). iPhone Voice Memos is fine. Audio files are
  gitignored; the CSV is the committed truth.
- Say it the way a conductor says it mid-rehearsal: quick, half-turned to the players, not read aloud. Keep the
  words close to the `text` column but do not force them; if you change wording, update the column.
- Record in the real room if you can (chairs, pages, a note being played). A second pass by a different voice,
  in files `v01b.m4a`, …, tells us whether the model keys on words or on voice.
- Lines marked `expect = none` are chatter that must produce **no** annotation. They are the most important
  negatives.

## Columns

`id, text, position, bar_from, bar_to, audience, kind, expect`

- `position`: `bar` (one bar), `range`, `mark` (rehearsal letter, resolved by the score), `global`, `none`.
- `audience`: `ensemble`, `part:<name>` (seat name as in `parts.name`), `member` (one named person).
- `kind`: `cut`, `dynamic`, `marking`, `text`, `breath`, `bowing`, `none`.
- `expect`: the one-line annotation the stand should show, or `none`.

Parts used: Violin I, Violin II, Viola, Cello (the Hart House quartet) and Soprano, Alto, Tenor, Bass (choir).
