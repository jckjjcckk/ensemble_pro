"""The writers of librarian agent v2 (`omr_agent`): Spark's answers become MusicXML by fixed rules, never a pitch,
duration, rest or barline change. No model.

  apply_front   the front-matter form: a `MetronomeMark` (the tempo heading as its text, the metronome's unit and
                number when printed) at offset 0 of the first bar of the first music page, in the top staff;
                Audiveris's own metronome marks and bold heading words in the first two bars are removed first, so
                the heading is never doubled and never lands on bar 2 (the Goldberg defect: Audiveris anchored
                "Andante espressivo." to a chord in bar 2). Title, composer, movement, opus, dedication and editor
                go into the score's metadata (music21 writes the work and identification elements; `musicxml_fix`
                carries them into the credits).
  apply_items   per system Spark answered: Audiveris's dynamics and plain (non-bold) words in its bars are dropped
                (v1's measured rule: text F1 1.00 on Goldberg p1-5 when Spark's text replaces the OCR's), then every
                item is written at the note it is anchored to (bar, staff, note index: chords once, grace notes
                counted, rests not):
                  words      TextExpression in italic (`font-style="italic"`), below the top staff of a part, above
                             the staves under it
                  dynamic    `<dynamics>` at that note's onset
                  fingering  `<technical><fingering>` on the note; a stack of digits on a chord, top digit first
                  pedal      `<pedal type="start|stop">` directions (a PedalMark spanner from the Ped. note to the *
                             note; an unmatched Ped. runs to the end of its bar, an unmatched * is dropped)
                  ornament   Mordent / InvertedMordent / Trill / Turn / Schleifer on the note
                Before writing, each item is checked against what the bar already holds (same kind and same text
                in the bar, or the same note): Audiveris's hairpins (a "cresc."/"dim." word where a wedge of that
                sense starts in the bar), pedal marks, ornaments and anything an earlier item wrote are never
                doubled. The skipped ones are counted (`duplicates`).
  apply_verify  an accidental the engine graded low: Spark's verdict never edits the pitch; a disagreement flags
                the bar. An ornament that Spark says is not one is removed from that bar's staff.
  flags         `omr_score.flagged_bars` as before (abnormal, rhythm, missing bars) plus the verify flags.
"""

from __future__ import annotations

import logging
from fractions import Fraction
from typing import Any

from music21 import articulations, chord, dynamics, duration, expressions, metadata, note, stream, tempo

from .omr_agent import UNITS
from .omr_score import staff_groups

log = logging.getLogger("folio.omr")

ORN = {"mordent": expressions.Mordent, "inverted_mordent": expressions.InvertedMordent, "trill": expressions.Trill,
       "turn": expressions.Turn, "schleifer": expressions.Schleifer}
ORN_CLASSES = (expressions.GeneralMordent, expressions.Trill, expressions.Turn, expressions.Schleifer)
ORN_SHAPES = {"MORDENT": expressions.Mordent, "MORDENT_INVERTED": expressions.InvertedMordent, "TR": expressions.Trill,
              "TURN": expressions.Turn, "TURN_INVERTED": expressions.Turn, "TURN_SLASH": expressions.Turn, "TURN_UP": expressions.Turn}
ALTER_SHAPES = {"SHARP": "sharp", "FLAT": "flat", "NATURAL": "natural", "DOUBLE_SHARP": "double_sharp", "DOUBLE_FLAT": "double_flat"}
CRESC_WORDS = ("cresc", "crescendo")
DIM_WORDS = ("dim", "dimin", "diminuendo", "decresc", "decrescendo")


# ---------------------------------------------------------------------------------------------------- helpers

def _measures(part: stream.Part) -> dict[int, stream.Measure]:
    return {m.number: m for m in part.getElementsByClass(stream.Measure)}


def _containers(m: stream.Measure):
    return list(m.voices) if m.voices else [m]


def note_slots(m: stream.Measure) -> list[note.NotRest]:
    """The bar's notes and chords as a reader counts them left to right: every voice merged by onset (a grace note
    before the note it leans on, voices in file order at a tie), a chord once, rests left out."""
    slots = []
    for vi, v in enumerate(_containers(m)):
        for el in v.notes:
            slots.append((Fraction(el.offset), 0 if el.duration.isGrace else 1, vi, el))
    slots.sort(key=lambda t: (t[0], t[1], t[2]))
    return [el for _, _, _, el in slots]


def _is_bold(el: expressions.TextExpression) -> bool:
    return str(getattr(el.style, "fontWeight", "") or "").lower() == "bold"


def clear_text(m: stream.Measure) -> list[str]:
    """Drop Audiveris's dynamics and plain words from a bar Spark answered; bold words (headings) and metronome marks
    stay (they belong to the tempo line, which `apply_front` handles for the first page)."""
    gone = []
    for el in list(m.recurse()):
        if isinstance(el, dynamics.Dynamic):
            gone.append(el.value)
            el.activeSite.remove(el)
        elif isinstance(el, expressions.TextExpression) and not _is_bold(el):
            gone.append(el.content)
            el.activeSite.remove(el)
    return gone


def _bar_of(part: stream.Part, el) -> int | None:
    m = el.getContextByClass(stream.Measure)
    return m.number if m is not None else None


def wedges_by_bar(part: stream.Part) -> dict[int, set[str]]:
    """Bar -> {"cresc", "dim"} for the hairpins that start there (music21 reads <wedge> as DynamicWedge spanners)."""
    out: dict[int, set[str]] = {}
    for sp in part.getElementsByClass(dynamics.DynamicWedge):
        first = sp.getFirst()
        n = _bar_of(part, first) if first is not None else None
        if n is not None:
            out.setdefault(n, set()).add("cresc" if isinstance(sp, dynamics.Crescendo) else "dim")
    return out


def pedals_by_bar(part: stream.Part) -> dict[int, set[str]]:
    out: dict[int, set[str]] = {}
    for sp in part.getElementsByClass(expressions.PedalMark):
        first, last = sp.getFirst(), sp.getLast()
        for el, what in ((first, "start"), (last, "stop")):
            n = _bar_of(part, el) if el is not None else None
            if n is not None:
                out.setdefault(n, set()).add(what)
    return out


def _sense(text: str) -> str | None:
    w = text.lower().split()[0].rstrip(".") if text.strip() else ""
    if w in CRESC_WORDS:
        return "cresc"
    if w in DIM_WORDS:
        return "dim"
    return None


# ---------------------------------------------------------------------------------------------------- front matter

def apply_front(sc: stream.Score, form: dict[str, Any], first_number: int, *, title: str | None = None,
                composer: str | None = None) -> list[dict]:
    """The form into the score: metadata (the book's own title and composer win over the page's), and the tempo line
    at the head of the first bar. Returns the log."""
    log_: list[dict] = []
    md = metadata.Metadata()
    md.title = title or form.get("title") or ""
    md.composer = composer or form.get("composer") or ""
    if form.get("movement_or_number"):
        md.movementName = form["movement_or_number"]
    if form.get("opus"):
        md.opusNumber = form["opus"]
    if form.get("dedication"):
        md.dedication = form["dedication"]
    if form.get("editor"):
        md.addContributor(metadata.Contributor(role="editor", name=form["editor"]))
    sc.metadata = md

    heading, mm = form.get("tempo_heading"), form.get("metronome")
    if not heading and not mm:
        return log_
    parts = list(sc.parts)
    if not parts or first_number not in _measures(parts[0]):
        return log_
    # Dedupe: Audiveris's metronome marks and bold heading words in the first two bars of every staff go.
    for p in parts:
        pm = _measures(p)
        for n in (first_number, first_number + 1):
            m = pm.get(n)
            if m is None:
                continue
            for el in list(m.recurse()):
                if isinstance(el, tempo.MetronomeMark) or (isinstance(el, expressions.TextExpression) and _is_bold(el)):
                    el.activeSite.remove(el)
                    log_.append({"layer": "front-clear", "number": n, "what": f"dropped Audiveris's {type(el).__name__} {getattr(el, 'text', None) or getattr(el, 'content', '')!r}"})
    kw: dict[str, Any] = {"text": heading} if heading else {}
    if mm:
        typ, dots = UNITS[mm["unit"]]
        kw.update(number=mm["bpm"], referent=duration.Duration(type=typ, dots=dots))
    mark = tempo.MetronomeMark(**kw)
    if mm and heading:
        mark.parentheses = True
    mark.placement = "above"
    _measures(parts[0])[first_number].insert(0, mark)
    log_.append({"layer": "front", "number": first_number, "what": f"tempo {heading!r}" + (f" {mm['unit']} = {mm['bpm']}" if mm else "")})
    return log_


# ---------------------------------------------------------------------------------------------------- items

def apply_items(sc: stream.Score, doc: dict, enriched: list[dict]) -> tuple[list[dict], dict[str, int]]:
    """Every system's items into the score. Returns (log, counts) with counts = {written per kind, duplicates,
    dropped, out_of_range}."""
    parts = list(sc.parts)
    pm = [_measures(p) for p in parts]
    group = staff_groups(sc)
    multi = {g: sum(1 for x in group if x == g) > 1 for g in set(group)}
    wedges = [wedges_by_bar(p) for p in parts]
    pedals = [pedals_by_bar(p) for p in parts]
    log_: list[dict] = []
    counts: dict[str, int] = {k: 0 for k in ("words", "dynamic", "fingering", "pedal", "ornament")} | {"duplicates": 0, "dropped": 0, "out_of_range": 0}
    seen: set[tuple] = set()

    def dup(key: tuple, it: dict, why: str) -> None:
        counts["duplicates"] += 1
        log_.append({"layer": "dup", "number": it["number"], "kind": it["kind"], "text": it["text"], "what": why})

    for r in enriched:
        if not r.get("ok"):
            continue
        counts["dropped"] += len(r.get("dropped") or [])
        system = next((s for s in doc["systems"] if s["page"] == r["page"] and s["system"] == r["system"]), None)
        if system is None or len(system["staves"]) != len(parts):
            log_.append({"layer": "skip", "number": r["numbers"][0], "what": f"p{r['page']} sys{r['system']}: "
                         f"{len(system['staves']) if system else '?'} staves on the page, {len(parts)} in the file; Audiveris text kept"})
            continue
        for n in r["numbers"]:
            gone = [w for i in range(len(parts)) if n in pm[i] for w in clear_text(pm[i][n])]
            if gone:
                log_.append({"layer": "clear", "number": n, "what": f"dropped Audiveris text {gone}"})
        open_pedal: dict[int, tuple[int, note.NotRest]] = {}      # staff index -> (bar, Ped. note) awaiting its *
        for it in sorted(r["items"], key=lambda x: (x["number"], x["staff"], x["note"])):
            n, si = it["number"], it["staff"] - 1
            if n not in pm[si]:
                continue
            m = pm[si][n]
            slots = note_slots(m)
            idx = it["note"] - 1
            target = slots[min(idx, len(slots) - 1)] if slots else None
            if idx >= len(slots):
                counts["out_of_range"] += 1
            off = float(target.offset) if target is not None else 0.0
            g = group[si]
            kind, text = it["kind"], it["text"]
            if kind == "dynamic":
                key = ("dynamic", g, n, text)
                if key in seen or any(d.value == text for i, s in enumerate(parts) if group[i] == g and n in pm[i]
                                      for d in pm[i][n].recurse().getElementsByClass(dynamics.Dynamic)):
                    dup(key, it, "the bar already has this dynamic")
                    continue
                el = dynamics.Dynamic(text)
                el.placement = "below" if si == 0 or not multi[g] else "above"
                m.insert(off, el)
            elif kind == "words":
                sense = _sense(text)
                if sense and any(sense in wedges[i].get(n, set()) for i in range(len(parts)) if group[i] == g):
                    dup(("wedge", g, n, sense), it, "a hairpin of that sense starts in this bar")
                    continue
                key = ("words", g, n, text.lower())
                if key in seen or any(t.content.strip().lower() == text.lower() for i, s in enumerate(parts) if group[i] == g and n in pm[i]
                                      for t in pm[i][n].recurse().getElementsByClass(expressions.TextExpression)):
                    dup(key, it, "the bar already has these words")
                    continue
                el = expressions.TextExpression(text)
                el.style.fontStyle = "italic"
                el.placement = "below" if si == 0 or not multi[g] else "above"
                m.insert(off, el)
            elif kind == "fingering":
                if target is None or idx >= len(slots):
                    log_.append({"layer": "skip", "number": n, "what": f"fingering {text!r} note {it['note']} of staff {it['staff']}: only {len(slots)} notes"})
                    continue
                key = ("fingering", si, n, it["note"], text)
                have = {str(a.fingerNumber) for a in target.articulations if isinstance(a, articulations.Fingering)}
                digits = [d for d in text.split() if d not in have]
                if key in seen or not digits:
                    dup(key, it, "the note already has this fingering")
                    continue
                if isinstance(target, chord.Chord):
                    # music21 hands a chord's fingerings to its notes in order, so sort the chord low to high and give
                    # Spark's top-to-bottom digits bottom-up: the top digit lands on the top note
                    target.sortAscending(inPlace=True)
                    k = len(target.notes)
                    digits = digits[-k:] if len(digits) >= k else digits
                    for d in reversed(digits):
                        target.articulations.append(articulations.Fingering(int(d)))
                else:
                    if len(digits) > 1:
                        log_.append({"layer": "skip", "number": n, "what": f"fingering {text!r} on a single note: only {digits[0]} written"})
                    target.articulations.append(articulations.Fingering(int(digits[0])))
            elif kind == "pedal":
                if target is None:
                    continue
                key = ("pedal", g, n, text)
                # music21 hangs every spanner on the part's first staff, so a pedal Audiveris read is looked up group-wide
                if key in seen or any(text in pedals[i].get(n, set()) for i in range(len(parts)) if group[i] == g):
                    dup(key, it, "the bar already has this pedal mark")
                    continue
                if text == "start":
                    if si in open_pedal:
                        _close_pedal(parts[si], open_pedal.pop(si), None)
                    open_pedal[si] = (n, target)
                else:
                    if si not in open_pedal:
                        log_.append({"layer": "skip", "number": n, "what": "pedal * without a Ped. before it"})
                        continue
                    _close_pedal(parts[si], open_pedal.pop(si), target)
                    pedals[si].setdefault(n, set()).add("stop")
                pedals[si].setdefault(n, set()).add(text)
            elif kind == "ornament":
                if target is None or idx >= len(slots):
                    log_.append({"layer": "skip", "number": n, "what": f"{text} note {it['note']} of staff {it['staff']}: only {len(slots)} notes"})
                    continue
                key = ("ornament", si, n, it["note"])
                if key in seen or any(isinstance(e, ORN_CLASSES) for e in target.expressions):
                    dup(key, it, "the note already has an ornament")
                    continue
                target.expressions.append(ORN[text]())
            seen.add(key)
            counts[kind] += 1
            log_.append({"layer": kind, "number": n, "staff": it["staff"], "note": it["note"], "text": text})
        for si, (n, start) in open_pedal.items():
            _close_pedal(parts[si], (n, start), None)
            log_.append({"layer": "pedal", "number": n, "what": "Ped. without a *: runs to the end of its bar"})
    return log_, counts


def _close_pedal(part: stream.Part, start: tuple[int, note.NotRest], end: note.NotRest | None) -> None:
    n, first = start
    if end is None:
        m = first.getContextByClass(stream.Measure)
        slots = note_slots(m) if m is not None else [first]
        end = slots[-1] if slots else first
    sp = expressions.PedalMark(first, end) if end is not first else expressions.PedalMark(first)
    part.insert(0, sp)


# ---------------------------------------------------------------------------------------------------- closed questions

def apply_verify(sc: stream.Score, verify: list[dict]) -> tuple[list[dict], dict[int, list[str]]]:
    """Accidentals: flags only. Ornaments: removed when Spark says the sign is not one."""
    parts = list(sc.parts)
    pm = [_measures(p) for p in parts]
    group = staff_groups(sc)
    log_: list[dict] = []
    flags: dict[int, list[str]] = {}
    for r in verify:
        d, ans = r["inter"], r.get("answer")
        if not ans:
            continue
        n, tag, verdict = d["number"], d["tag"], str(ans.get("verdict", "")).strip().lower()
        if n is None or not verdict:
            continue
        shape = (d.get("shape") or "").upper()
        if tag == "alter":
            read = ALTER_SHAPES.get(shape, shape.lower())
            if verdict != read:
                what = "no accidental" if verdict == "nothing_else" else verdict.replace("_", " ")
                flags.setdefault(n, []).append(f"accidental: the engine read a {read.replace('_', ' ')}; Spark sees {what} (not changed: the PDF is the truth)")
                log_.append({"layer": "flag", "number": n, "what": f"accidental {read} vs {verdict}"})
        elif tag == "ornament" and verdict != "ornament":
            cls = ORN_SHAPES.get(shape, expressions.GeneralMordent)
            rank = d.get("staff")
            idx = [rank - 1] if rank and 1 <= rank <= len(parts) else [i for i, g in enumerate(group)]
            k = 0
            for i in idx:
                if n not in pm[i]:
                    continue
                for el in pm[i][n].recurse().notes:
                    kept = [e for e in el.expressions if not isinstance(e, (cls, ORN_CLASSES) if cls is expressions.GeneralMordent else cls)]
                    if len(kept) != len(el.expressions):
                        el.expressions = kept
                        k += 1
            log_.append({"layer": "A", "number": n, "what": f"ornament {shape} is {verdict} {ans.get('value') or ''!s}: removed {k}".strip()})
    return log_, flags
