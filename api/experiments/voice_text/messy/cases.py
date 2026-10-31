"""The messy set: 50 lines of everyday rehearsal speech, written to be bad, with strict ground truth in the v4 schema.

Same score facts as the clean set (`voice_eval.FACTS`): parts Violin I, Violin II, Viola, Cello, Soprano, Alto,
Tenor, Bass; members Lin, Inès; bars 1-240; letters A-F with no letter-to-bar map.

Three groups:
- `comm` (20): poor communication, the transcript is what was said.
- `stt` (20): poor transcription, written in the style of Voice Transcribe's realtime output (numerals, lost
  punctuation, sound-alikes; see voice_stream/results/realtime_endpointing.json).
- `unrec` (10): the speech is unrecoverable. `gt` is "none" (nothing should be written) or "flag" (a mark, but a
  field cannot be known: that field accepts anything, and the mark must come with confidence below the gate, 0.9,
  so it reaches the admin instead of the stand). v4 has no "uncertain" field: confidence is the only flag it has.
  `also` lists the other outcome when it is also defensible.

Each case: id, cat (group), sub (what makes it messy), diff 1-3, text, answers (as in ../cases.py), note (what a
careful human librarian would write), intended (what the speaker meant, when the text cannot carry it).

    uv run python -m experiments.voice_text.messy.cases      # writes set.jsonl and prints counts
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from ..cases import AUD, _l


class _Any(list):
    """A field that accepts any value (the uncertain field of a 'flag' case)."""

    def __contains__(self, _x) -> bool:  # noqa: D105
        return True

    def __repr__(self) -> str:
        return "ANY"


ANY = "ANY"


def M(pos, bf, bt, aud, kind, text, keys=()):
    def acc(v):
        return _Any(["*"]) if v == ANY else _l(v)

    auds = _Any(["*"]) if aud == ANY else [sorted(AUD[a] for a in s.split("+")) for s in _l(aud)]
    return {"position": acc(pos), "bar_from": acc(bf), "bar_to": acc(bt), "audience": auds, "kind": acc(kind),
            "text": text, "keys": list(keys)}


CASES: list[dict] = []
DYN_TXT = ["dynamic", "text"]


def C(cid, cat, sub, diff, text, *answers, note, intended=None, gt=None, also=None):
    alts = [a if isinstance(a, list) else [a] for a in answers]
    CASES.append({"id": cid, "cat": cat, "sub": sub, "diff": diff, "text": text, "instruction": cat != "unrec",
                  "answers": alts, "note": note, "intended": intended, "gt": gt, "also": also})


# ---------------- poor communication (20) ----------------
C("pc01", "comm", "rambling", 2,
  "ok so um, what I'm hearing is, yeah, the second violins, that whole passage, let's say from thirty, thirty-ish, "
  "it's just too much, bring it down",
  M(["bar", "range"], 30, 30, "V2", DYN_TXT, "Softer from 30", ["soft|down|less|p|back|light"]),
  note="Vln II, bar 30: 'softer from here'. No end bar was said; a range to the end is not supported.")
C("pc02", "comm", "mid_change", 1, "Cellos, staccato at forty, no wait, forty-two.",
  M("bar", 42, 42, "Vc", "marking", "stacc. at 42", ["stacc"]), note="Vc, stacc. at 42 (40 corrected).")
C("pc03", "comm", "mid_change", 2,
  "Violas, sorry, no, seconds, I mean, the second violins, accent on the downbeat of 77.",
  M("bar", 77, 77, "V2", "marking", "Accent, bar 77", ["accent|>"]), note="Vln II, accent on beat 1 of 77.")
C("pc04", "comm", "aside", 2,
  "Sopranos, breathe after 52, and, I know it's a long phrase, I know, I'm sorry, but basses, crescendo into 56.",
  [M("bar", 52, 52, "S", "breath", "Breath after 52", ["breath"]),
   M(["bar", "range"], [55, 56], 56, "B", "dynamic", "cresc. into 56", ["cresc"])],
  note="Two cards: S breath after 52; B cresc. into 56. The apology is not a mark.")
C("pc05", "comm", "aside", 2,
  "Firsts, mute on at 100, oh and somebody remind me to email the hall about Thursday, and cellos pizz at 104.",
  [M("bar", 100, 100, "V1", "marking", "Mute on at 100", ["mute"]),
   M("bar", 104, 104, "Vc", "marking", "pizz. at 104", ["pizz"])],
  note="Vln I mute on 100; Vc pizz. 104. The email aside is not a mark.")
C("pc06", "comm", "roster_mix", 3, "Trumpets and cellos, bar 66, both of you, accent.",
  M("bar", 66, 66, "Vc", "marking", "Accent at 66", ["accent"]),
  M("bar", 66, 66, "E", "marking", "Trumpets and cellos: accent at 66", ["accent", "trumpet"]),
  [M("bar", 66, 66, "Vc", "marking", "Accent at 66", ["accent"]),
   M("bar", 66, 66, "E", "marking", "Trumpets: accent at 66", ["accent", "trumpet"])],
  note="Vc accent at 66; trumpets are not in the book (admin's card). Cello alone, ensemble with 'trumpets' kept, "
       "or both are defensible.")
C("pc07", "comm", "roster_mix", 3, "Clarinets, you're too loud at 140, and violas, you too.",
  M("bar", 140, 140, "Va", DYN_TXT, "Softer at 140", ["soft|less|down|p|back|loud"]),
  [M("bar", 140, 140, "Va", DYN_TXT, "Softer at 140", ["soft|less|down|p|back|loud"]),
   M("bar", 140, 140, "E", DYN_TXT, "Clarinets softer at 140", ["clarinet"])],
  M("bar", 140, 140, "E", DYN_TXT, "Clarinets and violas softer at 140", ["clarinet"]),
  note="Va softer at 140; clarinets are not in the book.")
C("pc08", "comm", "negative", 1, "Don't rush at 60, everybody.",
  M("bar", 60, 60, "E", "text", "Don't rush at 60", ["rush|tempo|steady|hold"]), note="Tutti, 'don't rush' at 60.")
C("pc09", "comm", "negative", 2, "Basses, whatever you do, don't breathe in bar 118.",
  M("bar", 118, 118, "B", ["breath", "text"], "No breath in 118", ["no|don|carry|without"]),
  note="B, 'no breath' through 118. The negation must survive.")
C("pc10", "comm", "implicit", 1, "Bar 92, the tenors, yeah, that one, again, but softer, much softer.",
  M("bar", 92, 92, "T", "dynamic", "Much softer at 92", ["soft|p|less"]), note="T, much softer (pp?) at 92.")
C("pc11", "comm", "sarcasm", 3,
  "Oh brilliant, cellos, really, forte at 30, that's exactly what pianissimo looks like.",
  M("bar", 30, 30, "Vc", "dynamic", "pp at 30", ["pp|soft|p"]),
  note="Vc pp at 30: the sarcasm says they played forte where pianissimo is written. 'f at 30' is the wrong card.")
C("pc12", "comm", "nickname", 2, "Linny, bar 84, a bit more bow.",
  M("bar", 84, 84, "Lin", ["text", "bowing"], "More bow at 84", ["bow"]), note="Lin, 'more bow' at 84.")
C("pc13", "comm", "nickname", 2, "Benji, you're rushing at 150.",
  M("bar", 150, 150, "E", "text", "Benji: don't rush at 150", ["rush"]),
  note="Benji is not in Members: ensemble card with the name kept, the admin re-addresses it.")
C("pc14", "comm", "nickname", 2, "Concertmaster, up bow at 9.",
  M("bar", 9, 9, ["V1", "E"], "bowing", "Up bow at 9", ["up"]),
  note="The concertmaster leads the firsts: Vln I up bow at 9 (ensemble with the word kept is the v4d-literal card).")
C("pc15", "comm", "dyn_unnamed", 2, "Violas, I can't hear you at all at 20, that's the tune.",
  M("bar", 20, 20, "Va", DYN_TXT, "More at 20, melody", ["more|out|louder|f|melody|tune"]),
  note="Va, 'bring out, melody' at 20.")
C("pc16", "comm", "dyn_unnamed", 2, "At 120 the sopranos are just drowning everyone, it's a wall of sound.",
  M("bar", 120, 120, "S", DYN_TXT, "Less at 120", ["less|soft|back|down|p|light|drown|wall"]),
  note="S, 'less' at 120. 'drown'/'wall' added 2026-10-31: v4f keeps the conductor's words on the stand.")
C("pc17", "comm", "rambling", 3,
  "right, so, okay, the thing about bar one-seventy, and this is everyone, is that it's not a ritardando, I know "
  "it looks like one, it's in tempo, keep going.",
  M("bar", 170, 170, "E", "text", "In tempo at 170 (no rit.)", ["tempo|no|keep"]),
  note="Tutti, 'in tempo, no rit.' at 170. A bare 'rit.' would be the opposite card.")
C("pc18", "comm", "mid_change", 1, "Violas, crescendo at 30, actually, no, make it a diminuendo.",
  M("bar", 30, 30, "Va", "dynamic", "dim. at 30", ["dim"]), note="Va, dim. at 30 (cresc. corrected).")
C("pc19", "comm", "mid_change", 3,
  "Cellos and basses, wait, basses are the singers, just cellos, pizz at 12, and the singers, the basses I mean, "
  "breathe at 14.",
  [M("bar", 12, 12, "Vc", "marking", "pizz. at 12", ["pizz"]), M("bar", 14, 14, "B", "breath", "Breath at 14", ["breath"])],
  note="Vc pizz. 12; B (voices) breath at 14.")
C("pc20", "comm", "implicit", 3, "From 44 to 48 everyone, and same thing again at 60 to 64, lighter.",
  M("range", 44, 64, "E", DYN_TXT, "Lighter 44–48 and 60–64", ["light"]),
  [M("range", 44, 48, "E", DYN_TXT, "Lighter 44–48", ["light"]), M("range", 60, 64, "E", DYN_TXT, "Lighter 60–64", ["light"])],
  note="Tutti, 'lighter' over 44–48 and 60–64: two cards, or one per the v4 one-audience rule.")

# ---------------- poor transcription (20) ----------------
C("pt01", "stt", "dropped_word", 2, "and violas from 96 to the end no vibrato",
  M("range", 96, "end", "Va", "marking", "senza vib. 96 to end", ["vib"]),
  note="'Cellos' was dropped: the text supports Va only.", intended="part:Cello;part:Viola")
C("pt02", "stt", "dropped_word", 2, "bar 33 you're sharp on the high G",
  M("bar", 33, 33, "E", "text", "Sharp on high G, bar 33", ["sharp|lower"]),
  note="'Inès,' was dropped: ensemble is all the text supports; low confidence is the useful answer.",
  intended="member:Inès")
C("pt03", "stt", "homophone", 2, "Sopranos bar too breathe after the first note",
  M("bar", 2, 2, "S", "breath", "Breath after 1st note, bar 2", ["breath"]), note="'bar too' = bar 2.")
C("pt04", "stt", "homophone", 2, "seconds bar for teen down bow",
  M("bar", 14, 14, "V2", "bowing", "Down bow at 14", ["down"]), note="'for teen' = fourteen.")
C("pt05", "stt", "homophone", 1, "cellos bar 40 you're two loud",
  M("bar", 40, 40, "Vc", DYN_TXT, "Softer at 40", ["soft|less|down|p|loud|back"]), note="'two loud' = too loud.")
C("pt06", "stt", "homophone", 1, "violas bah 60 accent",
  M("bar", 60, 60, "Va", "marking", "Accent at 60", ["accent"]), note="'bah' = bar.")
C("pt07", "stt", "homophone", 2, "everyone at 110 pianist please",
  M("bar", 110, 110, "E", "dynamic", "p at 110", ["p|soft"]),
  note="'pianist' = piano (there is no piano part).")
C("pt08", "stt", "merged", 2, "cellospizz at thirty one",
  M("bar", 31, 31, "Vc", "marking", "pizz. at 31", ["pizz"]), note="'cellospizz' = cellos, pizz.")
C("pt09", "stt", "wrong_number", 2, "bar 1 40 everyone forte",
  M("bar", 140, 140, "E", "dynamic", "f at 140", ["f"]), note="'1 40' = one forty = 140, as realtime STT splits it.")
C("pt10", "stt", "part_name", 1, "Vidos pizz at 58",
  M("bar", 58, 58, "Va", "marking", "pizz. at 58", ["pizz"]), note="'Vidos' = violas.")
C("pt11", "stt", "part_name", 1, "Autos from 20 to 24 staccato",
  M("range", 20, 24, "A", "marking", "stacc. 20–24", ["stacc"]), note="'Autos' = altos (seen in CK's takes).")
C("pt12", "stt", "part_name", 2, "base at 200 you're coming in early",
  M("bar", 200, 200, "B", "text", "Entry at 200, don't come in early", ["early|earl|late|wait"]),
  note="'base' = basses.")
C("pt13", "stt", "term_mangled", 3, "Violets attempt oh at 75",
  M("bar", 75, 75, "Va", "text", "a tempo at 75", ["tempo"]), note="'Violets' = violas, 'attempt oh' = a tempo.")
C("pt14", "stt", "term_mangled", 2, "everybody retard and oh at bar 130 to 134",
  M("range", 130, 134, "E", "text", "rit. 130–134", ["rit"]), note="'retard and oh' = ritardando.")
C("pt15", "stt", "term_mangled", 2, "cellos pizza cutter at 61",
  M("bar", 61, 61, "Vc", "marking", "pizz. at 61", ["pizz"]), note="'pizza cutter' = pizzicato.")
C("pt16", "stt", "term_mangled", 1, "Chelos, put a fermenta on the last note of 99",
  M("bar", 99, 99, "Vc", "marking", "Fermata, last note of 99", ["fermata"]), note="'Chelos' = cellos, 'fermenta' = fermata.")
C("pt17", "stt", "run_on", 3,
  "okay second violins 80 to 84 softer and then the violas at 85 come in strong forte and everybody else just wait",
  [M("range", 80, 84, "V2", "dynamic", "Softer 80–84", ["soft|p|less|dim"]),
   M("bar", 85, 85, "Va", "dynamic", "f entry at 85", ["f"])],
  note="Vln II softer 80–84; Va f entry at 85. 'everybody else just wait' is not a mark.")
C("pt18", "stt", "stray_reply", 2, "tenors bar 66 breathe after the tie which one the first tie yeah after the first one",
  M("bar", 66, 66, "T", "breath", "Breath after 1st tie, bar 66", ["breath"]),
  note="'which one' is a tenor asking; the answer is the first tie.")
C("pt19", "stt", "stray_reply", 3, "cellos bar 50 up bow is that 50 or 15 50 five zero up bow",
  M("bar", 50, 50, "Vc", "bowing", "Up bow at 50", ["up"]), note="A player asks '50 or 15?'; the conductor says 50.")
C("pt20", "stt", "homophone", 2, "fore the sopranos bar 140 mezzo piano",
  M("bar", 140, 140, "S", "dynamic", "mp at 140", ["mp"]), note="'fore' = for; not bar 4.")

# ---------------- unrecoverable (10) ----------------
FLAG_NOTE = " The answer to be right: a card with confidence below 0.9 (the admin asks), or none where 'also'."
C("un01", "unrec", "sarcasm", 2, "Lovely, let's never play 55 like that again.",
  gt="none", also="flag", note="Nothing to write: no instruction in it. A low-confidence card at 55 is acceptable.")
C("un02", "unrec", "implicit", 2, "that bar again, softer",
  M(ANY, ANY, ANY, "E", ["dynamic", "text"], "Softer (bar?)", []), gt="flag", also="none",
  note="An instruction with no place: a careful librarian asks 'which bar?'." + FLAG_NOTE)
C("un03", "unrec", "wrong_number", 3, "tenors bar 2 forty accent",
  M("bar", [2, 40, 240], [2, 40, 240], "T", "marking", "Accent, bar 40 or 240?", ["accent"]), gt="flag",
  note="'2 forty' is 240 or a stray 2 before 40: the bar is unknown." + FLAG_NOTE)
C("un04", "unrec", "garbled", 3, "the cello the bar the thirty the uh fermenta no the other one",
  M(ANY, ANY, ANY, "Vc", ANY, "Bar 30: not the fermata, the other one (ask)", []), gt="flag", also="none",
  note="Cello, bar 30, some mark that is not a fermata: what to write is unknown." + FLAG_NOTE)
C("un05", "unrec", "garbled", 2, "uh violas at the um can we just the thing at the end of the",
  gt="none", note="Nothing recoverable.")
C("un06", "unrec", "cut_off", 2, "Sopranos, at bar sixty-",
  gt="none", note="Cut off before the instruction.")
C("un07", "unrec", "who", 2, "you, yes you, bar 88, too loud",
  M("bar", 88, 88, "E", DYN_TXT, "Softer at 88 (who?)", ["soft|less|loud|down|p"]), gt="flag",
  note="The place and the instruction are clear, the player is not: ensemble card, the admin asks." + FLAG_NOTE)
C("un08", "unrec", "deferred", 2, "Everyone, cut from forty to, uh, to, hmm, I'll tell you later.",
  gt="none", also="flag", note="The cut is not decided yet; a low-confidence card at 40 is acceptable.")
C("un09", "unrec", "undecided", 2, "Violas, louder at 70, no, softer, no, actually, I don't know, let's hear it.",
  gt="none", note="Undecided: nothing to write.")
C("un10", "unrec", "garbled", 3, "base is a piano tuna at for tea",
  M(ANY, ANY, ANY, ["B", "E"], ANY, "?", []), gt="flag", also="none",
  note="Maybe 'basses, piano, tune at forty': too far gone to write; any card must reach the admin." + FLAG_NOTE)


def main() -> None:
    ids = [c["id"] for c in CASES]
    assert len(ids) == len(set(ids)) == 50
    out = Path(__file__).with_name("set.jsonl")
    out.write_text("".join(json.dumps(c, ensure_ascii=False, default=str) + "\n" for c in CASES))
    print(len(CASES), Counter(c["cat"] for c in CASES), Counter(c["diff"] for c in CASES))
    print(Counter(c["gt"] for c in CASES if c["cat"] == "unrec"))


if __name__ == "__main__":
    main()
