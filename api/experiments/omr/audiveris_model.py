"""Read an unzipped Audiveris 5.11 book (book.xml + sheet#N/sheet#N.xml, from book_box.py) into one model.json
over the whole page set, with continuous bar ids (measure_map) and the grade gate for the symbol verifier.

What comes out (all pixel values in the 300 dpi page frame Audiveris works in, = pdftoppm -r 300 within 1 px):
  pages       per scan page: sheet, pdf page, width, height, interline
  systems     per system: page, system (1-based top to bottom), staves (top/bottom/left/right), measure numbers
  measures    measure_map records: key "page.system.bar", global number, box fractions, movement, Audiveris's
              own rhythm check (abnormal, expected, duration, excess)
  placements  the 004 measure_placements view
  movements   per movement: name OCR read, first/last global number, bar count
  inters      every recognised symbol with shape, grade, bounds, pitch, staff (1/2 within its system) and the
              bar it falls in (number + key), by the centre of its bounds
  doubtful    inters of the verifier's classes graded under the gate: what Spark is asked about (insertion A)
  gate_skipped the same classes at or above the gate: what the gate let through unasked, so a run records
              what it did not check (the p1-3 run missed fingering read as a tuplet this way)

The gate: --gate 0.6 (default, as in the p1-3 run) and per class overrides, --gate-tag tuplet=0.9.

Usage: uv run python experiments/omr/audiveris_model.py BOOK_DIR MOVEMENTS_JSON OUT_JSON [--first 1]
       [--gate 0.6] [--gate-tag tuplet=0.9 ...]
"""

from __future__ import annotations

import argparse
import json
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from measure_map import build_measures, placements  # noqa: E402

# classes verify_symbols.py has a closed question for
VERIFY_TAGS = ("tuplet", "dynamics", "fermata", "rest", "augmentation-dot", "ornament", "wedge")
DEFAULT_GATE = 0.6


def gate_for(tag: str, gate: float, per_tag: dict[str, float]) -> float:
    return per_tag.get(tag, gate)


def split_gate(inters: list[dict], gate: float, per_tag: dict[str, float]) -> tuple[list[dict], list[dict]]:
    """(doubtful, skipped) among the verifier's classes: under the gate is asked about, the rest is skipped."""
    doubtful, skipped = [], []
    for it in inters:
        if it["tag"] not in VERIFY_TAGS or it["grade"] != it["grade"]:  # NaN grade: nothing to gate on
            continue
        (doubtful if it["grade"] < gate_for(it["tag"], gate, per_tag) else skipped).append(it)
    return sorted(doubtful, key=lambda r: r["grade"]), sorted(skipped, key=lambda r: r["grade"])


def read_sheet(path: Path, sheet: int) -> tuple[dict, list[tuple[int, int, ET.Element]]]:
    root = ET.parse(path).getroot()
    pic = root.find("picture")
    geo = {"sheet": sheet, "width": int(pic.get("width")), "height": int(pic.get("height")),
           "interline": int(root.find("scale/interline").get("main")), "pages": []}
    raw = []
    for pg in root.findall("page"):
        pid = int(pg.get("id"))
        systems = []
        for sys_el in pg.findall("system"):
            staves = []
            for part in sys_el.findall("part"):
                for st in part.findall("staff"):
                    ys = [float(p.get("y")) for ln in st.findall("lines/line") for p in ln.findall("point")]
                    staves.append({"id": int(st.get("id")), "left": int(st.get("left")), "right": int(st.get("right")),
                                   "top": min(ys), "bottom": max(ys)})
            staves.sort(key=lambda s: s["top"])
            abnormal = {int(m.get("id")) for part in sys_el.findall("part") for m in part.findall("measure")
                        if m.get("abnormal") == "true"}
            stacks = [{"id": int(k.get("id")), "left": int(k.get("left")), "right": int(k.get("right")),
                       "expected": k.get("expected"), "duration": k.get("duration"), "excess": k.get("excess"),
                       "abnormal": int(k.get("id")) in abnormal} for k in sys_el.findall("stack")]
            systems.append({"id": int(sys_el.get("id")), "top": min(s["top"] for s in staves),
                            "bottom": max(s["bottom"] for s in staves), "left": min(s["left"] for s in staves),
                            "right": max(s["right"] for s in staves), "staves": staves, "stacks": stacks})
            raw.append((pid, int(sys_el.get("id")), sys_el))
        geo["pages"].append({"page": pid, "systems": systems})
    return geo, raw


def inters_of(sys_el: ET.Element, staff_rank: dict[int, int], stacks: dict[int, dict]) -> list[dict]:
    """Every inter with bounds; bar by the centre of its bounds against this system's stacks (keyed by stack id)."""
    out = []
    sig = sys_el.find("sig")
    inters_el = sig.find("inters") if sig is not None else None
    if inters_el is None:
        return out
    for el in inters_el:
        b = el.find("bounds")
        if b is None:
            continue
        x, y, w, h = (int(b.get(k)) for k in ("x", "y", "w", "h"))
        cx = x + w / 2
        m = next((m for m in stacks.values() if m["px"][0] <= cx <= m["px"][2]), None)
        staff = int(el.get("staff")) if el.get("staff") else None
        out.append({"id": int(el.get("id")), "tag": el.tag, "shape": el.get("shape"),
                    "grade": float(el.get("grade", "nan")),
                    "ctx_grade": float(el.get("ctx-grade")) if el.get("ctx-grade") else None,
                    "bounds": [x, y, w, h], "number": m["number"] if m else None, "key": m["key"] if m else None,
                    "page": m["page"] if m else None, "pitch": el.get("pitch"),
                    "staff": staff_rank.get(staff) if staff else None, "value": el.get("value"), "role": el.get("role")})
    return out


def build(book_dir: Path, movements: list[dict], first: int, gate: float, per_tag: dict[str, float]) -> dict:
    book = ET.parse(book_dir / "book.xml").getroot()
    sheet_nums = [int(s.get("number")) for s in book.findall("sheet")
                  if (book_dir / f"sheet#{s.get('number')}" / f"sheet#{s.get('number')}.xml").exists()]
    sheets, raws = [], []
    for n in sheet_nums:
        geo, raw = read_sheet(book_dir / f"sheet#{n}" / f"sheet#{n}.xml", n)
        sheets.append(geo)
        raws.append(raw)
    measures = build_measures(sheets, movements, first)
    pdf_page = {m["sheet"]: m.get("pdf_page", m["sheet"]) for m in movements}
    model: dict = {"pages": [], "systems": [], "measures": measures, "placements": placements(measures),
                   "movements": [], "inters": [], "gate": {"default": gate, "per_tag": per_tag}}
    for i, geo in enumerate(sheets, start=1):
        model["pages"].append({"page": i, "sheet": geo["sheet"], "pdf_page": pdf_page.get(geo["sheet"], geo["sheet"]),
                               "width": geo["width"], "height": geo["height"], "interline": geo["interline"]})
    by_aud = {(m["audiveris"]["sheet"], m["audiveris"]["system"]): [] for m in measures}
    for m in measures:
        by_aud[(m["audiveris"]["sheet"], m["audiveris"]["system"])].append(m)
    for geo, raw in zip(sheets, raws):
        sys_geo = {sy["id"]: sy for pg in geo["pages"] for sy in pg["systems"]}
        for pid, sid, sys_el in raw:
            ms = by_aud.get((geo["sheet"], sid), [])
            if not ms:
                continue
            sy = sys_geo[sid]
            model["systems"].append({"page": ms[0]["page"], "system": ms[0]["system"], "movement": ms[0]["movement"],
                                     "audiveris": {"sheet": geo["sheet"], "page": pid, "system": sid},
                                     "top": sy["top"], "bottom": sy["bottom"], "left": sy["left"], "right": sy["right"],
                                     "staves": [{k: s[k] for k in ("top", "bottom", "left", "right")} for s in sy["staves"]],
                                     "numbers": [m["number"] for m in ms]})
            rank = {s["id"]: r for r, s in enumerate(sy["staves"], start=1)}
            model["inters"] += inters_of(sys_el, rank, {m["audiveris"]["stack"]: m for m in ms})
    model["systems"].sort(key=lambda s: (s["page"], s["system"]))
    names = {m["movement"]: m.get("name") for m in movements if m.get("movement_start")}
    for k in sorted({m["movement"] for m in measures}):
        ms = [m for m in measures if m["movement"] == k]
        model["movements"].append({"movement": k, "name": names.get(k), "first_number": ms[0]["number"],
                                   "last_number": ms[-1]["number"], "bars": len(ms)})
    model["doubtful"], model["gate_skipped"] = split_gate(model["inters"], gate, per_tag)
    return model


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("book_dir")
    ap.add_argument("movements")
    ap.add_argument("out")
    ap.add_argument("--first", type=int, default=1, help="global number of the first bar (0 for a pickup)")
    ap.add_argument("--gate", type=float, default=DEFAULT_GATE, help="grade under which a symbol is verified")
    ap.add_argument("--gate-tag", action="append", default=[], metavar="TAG=GRADE", help="per-class gate, e.g. tuplet=0.9")
    a = ap.parse_args()
    per_tag = {}
    for spec in a.gate_tag:
        tag, _, val = spec.partition("=")
        if tag not in VERIFY_TAGS:
            sys.exit(f"--gate-tag {spec}: tag must be one of {VERIFY_TAGS}")
        per_tag[tag] = float(val)
    model = build(Path(a.book_dir), json.load(open(a.movements)), a.first, a.gate, per_tag)
    Path(a.out).write_text(json.dumps(model, indent=1))
    ms = model["measures"]
    print(f"{len(model['pages'])} pages, {len(model['systems'])} systems, {len(ms)} bars ({ms[0]['number']}..{ms[-1]['number']}), "
          f"{sum(m['abnormal'] for m in ms)} abnormal, {len(model['inters'])} inters")
    for mv in model["movements"]:
        print(f"  movement {mv['movement']} {mv['name']!r}: bars {mv['first_number']}..{mv['last_number']} ({mv['bars']})")
    print(f"gate {a.gate} {per_tag or ''}: {len(model['doubtful'])} doubtful -> Spark, {len(model['gate_skipped'])} skipped "
          f"{dict(Counter(i['tag'] for i in model['gate_skipped']))}")
    for d in model["gate_skipped"]:
        if d["tag"] in ("tuplet", "fermata") and d["grade"] < 0.8:
            print(f"  skipped near the gate: m{d['number']} {d['tag']} {d['shape']} grade={d['grade']:.3f}")


if __name__ == "__main__":
    main()
