"""Continuous bar ids for an OMR book, in the shape feature 004 uses (pure functions, no I/O).

Audiveris numbers stacks per Audiveris page (a scanned sheet holding the end of one movement and the start of
the next is two Audiveris pages, each starting at 1), and its MusicXML numbers measures per movement. The app
numbers bars once per score, continuously over every page (004 `process_pages`: `n += 1` for every bar the
geometry finds), and addresses a bar on the page by (page, system, bar). This module gives every stack:

  key           "page.system.bar", 1-based: page = position in the score's page set (004
                `measure_placements.page`), system = top-to-bottom on that page, bar = left-to-right in the system
  number        the global bar number (004 `measures.number`), first_number for the first stack, +1 per stack
  box           {x0, y0, x1, y1} as fractions of the page image (004 `measure_placements.box`)
  movement      1-based movement (Audiveris movement-start pages), movement_bar = 1-based index inside it,
                which is the ordinal of the measure in that movement's MusicXML export
  audiveris     {sheet, page, system, stack}: where the stack lives in the .omr

Input `sheets` (book order): [{"sheet": 1, "width": W, "height": H, "pages": [{"page": 1, "systems": [
    {"id": 3, "top": y, "bottom": y, "stacks": [{"id": 1, "left": x, "right": x, ...extra}]}]}]}]
Extra stack fields (abnormal, expected, duration, excess, ...) are carried through.
`movements` (from book_box.py movements.json): [{"sheet": 1, "page": 1, "movement": 1}, ...].
"""

from __future__ import annotations

from typing import Any

STACK_KEYS = ("id", "left", "right")


def measure_key(page: int, system: int, bar: int) -> str:
    return f"{page}.{system}.{bar}"


def parse_key(key: str) -> tuple[int, int, int]:
    page, system, bar = (int(x) for x in key.split("."))
    return page, system, bar


def build_measures(sheets: list[dict[str, Any]], movements: list[dict[str, Any]] | None = None,
                   first_number: int = 1) -> list[dict[str, Any]]:
    mvt_of = {(m["sheet"], m["page"]): m["movement"] for m in (movements or [])}
    out: list[dict[str, Any]] = []
    number = first_number
    movement_bar: dict[int, int] = {}
    for page_index, sheet in enumerate(sheets, start=1):
        w, h = sheet["width"], sheet["height"]
        # systems of every Audiveris page of the sheet, top to bottom (an Audiveris page boundary is a movement
        # boundary inside the scan; the scan page is still one page to the app)
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
                    "key": measure_key(page_index, sys_index, bar_index),
                    "number": number,
                    "page": page_index,
                    "system": sys_index,
                    "bar": bar_index,
                    "box": {"x0": round(st["left"] / w, 4), "y0": round(top / h, 4),
                            "x1": round(st["right"] / w, 4), "y1": round(bottom / h, 4)},
                    "px": [st["left"], top, st["right"], bottom],
                    "movement": mvt,
                    "movement_bar": movement_bar[mvt],
                    "audiveris": {"sheet": sheet["sheet"], "page": aud_page, "system": sy["id"], "stack": st["id"]},
                }
                rec.update({k: v for k, v in st.items() if k not in STACK_KEYS})
                out.append(rec)
                number += 1
    return out


def placements(measures: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The 004 `measure_placements` view of the map (plus the key): confidence high unless Audiveris marked
    the stack abnormal (its own rhythm check failed), then low with the reason as the flag."""
    rows = []
    for m in measures:
        flag = None
        if m.get("abnormal"):
            flag = f"Audiveris abnormal: duration {m.get('duration')} vs expected {m.get('expected')}"
        rows.append({"key": m["key"], "number": m["number"], "page": m["page"], "system": m["system"], "box": m["box"],
                     "confidence": "low" if flag else "high", "flag": flag, "rehearsal_mark": None})
    return rows


def number_of(measures: list[dict[str, Any]]) -> dict[str, int]:
    return {m["key"]: m["number"] for m in measures}


def by_movement(measures: list[dict[str, Any]]) -> dict[int, list[dict[str, Any]]]:
    out: dict[int, list[dict[str, Any]]] = {}
    for m in measures:
        out.setdefault(m["movement"], []).append(m)
    return out


def stack_lookup(measures: list[dict[str, Any]]) -> dict[tuple[int, int, int], dict[str, Any]]:
    """(sheet, Audiveris page, stack id) -> measure, for attaching Audiveris inters to bars."""
    return {(m["audiveris"]["sheet"], m["audiveris"]["page"], m["audiveris"]["stack"]): m for m in measures}
