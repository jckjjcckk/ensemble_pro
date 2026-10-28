"""An Audiveris 5.11 book as Folio's bar map (feature 005). Pure reading, no model, no network.

Ported from `api/experiments/omr/measure_map.py` and `audiveris_model.py` (same rules, same numbers on the Goldberg
run), with one change for chamber music: a system may hold any number of staves, not just a grand staff.

  measures  one record per Audiveris stack, in the 004 shape: key "page.system.bar" (page = position in the
            converted page set, system top to bottom, bar left to right), global `number` (+1 per stack over
            the whole book, so the movements' own numbering never collides), `box` as page fractions, `px`,
            `movement` and `movement_bar` (= the ordinal in that movement's MusicXML export), plus Audiveris's
            own rhythm check (abnormal, expected, duration, excess)
  systems   per system: page, system, staves top to bottom (page pixels), the bar numbers it holds
  inters    every recognised symbol with tag, shape, grade, bounds, pitch, staff rank in its system, bar
  doubtful  inters of the classes the closed questions cover, graded under the gate (what Spark is asked)
  skipped   the same classes at or above the gate (what the gate let through unasked)

Models never place staves or bars: every box here is Audiveris's.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

# classes the closed questions (omr_agent.VERIFY_OPTIONS) cover: accidentals (flag only) and ornaments (v2, 2026-10-28;
# v1 also asked about tuplets, dynamics, fermatas, rests, dots and wedges)
VERIFY_TAGS = ("alter", "ornament")
DEFAULT_GATE = 0.6
STACK_KEYS = ("id", "left", "right")


def measure_key(page: int, system: int, bar: int) -> str:
    return f"{page}.{system}.{bar}"


def build_measures(sheets: list[dict[str, Any]], movements: list[dict[str, Any]] | None = None,
                   first_number: int = 1) -> list[dict[str, Any]]:
    """Every stack of the book in reading order with a global number (measure_map.build_measures)."""
    mvt_of = {(m["sheet"], m["page"]): m["movement"] for m in (movements or [])}
    out: list[dict[str, Any]] = []
    number = first_number
    movement_bar: dict[int, int] = {}
    for page_index, sheet in enumerate(sheets, start=1):
        w, h = sheet["width"], sheet["height"]
        systems = [(pg["page"], sy) for pg in sheet["pages"] for sy in pg["systems"]]
        systems.sort(key=lambda t: t[1]["top"])
        last_mvt = 1
        for sys_index, (aud_page, sy) in enumerate(systems, start=1):
            mvt = mvt_of.get((sheet["sheet"], aud_page), last_mvt if out else 1)
            last_mvt = mvt
            for bar_index, st in enumerate(sorted(sy["stacks"], key=lambda s: s["left"]), start=1):
                movement_bar[mvt] = movement_bar.get(mvt, 0) + 1
                top, bottom = sy["top"], sy["bottom"]
                rec = {
                    "key": measure_key(page_index, sys_index, bar_index), "number": number, "page": page_index,
                    "system": sys_index, "bar": bar_index,
                    "box": {"x0": round(st["left"] / w, 4), "y0": round(top / h, 4),
                            "x1": round(st["right"] / w, 4), "y1": round(bottom / h, 4)},
                    "px": [st["left"], top, st["right"], bottom], "movement": mvt, "movement_bar": movement_bar[mvt],
                    "audiveris": {"sheet": sheet["sheet"], "page": aud_page, "system": sy["id"], "stack": st["id"]},
                }
                rec.update({k: v for k, v in st.items() if k not in STACK_KEYS})
                out.append(rec)
                number += 1
    return out


def split_gate(inters: list[dict], gate: float = DEFAULT_GATE, per_tag: dict[str, float] | None = None) -> tuple[list[dict], list[dict]]:
    """(doubtful, skipped) among the closed-question classes: under the gate is asked about, the rest is skipped."""
    per_tag = per_tag or {}
    doubtful, skipped = [], []
    for it in inters:
        if it["tag"] not in VERIFY_TAGS or it["grade"] != it["grade"]:  # NaN grade: nothing to gate on
            continue
        (doubtful if it["grade"] < per_tag.get(it["tag"], gate) else skipped).append(it)
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
                    if ys:
                        staves.append({"id": int(st.get("id")), "left": int(st.get("left")), "right": int(st.get("right")),
                                       "top": min(ys), "bottom": max(ys)})
            if not staves:
                continue
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
    """Every inter with bounds; its bar by the centre of its bounds against this system's stacks."""
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
                    "bounds": [x, y, w, h], "number": m["number"] if m else None, "key": m["key"] if m else None,
                    "page": m["page"] if m else None, "pitch": el.get("pitch"),
                    "staff": staff_rank.get(staff) if staff else None, "value": el.get("value")})
    return out


def read_book(book_dir: Path, movements: list[dict], gate: float = DEFAULT_GATE,
              per_tag: dict[str, float] | None = None, first: int = 1) -> dict:
    """The unzipped book (book.xml + sheet#N/sheet#N.xml) and movements.json -> the model (audiveris_model.build).
    A sheet with no sheet#N.xml (Audiveris gave up on the page) is left out; `unreadable` lists its sheet numbers."""
    per_tag = per_tag or {}
    book = ET.parse(book_dir / "book.xml").getroot()
    all_sheets = [int(s.get("number")) for s in book.findall("sheet")]
    sheet_nums = [n for n in all_sheets if (book_dir / f"sheet#{n}" / f"sheet#{n}.xml").exists()]
    sheets, raws = [], []
    for n in sheet_nums:
        geo, raw = read_sheet(book_dir / f"sheet#{n}" / f"sheet#{n}.xml", n)
        if not any(sy["stacks"] for pg in geo["pages"] for sy in pg["systems"]):
            continue                                  # a page with no bars (a title page, a blank) is no page of music
        sheets.append(geo)
        raws.append(raw)
    measures = build_measures(sheets, movements, first)
    pdf_page = {m["sheet"]: m.get("pdf_page", m["sheet"]) for m in movements}
    model: dict = {"pages": [], "systems": [], "measures": measures, "movements": [], "inters": [],
                   "gate": {"default": gate, "per_tag": per_tag},
                   "unreadable": [pdf_page.get(n, n) for n in all_sheets if n not in {g["sheet"] for g in sheets}]}
    for i, geo in enumerate(sheets, start=1):
        model["pages"].append({"page": i, "sheet": geo["sheet"], "pdf_page": pdf_page.get(geo["sheet"], geo["sheet"]),
                               "width": geo["width"], "height": geo["height"], "interline": geo["interline"]})
    by_aud: dict[tuple[int, int], list[dict]] = {}
    for m in measures:
        by_aud.setdefault((m["audiveris"]["sheet"], m["audiveris"]["system"]), []).append(m)
    for geo, raw in zip(sheets, raws):
        sys_geo = {sy["id"]: sy for pg in geo["pages"] for sy in pg["systems"]}
        for pid, sid, sys_el in raw:
            ms = by_aud.get((geo["sheet"], sid), [])
            if not ms or sid not in sys_geo:
                continue
            sy = sys_geo[sid]
            model["systems"].append({"page": ms[0]["page"], "system": ms[0]["system"], "movement": ms[0]["movement"],
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
    model["doubtful"], model["skipped"] = split_gate(model["inters"], gate, per_tag)
    return model


def load_run(run: Path, gate: float = DEFAULT_GATE, per_tag: dict[str, float] | None = None) -> dict:
    """A run directory as the box leaves it (omr_box.py): book/, movements.json, book_run.json."""
    movements = json.loads((run / "movements.json").read_text())
    model = read_book(run / "book", movements, gate, per_tag)
    model["book_run"] = json.loads((run / "book_run.json").read_text())
    return model
