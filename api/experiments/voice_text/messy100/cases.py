"""100 new messy instructions with strict ground truth in the v4 schema (none from the clean 130 or script.csv).

Two fixture books:
  A  the eval's book: Violin I, Violin II, Viola, Cello, Soprano, Alto, Tenor, Bass; members Lin, Inès; bars 1-240;
     letters A-F (no letter-to-bar map). Landmarks made up for v4e, consistent with 1-240: segno 17, double bar
     after 64, key change 97 (E-flat major), Adagio (the slow section) 121-160, Tempo primo 161, To Coda 200,
     coda 221-240. Groups: Strings (V1, V2, Va, Vc), Voices (S, A, T, B).
  B  a piano concerto: Piano + Flute, Oboe, Clarinet, Bassoon, Horn, Trumpet, Timpani, Violin I, Violin II, Viola,
     Cello, Double Bass; members Mei (the soloist), Tomás; bars 1-312; letters A-K. Landmarks: key change 75
     (F major), double bar after 150, Andante (the slow section) 151-210, Allegro (Tempo I) 211, cadenza 268,
     coda 281-312. Groups: Soloist (Piano), Orchestra (the other 12), Woodwinds, Brass, Strings (with Double Bass).

Ground truth is what the book means (landmarks resolved to bars, groups to their parts); v4d is not given landmarks
or the concerto's groups, so those cases measure exactly what (a) and (b) add. Where two answers are defensible
both are accepted. `none_ok` = an empty answer is also right (unrecoverable but guessable). `term` tags the
mishearing cases: listed (a pair named in v4e's rule), unlisted (not named), part (a part/name mangle).

    uv run python -m experiments.voice_text.messy100.cases     # writes set.jsonl, prints counts
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from .prompts import ScoreFactsE

PARTS_A = ["Violin I", "Violin II", "Viola", "Cello", "Soprano", "Alto", "Tenor", "Bass"]
PARTS_B = ["Piano", "Flute", "Oboe", "Clarinet", "Bassoon", "Horn", "Trumpet", "Timpani", "Violin I", "Violin II",
           "Viola", "Cello", "Double Bass"]
ORCH = PARTS_B[1:]
FIX = {
    "A": ScoreFactsE(parts=PARTS_A, members=["Lin", "Inès"], bar_first=1, bar_last=240, rehearsal_marks=list("ABCDEF"),
                     landmarks=["segno at bar 17", "double bar after bar 64", "key change at bar 97 (E-flat major)",
                                "Adagio (the slow section) bars 121-160", "Tempo primo at bar 161",
                                "To Coda at bar 200", "coda bars 221-240"],
                     groups=[("Strings", PARTS_A[:4]), ("Voices", PARTS_A[4:])]),
    "B": ScoreFactsE(parts=PARTS_B, members=["Mei", "Tomás"], bar_first=1, bar_last=312,
                     rehearsal_marks=list("ABCDEFGHIJK"),
                     landmarks=["key change at bar 75 (F major)", "double bar after bar 150",
                                "Andante (the slow section) bars 151-210", "Allegro (Tempo I) at bar 211",
                                "cadenza at bar 268", "coda bars 281-312"],
                     groups=[("Soloist", ["Piano"]), ("Orchestra", ORCH), ("Woodwinds", ORCH[:4]),
                             ("Brass", ORCH[4:6]), ("Strings", ORCH[7:])]),
}

AB = {"V1": "Violin I", "V2": "Violin II", "Va": "Viola", "Vc": "Cello", "S": "Soprano", "A": "Alto", "T": "Tenor",
      "B": "Bass", "Pno": "Piano", "Fl": "Flute", "Ob": "Oboe", "Cl": "Clarinet", "Bn": "Bassoon", "Hn": "Horn",
      "Tp": "Trumpet", "Timp": "Timpani", "Db": "Double Bass"}
GROUPS = {"STRA": "V1+V2+Va+Vc", "VOX": "S+A+T+B", "STRB": "V1+V2+Va+Vc+Db", "WW": "Fl+Ob+Cl+Bn",
          "ORCH": "Fl+Ob+Cl+Bn+Hn+Tp+Timp+V1+V2+Va+Vc+Db"}
MEMBERS = {"Lin": "Lin", "Ines": "Inès", "Mei": "Mei", "Tomas": "Tomás"}


def _l(x):
    return x if isinstance(x, list) else [x]


def _aud(s: str) -> list[str]:
    toks = []
    for t in s.split("+"):
        toks += GROUPS[t].split("+") if t in GROUPS else [t]
    out = set()
    for t in toks:
        if t.startswith("-"):
            out.discard(f"part:{AB[t[1:]]}")
        elif t == "E":
            out.add("ensemble")
        elif t in MEMBERS:
            out.add(f"member:{MEMBERS[t]}")
        else:
            out.add(f"part:{AB[t]}")
    return sorted(out)


def _minus(s: str) -> str:
    """"ORCH-Ob" -> group then removals."""
    head, *rest = s.split("-")
    return "+".join([head] + [f"-{r}" for r in rest])


def M(pos, bf, bt, aud, kind, text, keys=()):
    """One expected mark; any field may be a list of accepted values; aud is "V1+V2" (groups, "ORCH-Ob") or a list."""
    auds = [_aud(_minus(a)) for a in _l(aud)]
    return {"position": _l(pos), "bar_from": _l(bf), "bar_to": _l(bt), "audience": auds, "kind": _l(kind),
            "text": text, "keys": list(keys)}


CASES: list[dict] = []


def C(cid, cat, diff, fix, text, *answers, none_ok=False, intended=None, term=None, note=None):
    alts = [a if isinstance(a, list) else [a] for a in answers]
    CASES.append({"id": cid, "cat": cat, "diff": diff, "fix": fix, "text": text, "answers": alts,
                  "instruction": bool(alts), "none_ok": none_ok or not alts, "intended": intended, "term": term,
                  "note": note})


DYN, MK, TX, BOW, BR, CUT = "dynamic", "marking", "text", "bowing", "breath", "cut"
BAL = [DYN, TX]          # balance: dynamic or text (as in the clean set)

# ---------------- terms (25): mangled musical terms and part names ----------------
C("t01", "terms", 1, "A", "Everyone, bar forty, fermenta on the downbeat.", M("bar", 40, 40, "E", MK, "Fermata at 40", ["fermata"]), term="listed")
C("t02", "terms", 1, "A", "Cellos, bar twelve, pizza cutter.", M("bar", 12, 12, "Vc", MK, "pizz. at 12", ["pizz"]), term="listed")
C("t03", "terms", 2, "A", "Violas, at fifty retard and oh, then attempt oh at fifty-four.",
  M("range", 50, 54, "Va", TX, "rit. 50, a tempo 54", ["rit", "tempo"]),
  [M("bar", 50, 50, "Va", TX, "rit. at 50", ["rit"]), M("bar", 54, 54, "Va", TX, "a tempo at 54", ["tempo"])], term="listed")
C("t04", "terms", 1, "A", "Bar eighty-eight, spores and oh, everybody.", M("bar", 88, 88, "E", DYN, "sfz at 88", ["sfz"]), term="listed")
C("t05", "terms", 2, "A", "Seconds, bar thirty-two, arc oh.", M("bar", 32, 32, "V2", MK, "arco at 32", ["arco"]), term="listed")
C("t06", "terms", 2, "A", "Firsts, from sixty to sixty-four, stuck auto, short and light.",
  M("range", 60, 64, "V1", MK, "stacc. 60–64", ["stacc"]), term="listed")
C("t07", "terms", 2, "A", "Cellos, bar one-forty, the visi, top line and bottom line.",
  M("bar", 140, 140, "Vc", [MK, TX], "div. at 140", ["divisi|div"]), term="listed")
C("t08", "terms", 2, "A", "Sopranos, bar seventy-two, crash endo into seventy-five.",
  M("range", 72, 75, "S", DYN, "cresc. 72–75", ["cresc"]), term="unlisted")
C("t09", "terms", 2, "A", "Altos and tenors, from ninety, dim in your endo to the end.",
  M("range", 90, [None, 240], "A+T", DYN, "dim. 90 to end", ["dim"]), term="unlisted")
C("t10", "terms", 2, "A", "Violins, bar one hundred, tenure toe on all four quarters.",
  M("bar", 100, 100, "V1+V2", MK, "ten. at 100", ["ten"]), term="unlisted")
C("t11", "terms", 2, "A", "Everyone, bar twenty-six, marked oh, really lean on it.",
  M("bar", 26, 26, "E", MK, "marc. at 26", ["marc"]), term="unlisted")
C("t12", "terms", 3, "A", "Violas, from one-twenty, con sore dino.",
  M(["bar", "range"], 120, [120, None, 240], "Va", MK, "con sord. from 120", ["sord|mute"]), term="unlisted")
C("t13", "terms", 2, "A", "Basses, bar sixty-eight, sub eat oh piano.", M("bar", 68, 68, "B", DYN, "sub. p at 68", ["p"]), term="unlisted")
C("t14", "terms", 1, "A", "Firsts, bar fifty-one, no vibrator there, just straight.",
  M("bar", 51, 51, "V1", MK, "senza vib. at 51", ["vib"]), term="unlisted")
C("t15", "terms", 2, "A", "Chelos and Violets, bar one-ten, pits.", M("bar", 110, 110, "Va+Vc", MK, "pizz. at 110", ["pizz"]),
  [M("bar", 110, 110, "Vc", MK, "pizz. at 110", ["pizz"]), M("bar", 110, 110, "Va", MK, "pizz. at 110", ["pizz"])], term="unlisted")
C("t16", "terms", 2, "A", "Tenners, bar eighty-two, breath after the comma.", M("bar", 82, 82, "T", BR, "Breath at 82", ["breath"]), term="part")
C("t17", "terms", 2, "A", "So pranos, from forty-four to forty-eight, lay gato, one line.",
  M("range", 44, 48, "S", [MK, TX], "legato 44–48", ["legato"]), term="listed")
C("t18", "terms", 1, "A", "Everybody, bar two hundred, fur mata on the last beat.",
  M("bar", 200, 200, "E", MK, "Fermata at 200", ["fermata"]), term="unlisted")
C("t19", "terms", 2, "A", "Fiddles, bar nine, up bar, both of you.", M("bar", 9, 9, "V1+V2", BOW, "Up bow at 9", ["up"]), term="unlisted")
C("t20", "terms", 3, "A", "Second violence, bar one-fifty, ritter dando, poco a poco.",
  M("bar", 150, 150, "V2", TX, "poco a poco rit. at 150", ["rit"]), term="unlisted")
C("t21", "terms", 2, "A", "Cellos, bar eighty, at the heel, down bough.", M("bar", 80, 80, "Vc", BOW, "Down bow at 80", ["down"]), term="unlisted")
C("t22", "terms", 2, "A", "In-ezz, bar fifty-seven, that's pizza cutter, not arco.",
  M("bar", 57, 57, "Ines", MK, "pizz. at 57", ["pizz"]), term="listed")
C("t23", "terms", 2, "B", "Clarinets, bar ninety, stuck auto.", M("bar", 90, 90, "Cl", MK, "stacc. at 90", ["stacc"]), term="listed")
C("t24", "terms", 2, "B", "Horns, bar forty-one, spores and oh on the entry, and the timp knee too.",
  M("bar", 41, 41, "Hn+Timp", DYN, "sfz at 41", ["sfz"]),
  [M("bar", 41, 41, "Hn", DYN, "sfz at 41", ["sfz"]), M("bar", 41, 41, "Timp", DYN, "sfz at 41", ["sfz"])], term="listed")
C("t25", "terms", 3, "B", "Double basses, bar two-twenty, arc oh after the pizza cutter bit.",
  M("bar", 220, 220, "Db", MK, "arco at 220", ["arco"]), term="listed")

# ---------------- landmarks (20) ----------------
C("lm01", "landmark", 1, "A", "Everyone, two after the key change, forte.", M("bar", [98, 99], [98, 99], "E", DYN, "f at 99", ["f"]))
C("lm02", "landmark", 2, "A", "Cellos, the bar before the double bar, ritard.", M("bar", 64, 64, "Vc", TX, "rit. at 64", ["rit"]))
C("lm03", "landmark", 1, "A", "From the coda, everybody pianissimo.",
  M(["bar", "range"], 221, [221, None, 240], "E", DYN, "pp from the coda", ["pp"]))
C("lm04", "landmark", 2, "A", "Violas, in the slow section, play it with a mute.",
  M(["range", "bar"], 121, [160, 121], "Va", MK, "Mute 121–160", ["mute|sord"]))
C("lm05", "landmark", 2, "A", "Sopranos, first bar of the Adagio, breathe before you come in.",
  M("bar", [120, 121], 121, "S", BR, "Breath before 121", ["breath"]))
C("lm06", "landmark", 2, "A", "At the segno, everybody, mezzo piano.", M("bar", 17, 17, "E", DYN, "mp at 17", ["mp"]))
C("lm07", "landmark", 3, "A", "Seconds, three bars before the coda, that's where you come in, mark it.",
  M("bar", 218, 218, "V2", TX, "Entry at 218", ["in|entr|enter|come"]))
C("lm08", "landmark", 2, "A", "Everyone, the last two bars before the key change, crescendo.",
  M("range", 95, 96, "E", DYN, "cresc. 95–96", ["cresc"]))
C("lm09", "landmark", 2, "A", "Basses, at Tempo primo, back in tempo, don't drag.", M("bar", 161, 161, "B", TX, "Tempo I at 161, don't drag", ["tempo|drag"]))
C("lm10", "landmark", 3, "A", "Tenors, from the double bar to the key change, it's all mezzo forte.",
  M("range", 65, [96, 97], "T", DYN, "mf 65–96", ["mf"]))
C("lm11", "landmark", 3, "A", "From the To Coda sign we jump straight to the coda, everybody.",
  M("range", [200, 201], [220, 221], "E", CUT, "Cut 201–220, to coda", ["cut|coda|jump"]))
C("lm12", "landmark", 2, "A", "Firsts, the bar after the double bar, up bow.", M("bar", 65, 65, "V1", BOW, "Up bow at 65", ["up"]))
C("lm13", "landmark", 1, "A", "Everyone, last bar of the slow section, fermata.", M("bar", 160, 160, "E", MK, "Fermata at 160", ["fermata"]))
C("lm14", "landmark", 3, "A", "Altos, one before the segno, that's your pickup, mark it.",
  M("bar", 16, [16, 17], "A", TX, "Pickup at 16", ["pick|entr|in|come"]))
C("lm15", "landmark", 2, "B", "Piano, the bar before the double bar, ritardando, take your time.",
  M("bar", 150, 150, "Pno", TX, "rit. at 150", ["rit"]))
C("lm16", "landmark", 2, "B", "Strings, two after the key change, pizz.", M("bar", [76, 77], [76, 77], "STRB", MK, "pizz. at 77", ["pizz"]))
C("lm17", "landmark", 2, "B", "Oboe, in the slow section, you lead, a bit louder.",
  M(["range", "bar"], 151, [210, 151], "Ob", BAL, "Lead, louder 151–210", ["lead|out|loud|more|f"]))
C("lm18", "landmark", 2, "B", "Mei, at the cadenza, take all the time you want.",
  M("bar", 268, 268, "Mei", TX, "Cadenza: take time", ["time|free|rubato"]))
C("lm19", "landmark", 1, "B", "Everyone, from the coda, fortissimo.", M(["bar", "range"], 281, [281, None, 312], "E", DYN, "ff from the coda", ["ff"]))
C("lm20", "landmark", 3, "B", "Horns, at the Allegro after the slow section, you're back to forte, and timpani with them.",
  M("bar", 211, 211, "Hn+Timp", DYN, "f at 211", ["f"]),
  [M("bar", 211, 211, "Hn", DYN, "f at 211", ["f"]), M("bar", 211, 211, "Timp", DYN, "f at 211", ["f"])])

# ---------------- groups (15): except / everyone else / named groups ----------------
C("g01", "group", 1, "A", "Everyone except the violas, bar thirty, piano.", M("bar", 30, 30, "V1+V2+Vc", DYN, "p at 30", ["p"]))
C("g02", "group", 2, "A", "Strings, bar seventy, pizz.", M("bar", 70, 70, "STRA", MK, "pizz. at 70", ["pizz"]))
C("g03", "group", 2, "A", "The choir, bar one-oh-five, everyone but the basses, crescendo.",
  M("bar", 105, 105, "S+A+T", DYN, "cresc. at 105", ["cresc"]))
C("g04", "group", 2, "A", "Sopranos, bring it out at fifty, everyone else back off.",
  [M("bar", 50, 50, "S", BAL, "Bring out at 50", ["out|more|loud|f"]), M("bar", 50, 50, "A+T+B", BAL, "Back off at 50", ["back|soft|less|p|quiet|light"])])
C("g05", "group", 3, "A", "Voices, bar one-thirty, all of you except tenors, staccato.",
  M("bar", 130, 130, "S+A+B", MK, "stacc. at 130", ["stacc"]))
C("g06", "group", 2, "A", "All the strings except the cellos, from one-eighty, mute.",
  M(["bar", "range"], 180, [180, None, 240], "V1+V2+Va", MK, "Mute from 180", ["mute|sord"]))
C("g07", "group", 1, "B", "Everyone except the piano, bar twenty, softer.", M("bar", 20, 20, "ORCH", BAL, "Softer at 20", ["soft|p|less|quiet"]))
C("g08", "group", 3, "B", "Orchestra, bar fifty, mezzo forte, piano stays forte.",
  M("bar", 50, 50, "ORCH", DYN, "mf at 50", ["mf"]),
  [M("bar", 50, 50, "ORCH", DYN, "mf at 50", ["mf"]), M("bar", 50, 50, "Pno", DYN, "f at 50", ["f"])])
C("g09", "group", 2, "B", "Woodwinds, bar ninety-two, breath before the phrase.", M("bar", 92, 92, "WW", BR, "Breath at 92", ["breath"]))
C("g10", "group", 2, "B", "Strings except the basses, bar one-forty, down bow.", M("bar", 140, 140, "V1+V2+Va+Vc", BOW, "Down bow at 140", ["down"]))
C("g11", "group", 2, "B", "Everybody but the soloist, from one-sixty to one-seventy, diminuendo.",
  M("range", 160, 170, "ORCH", DYN, "dim. 160–170", ["dim"]))
C("g12", "group", 3, "B", "Brass and timpani, bar two-thirty, accent, the rest of the orchestra no accent.",
  M("bar", 230, 230, "Hn+Tp+Timp", MK, "Accent at 230", ["accent"]),
  [M("bar", 230, 230, "Hn+Tp+Timp", MK, "Accent at 230", ["accent"]), M("bar", 230, 230, "WW+STRB", [MK, TX], "No accent at 230", ["accent"])])
C("g13", "group", 2, "B", "Everyone except the oboe, bar sixty, piano.", M("bar", 60, 60, ["ORCH-Ob", "ORCH-Ob+Pno"], DYN, "p at 60", ["p"]))
C("g14", "group", 2, "B", "Cellos and basses, bar one-twelve, the low line, louder.", M("bar", 112, 112, "Vc+Db", BAL, "Louder at 112", ["loud|more|out|f"]),
  [M("bar", 112, 112, "Vc", BAL, "Louder at 112", ["loud|more|out|f"]), M("bar", 112, 112, "Db", BAL, "Louder at 112", ["loud|more|out|f"])])
C("g15", "group", 3, "B", "Violins only, everyone else in the strings rest, bar two-forty, tremolo.",
  M("bar", 240, 240, "V1+V2", [MK, TX], "trem. at 240", ["trem"]),
  [M("bar", 240, 240, "V1+V2", [MK, TX], "trem. at 240", ["trem"]), M("bar", 240, 240, "Va+Vc+Db", TX, "Rest at 240", ["rest|tacet"])])

# ---------------- rambling / self-correcting / buried (20) ----------------
C("r01", "ramble", 2, "A", "So, um, what I'd like, and this is really important, is the cellos at bar forty-six, can we, yeah, just a bit softer there.",
  M("bar", 46, 46, "Vc", BAL, "Softer at 46", ["soft|p|less|quiet"]))
C("r02", "ramble", 2, "A", "Violas, bar seventy, no, seventy-one, no, seventy is right, crescendo.", M("bar", 70, 70, "Va", DYN, "cresc. at 70", ["cresc"]))
C("r03", "ramble", 3, "A", "Okay, I know we've been at this for a while, and the tenors were lovely by the way, but sopranos, at eighty-four, I need a breath, after the word light, you know the spot.",
  M("bar", 84, 84, "S", BR, "Breath after 'light', 84", ["breath"]))
C("r04", "ramble", 2, "A", "Seconds, from twenty, sorry, firsts, from twenty to twenty-four, staccato.", M("range", 20, 24, "V1", MK, "stacc. 20–24", ["stacc"]))
C("r05", "ramble", 2, "A", "Everyone, bar one-oh-two, that's, um, that's a forte, not a fortissimo, just forte.", M("bar", 102, 102, "E", DYN, "f at 102", ["f"]))
C("r06", "ramble", 3, "A", "Right, so we're cutting, let me just check, yes, we're cutting one-thirty to one-thirty-seven, everybody, sorry, one-thirty to one-thirty-six.",
  M("range", 130, 136, "E", CUT, "Cut 130–136", ["cut"]))
C("r07", "ramble", 2, "A", "Basses, I keep saying this, and I'm not cross, but bar ninety, it's piano, please write it in.", M("bar", 90, 90, "B", DYN, "p at 90", ["p"]))
C("r08", "ramble", 3, "A", "Altos, bar fifty-six, could you, actually no, everyone, bar fifty-six, could you all take a breath there.",
  M("bar", 56, 56, "E", BR, "Breath at 56", ["breath"]))
C("r09", "ramble", 2, "A", "Lin, about bar twenty-two, I think it's twenty-two, yes, you're rushing, hold back.",
  M("bar", 22, 22, "Lin", TX, "Don't rush, 22", ["rush|back|hold|steady|tempo"]))
C("r10", "ramble", 2, "A", "Firsts, bar one-forty-four, down bow, wait, up bow, sorry, it starts up bow.", M("bar", 144, 144, "V1", BOW, "Up bow at 144", ["up"]))
C("r11", "ramble", 3, "A", "Cellos, bar thirty, pizz, and then, where does it go back, thirty-four, arco at thirty-four.",
  M("range", 30, 34, "Vc", MK, "pizz. 30, arco 34", ["pizz", "arco"]),
  [M("bar", 30, 30, "Vc", MK, "pizz. at 30", ["pizz"]), M("bar", 34, 34, "Vc", MK, "arco at 34", ["arco"])])
C("r12", "ramble", 2, "A", "Everyone, the crescendo, it starts at sixty, not sixty-two like in the old edition, sixty.",
  M("bar", 60, 60, "E", DYN, "cresc. from 60", ["cresc"]))
C("r13", "ramble", 3, "A", "Hmm, okay, so the thing is, the rit, the rit at the end, I'd rather it started earlier, at two-thirty-two, everyone.",
  M(["bar", "range"], 232, [232, None, 240], "E", TX, "rit. from 232", ["rit"]))
C("r14", "ramble", 2, "A", "Tenors, and basses too actually, bar forty-one, accent on the downbeat.", M("bar", 41, 41, "T+B", MK, "Accent at 41", ["accent"]))
C("r15", "ramble", 2, "A", "Sopranos, from one-ninety, no, one-ninety-two, mezzo piano until two hundred.", M("range", 192, 200, "S", DYN, "mp 192–200", ["mp"]))
C("r16", "ramble", 3, "A", "Violas, it's, uh, it's bar eighty-eight, eighty-eight, no vibrato there, senza, and then vibrato back at ninety.",
  M("range", 88, 90, "Va", MK, "senza vib. 88, vib. 90", ["vib"]),
  [M("bar", 88, 88, "Va", MK, "senza vib. at 88", ["vib"]), M("bar", 90, 90, "Va", MK, "vib. at 90", ["vib"])])
C("r17", "ramble", 2, "B", "Mei, so at bar sixty, it's, you know, I want you to play out, it's your tune, forte.", M("bar", 60, 60, "Mei", DYN, "f at 60", ["f"]))
C("r18", "ramble", 2, "B", "Flute, bar one-twenty, uh, one-twenty-one, breath before the run.", M("bar", 121, 121, "Fl", BR, "Breath at 121", ["breath"]))
C("r19", "ramble", 3, "B", "Okay, everybody, and I mean the whole orchestra, not you Mei, bar ninety-eight, subito piano.",
  M("bar", 98, 98, "ORCH", DYN, "sub. p at 98", ["p"]))
C("r20", "ramble", 2, "A", "Everyone, bar twelve, twelve, wait, is it twelve, yes, twelve, mezzo forte.", M("bar", 12, 12, "E", DYN, "mf at 12", ["mf"]))

# ---------------- dropped addressee / stray player reply (10) ----------------
C("a01", "addressee", 2, "A", "bar twelve, up bow on the first note.", M("bar", 12, 12, "E", BOW, "Up bow at 12", ["up"]), intended="Cello")
C("a02", "addressee", 2, "A", "from sixty, breathe after the comma.", M("bar", 60, 60, "E", BR, "Breath at 60", ["breath"]), intended="Alto")
C("a03", "addressee", 2, "A", "Violas, bar thirty, which thirty, the first time? Yes, the first time, mute on.",
  M("bar", 30, 30, "Va", MK, "Mute at 30", ["mute|sord"]))
C("a04", "addressee", 3, "A", "Cellos, from seventy, us too? No, just cellos, pizz.",
  M(["bar", "range"], 70, [70, None, 240], "Vc", MK, "pizz. from 70", ["pizz"]))
C("a05", "addressee", 2, "A", "Sopranos, bar forty-four, breathe, after light? Yes, after the word light.", M("bar", 44, 44, "S", BR, "Breath at 44", ["breath"]))
C("a06", "addressee", 3, "A", "Seconds, bar eighteen, is that the down bow? Yes, down bow, all of you.", M("bar", 18, 18, "V2", BOW, "Down bow at 18", ["down"]))
C("a07", "addressee", 2, "A", "you're late at seventy-one, the entry's on the end of two.",
  M("bar", 71, 71, "E", TX, "Entry on the and of 2, 71", ["two|2|late|entr|early|end"]), intended="Viola")
C("a08", "addressee", 2, "B", "bar sixty, play out, it's your tune.", M("bar", 60, 60, "E", BAL, "Play out at 60", ["out|loud|f|tune"]), intended="Mei")
C("a09", "addressee", 3, "A", "Tenors, bar ninety-nine, sorry, what's the dynamic? Mezzo piano, tenors, mezzo piano.", M("bar", 99, 99, "T", DYN, "mp at 99", ["mp"]))
C("a10", "addressee", 3, "B", "Oboe, bar forty, me? Yes you, oboe, forty, play it staccato.", M("bar", 40, 40, "Ob", MK, "stacc. at 40", ["stacc"]))

# ---------------- unrecoverable (10): none, or an uncertain mark ----------------
C("u01", "unrecoverable", 2, "A", "uh the the thing at the um you know there softer",
  M(["global", "mark"], None, None, "E", BAL, "Softer", ["soft|p|less|quiet"]), none_ok=True)
C("u02", "unrecoverable", 2, "A", "Violas bar forty or fourteen whatever, piano",
  M("bar", [40, 14], [40, 14], "Va", DYN, "p at 40", ["p"]), none_ok=True)
C("u03", "unrecoverable", 1, "A", "and, bar, the, and")
C("u04", "unrecoverable", 2, "A", "Cellos, at bar, um.")
C("u05", "unrecoverable", 3, "A", "Everyone, the bar before the double bar, no wait, there are two double bars in my score, never mind.")
C("u06", "unrecoverable", 2, "A", "Sopranos, can you, no, forget it, let's just sing.")
C("u07", "unrecoverable", 3, "A", "Bar eighty, the, the, the firsts, lighter, the other one.",
  M("bar", 80, 80, ["V1", "V2", "E"], BAL, "Lighter at 80", ["light|soft|less|p"]), none_ok=True)
C("u08", "unrecoverable", 2, "B", "Somebody's flat at bar fifty, I don't know who.",
  M("bar", 50, 50, "E", TX, "Flat at 50", ["flat|tun|pitch"]), none_ok=True)
C("u09", "unrecoverable", 3, "B", "Piano, the, the cadenza thing, we'll talk about it later.")
C("u10", "unrecoverable", 2, "A", "Violins, there, the bit, you know the bit, do the thing we said.")


def main() -> None:
    ids = [c["id"] for c in CASES]
    assert len(ids) == len(set(ids)) == 100, len(ids)
    for c in CASES:
        parts = set(FIX[c["fix"]].parts)
        for ans in c["answers"]:
            for m in ans:
                for s in m["audience"]:
                    for a in s:
                        assert a == "ensemble" or a.startswith("member:") or a[5:] in parts, (c["id"], a)
    Path(__file__).with_name("set.jsonl").write_text("".join(json.dumps(c, ensure_ascii=False) + "\n" for c in CASES))
    print(Counter(c["cat"] for c in CASES), Counter(c["diff"] for c in CASES), Counter(c["fix"] for c in CASES),
          Counter(c["term"] for c in CASES if c["term"]))


if __name__ == "__main__":
    main()
