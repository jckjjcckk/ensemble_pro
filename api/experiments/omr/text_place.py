"""Place the text Spark reads (dynamics, direction words) on bars by position, not by Spark's bar label.

Spark sees one system crop and reports each word with its centre on its native 0-1000 grid over the image.
The grid point goes back to page pixels through the crop's origin and size. Spark's points drift by 50 to 150
px on a 2500 px page (Goldberg p1-5), which is enough to cross a barline, so geometry refines the point:

  1. snap   if Audiveris found a text glyph (an OCR word that is not a fingering digit, or a dynamics symbol)
            within 8 interlines of Spark's point, the glyph's centre replaces the point. Spark says what the
            word is; Audiveris says exactly where its ink is (its OCR of the word itself is often garbage,
            "erase." for cresc., SF for mf, which is why Spark reads the text).
  2. anchor a dynamic belongs to the note it is printed under, and its ink can start left of that note's
            barline; it never applies to a note left of where its ink starts. So a dynamic takes the bar of the
            first notehead (either staff) at or right of its left edge, if that head is within 3 interlines of
            its centre. Words, and dynamics with no head close by, take the bar whose [left, right) contains
            the point (left of the first bar -> first, right of the last -> last).
  3. staff  the nearer staff band by y (ties go to the upper staff: a dynamic centred between the staves of a
            grand staff sits on the upper one, below it); placement above/below that staff's middle.

Spark's own bar label is kept only as a cross-check (`label_agrees`) and as the fallback when a word comes
back without a usable x. Models never place bars or staves; Spark only says where the ink is.

Pure functions, no I/O:
  grid_to_page(x, y, crop) -> (X, Y) page pixels
  place(items, measures, staves, crop, glyphs=None, heads=None, interline=20) -> (placed, dropped)
  measures: this system's measures from measure_map (need "number", "key", "px" = [left, top, right, bottom])
  staves:   this system's staves top to bottom, [{"top": y, "bottom": y}, ...] in page pixels
  crop:     {"origin": [x0, y0], "size": [w, h]} of the image Spark saw, in page pixels
  glyphs:   Audiveris text-ish inters in this system: [{"tag": "word"|"dynamics", "value": str|None,
            "bounds": [x, y, w, h]}]
  heads:    Audiveris noteheads in this system: [{"x": centre x, "number": global bar}]
"""

from __future__ import annotations

import re
from typing import Any

GRID = 1000.0
DYNAMICS = {"p", "pp", "ppp", "mp", "mf", "f", "ff", "fff", "sf", "sfz", "fp", "fz", "rf", "rfz", "sfp"}
SNAP_IL = 8.0    # how far (interlines) a Spark point may be from the Audiveris glyph it snaps to
ANCHOR_IL = 3.0  # how far (interlines, horizontally) a dynamic may be from the notehead it anchors to


def grid_to_page(x: float, y: float, crop: dict[str, Any]) -> tuple[float, float]:
    (ox, oy), (w, h) = crop["origin"], crop["size"]
    return ox + x / GRID * w, oy + y / GRID * h


def bar_at(px_x: float, measures: list[dict[str, Any]]) -> tuple[dict[str, Any], str]:
    """The measure whose [left, right) contains x; left of the first bar (header zone, indent) -> the first,
    right of the last -> the last, in a gap between stacks -> the nearer one. Returns (measure, how)."""
    ms = sorted(measures, key=lambda m: m["px"][0])
    for m in ms:
        if m["px"][0] <= px_x < m["px"][2]:
            return m, "x"
    if px_x < ms[0]["px"][0]:
        return ms[0], "x-before-first"
    if px_x >= ms[-1]["px"][2]:
        return ms[-1], "x-after-last"
    return min(ms, key=lambda m: min(abs(px_x - m["px"][0]), abs(px_x - m["px"][2]))), "x-gap"


def staff_at(px_y: float, staves: list[dict[str, Any]]) -> tuple[int, str]:
    """1-based staff (top to bottom) nearest to y and the placement relative to it ("above"/"below")."""
    def dist(s):
        return 0.0 if s["top"] <= px_y <= s["bottom"] else min(abs(px_y - s["top"]), abs(px_y - s["bottom"]))
    best = min(range(len(staves)), key=lambda i: (dist(staves[i]), i))
    s = staves[best]
    return best + 1, "above" if px_y < (s["top"] + s["bottom"]) / 2 else "below"


def is_text_glyph(g: dict[str, Any]) -> bool:
    """Dynamics symbols and OCR words that are not fingering (digits, punctuation, single stray marks)."""
    if g.get("tag") == "dynamics":
        return True
    if g.get("tag") != "word":
        return False
    v = (g.get("value") or "").strip()
    return bool(re.search(r"[A-Za-z]", v))


def centre(b: list[float]) -> tuple[float, float]:
    return b[0] + b[2] / 2, b[1] + b[3] / 2


def snap(X: float, Y: float, glyphs: list[dict[str, Any]], interline: float) -> dict[str, Any] | None:
    best, best_d = None, SNAP_IL * interline
    for g in glyphs:
        if not is_text_glyph(g):
            continue
        cx, cy = centre(g["bounds"])
        d = ((cx - X) ** 2 + (cy - Y) ** 2) ** 0.5
        if d <= best_d:
            best, best_d = g, d
    return best


def anchor(left: float, X: float, heads: list[dict[str, Any]], interline: float) -> dict[str, Any] | None:
    """First notehead at or right of the glyph's left edge (half an interline of slack), within ANCHOR_IL
    interlines of its centre X."""
    near = [h for h in heads if h["x"] >= left - interline / 2 and abs(h["x"] - X) <= ANCHOR_IL * interline]
    return min(near, key=lambda h: h["x"]) if near else None


def _num(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if -50 <= f <= GRID + 50 else None  # a little overshoot is the model's rounding, more is garbage


def place(items: list[dict[str, Any]], measures: list[dict[str, Any]], staves: list[dict[str, Any]],
          crop: dict[str, Any], glyphs: list[dict[str, Any]] | None = None, heads: list[dict[str, Any]] | None = None,
          interline: float = 20.0) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Returns (placed, dropped). Each placed item: text, kind (dynamic/words), number, key, staff, placement,
    px [X, Y] (final point), spark_px (Spark's point), how ("x" / "x-before-first" / "x-after-last" / "x-gap",
    prefixed "glyph+" when snapped, "head" when a dynamic anchored to a notehead, or "label"), spark_bar,
    label_agrees, frac (0..1 position of X inside the bar, for snapping to a beat)."""
    placed, dropped = [], []
    by_number = {m["number"]: m for m in measures}
    for it in items:
        text = str(it.get("text", "")).strip() if isinstance(it, dict) else ""
        if not text:
            dropped.append({"item": it, "why": "no text"})
            continue
        kind = "dynamic" if text.rstrip(".").lower() in DYNAMICS else "words"
        x, y = _num(it.get("x")), _num(it.get("y"))
        label = it.get("bar")
        label = int(label) if isinstance(label, (int, float)) or (isinstance(label, str) and label.isdigit()) else None
        spark_px = None
        if x is not None:
            X, Y = grid_to_page(min(max(x, 0), GRID), min(max(y if y is not None else GRID / 2, 0), GRID), crop)
            spark_px = [round(X), round(Y)]
            g = snap(X, Y, glyphs or [], interline)
            prefix, left = "", X - interline / 2
            if g is not None:
                X, Y = centre(g["bounds"])
                prefix, left = "glyph+", g["bounds"][0]
            h = anchor(left, X, heads or [], interline) if kind == "dynamic" else None
            if h is not None and h["number"] in by_number:
                m, how = by_number[h["number"]], prefix + "head"
            else:
                m, how = bar_at(X, measures)
                how = prefix + how
        elif label in by_number:
            m, how = by_number[label], "label"
            X = (m["px"][0] + m["px"][2]) / 2
            Y = grid_to_page(0, min(max(y, 0), GRID), crop)[1] if y is not None else None
        else:
            dropped.append({"item": it, "why": "no position and no bar label in this system"})
            continue
        staff, placement = staff_at(Y, staves) if Y is not None else (1, "below")
        left, right = m["px"][0], m["px"][2]
        placed.append({
            "text": text, "kind": kind, "number": m["number"], "key": m["key"], "staff": staff, "placement": placement,
            "px": [round(X), round(Y) if Y is not None else None], "spark_px": spark_px, "how": how,
            "spark_bar": label, "label_agrees": (label == m["number"]) if label is not None else None,
            "frac": round(min(max((X - left) / (right - left), 0.0), 1.0), 3) if right > left else 0.0,
        })
    return placed, dropped
