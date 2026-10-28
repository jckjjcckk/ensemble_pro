"""The score header for part_cut: what page 1 says about the instruments, and how a wanted name finds its entry.

Ported from the piano-cut experiment (`api/experiments/grounding/score_header.py` for the prompt and the box
reconciliation, `piano_cut_label.py` for the JSON repair, the synonym matcher and the by-order context). Muse Spark
reads page 1 with the geometry's numbered overlay (blue staff boxes, yellow staff-number tags) and returns the
instruments in score order with the box numbers each occupies; when the boxes run first..last exactly once, the
box count is the staff count (Spark says "2 staves" for a wind pair that shares one staff; its boxes say 1).
No model call here: the handler makes the call (`part_cut.ask_model`) and hands the text to `parse_json`.
"""
from __future__ import annotations

import json
import re
from typing import Any

HEADER_MAX_TOKENS = 8000   # Spark's reasoning counts against max_tokens; 2048 cut the 17-instrument header off

PROMPT = """This is page {page} of a scanned orchestral full score{title}, the first page of music. A geometry detector has drawn a blue box around every staff it found and a yellow tag with the staff number at the left end of each box (staves {first}..{last}, top to bottom, {n_staves} boxes in system 1). It may have missed a staff: trust the printed page, not the boxes.

Read the margin labels (full names on this first page) and list every instrument in score order, top to bottom, with the yellow box numbers it occupies on this page (count the boxes: a piano or harp has 2, a wind pair written on one shared staff is one instrument with 1 box, "Violoncello e Basso" on one staff is 1; a label spanning two boxes with a bracket means 2), the clef of each staff, and the abbreviation this edition is likely to use on later pages (e.g. "Fl.", "Ob.", "Cor.", "Pno.", "Klav.", "Vl. I"). Every box number from {first} to {last} must appear exactly once, in order; a staff with no box is "boxes": [] and "staves": 1. Also give the key signature, the time signature, the tempo text, and any movement or section heading visible.

Return only JSON of this shape:
{{"instruments": [{{"label": "Flauti I. II.", "abbreviations": ["Fl."], "boxes": [1], "staves": 1, "clefs": ["treble"], "family": "woodwind|brass|percussion|keyboard|strings|voice|other"}}],
 "staff_total": 13,
 "key": "C minor (3 flats)", "time": "4/4", "tempo": "Allegro con brio",
 "sections": ["I."],
 "piano_present": true,
 "notes": "one sentence if anything is odd"}}"""


def prompt(page: int, geom: dict, title: str = "") -> str:
    first_sys = geom["systems"][0]["staff_indices"] if geom["systems"] else []
    return PROMPT.format(page=page, title=f" ({title})" if title else "", first=first_sys[0] if first_sys else 1,
                         last=first_sys[-1] if first_sys else len(geom["staves"]), n_staves=len(first_sys))


def parse_json(text: str) -> tuple[dict[str, Any], bool]:
    """Spark's JSON and whether it was repaired. Spark 1.3 occasionally drops a stray token right after a closing
    bracket (`}-math]`, `]} apron,`); the repair strips one stray word after a bracket (or puts the bracket it
    stood for back) and retries. Raises ValueError / JSONDecodeError when there is nothing to parse."""
    text = (text or "").strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < 0:
        raise ValueError(f"Spark returned no JSON: {text[:200]!r}")
    body = text[start:end + 1]
    try:
        return json.loads(body), False
    except json.JSONDecodeError:
        pass
    stray = r"(?<=[\]\}])\s*-?[A-Za-z_]+(?:=\d+)?(?=\s*[,\]\}])"
    for repl in ("", "]", "}"):
        try:
            return json.loads(re.sub(stray, repl, body, count=1)), True
        except json.JSONDecodeError:
            continue
    return json.loads(body), False   # raise the original error


def reconcile(data: dict[str, Any], geom: dict) -> dict[str, Any]:
    """The stored header: instruments in order (name, label, abbreviations, boxes, staves, clefs, family, position),
    key, time, tempo, expected_staves and a validation against the geometry of page 1's first system."""
    first_sys = list(geom["systems"][0]["staff_indices"]) if geom["systems"] else []
    inst: list[dict[str, Any]] = []
    for k, i in enumerate(x for x in (data.get("instruments") or []) if isinstance(x, dict)):
        label = str(i.get("label") or i.get("name") or "").strip()
        boxes = [int(b) for b in (i.get("boxes") or []) if str(b).strip().lstrip("-").isdigit()]
        try:
            staves = max(1, int(i.get("staves") or 1))
        except (TypeError, ValueError):
            staves = 1
        inst.append({"position": k + 1, "name": label, "label": label, "abbreviations": [str(a) for a in (i.get("abbreviations") or [])],
                     "boxes": boxes, "staves": staves, "clefs": [str(c) for c in (i.get("clefs") or [])], "family": str(i.get("family") or "")})
    boxes = [b for i in inst for b in i["boxes"]]
    boxes_ok = bool(first_sys) and boxes == first_sys
    if boxes_ok:
        for i in inst:
            if i["boxes"]:
                i["staves_said"], i["staves"] = i["staves"], len(i["boxes"])
    total = sum(i["staves"] for i in inst) or int(data.get("staff_total") or 0)
    return {"instruments": inst, "key": data.get("key"), "time": data.get("time"), "tempo": data.get("tempo"),
            "sections": data.get("sections") or [], "notes": data.get("notes", ""), "expected_staves": total,
            "validation": {"geometry_staves_system1": len(first_sys), "header_staves": total, "boxes_in_order": boxes_ok,
                           "match": total == len(first_sys)}}


# ---------------------------------------------------------------- the matcher

# instrument names as editions print them (Italian, German, French, English, abbreviations), lower case, no dots
SYNONYMS = {
    "piano": ["piano", "pianoforte", "klavier", "pfte", "pno", "p-no", "pf", "cembalo", "clavier"],
    "violin": ["violin", "violins", "violino", "violini", "violine", "violinen", "violon", "violons", "vl", "vn", "vln", "viol"],
    "viola": ["viola", "violas", "viole", "bratsche", "bratschen", "altos", "va", "vla"],
    "cello": ["cello", "cellos", "celli", "violoncello", "violoncelli", "violoncelle", "vc", "vcl", "vcll"],
    "double bass": ["double bass", "contrabass", "contrabasso", "contrabassi", "kontrabass", "kontrabaß", "contrebasse", "cb", "kb", "k-b"],
    "flute": ["flute", "flutes", "flauto", "flauti", "flöte", "flöten", "floete", "fl"],
    "piccolo": ["piccolo", "flauto piccolo", "kleine flöte", "picc"],
    "oboe": ["oboe", "oboes", "oboi", "oboen", "hautbois", "ob"],
    "english horn": ["english horn", "corno inglese", "englisch horn", "englisches horn", "cor anglais", "c ingl"],
    "clarinet": ["clarinet", "clarinets", "clarinetto", "clarinetti", "klarinette", "klarinetten", "clarinette", "cl", "klar"],
    "bassoon": ["bassoon", "bassoons", "fagotto", "fagotti", "fagott", "fagotte", "basson", "fag", "fg", "bsn", "bn"],
    "horn": ["horn", "horns", "corno", "corni", "hörner", "horner", "cor", "cors", "hr", "hn"],
    "trumpet": ["trumpet", "trumpets", "tromba", "trombe", "trompete", "trompeten", "trompette", "tr", "tpt", "tromp", "trbe"],
    "trombone": ["trombone", "trombones", "tromboni", "posaune", "posaunen", "trbni", "trbne", "tbn", "trb", "pos"],
    "tuba": ["tuba", "basstuba", "tb"],
    "timpani": ["timpani", "pauken", "timbales", "timp", "pk", "pauk"],
    "harp": ["harp", "arpa", "harfe", "harpe"],
    "organ": ["organ", "organo", "orgel", "orgue", "org"],
    "soprano": ["soprano", "soprani", "sopran", "sopr", "canto", "discant"],
    "alto": ["alto", "alti", "alt", "contralto"],
    "tenor": ["tenor", "tenore", "tenori", "ten"],
    "bass": ["bass", "basses", "basso", "bassi", "bässe"],
    "chorus": ["chorus", "coro", "chor", "choir"],
}
VOICES = {"soprano", "alto", "tenor", "bass", "chorus", "mezzo", "baritone", "voice"}
ROMAN = {"i": 1, "ii": 2, "iii": 3, "iv": 4, "1": 1, "2": 2, "3": 3, "4": 4, "1st": 1, "2nd": 2, "3rd": 3}
IGNORE = {"solo", "in", "e", "and", "und", "et", "the"}


def tokens(text: str) -> list[str]:
    return [t for t in re.split(r"[^a-z0-9äöüß-]+", (text or "").lower()) if t]


def numerals(text: str) -> list[int]:
    return [ROMAN[t] for t in tokens(text) if t in ROMAN]


def family(name: str) -> str | None:
    """The canonical family of a printed or wanted name ("Vn. I" -> violin, "Corno inglese" -> english horn,
    "Piano (solo)" -> piano): the longest synonym found as a whole word or phrase wins."""
    toks = [t for t in tokens(name) if t not in ROMAN]
    text = " ".join(toks)
    best: tuple[int, str] | None = None
    for key, syns in SYNONYMS.items():
        for s in (*syns, key):
            hit = (s in toks) if " " not in s else (f" {s} " in f" {text} ")
            if hit and (best is None or len(s) > best[0]):
                best = (len(s), key)
    return best[1] if best else None


def same_instrument(a: str, b: str) -> bool:
    """Two names for one instrument: same family through the synonym table ("Pno." ~ "Piano (solo)", "Vn. I" ~
    "Violini I"), and when both carry numerals they share one ("Violin I" is not "Violini II"; "Flauti I. II." is
    Flute 1). Names the table does not know fall back to a 3+ letter prefix of the first word."""
    fa, fb = family(a), family(b)
    if fa or fb:
        if fa != fb:
            return False
        na, nb = numerals(a), numerals(b)
        return not (na and nb and not set(na) & set(nb))
    def first(s: str) -> str:
        w = tokens(s)
        return w[0] if w else ""
    x, y = first(a), first(b)
    return len(x) >= 3 and len(y) >= 3 and (x.startswith(y) or y.startswith(x))


def match_instrument(instruments: list[dict], wanted: str) -> dict | None:
    """The header entry for the wanted instrument ("Violin I", "Flute 1", "Soprano", "Piano (solo)"): the family is
    matched through the synonym table against the label and abbreviations, a numeral in the wanted name must
    appear in the entry when the entry has numerals ("Violini I." has it, "Violini II." does not, "Flauti I. II."
    has both: a shared staff). A voice name prefers a voice-family entry. Without a numeral the first entry of the
    family wins."""
    want = family(wanted.split(" (")[0]) or family(wanted)
    if want is None:
        return None
    wnums = numerals(wanted.split(" (")[0])
    voice = want in VOICES
    best: tuple[int, int, dict] | None = None
    for k, inst in enumerate(instruments):
        names = [inst.get("label") or inst.get("name") or "", *(inst.get("abbreviations") or [])]
        fam = (inst.get("family") or "").lower()
        hit = any(family(n) == want for n in names if n)
        if not hit and want == "piano" and fam == "keyboard":
            hit = True
        if not hit:
            continue
        inums = [x for n in names for x in numerals(n)]
        if wnums and inums and not all(n in inums for n in wnums):
            continue
        score = (2 if voice and fam in ("voice", "vocal", "choir", "chorus") else 0) \
            + (-2 if voice and fam in ("brass", "strings", "woodwind") else 0) \
            + (1 if wnums and inums else 0)
        if best is None or score > best[0]:
            best = (score, k, inst)
    return best[2] if best else None


def positions(instruments: list[dict], cand: dict | None) -> list[int] | None:
    """The 1-based staff positions of `cand` in a full system, by score order."""
    if cand is None:
        return None
    k = 1
    for i in instruments:
        ns = int(i.get("staves") or 1)
        if i is cand:
            return list(range(k, k + ns))
        k += ns
    return None


def at_position(header: dict | None, system: dict, staff_index: int) -> dict | None:
    """The header entry printed on a staff of a system, by score order; only when the system has the header's
    full staff count (a cut-away system drops resting instruments, so position says nothing there)."""
    inst = (header or {}).get("instruments") or []
    idxs = system["staff_indices"]
    if not inst or staff_index not in idxs or len(idxs) != sum(int(i.get("staves") or 1) for i in inst):
        return None
    k = idxs.index(staff_index) + 1
    for i in inst:
        ns = int(i.get("staves") or 1)
        if k <= ns:
            return i
        k -= ns
    return None


def previous_entry(header: dict | None, instrument: str) -> dict | None:
    """The header entry printed above the wanted instrument in score order (None for the first, or when the
    instrument is not in the header)."""
    inst = (header or {}).get("instruments") or []
    cand = match_instrument(inst, instrument)
    if cand is None:
        return None
    k = next((i for i, x in enumerate(inst) if x is cand), 0)
    return inst[k - 1] if k > 0 else None


def is_voice(entry: dict | None, name: str | None = None) -> bool:
    """A vocal staff: the header entry's family says voice (or chorus), else the name itself is a voice ("Soprano",
    "CORO Alto"; "Bass" alone is a voice too, the header's family tells a double bass apart)."""
    fam = str((entry or {}).get("family") or "").lower()
    if fam:
        return fam in ("voice", "vocal", "choir", "chorus", "voices")
    return family(name or "") in VOICES


def by_order(header: dict | None, instrument: str, system: dict) -> list[int] | None:
    """When a system has exactly the header's full staff count, the wanted instrument's staves by score order."""
    inst = (header or {}).get("instruments") or []
    total = sum(int(i.get("staves") or 1) for i in inst)
    pos = positions(inst, match_instrument(inst, instrument))
    idxs = system["staff_indices"]
    if not pos or len(idxs) != total:
        return None
    return [idxs[p - 1] for p in pos]


def context(header: dict | None, instrument: str, geom: dict) -> str:
    """Score order and the by-order guess per system, as prompt context for the page label call."""
    inst = (header or {}).get("instruments") or []
    if not inst:
        return ""
    order, k = [], 1
    for i in inst:
        ns = int(i.get("staves") or 1)
        abbr = ", ".join(i.get("abbreviations") or [])
        order.append(f"{k}" + (f"..{k + ns - 1}" if ns > 1 else "") + f" {i.get('label') or i.get('name')}" + (f" ({abbr})" if abbr else ""))
        k += ns
    total = k - 1
    lines = [f"Score header (read from the first page): {total} staves per full system, in this order (position: instrument): " + "; ".join(order) + "."]
    cand = match_instrument(inst, instrument)
    if cand is None:
        lines.append(f'The header does not list "{instrument}"; if it is not on the page, answer "absent" for every system.')
    else:
        ns = int(cand.get("staves") or 1)
        clefs = ", ".join(cand.get("clefs") or [])
        lines.append(f'In this edition "{instrument}" is printed as "{cand.get("label") or cand.get("name")}" (abbreviated '
                     f'{", ".join(cand.get("abbreviations") or []) or "variously"}), {ns} staff{"s" if ns != 1 else ""}'
                     + (f" ({clefs})" if clefs else "") + ".")
        for sysd in geom["systems"]:
            guess = by_order(header, instrument, sysd)
            if guess:
                lines.append(f"System {sysd['index']} has {len(sysd['staff_indices'])} staves, the full set, so by order the wanted instrument is staff {guess}: confirm from the labels/clefs/brace, or correct it.")
            else:
                lines.append(f"System {sysd['index']} has {len(sysd['staff_indices'])} staves, not the full {total}: either resting instruments are not printed (then say which are absent) or the detector missed a staff (then say so in notes); identify the wanted instrument from the labels, clefs, brace and position, and answer \"absent\" if its staves are not printed.")
    return "\n".join(lines) + "\n"
