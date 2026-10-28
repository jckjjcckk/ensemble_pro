"""Review flags per bar and per-page MusicXML slices for rendering. GT-free.

Flags (keyed by global bar number, with the 004 key): Audiveris's own `abnormal` stacks (its rhythm check, with
expected/actual duration and excess), plus a durations-add-up check on the final file (a voice overflowing the
bar, or the longest voice shorter than the time signature in force). Per page it also lists the text Spark
wrote (bar, staff, how it was placed), the ornaments written/skipped and the symbol verdicts (edits.json).

Slices: final-p{N}.musicxml holds the bars of scan page N (clef, key and time in force carried into the first
bar; a movement that starts on the page gets a system break and its name as a rehearsal mark). Spanners are
not carried into slices; final.musicxml keeps them.

Usage: uv run python experiments/omr/review.py RUN_DIR   (needs model.json, final.musicxml, edits.json, reread.json)
Writes flags.json and slices/final-p{N}.musicxml.
"""

from __future__ import annotations

import copy
import json
import sys
from fractions import Fraction
from pathlib import Path

from music21 import clef, converter, expressions, key, layout, meter, stream


def rhythm_flags(m: stream.Measure, staff: str) -> list[str]:
    ts = m.timeSignature or m.getContextByClass(meter.TimeSignature)
    if ts is None:
        return []
    bar = Fraction(ts.barDuration.quarterLength)
    out, longest = [], Fraction(0)
    for v in (list(m.voices) if m.voices else [m]):
        total = Fraction(0)
        for el in v.notesAndRests:
            if not el.duration.isGrace:
                total = max(total, Fraction(el.offset) + Fraction(el.duration.quarterLength))
        if total > bar:
            out.append(f"rhythm: {staff} staff voice sums to {total} > {bar} ({ts.ratioString})")
        longest = max(longest, total)
    if 0 < longest < bar:
        out.append(f"rhythm: {staff} staff fills only {longest} of {bar} ({ts.ratioString})")
    return out


def main() -> None:
    run = Path(sys.argv[1])
    model = json.load(open(run / "model.json"))
    sc = converter.parse(str(run / "final.musicxml"))
    parts = list(sc.parts)
    pm = [{m.number: m for m in p.getElementsByClass(stream.Measure)} for p in parts]
    edits = json.load(open(run / "edits.json"))
    reread = json.load(open(run / "reread.json")) if (run / "reread.json").exists() else []
    names = {mv["first_number"]: mv["name"] or f"Movement {mv['movement']}" for mv in model["movements"]}

    pages = []
    (run / "slices").mkdir(exist_ok=True)
    for pg in model["pages"]:
        ms = [m for m in model["measures"] if m["page"] == pg["page"]]
        nums = [m["number"] for m in ms]
        flags: dict[str, list[str]] = {}
        for m in ms:
            whys = []
            if m["abnormal"]:
                why = f"Audiveris abnormal: duration {m['duration']} vs expected {m['expected']}"
                whys.append(why + (f" (excess {m['excess']})" if m["excess"] else ""))
            for i, staff in enumerate(("upper", "lower")):
                if m["number"] in pm[i]:
                    whys += rhythm_flags(pm[i][m["number"]], staff)
                else:
                    whys.append(f"{staff} staff: bar missing from the export")
            if whys:
                flags[f"{m['number']} ({m['key']})"] = whys
        text = {}
        for r in reread:
            if r["page"] != pg["page"]:
                continue
            for it in r["placed"]:
                where = f"staff {it['staff']} {it['placement']}" + ("" if it["how"] == "x" else f", {it['how']}")
                if it["label_agrees"] is False:
                    where += f", Spark's label said {it['spark_bar']}"
                    if not it["how"].startswith("glyph"):
                        # no Audiveris glyph confirmed the point: x and label disagree, a person should look
                        m = next(x for x in ms if x["number"] == it["number"])
                        flags.setdefault(f"{m['number']} ({m['key']})", []).append(
                            f"text: Spark's position puts {it['text']!r} here, its bar label says {it['spark_bar']}")
                text.setdefault(str(it["number"]), []).append(f"{it['text']} ({where})")
        on_page = [e for e in edits if e["number"] in set(nums)]
        pages.append({
            "page": pg["page"], "pdf_page": pg["pdf_page"], "bars": len(ms), "first": nums[0], "last": nums[-1],
            "movements": sorted({m["movement"] for m in ms}), "flags": flags, "text_added": text,
            "ornaments_added": [f"m{e['number']}: {e['what']}" for e in on_page if e["layer"] == "B-orn"],
            "ornaments_skipped": [f"m{e['number']}: {e['what']}" for e in on_page if e["layer"] == "B-orn-skip"],
            "symbol_edits": [f"m{e['number']}: {e['what']}" for e in on_page if e["layer"] == "A"],
        })

        # slice for rendering
        out = stream.Score()
        new_parts = []
        for i, p in enumerate(parts):
            np_ = stream.Part(id=f"P{i + 1}")
            np_.partName = p.partName or "Piano"
            for j, n in enumerate(nums):
                src = pm[i].get(n)
                if src is None:
                    continue
                m2 = copy.deepcopy(src)
                if j == 0:
                    for cls in (clef.Clef, key.KeySignature, meter.TimeSignature):
                        if not m2.getElementsByClass(cls):
                            ctx = src.getContextByClass(cls)
                            if ctx is not None:
                                m2.insert(0, copy.deepcopy(ctx))
                if n in names and i == 0:
                    if j > 0:
                        m2.insert(0, layout.SystemLayout(isNew=True))
                    m2.insert(0, expressions.RehearsalMark(names[n]))
                np_.append(m2)
            new_parts.append(np_)
        for np_ in new_parts:
            out.insert(0, np_)
        out.write("musicxml", fp=str(run / "slices" / f"final-p{pg['page']}.musicxml"), makeNotation=False)
        print(f"page {pg['page']}: bars {nums[0]}..{nums[-1]} ({len(ms)}), {len(flags)} flagged, text in {len(text)} bars")
    (run / "flags.json").write_text(json.dumps(pages, indent=1))


if __name__ == "__main__":
    main()
