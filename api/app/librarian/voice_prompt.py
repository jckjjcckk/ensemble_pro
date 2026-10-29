"""Voice note to proposed mark (013): the score facts, the Spark prompt and the proposal check.

One Spark call per utterance (effort low, JSON only). The answer is one mark, a list of marks, or
`{"none": true}`. A mark the check refuses is dropped: the quote must be a verbatim span of the transcript,
bars inside the score, the audience a known part, member or the ensemble. The admin confirms every survivor.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

POSITIONS = {"bar", "range", "mark", "global"}
KINDS = {"cut", "dynamic", "marking", "text", "breath", "bowing"}


@dataclass(frozen=True)
class ScoreFacts:
    parts: list[str]
    members: list[str]
    bar_first: int = 1
    bar_last: int = 240
    rehearsal_marks: list[str] = field(default_factory=lambda: list("ABCDEF"))

    def as_text(self) -> str:
        return (f"Parts: {', '.join(self.parts)}.\n"
                f"Members (players addressed by name): {', '.join(self.members)}.\n"
                f"Bars: {self.bar_first} to {self.bar_last}.\n"
                f"Rehearsal letters: {', '.join(self.rehearsal_marks)}.")


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
