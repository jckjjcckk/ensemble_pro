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


def v5(transcript: str, facts: ScoreFacts, holdout: set[str], examples: list[dict]) -> tuple[str, str]:
    """v4's rules without the worked examples: does the few-shot earn its tokens?"""
    system, user = v2(transcript, facts, holdout, examples)
    assert RULES in user
    return system, user.replace(RULES, RULES_V4)


# The same prompt as v4, run again: the run-to-run spread of Spark at effort low.
v4r2 = v4


# The app's prompt is v4f (below) with the full example list (no hold-out in production): keep the two in step.
from app.librarian import voice_prompt as _app  # noqa: E402

# v4d (2026-10-30, docs/features/013-text-eval.md): v4 plus three rule edits found by the text eval. Flow marks: a
# start point for a later run, or anything the speaker asks to be written, is a mark. Roster scope: an exclusion
# stays inside the excluded part's group, and a section or name not in the score facts is the ensemble with the
# word kept in the text. The app's prompt is v4d (v4 stays here as scored on 2026-10-29).
FLOW_OLD = "Telling a part where it comes in (its entry) is a mark.\n"
FLOW_NEW = ("Telling a part where it comes in (its entry) is a mark. A start point for a later run (\"next time\",\n"
            "  \"tomorrow\", \"after the break\") is a mark at that place (text \"Start here next time\"), and so is anything the\n"
            "  speaker asks to have written or marked.\n")
GROUP_OLD = """When the speaker excludes a part, list every other part of its group
  (strings: Violin I, Violin II, Viola, Cello; voices: Soprano, Alto, Tenor, Bass)."""
GROUP_NEW = """When the speaker excludes a part ("everyone except X", "everyone else",
  "all but X"), list every other part of X's group only, never parts of the other group (strings: Violin I,
  Violin II, Viola, Cello; voices: Soprano, Alto, Tenor, Bass)."""
ROSTER_OLD = """part may be "except". Numbers are usually right."""
ROSTER_NEW = """part may be "except". Numbers are usually right. A section or a name that is not in the score facts (e.g.
  "the winds", "percussion", a player not in Members) is not a part or member: use "ensemble" and keep that word in
  the text ("Winds softer at 12"), never the nearest-sounding part."""


RULES_V4D = RULES_V4
for _old, _new in ((FLOW_OLD, FLOW_NEW), (GROUP_OLD, GROUP_NEW), (ROSTER_OLD, ROSTER_NEW)):
    assert RULES_V4D.count(_old) == 1, _old
    RULES_V4D = RULES_V4D.replace(_old, _new)


def v4d(transcript: str, facts: ScoreFacts, holdout: set[str], examples: list[dict]) -> tuple[str, str]:
    system, user = v3(transcript, facts, holdout, examples)
    return system, user.replace(RULES, RULES_V4D)


# v4e (2026-10-30, docs/features/013-v4e-eval.md): v4d plus the eval's parts (a) and (b), not (c) (the musical-terms
# mishearing line had no measured gain). (b) the book's groups are listed in the facts and an exclusion refers to them
# instead of the two hardcoded groups; (a) the book's landmarks with bars, and a place named from one resolves to bars.
# v4d stays above for reproducibility.
GROUPS_V4E_OLD = """list every other part of X's group only, never parts of the other group (strings: Violin I,
  Violin II, Viola, Cello; voices: Soprano, Alto, Tenor, Bass)."""
GROUPS_V4E_NEW = """list every other part of the widest group in the score facts that holds X (or of the group the
  speaker names: "strings except the cellos"), never parts of another group; a soloist alone in its group
  is excluded from the Orchestra ("everyone but the piano" = every Orchestra part). A group the speaker
  names ("the strings", "the orchestra") is every part listed in it."""
LANDMARKS_V4E_OLD = '"global" for the whole piece or its very beginning or end (bars null).'
LANDMARKS_V4E_NEW = ('"global" for the whole piece or its very beginning or end (bars null). When the score facts list a\n'
                     '  landmark with its bars, a place named from it resolves to bars ("two after the key change", "the bar\n'
                     '  before the double bar", "from the coda", "in the slow section"): use "bar" or "range"; a landmark the\n'
                     '  facts do not list stays "mark".')
V4E_EDITS = [(LANDMARKS_V4E_OLD, LANDMARKS_V4E_NEW), (GROUPS_V4E_OLD, GROUPS_V4E_NEW)]

RULES_V4E = RULES_V4D
for _old, _new in V4E_EDITS:
    assert RULES_V4E.count(_old) == 1, _old
    RULES_V4E = RULES_V4E.replace(_old, _new)

# v4f (2026-10-31, CK's decision): the stand text keeps the conductor's own words, as a player pencils what was
# said ("you're too sharp on the F" stays that), never a remedy ("Lower the F") or a category ("Intonation: F");
# cleanup is light (filler, the addressee, a misheard term's spelling, digits, standard abbreviations). Scored on
# the clean 130, messy 50 and messy 100 sets in experiments/voice_text/v4f. The app's prompt is v4f.
TEXT_V4F_OLD = """- text: what a player would pencil on the part, short, standard abbreviations (mf, sfz, cresc., dim., pizz., rit.),
  with the place: "mf at bar 9", "Cut 130–137", "From E: lighter"."""
TEXT_V4F_NEW = """- text: the conductor's own words with the place, the way a player pencils what was said: keep the remark as it
  was said, never a remedy or a category word in its place. "Seconds, bar 30, you're too sharp on the F" is
  "You're too sharp on the F, bar 30" (not "Lower the F", not "Intonation: F"); "in tune at bar fifteen" is "In
  tune at bar 15"; "we're dragging from E" is "Dragging from E" (not "Push on from E"). Clean up lightly: drop
  filler, false starts and the name of the part or player addressed, spell a misheard musical term right, write
  numbers as digits and dynamics and terms the short way (mf, sfz, cresc., dim., pizz., rit.): "mf at bar 9",
  "Cut 130–137"."""
assert RULES_V4E.count(TEXT_V4F_OLD) == 1, TEXT_V4F_OLD
RULES_V4F = RULES_V4E.replace(TEXT_V4F_OLD, TEXT_V4F_NEW)

# The app's prompt is checked here at import: its rules are v4f (the header line aside) and its schema the list one.
assert _app.RULES.split("\n", 1)[1] == RULES_V4F.split("\n", 1)[1] and _app.SCHEMA == SCHEMA_LIST


# Prompts that read both recognisers' transcripts (diarisation and push-to-talk) of the same file.
TWO_TRANSCRIPTS: set[str] = set()

_HEARD_V4 = RULES_V4[RULES_V4.index("- The transcript is machine speech recognition"):]
assert _HEARD_V4.endswith("Numbers are usually right.")

# v6: v4 with the mishearing rule made generic (no example names, no "accept/stop" = except): how much of v4 is
# the hint written for v15 and v18?
RULES_V6 = RULES_V4.replace(_HEARD_V4, '''- The transcript is machine speech recognition and mishears words. A word that sounds like a part, a seat nickname
  or a member's name is that part or person. Numbers are usually right.''')


def v6(transcript: str, facts: ScoreFacts, holdout: set[str], examples: list[dict]) -> tuple[str, str]:
    system, user = v3(transcript, facts, holdout, examples)
    return system, user.replace(RULES, RULES_V6)


# v7: v4 plus fidelity of the stand text (the judge's refusals were dropped negations and invented detail).
RULES_V7 = RULES_V4.replace('''- quote: copy a contiguous span''', '''- text keeps what was said, including negations and contrasts ("not the octave", "instead of", "the opposite");
  never add an instruction that was not said.
- quote: copy a contiguous span''')


def v7(transcript: str, facts: ScoreFacts, holdout: set[str], examples: list[dict]) -> tuple[str, str]:
    system, user = v3(transcript, facts, holdout, examples)
    return system, user.replace(RULES, RULES_V7)


# v8: v6's generic rules, but Spark reads both recognisers' transcripts (diarisation and push-to-talk mode of the
# same file; they mishear differently). Does a second hearing replace the hint v4 wrote for v15 and v18?
TWO_TRANSCRIPTS.add("v8")


def v8(transcript: str, facts: ScoreFacts, holdout: set[str], examples: list[dict], alt: str | None = None
       ) -> tuple[str, str]:
    system, user = v6(transcript, facts, holdout, examples)
    one = f"Transcript of what the conductor said:\n\"{transcript}\"\n\n"
    assert one in user
    if alt is None:
        return system, user
    two = ("Two speech recognisers transcribed the same recording and mishear differently; use both to decide what "
           "was said. The quote must be copied exactly from one of them.\n"
           f"Transcript 1:\n\"{transcript}\"\nTranscript 2:\n\"{alt}\"\n\n")
    return system, user.replace(one, two)
