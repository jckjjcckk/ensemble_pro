"""Every prompt version the voice eval tried, kept with its scores in results/. Each builder returns
(system, user) for one transcript. Few-shot versions take `holdout`: the CSV line ids that must never appear
as an example (the line being scored, and for a retake its base line).
"""

from __future__ import annotations

import json

from app.librarian.voice_prompt import ScoreFacts

SCHEMA = ('{"position": "bar|range|mark|global", "bar_from": int|null, "bar_to": int|null, '
          '"audience": ["ensemble" | "part:<part name>" | "member:<name>", ...], '
          '"kind": "cut|dynamic|marking|text|breath|bowing", "text": "<the one-line mark for the stand>", '
          '"quote": "<verbatim span of the transcript the mark comes from>"}')


def v1(transcript: str, facts: ScoreFacts, holdout: set[str], examples: list[dict]) -> tuple[str, str]:
    system = ("You turn a conductor's spoken rehearsal instruction into a proposed mark on the players' parts. "
              "Answer with JSON only.")
    user = (f"Score facts:\n{facts.as_text()}\n\n"
            f"Transcript of what the conductor said:\n\"{transcript}\"\n\n"
            f"If it is an instruction to write on the music, answer one object:\n{SCHEMA}\n"
            "If it is not an instruction to mark the music, answer {\"none\": true}.")
    return system, user


SCHEMA_LIST = ('[{"position": "bar|range|mark|global", "bar_from": int|null, "bar_to": int|null, '
               '"audience": ["ensemble" | "part:<part name>" | "member:<name>", ...], '
               '"kind": "cut|dynamic|marking|text|breath|bowing", "text": "<the one-line mark for the stand>", '
               '"quote": "<verbatim span of the transcript the mark comes from>"}, ...]')

RULES = """Rules (examples here are made up; none is a line being scored):
- Not every sentence is a mark. Telling the players where to start playing ("again from the beginning", "OK, letter
  A, off we go", "once more from 57" with nothing to write), logistics (breaks, chairs, the time) and praise are not
  marks: answer {"none": true}. A start point that comes with something to remember ("from 57 and keep it light")
  is a mark at that bar.
- The speaker may correct themself mid-sentence ("18, no, 19"; "violas, sorry, cellos"): the last version wins.
  Ignore filler, repeated words and false starts.
- position: "bar" for one bar (bar_to = bar_from) or two adjacent bars named as one place (a pickup into bar 81 is
  bar_from 80, bar_to 81); "range" for "from X to Y" (bar_to = Y, or null for "to the end"); "mark" when the place
  is a rehearsal letter (bars null, name the letter in text); "global" when the place has no bar or letter (the
  whole piece, the beginning, the ending, the coda): bars null.
- audience: "ensemble" when everyone is meant or nobody is named. Seat nicknames: firsts = Violin I, seconds =
  Violin II, fiddles = both violin parts. When the speaker excludes a part, list every other part of its group
  (strings: Violin I, Violin II, Viola, Cello; voices: Soprano, Alto, Tenor, Bass). A player addressed by name is
  "member:<name>", only when the name is clearly said.
- kind: "dynamic" for loudness and its changes; "marking" for a symbol or playing technique written on the music
  (pizz., arco, mute, accent, fermata, vibrato); "bowing" for up/down bow; "breath" for a breath mark; "cut" for a
  cut or a skipped repeat; "text" for any other spoken instruction (tempo, rit., character, rhythm, tuning, pitch).
- text: what a player would pencil on the part, short, standard abbreviations (mf, sfz, cresc., dim., pizz., rit.),
  with the place: "mf at bar 9", "Cut 130–137", "From E: lighter".
- quote: copy a contiguous span of the transcript exactly, character for character.
- When one instruction has marks at different places or for different audiences, give one object per mark."""


def v2(transcript: str, facts: ScoreFacts, holdout: set[str], examples: list[dict]) -> tuple[str, str]:
    system = ("You turn a conductor's spoken rehearsal instruction into proposed marks on the players' parts. "
              "Answer with JSON only.")
    user = (f"Score facts:\n{facts.as_text()}\n\n{RULES}\n\n"
            f"Transcript of what the conductor said:\n\"{transcript}\"\n\n"
            f"Answer a JSON array of marks:\n{SCHEMA_LIST}\n"
            "or, if there is nothing to write on the music, {\"none\": true}.")
    return system, user
