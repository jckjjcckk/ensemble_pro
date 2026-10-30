"""The two prompts. v4d = the app's prompt (`app.librarian.voice_prompt.build_prompt`) with the always-on confidence
field (as `voice_stream.spark_lat` v4c adds it), i.e. the text eval's v4d. v4e = v4d plus three edits:
(a) score landmarks with bars in the facts, and a rule to resolve places named from them;
(b) the book's groups in the facts, and the exclusion rule refers to them;
(c) a musical-terms mishearing line.
Examples unchanged. Nothing in app/ is edited: v4e is built here by string replacement (each asserted to hit once)."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.librarian import voice_prompt as vp
from app.librarian.voice_prompt import ScoreFacts

from ...voice_stream.spark_lat import CONF_RULE, SCHEMA_C


@dataclass(frozen=True)
class ScoreFactsE(ScoreFacts):
    """ScoreFacts plus what the book knows about its landmarks and groups."""
    landmarks: list[str] = field(default_factory=list)       # "key change at bar 97 (E-flat major)"
    groups: list[tuple[str, list[str]]] = field(default_factory=list)

    def as_text(self) -> str:
        out = super().as_text()
        out += "\nLandmarks: " + ("; ".join(self.landmarks) if self.landmarks else "none listed") + "."
        if self.groups:
            out += "\nGroups: " + " ".join(f"{g}: {', '.join(ps)}." for g, ps in self.groups)
        return out


def _conf(user: str) -> str:
    user = user.replace(vp.SCHEMA, SCHEMA_C)
    user = user.replace("\n\nWorked examples", f"\n{CONF_RULE}\n\nWorked examples")
    user = user.replace('{"none": true}.', '{"none": true, "confidence": <0.0-1.0>}.')
    assert CONF_RULE in user and SCHEMA_C in user
    return user


def plain(facts: ScoreFacts) -> ScoreFacts:
    """The facts as today's app builds them (no landmarks, no groups)."""
    return ScoreFacts(parts=facts.parts, members=facts.members, bar_first=facts.bar_first, bar_last=facts.bar_last,
                      rehearsal_marks=facts.rehearsal_marks)


def build_v4d(transcript: str, facts: ScoreFacts) -> tuple[str, str]:
    system, user = vp.build_prompt(transcript, plain(facts))
    return system, _conf(user)


# (a) landmarks
POS_OLD = '"global" for the whole piece or its very beginning or end (bars null).'
POS_NEW = ('"global" for the whole piece or its very beginning or end (bars null). When the score facts list a\n'
           '  landmark with its bars, a place named from it resolves to bars ("two after the key change", "the bar\n'
           '  before the double bar", "from the coda", "in the slow section"): use "bar" or "range"; a landmark the\n'
           '  facts do not list stays "mark".')
# (b) groups
GRP_OLD = ("list every other part of X's group only, never parts of the other group (strings: Violin I,\n"
           "  Violin II, Viola, Cello; voices: Soprano, Alto, Tenor, Bass).")
GRP_NEW = ("list every other part of the widest group in the score facts that holds X (or of the group the\n"
           "  speaker names: \"strings except the cellos\"), never parts of another group; a soloist alone in its group\n"
           "  is excluded from the Orchestra (\"everyone but the piano\" = every Orchestra part). A group the speaker\n"
           "  names (\"the strings\", \"the orchestra\") is every part listed in it.")
# (c) musical terms
TERM_OLD = 'part may be "except". Numbers are usually right.'
TERM_NEW = ('part may be "except". Musical terms are misheard too: "fermenta" = fermata, "pizza cutter" =\n'
            '  pizzicato, "retard and oh" = ritardando, "attempt oh" = a tempo, "spores and oh" = sforzando, "arc oh" =\n'
            '  arco, "stuck auto" = staccato, "the visi" = divisi, "lay gato" = legato, "coal leg no" = col legno; a word\n'
            '  that sounds like a musical term is that term. Numbers are usually right.')
EDITS = {"a": (POS_OLD, POS_NEW), "b": (GRP_OLD, GRP_NEW), "c": (TERM_OLD, TERM_NEW)}


def build_v4e(transcript: str, facts: ScoreFactsE, parts: str = "abc") -> tuple[str, str]:
    system, user = vp.build_prompt(transcript, facts)
    for k in parts:
        old, new = EDITS[k]
        assert user.count(old) == 1, old
        user = user.replace(old, new)
    return system, _conf(user)


BUILD = {"v4d": build_v4d, "v4e": build_v4e}
