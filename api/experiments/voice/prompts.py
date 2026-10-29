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
