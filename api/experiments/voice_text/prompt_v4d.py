"""v4d = v4c plus two rule fixes from the text eval (docs/features/013-text-eval.md):
1. flow marks: a start point for a later run, or anything the speaker asks to be written, is a mark;
2. roster scope: a section or name not in the score facts is the ensemble with the word kept in the text, and an
   exclusion ("everyone else", "except") stays inside the excluded part's group.
Examples in the new wording are deliberately not this set's lines (no "brass", no "Marco"). The rule strings live in
`experiments/voice/prompts.py` (RULES_V4D), which the app's prompt is checked against."""

from __future__ import annotations

from ..voice.prompts import FLOW_NEW, FLOW_OLD, GROUP_NEW, GROUP_OLD, ROSTER_NEW, ROSTER_OLD
from ..voice_stream.spark_lat import build


def build_v4d(transcript: str, uid: str) -> tuple[str, str]:
    system, user = build("v4c", transcript, uid)
    for old, new in ((FLOW_OLD, FLOW_NEW), (GROUP_OLD, GROUP_NEW), (ROSTER_OLD, ROSTER_NEW)):
        assert user.count(old) == 1, old
        user = user.replace(old, new)
    return system, user
