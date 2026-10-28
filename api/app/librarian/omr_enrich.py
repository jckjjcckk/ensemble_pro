"""The writers of librarian agent v2 (`omr_agent`): Spark's answers become MusicXML by fixed rules, never a pitch,
duration, rest or barline change. No model. Every write is undoable by bar (`Undo`), so the verify step
(`omr_verify`) can put Audiveris's reading back where Spark's does not match the scan.

  apply_front   the front-matter form: a `MetronomeMark` (the tempo heading as its text, the metronome's unit and
                number when printed) at offset 0 of the first bar of the first music page, in the top staff;
                Audiveris's own metronome marks and bold heading words in the first two bars are removed first, so
                the heading is never doubled and never lands on bar 2 (the Goldberg defect: Audiveris anchored
                "Andante espressivo." to a chord in bar 2). Title and composer in the file are what the page prints
                (the form, else the scan's credits; the library's shelf title is never written into the MusicXML:
                CK, 2026-10-28 late); movement, opus, dedication and editor go into the metadata.
  apply_text    per system Spark answered: Audiveris's dynamics and plain (non-bold) words in its bars are dropped,
                then every placed item (a text glyph confirmed it, `omr_agent.place`) is written at the note onset
                nearest its position in the bar: a dynamic as `<dynamics>` (never as words), a phrase as
                `<words font-style="italic">`, below the top staff of a part and above the staves under it. Dedupe
                first: the same text already in the bar, or a "cresc."/"dim." word where a hairpin of that sense
                starts in the bar, is skipped and counted (`duplicates`).
  apply_verify  an accidental the engine graded low: Spark's verdict never edits the pitch; a disagreement flags
                the bar. An ornament that Spark says is not one is removed from that bar's staff.
  flags         `omr_score.flagged_bars` as before (abnormal, rhythm, missing bars) plus the verify flags.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from music21 import dynamics, duration, expressions, metadata, stream, tempo

from .omr_agent import UNITS
from .omr_score import staff_groups

log = logging.getLogger("folio.omr")

ORN_CLASSES = (expressions.GeneralMordent, expressions.Trill, expressions.Turn, expressions.Schleifer)
ORN_SHAPES = {"MORDENT": expressions.Mordent, "MORDENT_INVERTED": expressions.InvertedMordent, "TR": expressions.Trill,
              "TURN": expressions.Turn, "TURN_INVERTED": expressions.Turn, "TURN_SLASH": expressions.Turn, "TURN_UP": expressions.Turn}
ALTER_SHAPES = {"SHARP": "sharp", "FLAT": "flat", "NATURAL": "natural", "DOUBLE_SHARP": "double_sharp", "DOUBLE_FLAT": "double_flat"}
CRESC_WORDS = ("cresc", "crescendo")
DIM_WORDS = ("dim", "dimin", "diminuendo", "decresc", "decrescendo")


@dataclass
class Undo:
    """What the writers did to one bar: the elements they added (container, element) and the ones they removed
    (container, offset, element). `revert` puts the bar back as Audiveris read it."""
    added: list[tuple[stream.Stream, Any]] = field(default_factory=list)
    removed: list[tuple[stream.Stream, float, Any]] = field(default_factory=list)

    def revert(self) -> None:
        for container, el in self.added:
            if el in container:
                container.remove(el)
        for container, off, el in self.removed:
            container.insert(off, el)
        self.added.clear()
        self.removed.clear()


Undos = dict[int, Undo]


def _undo(undos: Undos, n: int) -> Undo:
    return undos.setdefault(n, Undo())


# ---------------------------------------------------------------------------------------------------- helpers

def _measures(part: stream.Part) -> dict[int, stream.Measure]:
    return {m.number: m for m in part.getElementsByClass(stream.Measure)}


def _containers(m: stream.Measure):
    return list(m.voices) if m.voices else [m]


def _is_bold(el: expressions.TextExpression) -> bool:
    return str(getattr(el.style, "fontWeight", "") or "").lower() == "bold"


def _remove(undo: Undo, el) -> None:
    site = el.activeSite
    undo.removed.append((site, float(el.getOffsetBySite(site)), el))
    site.remove(el)


def clear_text(m: stream.Measure, undo: Undo) -> list[str]:
    """Drop Audiveris's dynamics and plain words from a bar Spark answered; bold words (headings) and metronome marks
    stay (they belong to the tempo line, which `apply_front` handles for the first page)."""
    gone = []
    for el in list(m.recurse()):
        if isinstance(el, dynamics.Dynamic):
            gone.append(el.value)
            _remove(undo, el)
        elif isinstance(el, expressions.TextExpression) and not _is_bold(el):
            gone.append(el.content)
            _remove(undo, el)
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


def _sense(text: str) -> str | None:
    w = text.lower().split()[0].rstrip(".") if text.strip() else ""
    if w in CRESC_WORDS:
        return "cresc"
    if w in DIM_WORDS:
        return "dim"
    return None


def _snap_offset(bar: list[stream.Measure], frac: float) -> float:
    """The note onset in the bar nearest to the word's relative x position (a proportional guess of the beat)."""
    first = bar[0]
    bar_ql = first.barDuration.quarterLength if first.barDuration else 4.0
    onsets = sorted({float(el.offset) for m in bar for v in _containers(m) for el in v.notesAndRests if not el.duration.isGrace})
    if not onsets:
        return 0.0
    target = frac * bar_ql
    return min(onsets, key=lambda o: abs(o - target))


# ---------------------------------------------------------------------------------------------------- front matter

def apply_front(sc: stream.Score, form: dict[str, Any], first_number: int, undos: Undos, *, credit_title: str = "",
                credit_composer: str = "") -> list[dict]:
    """The form into the score: metadata (the page's own heading, else the scan's credits), and the tempo line at
    the head of the first bar. Returns the log."""
    log_: list[dict] = []
    md = metadata.Metadata()
    md.title = form.get("title") or credit_title or ""
    md.composer = form.get("composer") or credit_composer or ""
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
                    _remove(_undo(undos, n), el)
                    log_.append({"layer": "front-clear", "number": n, "what": f"dropped Audiveris's {type(el).__name__} {getattr(el, 'text', None) or getattr(el, 'content', '')!r}"})
    kw: dict[str, Any] = {"text": heading} if heading else {}
    if mm:
        typ, dots = UNITS[mm["unit"]]
        kw.update(number=mm["bpm"], referent=duration.Duration(type=typ, dots=dots))
    mark = tempo.MetronomeMark(**kw)
    if mm and heading:
        mark.parentheses = True
    mark.placement = "above"
    m1 = _measures(parts[0])[first_number]
    m1.insert(0, mark)
    _undo(undos, first_number).added.append((m1, mark))
    log_.append({"layer": "front", "number": first_number, "what": f"tempo {heading!r}" + (f" {mm['unit']} = {mm['bpm']}" if mm else "")})
    return log_


# ---------------------------------------------------------------------------------------------------- text

def apply_text(sc: stream.Score, doc: dict, reread: list[dict], undos: Undos) -> tuple[list[dict], dict[str, int]]:
    """Every system's placed text into the score. Returns (log, counts) with counts = {words, dynamic, duplicates,
    dropped (by the placement: junk, no glyph), systems, systems_answered}."""
    parts = list(sc.parts)
    pm = [_measures(p) for p in parts]
    group = staff_groups(sc)
    multi = {g: sum(1 for x in group if x == g) > 1 for g in set(group)}
    wedges = [wedges_by_bar(p) for p in parts]
    log_: list[dict] = []
    counts = {"words": 0, "dynamic": 0, "duplicates": 0, "dropped": 0, "systems": len(reread), "systems_answered": 0}
    seen: set[tuple] = set()

    def dup(it: dict, why: str) -> None:
        counts["duplicates"] += 1
        log_.append({"layer": "dup", "number": it["number"], "kind": it["kind"], "text": it["text"], "what": why})

    for r in reread:
        if not r.get("ok"):
            continue
        counts["systems_answered"] += 1
        counts["dropped"] += len(r.get("dropped") or [])
        system = next((s for s in doc["systems"] if s["page"] == r["page"] and s["system"] == r["system"]), None)
        if system is None or len(system["staves"]) != len(parts):
            log_.append({"layer": "skip", "number": r["numbers"][0], "what": f"p{r['page']} sys{r['system']}: "
                         f"{len(system['staves']) if system else '?'} staves on the page, {len(parts)} in the file; Audiveris text kept"})
            continue
        for n in r["numbers"]:
            gone = [w for i in range(len(parts)) if n in pm[i] for w in clear_text(pm[i][n], _undo(undos, n))]
            if gone:
                log_.append({"layer": "clear", "number": n, "what": f"dropped Audiveris text {gone}"})
        for it in r["placed"]:
            n, si = it["number"], it["staff"] - 1
            if n not in pm[si]:
                continue
            m = pm[si][n]
            g = group[si]
            kind, text = it["kind"], it["text"]
            bar = [pm[i][n] for i in range(len(parts)) if n in pm[i]]
            off = _snap_offset(bar, it["frac"])
            if kind == "dynamic":
                key = ("dynamic", g, n, text)
                if key in seen or any(d.value == text for i in range(len(parts)) if group[i] == g and n in pm[i]
                                      for d in pm[i][n].recurse().getElementsByClass(dynamics.Dynamic)):
                    dup(it, "the bar already has this dynamic")
                    continue
                el = dynamics.Dynamic(text)
            else:
                sense = _sense(text)
                if sense and any(sense in wedges[i].get(n, set()) for i in range(len(parts)) if group[i] == g):
                    dup(it, "a hairpin of that sense starts in this bar")
                    continue
                key = ("words", g, n, text.lower())
                if key in seen or any(t.content.strip().lower() == text.lower() for i in range(len(parts)) if group[i] == g and n in pm[i]
                                      for t in pm[i][n].recurse().getElementsByClass(expressions.TextExpression)):
                    dup(it, "the bar already has these words")
                    continue
                el = expressions.TextExpression(text)
                el.style.fontStyle = "italic"
            el.placement = "below" if si == 0 or not multi[g] else "above"
            m.insert(off, el)
            _undo(undos, n).added.append((m, el))
            seen.add(key)
            counts[kind] += 1
            log_.append({"layer": kind, "number": n, "staff": it["staff"], "text": text, "how": it["how"], "glyph": it.get("glyph")})
    return log_, counts


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
            cls = ORN_SHAPES.get(shape)
            rank = d.get("staff")
            idx = [rank - 1] if rank and 1 <= rank <= len(parts) else [i for i, g in enumerate(group)]
            k = 0
            for i in idx:
                if n not in pm[i]:
                    continue
                for el in pm[i][n].recurse().notes:
                    kept = [e for e in el.expressions if not isinstance(e, cls or ORN_CLASSES)]
                    if len(kept) != len(el.expressions):
                        el.expressions = kept
                        k += 1
            log_.append({"layer": "A", "number": n, "what": f"ornament {shape} is {verdict} {ans.get('value') or ''!s}: removed {k}".strip()})
    return log_, flags
