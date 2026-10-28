"""Turn the Spark answers into MusicXML edits on the merged, globally numbered score (score.py). GT-free rules,
the same code would run in the product. Every edit is addressed by global bar number.

  A  verify.json  tuplet that is not a tuplet -> un-tuplet the bar's notes; dynamic re-read -> replace the value
                  or drop it; fermata that is not a fermata -> drop it
  B  reread.json  text: for every system Spark answered, Audiveris's words and dynamics in its bars are dropped
                  and Spark's words are written where text_place.py put them (bar by x, staff by y, placement
                  above/below; the offset snaps to the note onset nearest the word's position in the bar)
                  ornaments: added to the n-th notehead of the melody voice of that staff, only when placement
                  is unambiguous (single voice, no grace notes, bar not abnormal, index in range)

The written file goes through the app's `musicxml_fix` again (music21 renumbers the voices on every write; the
`<defaults>` and credits come from the base file, which score.py already fixed).

Usage: uv run python experiments/omr/apply_edits.py RUN_DIR [--base base.musicxml] [--out final.musicxml]
Writes RUN_DIR/final.musicxml and RUN_DIR/edits.json (one record per edit or skip).
"""

from __future__ import annotations

import argparse
import json
import sys
from fractions import Fraction
from pathlib import Path

from music21 import converter, duration, dynamics, expressions, stream

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))           # api/, for app.librarian.musicxml_fix
from app.librarian.musicxml_fix import PageLayout, fix_musicxml  # noqa: E402

ORN = {"mordent": expressions.Mordent, "inverted_mordent": expressions.InvertedMordent, "trill": expressions.Trill,
       "turn": expressions.Turn, "schleifer": expressions.Schleifer}
ORN_CLASSES = tuple(ORN.values())
DYN = {"p", "pp", "ppp", "mp", "mf", "f", "ff", "fff", "sf", "sfz", "fp", "fz", "rf", "rfz", "sfp"}


def measures(part: stream.Part) -> dict[int, stream.Measure]:
    return {m.number: m for m in part.getElementsByClass(stream.Measure)}


def containers(m: stream.Measure):
    return list(m.voices) if m.voices else [m]


def note_elements(m: stream.Measure, staff: int) -> list:
    """Non-grace notes/chords of the outer voice (highest voice on the upper staff, lowest on the lower), left to
    right; how a reader counts noteheads when inner voices share the staff."""
    vs = containers(m)
    if len(vs) > 1:
        def mean_pitch(v):
            ps = [p.midi for el in v.notes for p in el.pitches]
            return sum(ps) / len(ps) if ps else (0 if staff == 1 else 999)
        vs = [max(vs, key=mean_pitch) if staff == 1 else min(vs, key=mean_pitch)]
    els = [(Fraction(el.offset), el) for v in vs for el in v.notes if not el.duration.isGrace]
    return [el for _, el in sorted(els, key=lambda t: t[0])]


def untuplet(m: stream.Measure) -> int:
    n = 0
    for v in containers(m):
        for el in v.notesAndRests:
            if el.duration.tuplets:
                el.duration = duration.Duration(type=el.duration.type, dots=el.duration.dots)
                n += 1
    return n


def clear_text(m: stream.Measure) -> list[str]:
    gone = []
    for el in list(m.recurse()):
        if isinstance(el, dynamics.Dynamic):
            gone.append(el.value)
            el.activeSite.remove(el)
        elif isinstance(el, expressions.TextExpression):
            gone.append(el.content)
            el.activeSite.remove(el)
    return gone


def snap_offset(m_upper: stream.Measure, m_lower: stream.Measure, frac: float) -> float:
    """The note onset in the bar nearest to the word's relative x position (a proportional guess of the beat)."""
    bar_ql = m_upper.barDuration.quarterLength if m_upper.barDuration else 3.0
    onsets = sorted({float(el.offset) for m in (m_upper, m_lower) for v in containers(m) for el in v.notesAndRests
                     if not el.duration.isGrace})
    if not onsets:
        return 0.0
    target = frac * bar_ql
    return min(onsets, key=lambda o: abs(o - target))


def apply(base: str, run: Path) -> tuple[stream.Score, list[dict]]:
    sc = converter.parse(base)
    parts = list(sc.parts)
    staff_m = {1: measures(parts[0]), 2: measures(parts[1])}
    model = json.load(open(run / "model.json"))
    abnormal = {m["number"] for m in model["measures"] if m["abnormal"]}
    log: list[dict] = []

    verify = json.load(open(run / "verify.json")) if (run / "verify.json").exists() else []
    for r in verify:
        d, ans = r["inter"], r["answer"]
        n, tag, verdict = d["number"], d["tag"], str(ans.get("verdict", ""))
        if n not in staff_m[1]:
            continue
        both = (staff_m[1][n], staff_m[2][n])
        if tag == "tuplet" and verdict != "tuplet_number":
            k = sum(untuplet(m) for m in both)
            log.append({"layer": "A", "number": n, "what": f"tuplet is {verdict} {ans.get('value', '')!r}: un-tupleted {k} notes"})
        elif tag == "dynamics":
            shape = (d["shape"] or "").replace("DYNAMICS_", "").lower()
            val = str(ans.get("value", "")).strip().rstrip(".").lower()
            for m in both:
                for el in list(m.recurse().getElementsByClass(dynamics.Dynamic)):
                    if el.value == shape:
                        el.activeSite.remove(el)
            if verdict == "dynamic_marking" and val in DYN:
                staff_m[d["staff"] or 1][n].insert(0, dynamics.Dynamic(val))
                log.append({"layer": "A", "number": n, "what": f"dynamic {shape} -> {val}"})
            else:
                log.append({"layer": "A", "number": n, "what": f"dropped dynamic {shape} ({verdict} {ans.get('value', '')!r})"})
        elif tag == "fermata" and verdict != "fermata":
            for m in both:
                for el in m.recurse().notesAndRests:
                    kept = [e for e in el.expressions if not isinstance(e, expressions.Fermata)]
                    if len(kept) != len(el.expressions):
                        el.expressions = kept
                        log.append({"layer": "A", "number": n, "what": f"dropped fermata ({verdict})"})

    reread = json.load(open(run / "reread.json")) if (run / "reread.json").exists() else []
    for r in reread:
        if not r["ok"]:
            log.append({"layer": "B", "number": r["numbers"][0], "what": f"p{r['page']} sys{r['system']}: no answer, Audiveris text kept"})
            continue
        for n in r["numbers"]:
            gone = clear_text(staff_m[1][n]) + clear_text(staff_m[2][n])
            if gone:
                log.append({"layer": "B-clear", "number": n, "what": f"dropped Audiveris text {gone}"})
        for it in r["placed"]:
            n, staff = it["number"], it["staff"]
            off = snap_offset(staff_m[1][n], staff_m[2][n], it["frac"])
            word = it["text"].strip()
            el = dynamics.Dynamic(word.rstrip(".").lower()) if it["kind"] == "dynamic" else expressions.TextExpression(word)
            el.placement = it["placement"]
            staff_m[staff][n].insert(off, el)
            log.append({"layer": "B-text", "number": n, "staff": staff, "text": word, "offset": off, "how": it["how"],
                        "spark_bar": it["spark_bar"], "what": f"+{word!r} staff {staff} {it['placement']} at {off} ({it['how']})"})
        for mrec in r["answer"].get("measures", []) or []:
            n = mrec.get("number")
            if n not in r["numbers"]:
                continue
            for o in mrec.get("ornaments", []) or []:
                staff = 2 if o.get("staff") == "lower" else 1
                m = staff_m[staff][n]
                els = note_elements(m, staff)
                idx, kind = o.get("note_index"), ORN.get(str(o.get("kind", "")).lower())
                if not isinstance(idx, int) or not 1 <= idx <= len(els) or kind is None:
                    log.append({"layer": "B-orn-skip", "number": n, "what": f"{o} not applicable ({len(els)} notes on staff {staff})"})
                    continue
                n_voices = len(m.voices) if m.voices else 1
                grace = any(el.duration.isGrace for v in containers(m) for el in v.notes)
                if n_voices > 1 or grace or n in abnormal:
                    log.append({"layer": "B-orn-skip", "number": n, "what": f"{o.get('kind')} staff {staff} note {idx}: ambiguous "
                                f"(voices={n_voices}, grace={grace}, abnormal={n in abnormal})"})
                    continue
                el = els[idx - 1]
                if any(isinstance(e, ORN_CLASSES) for e in el.expressions):
                    continue
                el.expressions.append(kind())
                log.append({"layer": "B-orn", "number": n, "what": f"+{o.get('kind')} staff {staff} note {idx} "
                            f"({el.pitches[0].nameWithOctave if el.pitches else '?'})"})
    return sc, log


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("run")
    ap.add_argument("--base", default="base.musicxml")
    ap.add_argument("--out", default="final.musicxml")
    a = ap.parse_args()
    run = Path(a.run)
    sc, log = apply(str(run / a.base), run)
    sc.write("musicxml", fp=str(run / a.out), makeNotation=False)
    (run / a.out).write_bytes(fix_musicxml((run / a.out).read_bytes(), PageLayout.read(run / a.base)))
    (run / "edits.json").write_text(json.dumps(log, indent=1))
    by = {}
    for e in log:
        by[e["layer"]] = by.get(e["layer"], 0) + 1
    print(f"wrote {run / a.out}: {by}")


if __name__ == "__main__":
    main()
