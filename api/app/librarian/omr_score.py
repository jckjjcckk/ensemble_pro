"""One MusicXML for the converted book, with Spark's answers applied and the review flags (feature 005). No model.

Ported from `api/experiments/omr/{score,apply_edits,review}.py`, generalised from the grand staff to any staves:

  merge   Audiveris writes one file per movement (`<stem>.mvtK.mxl`), each numbered from 1. The k-th measure of
          movement K is the stack with movement == K and movement_bar == k in the bar map (`omr_book`), so every
          measure gets its global number. A part the export left a bar out of is lined up by Audiveris's own
          measure numbers and gets a whole-bar rest there, flagged; any other mismatch stops the run before any
          model call (the map and the file would address different bars). Measures are moved, not copied; each movement's spanners are carried.
          Parts keep Audiveris's ids, so a two-staff piano stays one part ("P1-Staff1", "P1-Staff2").
  flags   per bar: Audiveris's own `abnormal` (its rhythm check), a durations-add-up check on every staff of the
          final file, plus whatever the writers add (`omr_enrich`: an accidental Spark disagrees with, a bar a staff
          had to be filled in). A flagged bar is "doubtful": the PDF is the truth.

Spark's answers are written by `omr_enrich` (v2, 2026-10-28); the v1 `apply` (closed-question edits, text placed by
Spark's pixel position) is gone with `omr_spark`.
"""

from __future__ import annotations

from fractions import Fraction
from pathlib import Path
from typing import Any

from music21 import converter, layout, meter, note, stream


class BarsDoNotLineUp(RuntimeError):
    pass


def movement_files(run: Path) -> list[Path]:
    files = sorted(run.glob("*.mvt*.mxl"), key=lambda p: int(p.name.rsplit("mvt", 1)[1].split(".")[0]))
    return files or sorted(run.glob("*.mxl"))


def merge(doc: dict, files: list[Path]) -> tuple[stream.Score, dict[int, list[str]]]:
    """The movements on the global bar numbers, and the bars a staff had to be filled in (number -> reasons)."""
    filled: dict[int, list[str]] = {}
    groups: dict[int, list[dict]] = {}
    for m in doc["measures"]:
        groups.setdefault(m["movement"], []).append(m)
    if sorted(groups) != list(range(1, len(files) + 1)):
        raise BarsDoNotLineUp(f"the page map has movements {sorted(groups)}, the engine exported {len(files)} files")
    out = stream.Score()
    parts: list[stream.Part] | None = None
    for k, path in enumerate(files, start=1):
        src_score = converter.parse(str(path))
        src = list(src_score.parts)
        if parts is None:
            parts = []
            for s in src:
                p = stream.PartStaff(id=s.id) if isinstance(s, stream.PartStaff) else stream.Part(id=s.id)
                p.partName = s.partName or ""
                parts.append(p)
            index = {id(s): i for i, s in enumerate(src)}
            for g in src_score.getElementsByClass(layout.StaffGroup):
                kept = [parts[index[id(p)]] for p in g.getSpannedElements() if id(p) in index]
                if len(kept) >= 2:
                    out.insert(0, layout.StaffGroup(kept, name=g.name, symbol=g.symbol or "bracket", barTogether=g.barTogether))
        if len(src) != len(parts):
            raise BarsDoNotLineUp(f"movement {k} has {len(src)} staves, movement 1 had {len(parts)}")
        bars = groups[k]
        for i, (p, s) in enumerate(zip(parts, src), start=1):
            for m, rec in zip(_line_up(list(s.getElementsByClass(stream.Measure)), bars, k), bars):
                if m is None:                      # the export left this staff's bar out: a whole-bar rest, flagged
                    m = _rest_bar(p, s)
                    filled.setdefault(rec["number"], []).append(f"staff {i}: bar missing from the export (a rest stands in)")
                m.number = rec["number"]
                p.append(m)
            for sp in s.spanners:
                p.insert(0, sp)
    for p in parts or []:
        out.insert(0, p)
    if parts and len(parts) == 2 and not out.getElementsByClass(layout.StaffGroup):
        out.insert(0, layout.StaffGroup(parts, symbol="brace", barTogether=True, name="Piano"))
    return out, filled


def _line_up(ms: list[stream.Measure], bars: list[dict], k: int) -> list[stream.Measure | None]:
    """The export's measures in the order of the movement's bars. Same count: by ordinal (score.py's rule). Fewer:
    Audiveris numbers a movement's measures 1..N in stack order and leaves out a part's bar it could not build (Rach 1
    two-piano p3-5: Piano II lacks 17 and 19), so by number, a gap where one is missing. Anything else stops the run."""
    if len(ms) == len(bars):
        return ms
    nums = [m.number for m in ms]
    if (len(ms) < len(bars) and len(set(nums)) == len(nums) and all(not m.numberSuffix for m in ms)
            and all(1 <= n <= len(bars) for n in nums)):
        by = dict(zip(nums, ms))
        return [by.get(rec["movement_bar"]) for rec in bars]
    raise BarsDoNotLineUp(f"movement {k}: {len(ms)} measures in the export, {len(bars)} bars on the pages")


def _rest_bar(p: stream.Part, src: stream.Part) -> stream.Measure:
    """A whole-bar rest in the time signature in force (the part's last bar's, else the export's first)."""
    prev = p.getElementsByClass(stream.Measure).last() if p.getElementsByClass(stream.Measure) else None
    ts = (prev.timeSignature or prev.getContextByClass(meter.TimeSignature)) if prev is not None else None
    if ts is None:
        ts = next(iter(src.recurse().getElementsByClass(meter.TimeSignature)), None)
    m = stream.Measure()
    r = note.Rest(quarterLength=ts.barDuration.quarterLength if ts else 4.0)
    r.fullMeasure = True
    m.append(r)
    return m


# ---------------------------------------------------------------------------------------------------- flags

def _measures(part: stream.Part) -> dict[int, stream.Measure]:
    return {m.number: m for m in part.getElementsByClass(stream.Measure)}


def _containers(m: stream.Measure):
    return list(m.voices) if m.voices else [m]


def staff_groups(sc: stream.Score) -> list[int]:
    """For every staff (music21 part, top to bottom) the index of the app part it belongs to (PartStaffs of one
    part share an id prefix, as `import_musicxml.part_groups` reads them)."""
    out, last, g = [], None, -1
    for p in sc.parts:
        sid = str(p.id).rsplit("-Staff", 1)[0] if isinstance(p, stream.PartStaff) and "-Staff" in str(p.id) else None
        if sid is None or sid != last:
            g += 1
        out.append(g)
        last = sid
    return out


def rhythm_flags(m: stream.Measure, staff: int) -> list[str]:
    ts = m.timeSignature or m.getContextByClass(meter.TimeSignature)
    if ts is None:
        return []
    bar = Fraction(ts.barDuration.quarterLength)
    out, longest = [], Fraction(0)
    for v in _containers(m):
        total = Fraction(0)
        for el in v.notesAndRests:
            if not el.duration.isGrace:
                total = max(total, Fraction(el.offset) + Fraction(el.duration.quarterLength))
        if total > bar:
            out.append(f"rhythm: staff {staff} voice sums to {total} > {bar} ({ts.ratioString})")
        longest = max(longest, total)
    if 0 < longest < bar:
        out.append(f"rhythm: staff {staff} fills only {longest} of {bar} ({ts.ratioString})")
    return out


def flagged_bars(sc: stream.Score, doc: dict, extra: dict[int, list[str]]) -> list[dict[str, Any]]:
    """Every doubtful bar: global number, PDF page, the 004 key, its box on that page (fractions), the reasons."""
    pm = [_measures(p) for p in sc.parts]
    pdf_page = {p["page"]: p["pdf_page"] for p in doc["pages"]}
    out = []
    for m in doc["measures"]:
        whys = []
        if m.get("abnormal"):
            why = f"Audiveris abnormal: duration {m.get('duration')} vs expected {m.get('expected')}"
            whys.append(why + (f" (excess {m['excess']})" if m.get("excess") else ""))
        for i, staff in enumerate(pm, start=1):
            if m["number"] in staff:
                whys += rhythm_flags(staff[m["number"]], i)
            else:
                whys.append(f"staff {i}: bar missing from the export")
        whys += extra.get(m["number"], [])
        if whys:
            out.append({"number": m["number"], "page": pdf_page[m["page"]], "key": m["key"], "box": m["box"],
                        "reasons": list(dict.fromkeys(whys))})
    return out
