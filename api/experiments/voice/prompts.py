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


# Few-shot order of preference: one of each kind and position, two negatives. The first EXAMPLES_N ids not held
# out are used, so the line being scored (and a retake's base line) is never shown.
FEW_SHOT_ORDER = ["v02", "v08", "v18", "v21", "v22", "v25", "v14", "v30", "v13", "v15", "v26", "v27", "v20", "v03",
                  "v17", "v19"]
EXAMPLES_N = 8


def _examples(examples: list[dict], holdout: set[str]) -> str:
    by_id = {e["id"]: e for e in examples}
    chosen = [by_id[i] for i in FEW_SHOT_ORDER if i not in holdout][:EXAMPLES_N]
    def ans(a: object) -> str:
        return json.dumps(a if isinstance(a, list) or (isinstance(a, dict) and a.get("none")) else [a],
                          ensure_ascii=False)
    return "\n\n".join(f"Transcript: \"{e['transcript']}\"\nAnswer: {ans(e['answer'])}" for e in chosen)


def v3(transcript: str, facts: ScoreFacts, holdout: set[str], examples: list[dict]) -> tuple[str, str]:
    system, user = v2(transcript, facts, holdout, examples)
    head, tail = user.split("Transcript of what the conductor said:", 1)
    user = (f"{head}Worked examples (other instructions, same score):\n\n{_examples(examples, holdout)}\n\n"
            f"Transcript of what the conductor said:{tail}")
    return system, user


# v4: rules revised after reading the v1-v3 misses (made-up examples still; tuned on the same 30 lines, so the
# retakes and a second voice are the check on overfitting).
RULES_V4 = (RULES
            .replace('''  is a mark at that bar.''', '''  is a mark at that bar. Telling a part where it comes in (its entry) is a mark.''')
            .replace('''  Ignore filler, repeated words and false starts.''',
                     '''  A correction replaces only what it corrects: keep the bar and the instruction already said. Ignore filler,
  repeated words and false starts.''')
            .replace('''"mark" when the place
  is a rehearsal letter (bars null, name the letter in text); "global" when the place has no bar or letter (the
  whole piece, the beginning, the ending, the coda): bars null.''',
                     '''"mark" when the place
  is a landmark the score must resolve: a rehearsal letter, a double bar, a key change, a coda, a section (bars
  null, name the landmark in text); "global" for the whole piece or its very beginning or end (bars null).''')
            .replace('''- audience: "ensemble" when everyone is meant or nobody is named.''',
                     '''- audience: "ensemble" when everyone is meant (the whole group, the whole choir, tutti) or nobody is named.''')
            .replace('''- When one instruction has marks at different places or for different audiences, give one object per mark.''',
                     '''- One object per audience: marks for different audiences are separate objects; several places for the same
  audience in one breath are one mark whose bars cover them.
- The transcript is machine speech recognition and mishears words. A word that sounds like a part, a seat nickname
  or a member's name (e.g. "Chelos", "Violets", "Lynn") is that part or person; "accept" or "stop" just before a
  part may be "except". Numbers are usually right.'''))


def v4(transcript: str, facts: ScoreFacts, holdout: set[str], examples: list[dict]) -> tuple[str, str]:
    system, user = v3(transcript, facts, holdout, examples)
    assert RULES in user
    return system, user.replace(RULES, RULES_V4)
