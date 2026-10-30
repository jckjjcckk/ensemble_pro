"""Voice note to proposed mark (013): the score facts, the Spark prompt and the proposal check.

One Spark call per utterance (effort low, JSON only). The answer is one mark, a list of marks, or
`{"none": true}`. A mark the check refuses is dropped: the quote must be a verbatim span of the transcript,
bars inside the score, the audience a known part, member or the ensemble. The admin confirms every survivor.

The facts carry the book's groups (`derive_groups`, from the part names: strings, voices, woodwinds, brass,
percussion, keyboard; a concerto is a Soloist plus the Orchestra), which the exclusion rule refers to (prompt v4e,
docs/features/013-v4e-eval.md part b).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from .header import family

POSITIONS = {"bar", "range", "mark", "global"}
KINDS = {"cut", "dynamic", "marking", "text", "breath", "bowing"}


# ---------- the book's groups (v4e part b) ----------

SECTION_OF_FAMILY = {
    "violin": "Strings", "viola": "Strings", "cello": "Strings", "double bass": "Strings",
    "flute": "Woodwinds", "piccolo": "Woodwinds", "oboe": "Woodwinds", "english horn": "Woodwinds",
    "clarinet": "Woodwinds", "bassoon": "Woodwinds",
    "horn": "Brass", "trumpet": "Brass", "trombone": "Brass", "tuba": "Brass",
    "timpani": "Percussion",
    "piano": "Keyboard", "organ": "Keyboard",
    "soprano": "Voices", "alto": "Voices", "tenor": "Voices", "bass": "Voices", "chorus": "Voices",
}
# Names the header's synonym table does not know, checked first (an "Alto Saxophone" is not an alto voice).
EXTRA_SECTION = [
    (r"\b(saxophones?|sax|contrabassoon|cor anglais|recorders?)\b", "Woodwinds"),
    (r"\b(cornets?|euphonium|flugelhorn)\b", "Brass"),
    (r"\b(percussion|drums?|snare|cymbals?|triangle|glockenspiel|xylophone|marimba|vibraphone|tam-tam|tambourine|"
     r"bells|chimes)\b", "Percussion"),
    (r"\b(celesta|harpsichord|cembalo|keyboard|harmonium)\b", "Keyboard"),
    (r"\b(mezzo|baritone|countertenor|contralto|voice|voices|choir)\b", "Voices"),
]
INSTRUMENT_SECTIONS = ("Strings", "Woodwinds", "Brass", "Percussion")


def section_of(name: str, parts: list[str] | None = None) -> str | None:
    """The section a part sits in ("Strings", "Woodwinds", "Brass", "Percussion", "Keyboard", "Voices"), else None
    (a harp, a guitar). "Bass" is the voice in a book with other voices or no strings, else the double bass."""
    low = name.lower()
    for pat, sec in EXTRA_SECTION:
        if re.search(pat, low):
            return sec
    fam = family(name)             # the header's synonym table (Italian, German, abbreviations)
    sec = SECTION_OF_FAMILY.get(fam or "")
    if fam == "bass" and parts is not None:
        others = [section_of(p) for p in parts if p != name]
        if "Voices" not in others and "Strings" in others:
            return "Strings"
    return sec


def derive_groups(parts: list[str]) -> list[tuple[str, list[str]]]:
    """The book's groups from its part names, in the order the facts list them.

    A book whose instruments span two or more of strings, woodwinds, brass and percussion has an Orchestra (its
    instruments; voices are their own group). In such a book a part named "solo", or failing that its one piano, is
    the Soloist and is not in the Orchestra or any section. Then each section with parts, in score order. A string
    quartet is Strings; a choir is Voices; strings and choir are Strings and Voices (the v4d rule's two groups)."""
    sec = {p: section_of(p, parts) for p in parts}
    orchestral = {s for s in sec.values() if s in INSTRUMENT_SECTIONS}
    has_orchestra = len(orchestral) >= 2
    soloists = [p for p in parts if re.search(r"\bsolo\b", p, re.I)]
    if not soloists and has_orchestra:
        pianos = [p for p in parts if sec[p] == "Keyboard" and family(p) == "piano"]
        soloists = pianos if len(pianos) == 1 else []
    out: list[tuple[str, list[str]]] = []
    if soloists:
        out.append(("Soloist" if len(soloists) == 1 else "Soloists", soloists))
    if has_orchestra:
        out.append(("Orchestra", [p for p in parts if p not in soloists and sec[p] != "Voices"]))
    for s in dict.fromkeys(v for v in sec.values() if v):
        members = [p for p in parts if sec[p] == s and p not in soloists]
        if members and all(members != g for _, g in out):
            out.append((s, members))
    return out


@dataclass(frozen=True)
class ScoreFacts:
    parts: list[str]
    members: list[str]
    bar_first: int = 1
    bar_last: int = 240
    rehearsal_marks: list[str] = field(default_factory=lambda: list("ABCDEF"))
    # None: the line is left out (the eval prompts before v4e); the app always passes a list (`derive_groups`).
    groups: list[tuple[str, list[str]]] | None = None

    def as_text(self) -> str:
        out = (f"Parts: {', '.join(self.parts) or 'none named'}.\n"
               f"Members (players addressed by name): {', '.join(self.members) or 'none'}.\n"
               f"Bars: {self.bar_first} to {self.bar_last}.\n"
               f"Rehearsal letters: {', '.join(self.rehearsal_marks) or 'none'}.")
        if self.groups:
            out += "\nGroups: " + " ".join(f"{g}: {', '.join(ps)}." for g, ps in self.groups)
        return out


def parse_answer(text: str) -> object:
    """The first JSON value in the reply (code fences tolerated)."""
    s = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", s, re.S)
    if m:
        s = m.group(1).strip()
    start = min([i for i in (s.find("{"), s.find("[")) if i >= 0], default=-1)
    if start < 0:
        raise ValueError("no JSON in reply")
    return json.JSONDecoder().raw_decode(s[start:])[0]


def _fold(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower()).strip()


def quote_ok(quote: str, transcript: str) -> bool:
    """Verbatim span, case and whitespace aside; outer punctuation of the quote is ignored."""
    q = _fold(quote).strip(" \"'“”‘’.,;:!?")
    return bool(q) and q in _fold(transcript)


def check_mark(mark: dict, transcript: str, facts: ScoreFacts) -> str | None:
    """None when the mark stands, else the reason it is refused."""
    if mark.get("position") not in POSITIONS:
        return f"position {mark.get('position')!r}"
    if mark.get("kind") not in KINDS:
        return f"kind {mark.get('kind')!r}"
    for k in ("bar_from", "bar_to"):
        v = mark.get(k)
        if v is None:
            continue
        if not isinstance(v, int) or isinstance(v, bool) or not facts.bar_first <= v <= facts.bar_last:
            return f"{k} {v!r} outside {facts.bar_first}-{facts.bar_last}"
    if mark.get("position") in {"bar", "range"} and mark.get("bar_from") is None:
        return "bar position without bar_from"
    if isinstance(mark.get("bar_from"), int) and isinstance(mark.get("bar_to"), int) and mark["bar_to"] < mark["bar_from"]:
        return "bar_to before bar_from"
    aud = mark.get("audience")
    aud = aud if isinstance(aud, list) else [aud]
    if not aud:
        return "no audience"
    for a in aud:
        if a == "ensemble":
            continue
        if isinstance(a, str) and a.startswith("part:") and a[5:] in facts.parts:
            continue
        if isinstance(a, str) and a.startswith("member:") and a[7:] in facts.members:
            continue
        return f"audience {a!r}"
    if not isinstance(mark.get("text"), str) or not mark["text"].strip():
        return "no text"
    if not isinstance(mark.get("quote"), str) or not quote_ok(mark["quote"], transcript):
        return f"quote not verbatim: {mark.get('quote')!r}"
    return None


def checked_marks(answer: object, transcript: str, facts: ScoreFacts) -> tuple[list[dict], list[str]]:
    """(marks that stand, reasons for each refused one). `{"none": true}` is no marks and no refusals."""
    if isinstance(answer, dict) and answer.get("none") is True:
        return [], []
    if isinstance(answer, dict) and isinstance(answer.get("marks"), list):
        answer = answer["marks"]
    marks = answer if isinstance(answer, list) else [answer]
    ok, refused = [], []
    for m in marks:
        if not isinstance(m, dict):
            refused.append(f"not an object: {m!r}")
            continue
        why = check_mark(m, transcript, facts)
        (refused.append(why) if why else ok.append(m))
    return ok, refused


# ---------- the prompt (eval version v4, chosen 2026-10-29; v4d rule edits 2026-10-30: flow marks and roster
# scope, docs/features/013-text-eval.md; v4e 2026-10-30: the book's groups, docs/features/013-v4e-eval.md) ----------

SYSTEM = ("You turn a conductor's spoken rehearsal instruction into proposed marks on the players' parts. "
          "Answer with JSON only.")

SCHEMA = ('[{"position": "bar|range|mark|global", "bar_from": int|null, "bar_to": int|null, "audience": ["ensemble" | "part:<part name>" | "member:<name>", ...], "kind": "cut|dynamic|marking|text|breath|bowing", "text": "<the one-line mark for the stand>", "quote": "<verbatim span of the transcript the mark comes from>"}, ...]')

RULES = """Rules:
- Not every sentence is a mark. Telling the players where to start playing ("again from the beginning", "OK, letter
  A, off we go", "once more from 57" with nothing to write), logistics (breaks, chairs, the time) and praise are not
  marks: answer {"none": true}. A start point that comes with something to remember ("from 57 and keep it light")
  is a mark at that bar. Telling a part where it comes in (its entry) is a mark. A start point for a later run ("next time",
  "tomorrow", "after the break") is a mark at that place (text "Start here next time"), and so is anything the
  speaker asks to have written or marked.
- The speaker may correct themself mid-sentence ("18, no, 19"; "violas, sorry, cellos"): the last version wins.
  A correction replaces only what it corrects: keep the bar and the instruction already said. Ignore filler,
  repeated words and false starts.
- position: "bar" for one bar (bar_to = bar_from) or two adjacent bars named as one place (a pickup into bar 81 is
  bar_from 80, bar_to 81); "range" for "from X to Y" (bar_to = Y, or null for "to the end"); "mark" when the place
  is a landmark the score must resolve: a rehearsal letter, a double bar, a key change, a coda, a section (bars
  null, name the landmark in text); "global" for the whole piece or its very beginning or end (bars null).
- audience: "ensemble" when everyone is meant (the whole group, the whole choir, tutti) or nobody is named. Seat nicknames: firsts = Violin I, seconds =
  Violin II, fiddles = both violin parts. When the speaker excludes a part ("everyone except X", "everyone else",
  "all but X"), list every other part of the widest group in the score facts that holds X (or of the group the
  speaker names: "strings except the cellos"), never parts of another group; a soloist alone in its group
  is excluded from the Orchestra ("everyone but the piano" = every Orchestra part). A group the speaker
  names ("the strings", "the orchestra") is every part listed in it. A player addressed by name is
  "member:<name>", only when the name is clearly said.
- kind: "dynamic" for loudness and its changes; "marking" for a symbol or playing technique written on the music
  (pizz., arco, mute, accent, fermata, vibrato); "bowing" for up/down bow; "breath" for a breath mark; "cut" for a
  cut or a skipped repeat; "text" for any other spoken instruction (tempo, rit., character, rhythm, tuning, pitch).
- text: what a player would pencil on the part, short, standard abbreviations (mf, sfz, cresc., dim., pizz., rit.),
  with the place: "mf at bar 9", "Cut 130–137", "From E: lighter".
- quote: copy a contiguous span of the transcript exactly, character for character.
- One object per audience: marks for different audiences are separate objects; several places for the same
  audience in one breath are one mark whose bars cover them.
- The transcript is machine speech recognition and mishears words. A word that sounds like a part, a seat nickname
  or a member's name (e.g. "Chelos", "Violets", "Lynn") is that part or person; "accept" or "stop" just before a
  part may be "except". Numbers are usually right. A section or a name that is not in the score facts (e.g.
  "the winds", "percussion", a player not in Members) is not a part or member: use "ensemble" and keep that word in
  the text ("Winds softer at 12"), never the nearest-sounding part."""

# Eight worked examples from api/fixtures/voice/script.csv. The eval held each scored line out of this list.
EXAMPLES = """Transcript: "Second violins, from forty-two to forty-eight we're cutting that, go straight to forty-nine."
Answer: [{"position": "range", "bar_from": 42, "bar_to": 48, "audience": ["part:Violin II"], "kind": "cut", "text": "Cut 42–48", "quote": "Second violins, from forty-two to forty-eight we're cutting that, go straight to forty-nine."}]

Transcript: "Bar one-twelve, everyone, crescendo through to one-sixteen."
Answer: [{"position": "range", "bar_from": 112, "bar_to": 116, "audience": ["ensemble"], "kind": "dynamic", "text": "cresc. 112–116", "quote": "Bar one-twelve, everyone, crescendo through to one-sixteen."}]

Transcript: "Fiddles, bar seven, down bow, both of you."
Answer: [{"position": "bar", "bar_from": 7, "bar_to": 7, "audience": ["part:Violin I", "part:Violin II"], "kind": "bowing", "text": "Down bow at bar 7", "quote": "Fiddles, bar seven, down bow, both of you."}]

Transcript: "Bar sixty-four, altos and tenors, breath mark, then sixty-five sforzando, everyone."
Answer: [{"position": "bar", "bar_from": 64, "bar_to": 64, "audience": ["part:Alto", "part:Tenor"], "kind": "breath", "text": "Breath at 64", "quote": "Bar sixty-four, altos and tenors, breath mark, then sixty-five sforzando, everyone."}, {"position": "bar", "bar_from": 65, "bar_to": 65, "audience": ["ensemble"], "kind": "dynamic", "text": "sfz at 65", "quote": "Bar sixty-four, altos and tenors, breath mark, then sixty-five sforzando, everyone."}]

Transcript: "Inès, bar thirty, that harmonic, try it on the A string."
Answer: [{"position": "bar", "bar_from": 30, "bar_to": 30, "audience": ["member:Inès"], "kind": "text", "text": "Harmonic on the A string, bar 30", "quote": "Inès, bar thirty, that harmonic, try it on the A string."}]

Transcript: "Viola, ritard in the bar before letter F, then a tempo at F."
Answer: [{"position": "mark", "bar_from": null, "bar_to": null, "audience": ["part:Viola"], "kind": "text", "text": "rit. before F, a tempo at F", "quote": "Viola, ritard in the bar before letter F, then a tempo at F."}]

Transcript: "Okay that's lunch, back at one thirty."
Answer: {"none": true}

Transcript: "Right, bar one, here we go."
Answer: {"none": true}"""


def build_prompt(transcript: str, facts: ScoreFacts) -> tuple[str, str]:
    """(system, user) for one utterance; send with effort low and an 8k output budget."""
    user = (f"Score facts:\n{facts.as_text()}\n\n{RULES}\n\n"
            f"Worked examples (other instructions, same score):\n\n{EXAMPLES}\n\n"
            f"Transcript of what the conductor said:\n\"{transcript}\"\n\n"
            f"Answer a JSON array of marks:\n{SCHEMA}\n"
            "or, if there is nothing to write on the music, {\"none\": true}.")
    return SYSTEM, user
