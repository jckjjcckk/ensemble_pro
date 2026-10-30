"""The text set: 100 instructions and 30 non-instructions, each with ground truth in the v4 schema.

Score facts are the eval's (`voice_eval.FACTS`): parts Violin I, Violin II, Viola, Cello, Soprano, Alto, Tenor,
Bass; members Lin, Inès; bars 1-240; letters A-F with no letter-to-bar map. So a letter, a key change, a double bar
or a coda is `position: mark` with null bars, and "the bar before C" stays a `mark` (the fixture cannot resolve it).

Ground truth is strict on the v4 rules, fair where the taxonomy is genuinely open: a field may list several
accepted values, and a case may list alternative answers (e.g. one mark covering two places for one audience, as
the v4 rule says, or the two marks a musician would also accept). `keys` are the words the stand text must carry
(lenient text match; see run.text_ok).

    uv run python -m experiments.voice_text.cases      # writes set.jsonl (the set as data) and prints counts
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

AUD = {"V1": "part:Violin I", "V2": "part:Violin II", "Va": "part:Viola", "Vc": "part:Cello", "S": "part:Soprano",
       "A": "part:Alto", "T": "part:Tenor", "B": "part:Bass", "Lin": "member:Lin", "Ines": "member:Inès",
       "E": "ensemble"}


def _l(x):
    return x if isinstance(x, list) else [x]


def M(pos, bf, bt, aud, kind, text, keys=()):
    """One expected mark. pos/bf/bt/kind: a value or a list of accepted values. aud: "V1+V2" or a list of accepted
    sets. bt "end" = to the end (null or the last bar). text is the reference stand text; keys must appear in it."""
    auds = [sorted(AUD[a] for a in s.split("+")) for s in _l(aud)]
    return {"position": _l(pos), "bar_from": _l(bf), "bar_to": _l(bt), "audience": auds, "kind": _l(kind),
            "text": text, "keys": list(keys)}


CASES: list[dict] = []


def C(cid, cat, diff, text, *answers, note=None, intended=None):
    """answers: one or more accepted answers; each is a mark (dict) or a list of marks. No answers = no instruction."""
    alts = [a if isinstance(a, list) else [a] for a in answers]
    CASES.append({"id": cid, "cat": cat, "diff": diff, "text": text, "instruction": bool(alts), "answers": alts,
                  "note": note, "intended": intended})


# ---------------- dynamics (9) ----------------
C("d01", "dynamics", "easy", "Everyone, bar twenty, forte.", M("bar", 20, 20, "E", "dynamic", "f at bar 20", ["f"]))
C("d02", "dynamics", "easy", "Cellos, mezzo forte at fifty-two.", M("bar", 52, 52, "Vc", "dynamic", "mf at 52", ["mf"]))
C("d03", "dynamics", "easy", "Sopranos, from eighty to eighty-four, diminuendo.",
  M("range", 80, 84, "S", "dynamic", "dim. 80–84", ["dim"]))
C("d04", "dynamics", "easy", "Bar 118, subito piano, everybody.", M("bar", 118, 118, "E", "dynamic", "sub. p at 118", ["p"]))
C("d05", "dynamics", "easy", "Violas, pianissimo at one forty.", M("bar", 140, 140, "Va", "dynamic", "pp at 140", ["pp"]))
C("d06", "dynamics", "medium", "Basses, crescendo from ninety to ninety-three, but don't get there too early.",
  M("range", 90, 93, "B", "dynamic", "cresc. 90–93, arrive late", ["cresc"]))
C("d07", "dynamics", "easy", "Second violins, bar sixty-one, that's fortissimo, really go for it.",
  M("bar", 61, 61, "V2", "dynamic", "ff at 61", ["ff"]))
C("d08", "dynamics", "medium", "Everyone, from one sixty to the end, keep it pianissimo.",
  M("range", 160, "end", "E", "dynamic", "pp 160 to end", ["pp"]))
C("d09", "dynamics", "easy", "Altos, sforzando on the downbeat of 33.", M("bar", 33, 33, "A", "dynamic", "sfz at 33", ["sfz"]))

# ---------------- articulation (8) ----------------
C("a01", "articulation", "easy", "Cellos, pizz at bar thirty-eight.", M("bar", 38, 38, "Vc", "marking", "pizz. at 38", ["pizz"]))
C("a02", "articulation", "easy", "Violas, arco at forty-four.", M("bar", 44, 44, "Va", "marking", "arco at 44", ["arco"]))
C("a03", "articulation", "easy", "Everybody, accents on every note in bar 70.",
  M("bar", 70, 70, "E", "marking", "Accents, bar 70", ["accent"]))
C("a04", "articulation", "easy", "Second violins, staccato in bars twelve to fifteen.",
  M("range", 12, 15, "V2", "marking", "stacc. 12–15", ["stacc"]))
C("a05", "articulation", "medium", "Firsts, mutes on at letter E.", M("mark", None, None, "V1", "marking", "Mute on at E", ["mute", "e"]))
C("a06", "articulation", "medium", "Sopranos, the high note in 96, put a fermata on it.",
  M("bar", 96, 96, "S", "marking", "Fermata, bar 96", ["fermata"]))
C("a07", "articulation", "easy", "Cellos, no vibrato from one twenty to one twenty-eight.",
  M("range", 120, 128, "Vc", "marking", "senza vib. 120–128", ["vib"]))
C("a08", "articulation", "easy", "Everyone, bar 200, marcato, heavy.", M("bar", 200, 200, "E", "marking", "marc. at 200", ["marc"]))

# ---------------- tempo (8) ----------------
C("t01", "tempo", "easy", "Everyone, ritardando in bar 47.", M("bar", 47, 47, "E", "text", "rit. at 47", ["rit"]))
C("t02", "tempo", "easy", "A tempo at bar fifty, everyone.", M("bar", 50, 50, "E", "text", "a tempo at 50", ["tempo"]))
C("t03", "tempo", "medium", "From letter C, a little faster, everyone.",
  M("mark", None, None, "E", "text", "From C: a little faster", ["c", "faster|mosso|accel|quicker"]))
C("t04", "tempo", "hard", "Bar eighty-eight, rit, then a tempo at ninety.",
  M("range", 88, 90, "E", "text", "rit. 88, a tempo at 90", ["rit", "tempo"]),
  [M("bar", 88, 88, "E", "text", "rit. at 88", ["rit"]), M("bar", 90, 90, "E", "text", "a tempo at 90", ["tempo"])],
  note="two places, one audience: one mark per the v4 rule, two marks also accepted")
C("t05", "tempo", "medium", "Choir, don't rush bars thirty to thirty-four.",
  M("range", 30, 34, ["E", "S+A+T+B"], "text", "Don't rush 30–34", ["rush"]))
C("t06", "tempo", "medium", "Everyone, the last bar is a big ritardando.",
  M(["global", "bar"], [None, 240], [None, 240], "E", "text", "Big rit., last bar", ["rit"]),
  note="the last bar is a 'global' place in v4; bar 240 also accepted")
C("t07", "tempo", "medium", "From bar one-fifty, everyone, broaden, molto rit to the end.",
  M("range", 150, "end", "E", "text", "molto rit. 150 to end", ["rit|broad"]))
C("t08", "tempo", "medium", "Sopranos, at the key change, a tempo.",
  M("mark", None, None, "S", "text", "a tempo at the key change", ["tempo", "key"]))

# ---------------- cuts and jumps (8) ----------------
C("c01", "cut", "easy", "Everyone, skip forty-two to forty-eight.", M("range", 42, 48, "E", "cut", "Cut 42–48", ["42", "48"]))
C("c02", "cut", "easy", "We're cutting bars one hundred to one-oh-eight, everybody.",
  M("range", 100, 108, "E", "cut", "Cut 100–108", ["100", "108"]))
C("c03", "cut", "hard", "Cellos, after bar sixty jump straight to seventy-two.",
  M("range", [60, 61], [71, 72], "Vc", "cut", "Cut 61–71 (60 to 72)", ["cut|jump|skip"]),
  note="cut bars are 61-71; 60 to 72 (the jump) also accepted")
C("c04", "cut", "medium", "No repeat at bar 24, everyone, go straight on.",
  M("bar", 24, 24, "E", "cut", "No repeat at 24", ["repeat"]))
C("c05", "cut", "medium", "From letter D to letter E is out, everyone.", M("mark", None, None, "E", "cut", "Cut D to E", ["d", "e"]))
C("c06", "cut", "easy", "Altos and tenors, cut eighty-one through eighty-four.",
  M("range", 81, 84, "A+T", "cut", "Cut 81–84", ["81", "84"]))
C("c07", "cut", "medium", "Everybody, cut from 210 to the end, we stop at 209.",
  M("range", 210, "end", "E", "cut", "Cut 210 to end", ["210"]))
C("c08", "cut", "medium", "Violas, the cut is now forty-two to fifty, not forty-eight.",
  M("range", 42, 50, "Va", "cut", "Cut 42–50", ["42", "50"]))

# ---------------- bowing and breathing (8) ----------------
C("b01", "bowing_breath", "easy", "Firsts, up bow at bar 19.", M("bar", 19, 19, "V1", "bowing", "Up bow at 19", ["up"]))
C("b02", "bowing_breath", "easy", "Cellos, start bar 44 down bow.", M("bar", 44, 44, "Vc", "bowing", "Down bow at 44", ["down"]))
C("b03", "bowing_breath", "medium", "Second violins, two up bows in a row at sixty-two, hooked.",
  M("bar", 62, 62, "V2", "bowing", "Two up bows (hooked), bar 62", ["up|hook"]))
C("b04", "bowing_breath", "medium", "Violas, slur the two eighths in bar 15, one bow.",
  M("bar", 15, 15, "Va", ["bowing", "marking"], "Slur, one bow, bar 15", ["slur|one bow"]))
C("b05", "bowing_breath", "easy", "Sopranos, breathe at the end of bar 27.", M("bar", 27, 27, "S", "breath", "Breath end of 27", ["breath"]))
C("b06", "bowing_breath", "hard", "Basses, no breath between 50 and 51, carry it over.",
  M(["bar", "range"], 50, 51, "B", ["breath", "text"], "No breath 50–51", ["no"]),
  note="the negation must survive in the stand text")
C("b07", "bowing_breath", "easy", "Altos, a breath mark after the first beat of 75.",
  M("bar", 75, 75, "A", "breath", "Breath after beat 1, bar 75", ["breath"]))
C("b08", "bowing_breath", "medium", "Cellos, separate bows at 88, don't slur.",
  M("bar", 88, 88, "Vc", ["bowing", "marking"], "Separate bows at 88", ["separ|sep|slur"]))

# ---------------- balance (7) ----------------
C("l01", "balance", "medium", "Less cello at sixty, let the tune through.",
  M("bar", 60, 60, "Vc", ["dynamic", "text"], "Less at 60", ["less|softer|back|down|p|lighter"]))
C("l02", "balance", "medium", "Violas, you're covering the melody at 90, back off.",
  M("bar", 90, 90, "Va", ["dynamic", "text"], "Back off at 90", ["back|softer|less|lighter|down|p|cover"]))
C("l03", "balance", "hard", "Bring out the altos at bar 12, everyone else lighter.",
  [M("bar", 12, 12, "A", ["dynamic", "text"], "Bring out, bar 12", ["out|more|lead"]),
   M("bar", 12, 12, ["S+T+B", "E"], ["dynamic", "text"], "Lighter at 12", ["light|less|softer|back"])],
  note="'everyone else' of a choir part = the other voices (v4 exclusion rule)")
C("l04", "balance", "hard", "Too much brass at sixty.",
  M("bar", 60, 60, "E", ["dynamic", "text"], "Less brass at 60", ["brass"]),
  note="roster gap: no brass part in this book; the only legal audience is ensemble")
C("l05", "balance", "easy", "Firsts, more at bar 33, you're the melody there.",
  M("bar", 33, 33, "V1", ["dynamic", "text"], "More at 33 (melody)", ["more|out|melody|f|louder"]))
C("l06", "balance", "easy", "Basses, louder please from 150 to 160, I can't hear you.",
  M("range", 150, 160, "B", "dynamic", "Louder 150–160", ["louder|more|f|out"]))
C("l07", "balance", "medium", "Second violins, balance down at letter B, the violas have it.",
  M("mark", None, None, "V2", ["dynamic", "text"], "At B: down, violas lead", ["b"]))

# ---------------- rehearsal flow marks (5) ----------------
C("f01", "flow", "medium", "Next time we start at bar twelve, write that in.",
  M("bar", 12, 12, "E", "text", "Start here next time, bar 12", ["start|begin"]))
C("f02", "flow", "medium", "For tomorrow, we'll begin at letter D, put a mark there.",
  M("mark", None, None, "E", "text", "Start at D tomorrow", ["d"]))
C("f03", "flow", "hard", "Start at bar 12 next time.",
  M("bar", 12, 12, "E", "text", "Start at 12 next time", ["start|begin"]),
  note="a future start point: something to remember, so a mark; v4's rule on start points is the test")
C("f04", "flow", "easy", "From 57 next time, and keep it light.",
  M("bar", 57, 57, "E", "text", "From 57: light", ["light"]))
C("f05", "flow", "medium", "Seconds, you'll come in at 81 after the cut, mark your entry.",
  M("bar", 81, 81, "V2", "text", "Entry at 81", ["entry|come|in"]))

# ---------------- rehearsal letters (6) ----------------
C("r01", "letter", "easy", "Letter A, everyone, mezzo piano.", M("mark", None, None, "E", "dynamic", "mp at A", ["mp", "a"]))
C("r02", "letter", "easy", "Cellos, at letter B, pizz.", M("mark", None, None, "Vc", "marking", "pizz. at B", ["pizz", "b"]))
C("r03", "letter", "easy", "From letter E to letter F, everybody softer.",
  M("mark", None, None, "E", "dynamic", "Softer E to F", ["e", "f"]))
C("r04", "letter", "medium", "Violas, crescendo into letter C.", M("mark", None, None, "Va", "dynamic", "cresc. into C", ["cresc", "c"]))
C("r05", "letter", "medium", "Sopranos and altos, at letter A breathe together.",
  M("mark", None, None, "S+A", "breath", "Breath together at A", ["breath", "a"]))
C("r06", "letter", "easy", "Firsts, at letter C, up bow.", M("mark", None, None, "V1", "bowing", "Up bow at C", ["up", "c"]))

# ---------------- relative references (6) ----------------
C("x01", "relative", "medium", "The bar before C, everyone, ritardando.",
  M("mark", None, None, "E", "text", "rit. bar before C", ["rit", "c"]))
C("x02", "relative", "medium", "Two bars after the key change, cellos, forte.",
  M("mark", None, None, "Vc", "dynamic", "f 2 bars after the key change", ["f", "key"]))
C("x03", "relative", "medium", "Violas, three after letter D, that's an accent.",
  M("mark", None, None, "Va", "marking", "Accent 3 after D", ["accent", "d"]))
C("x04", "relative", "medium", "Everyone, the bar after the double bar, subito piano.",
  M("mark", None, None, "E", "dynamic", "sub. p after the double bar", ["p", "double"]))
C("x05", "relative", "medium", "Basses, at the coda, breathe before you come in.",
  M("mark", None, None, "B", "breath", "Breath before the coda entry", ["breath", "coda"]))
C("x06", "relative", "hard", "Firsts, mutes off two bars after bar forty.",
  M("bar", 42, 42, "V1", "marking", "Mute off at 42", ["mute"]), note="arithmetic: two bars after 40 = 42")

# ---------------- numbers as words (4) ----------------
C("w01", "words", "medium", "Everyone, bar two hundred and twelve, piano.", M("bar", 212, 212, "E", "dynamic", "p at 212", ["p"]))
C("w02", "words", "medium", "Cellos, one-oh-one to one-oh-four, cut.", M("range", 101, 104, "Vc", "cut", "Cut 101–104", ["101", "104"]))
C("w03", "words", "medium", "Altos, bar a hundred and nineteen, breath.", M("bar", 119, 119, "A", "breath", "Breath at 119", ["breath"]))
C("w04", "words", "hard", "Second violins, bar ninety, nine, sorry, nineteen, down bow.",
  M("bar", 19, 19, "V2", "bowing", "Down bow at 19", ["down"]), note="self-correction inside a number")

# ---------------- named members (6) ----------------
C("m01", "member", "easy", "Lin, bar 64, you're sharp on the F.", M("bar", 64, 64, "Lin", "text", "F is sharp, bar 64", ["sharp"]))
C("m02", "member", "easy", "Inès, up bow at forty-one.", M("bar", 41, 41, "Ines", "bowing", "Up bow at 41", ["up"]))
C("m03", "member", "easy", "Lin, your entry at 112, a little earlier.",
  M("bar", 112, 112, "Lin", "text", "Entry a little earlier, 112", ["earl"]))
C("m04", "member", "medium", "Inès and the violas, crescendo at 130.",
  M("bar", 130, 130, "Ines+Va", "dynamic", "cresc. at 130", ["cresc"]),
  [M("bar", 130, 130, "Ines", "dynamic", "cresc. at 130", ["cresc"]), M("bar", 130, 130, "Va", "dynamic", "cresc. at 130", ["cresc"])])
C("m05", "member", "medium", "Inès, bar seventy, take the harmonic out, play it normal.",
  M("bar", 70, 70, "Ines", ["text", "marking"], "No harmonic, bar 70 (normal)", ["harmonic|norm|ord"]))
C("m06", "member", "hard", "Marco, bar 20, softer.",
  M("bar", 20, 20, "E", "dynamic", "Softer at 20", ["soft|p"]),
  note="roster gap: Marco is not a member; the only legal audience is ensemble (a card the admin re-addresses)")

# ---------------- multi-instruction (10) ----------------
C("mu01", "multi", "medium", "Cellos pizz at 30, and everyone mf at 31.",
  [M("bar", 30, 30, "Vc", "marking", "pizz. at 30", ["pizz"]), M("bar", 31, 31, "E", "dynamic", "mf at 31", ["mf"])])
C("mu02", "multi", "medium", "Firsts, up bow at 12, seconds, down bow at 12.",
  [M("bar", 12, 12, "V1", "bowing", "Up bow at 12", ["up"]), M("bar", 12, 12, "V2", "bowing", "Down bow at 12", ["down"])])
C("mu03", "multi", "medium", "Sopranos breathe at 40, altos breathe at 42.",
  [M("bar", 40, 40, "S", "breath", "Breath at 40", ["breath"]), M("bar", 42, 42, "A", "breath", "Breath at 42", ["breath"])])
C("mu04", "multi", "medium", "Violas forte at 55, cellos piano at 55.",
  [M("bar", 55, 55, "Va", "dynamic", "f at 55", ["f"]), M("bar", 55, 55, "Vc", "dynamic", "p at 55", ["p"])])
C("mu05", "multi", "medium", "Bar 90, tenors, accent; bar 92, basses, staccato.",
  [M("bar", 90, 90, "T", "marking", "Accent at 90", ["accent"]), M("bar", 92, 92, "B", "marking", "stacc. at 92", ["stacc"])])
C("mu06", "multi", "hard", "Everyone, cut 20 to 24, and at 25 start piano.",
  [M("range", 20, 24, "E", "cut", "Cut 20–24", ["20", "24"]), M("bar", 25, 25, "E", "dynamic", "p at 25", ["p"])],
  note="one audience, two kinds: two marks (a mark has one kind)")
C("mu07", "multi", "medium", "Seconds, mute on at 70, and Lin, you too.",
  M("bar", 70, 70, "V2+Lin", "marking", "Mute on at 70", ["mute"]),
  [M("bar", 70, 70, "V2", "marking", "Mute on at 70", ["mute"]), M("bar", 70, 70, "Lin", "marking", "Mute on at 70", ["mute"])])
C("mu08", "multi", "medium", "Altos, bar 15 crescendo, then tenors at 16 the same.",
  [M("bar", 15, 15, "A", "dynamic", "cresc. at 15", ["cresc"]), M("bar", 16, 16, "T", "dynamic", "cresc. at 16", ["cresc"])])
C("mu09", "multi", "hard", "Cellos, pizz at 30 and arco at 34.",
  M("range", 30, 34, "Vc", "marking", "pizz. at 30, arco at 34", ["pizz", "arco"]),
  [M("bar", 30, 30, "Vc", "marking", "pizz. at 30", ["pizz"]), M("bar", 34, 34, "Vc", "marking", "arco at 34", ["arco"])],
  note="one audience, two places: one mark per the v4 rule, two also accepted")
C("mu10", "multi", "hard", "Everyone, crescendo from 60 to 64, then subito piano at 65.",
  M("range", 60, 65, "E", "dynamic", "cresc. 60–64, sub. p at 65", ["cresc", "p"]),
  [M("range", 60, 64, "E", "dynamic", "cresc. 60–64", ["cresc"]), M("bar", 65, 65, "E", "dynamic", "sub. p at 65", ["p"])])

# ---------------- hedged speech (6) ----------------
C("h01", "hedged", "medium", "Maybe, uh, violas a bit softer around forty.",
  M("bar", 40, 40, "Va", "dynamic", "Softer around 40", ["soft|p|less"]))
C("h02", "hedged", "medium", "I think, um, the cellos could, could try an up bow at, uh, twenty-six?",
  M("bar", 26, 26, "Vc", "bowing", "Up bow at 26", ["up"]))
C("h03", "hedged", "medium", "Let's, hmm, let's maybe cut, like, 150 to 154, everybody, if that's okay.",
  M("range", 150, 154, "E", "cut", "Cut 150–154", ["150", "154"]))
C("h04", "hedged", "medium", "Sopranos, you know, it might be nicer to breathe, um, after 88 instead.",
  M("bar", 88, 88, "S", "breath", "Breath after 88", ["breath"]))
C("h05", "hedged", "medium", "Could the firsts, maybe, just a touch less vibrato, around bar 100 or so.",
  M("bar", 100, 100, "V1", ["marking", "text"], "Less vib. at 100", ["vib"]))
C("h06", "hedged", "hard", "Uh, tenors, I'd, I'd like a little more, like a crescendo, into 47.",
  M(["bar", "range"], [46, 47], 47, "T", "dynamic", "cresc. into 47", ["cresc"]))

# ---------------- speech-to-text noise (9) ----------------
C("s01", "stt_noise", "hard", "bar fifteen is flat, listen to the viola there.",
  M("bar", 15, 15, "E", "text", "Flat at 15, tune to viola", ["flat"]),
  note="addressee dropped by ASR ('Lin, your C sharp'): ensemble is all the text supports", intended="member:Lin")
C("s02", "stt_noise", "medium", "Everybody, right in a fermenta on bar two hundred.",
  M("bar", 200, 200, "E", "marking", "Fermata at 200", ["fermata"]), note="'right in a fermenta' = write in a fermata")
C("s03", "stt_noise", "hard", "Violas, bar to, that's a down bow.",
  M("bar", 2, 2, "Va", "bowing", "Down bow at 2", ["down"]), note="'bar to' = bar two")
C("s04", "stt_noise", "easy", "Chelos, pizz at forty-nine.", M("bar", 49, 49, "Vc", "marking", "pizz. at 49", ["pizz"]))
C("s05", "stt_noise", "medium", "accept the basses, bar 120, forte.",
  M("bar", 120, 120, "S+A+T", "dynamic", "f at 120", ["f"]), note="'accept' = except; the other voices")
C("s06", "stt_noise", "easy", "Violets, a tempo at 72.", M("bar", 72, 72, "Va", "text", "a tempo at 72", ["tempo"]))
C("s07", "stt_noise", "hard", "Sopranos, bar for tea, mezzo forte.",
  M("bar", 40, 40, "S", "dynamic", "mf at 40", ["mf"]), note="'for tea' = forty")
C("s08", "stt_noise", "hard", "and seconds, from one ten to the end, no vibrato.",
  M("range", 110, "end", "V2", "marking", "senza vib. 110 to end", ["vib"]),
  note="leading 'Firsts' dropped by ASR: the text supports Violin II only", intended="part:Violin I;part:Violin II")
C("s09", "stt_noise", "medium", "Lynn, bar eighty, you're late.", M("bar", 80, 80, "Lin", "text", "Late at 80", ["late|early|earl"]))

# ---------------- non-instructions (30) ----------------
for cid, diff, text, note in [
    ("n01", "easy", "One, two, three, four.", "counting in"),
    ("n02", "easy", "And one, and two, and...", "counting in"),
    ("n03", "easy", "Okay, let's take it from the top.", "from the top"),
    ("n04", "easy", "From the top, guys, whenever you're ready.", "from the top"),
    ("n05", "medium", "Let's go again from bar 40.", "start point now, nothing to write"),
    ("n06", "medium", "Letter C, here we go.", "start point now"),
    ("n07", "medium", "Okay, go back to the pickup of 30.", "start point now (a jump in rehearsal, not in the music)"),
    ("n08", "medium", "Where were we, bar sixty-two?", "question with a bar"),
    ("n09", "easy", "Is everyone okay with a break at eight?", "logistics with a number"),
    ("n10", "medium", "Can the cellos move their chairs a bit closer?", "logistics naming a part"),
    ("n11", "easy", "That was lovely, really lovely.", "praise"),
    ("n12", "easy", "Who has the extra copies of the Brahms?", "logistics"),
    ("n13", "medium", "Did the altos get the new pages?", "question naming a part"),
    ("n14", "hard", "What's the difference between a viola and an onion? Nobody cries when you cut up a viola.",
     "joke with 'cut' and a part"),
    ("n15", "hard", "Should we cut bars 42 to 48? Let me think about it.", "considering a cut, not giving one"),
    ("n16", "hard", "Last week we had the cellos pizz at 30, that's still fine.", "an existing mark, nothing new"),
    ("n17", "hard", "Remember the crescendo I mentioned yesterday? We'll get to that later.", "talking about an instruction"),
    ("n18", "easy", "Can I have an A, please?", "tuning"),
    ("n19", "easy", "Phones off, please.", "logistics"),
    ("n20", "medium", "Alright, bar twelve, off we go.", "start point now"),
    ("n21", "medium", "Ha, that was terrible, my fault, I gave the wrong beat.", "chat"),
    ("n22", "hard", "Is the fermata at the end in your parts, or just mine?", "question about a mark"),
    ("n23", "easy", "Okay, five minute break, back at quarter past.", "logistics"),
    ("n24", "medium", "Lin, can you send me the recording later?", "member named, logistics"),
    ("n25", "medium", "Tenors, are you reading from the new edition?", "question naming a part"),
    ("n26", "easy", "Yeah, yeah, from the top, sure, why not.", "from the top, casual"),
    ("n27", "hard", "I don't know if we need a ritardando there, let's just hear it first.", "undecided instruction"),
    ("n28", "easy", "Thanks everyone, see you Thursday.", "chat"),
    ("n29", "easy", "Ready? And...", "counting in"),
    ("n30", "hard", "If I say cut, I mean stop playing, not a cut in the music.", "talking about the word cut"),
]:
    C(cid, "non_instruction", diff, text, note=note)


def main() -> None:
    ids = [c["id"] for c in CASES]
    assert len(ids) == len(set(ids))
    out = Path(__file__).with_name("set.jsonl")
    out.write_text("".join(json.dumps(c, ensure_ascii=False) + "\n" for c in CASES))
    print(len(CASES), sum(c["instruction"] for c in CASES), "instructions")
    print(Counter(c["cat"] for c in CASES))
    print(Counter(c["diff"] for c in CASES))


if __name__ == "__main__":
    main()
