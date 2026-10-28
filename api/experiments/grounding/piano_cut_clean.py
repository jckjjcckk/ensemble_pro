# /// script
# requires-python = ">=3.12"
# dependencies = ["opencv-python-headless", "numpy", "pillow"]
# ///
"""Piano-cut experiment, step 3b: clean-and-extend the cut of one system (no model).

The plain crop (piano_cut_build.crop_box) is the two piano staves plus a fixed margin of ~1.5 staff spaces.
That cuts the piano's own notation that lives outside the margin (8va dotted lines, high slurs, tempo words,
low ledger notes, hairpins) and a wider margin only brings in the neighbour's low notes and text. So, per
system:

  1. Band: from a few px below the bottom line of the staff above (the previous staff of the system, else
     the last staff of the previous system, else 12 spaces above the piano clipped to the page) to a few px
     above the top line of the staff below (symmetric). The neighbour's own staff lines are never in the band.
  2. Columns at the system's barline x positions (geom json) that are dark from a band edge to the piano's
     outer line (the left systemic line, a barline that runs on from the staff above) are masked out of the
     analysis in that gap, otherwise they join every staff into one component. They stay in the output.
  3. Dilate (7 wide x 3 tall: joins the dots of an 8va line, the letters of a word, the fragments of a thin
     slur, without reaching across the vertical white between two instruments), label connected components,
     measure each component on its real ink.
  4. Classify: PIANO when the ink overlaps the piano region (top line of the upper staff - 1 space to bottom
     line of the lower staff + 1 space); NEIGHBOUR when it reaches the band edge or lies within 1 space of the
     neighbour's outer line; BOTH when it does both (kept, logged). What is left sits in the gap: it is
     resolved greedily, nearest first, to whichever ink is closer: vertically within its own columns, or
     horizontally on its own rows within 1.5 spaces (the next word of the same text line), piano ink or
     neighbour ink (the band edge stands in for the neighbour's staff line). Nearest *ink*, not nearest
     staff line: an 8va line sits 3 px under the timpani's bottom line on p. 2 and 50 px above the piano's top
     line, but the piano's stems run straight up to its dots; the "a" of "a tempo" is 17 px under the
     timpani and 27 px above the piano, but 6 px from "tempo".
  5. Erase NEIGHBOUR components (paint white over the dilated mask), keep PIANO and BOTH in full, fit the crop
     vertically to the kept ink + 3 px, never narrower than the two staves + 1 space. The x range is the same
     as the plain crop (left margin for the label and brace, system right edge + 2 spaces) so the blocks stack.
  6. Flags: edge_ink_top / edge_ink_bottom = kept ink on the first/last row of the final crop (the band itself
     clipped it, so something is still cut); counts of erased / kept / both / gap-resolved components.

Usage (standalone, from api/):  uv run experiments/grounding/piano_cut_clean.py [--score <pdf stem>] [page ...]
Writes clean-debug-p<NN>-s<k>.png (band with every component tinted by class) and prints the stats.
piano_cut_build.py calls clean_crop() unless run with --no-clean.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field

import cv2
import numpy as np
from PIL import Image

KERNEL = (7, 3)  # (width, height) of the joining dilation, px at 150 dpi
PAD = 3  # px around the kept ink
SPECK = 4  # ink px; smaller components outside the piano region are scan noise

PIANO, NEIGHBOUR, BOTH, GAP = "piano", "neighbour", "both", "gap"
TINT = {PIANO: (40, 160, 70), NEIGHBOUR: (220, 50, 50), BOTH: (190, 40, 190),
        "gap->piano": (0, 150, 200), "gap->neighbour": (240, 140, 0), "speck": (160, 160, 160)}


@dataclass
class Comp:
    label: int
    y0: int
    y1: int
    x0: int
    x1: int
    area: int
    cls: str = GAP
    how: str = ""  # why it got its class
    d_piano: float | None = None
    d_neigh: float | None = None
    neighbour_side: str = ""

    def as_dict(self) -> dict:
        return {"bbox": [self.x0, self.y0, self.x1, self.y1], "area": self.area, "class": self.cls, "how": self.how}


def neighbours(geom: dict, system: dict, wanted: list[int]) -> tuple[dict | None, dict | None]:
    """The staff above and below the wanted block: within the system, else the adjacent system's edge staff."""
    staves = {s["index"]: s for s in geom["staves"]}
    idxs = system["staff_indices"]
    i0, i1 = idxs.index(min(wanted)), idxs.index(max(wanted))
    prev = staves[idxs[i0 - 1]] if i0 > 0 else None
    nxt = staves[idxs[i1 + 1]] if i1 + 1 < len(idxs) else None
    systems = {s["index"]: s for s in geom["systems"]}
    if prev is None and system["index"] - 1 in systems:
        prev = staves[systems[system["index"] - 1]["staff_indices"][-1]]
    if nxt is None and system["index"] + 1 in systems:
        nxt = staves[systems[system["index"] + 1]["staff_indices"][0]]
    return prev, nxt


def _ink_bbox(labels: np.ndarray, work: np.ndarray, st: np.ndarray, l: int) -> tuple[int, int, int, int, int] | None:
    x, y, w, h = int(st[cv2.CC_STAT_LEFT]), int(st[cv2.CC_STAT_TOP]), int(st[cv2.CC_STAT_WIDTH]), int(st[cv2.CC_STAT_HEIGHT])
    sub = (labels[y : y + h, x : x + w] == l) & (work[y : y + h, x : x + w] > 0)
    ys, xs = np.where(sub)
    if len(ys) == 0:
        return None
    return y + int(ys.min()), y + int(ys.max()), x + int(xs.min()), x + int(xs.max()), int(len(ys))


def _runs(xs: np.ndarray) -> list[list[int]]:
    """Column indices -> [x0, x1] runs (gaps of up to 2 px merged)."""
    runs: list[list[int]] = []
    for x in xs:
        if runs and x - runs[-1][1] <= 3:
            runs[-1][1] = int(x)
        else:
            runs.append([int(x), int(x)])
    return runs


def _first_ink_below(mask: np.ndarray, y: int, x0: int, x1: int) -> int | None:
    strip = mask[y + 1 :, x0 : x1 + 1]
    rows = np.where(strip.any(axis=1))[0]
    return y + 1 + int(rows[0]) if len(rows) else None


def _first_ink_above(mask: np.ndarray, y: int, x0: int, x1: int) -> int | None:
    strip = mask[:y, x0 : x1 + 1]
    rows = np.where(strip.any(axis=1))[0]
    return int(rows[-1]) if len(rows) else None


def clean_crop(bw: np.ndarray, page: Image.Image, geom: dict, system: dict, wanted: list[int], *,
               kernel: tuple[int, int] = KERNEL, debug: bool = False) -> tuple[Image.Image, dict, dict, Image.Image | None]:
    """Cut the wanted staves out of the deskewed page with the neighbours' ink erased.

    bw: deskewed binary page (1 = ink), page: deskewed RGB page. Returns (crop, box, stats, debug_image)."""
    staves = {s["index"]: s for s in geom["staves"]}
    h, w = bw.shape
    ss = [staves[i] for i in sorted(wanted)]
    a, b = ss[0], ss[-1]
    sp = float(np.median([s["spacing"] for s in ss]))
    prev, nxt = neighbours(geom, system, wanted)
    edge = int(round(0.5 * sp))  # px kept clear of the neighbour's outer line (3 px thick on this scan)
    band_top = prev["y_bottom"] + edge if prev else max(0, int(a["y_top"] - 12 * sp))
    band_bot = nxt["y_top"] - edge if nxt else min(h - 1, int(b["y_bottom"] + 12 * sp))
    bx0, bx1 = 0, int(min(w - 1, system["box"]["x1"] + 2 * sp))
    work = bw[band_top : band_bot + 1, bx0 : bx1 + 1].copy()
    H, W = work.shape

    # regions in band rows
    p_r0, p_r1 = a["y_top"] - sp - band_top, b["y_bottom"] + sp - band_top
    top_line, bot_line = a["y_top"] - band_top, b["y_bottom"] - band_top

    # columns dark all the way from a band edge to the piano's outer line (the left systemic line, a barline
    # that runs on from the staff above or into the staff below): out of the analysis in that gap, otherwise
    # they join every staff into one component and "touch" the neighbour; untouched in the output
    # Only columns at the system's known barline x positions (geom json, +-4 px) qualify, so a piano stem or
    # ledger run that reaches the neighbour's line is never masked (it must stay kept ink and raise the flag).
    wide = cv2.dilate(work, np.ones((1, 3), np.uint8))
    at_barline = np.zeros(W, dtype=bool)
    for lx0, lx1 in system["barlines"]:
        at_barline[max(0, lx0 - 4 - bx0) : min(W, lx1 + 5 - bx0)] = True
    col_mask = np.zeros_like(work, dtype=bool)
    line_cols: dict[str, list[int]] = {"top": [], "bottom": []}
    if prev is not None and top_line > 6:
        gap = wide[: top_line - 1]
        cols = np.where((gap.mean(axis=0) >= 0.85) & gap[:3].any(axis=0) & gap[-3:].any(axis=0) & at_barline)[0]
        for c in cols:
            col_mask[: top_line - 1, max(0, c - 1) : c + 2] = True
        line_cols["top"] = [int(c) for c in cols]
    if nxt is not None and H - bot_line > 7:
        gap = wide[bot_line + 2 :]
        cols = np.where((gap.mean(axis=0) >= 0.85) & gap[:3].any(axis=0) & gap[-3:].any(axis=0) & at_barline)[0]
        for c in cols:
            col_mask[bot_line + 2 :, max(0, c - 1) : c + 2] = True
        line_cols["bottom"] = [int(c) for c in cols]
    work[col_mask] = 0

    dil = cv2.dilate(work, np.ones((kernel[1], kernel[0]), np.uint8))
    n, labels, stats, _ = cv2.connectedComponentsWithStats(dil, connectivity=8)
    n_top_r1 = (prev["y_bottom"] + sp - band_top) if prev else None  # neighbour above: rows <= this
    n_bot_r0 = (nxt["y_top"] - sp - band_top) if nxt else None  # neighbour below: rows >= this

    comps: list[Comp] = []
    for l in range(1, n):
        bb = _ink_bbox(labels, work, stats[l], l)
        if bb is None:
            continue
        y0, y1, x0, x1, area = bb
        c = Comp(l, y0, y1, x0, x1, area)
        overlaps_piano = y1 >= p_r0 and y0 <= p_r1
        touch_top = prev is not None and (y0 <= 1 or y0 <= n_top_r1)
        touch_bot = nxt is not None and (y1 >= H - 2 or y1 >= n_bot_r0)
        if overlaps_piano and (touch_top or touch_bot):
            c.cls, c.how = BOTH, "overlaps the piano region and reaches the neighbour's"
        elif overlaps_piano:
            c.cls, c.how = PIANO, "overlaps the piano region"
        elif touch_top or touch_bot:
            c.cls, c.how = NEIGHBOUR, "reaches the band edge or within 1 space of the neighbour's outer line"
        elif area < SPECK:
            c.cls, c.how = "speck", f"< {SPECK} ink px outside the piano region"
        comps.append(c)

    # masks of classified ink, for the nearest-ink resolution of gap components
    piano_ink = np.zeros_like(work, dtype=bool)
    neigh_ink = np.zeros_like(work, dtype=bool)
    ink = work > 0
    for c in comps:
        m = (labels == c.label) & ink
        if c.cls in (PIANO, BOTH):
            piano_ink |= m
        elif c.cls == NEIGHBOUR:
            neigh_ink |= m
    margin = int(round(sp))
    reach = int(round(1.5 * sp))

    def beside(mask: np.ndarray, c: Comp) -> float:
        """Horizontal distance to ink of `mask` on the component's own rows, left or right within 1.5 spaces,
        when that ink covers at least half of the component's rows: the previous or next word of a text line
        ("a" and "tempo" are 6 px apart, "tempo" is joined to the piano's stems, "a" is not)."""
        h = c.y1 - c.y0 + 1
        best = float("inf")
        left = mask[c.y0 : c.y1 + 1, max(0, c.x0 - reach) : c.x0]
        if left.size and left.any(axis=1).sum() >= 0.5 * h:
            best = min(best, left.shape[1] - int(np.where(left.any(axis=0))[0].max()))
        right = mask[c.y0 : c.y1 + 1, c.x1 + 1 : min(W, c.x1 + 1 + reach)]
        if right.size and right.any(axis=1).sum() >= 0.5 * h:
            best = min(best, int(np.where(right.any(axis=0))[0].min()) + 1)
        return best

    def distances(c: Comp) -> tuple[float, float, str]:
        x0, x1 = max(0, c.x0 - margin), min(W - 1, c.x1 + margin)
        if c.y1 < p_r0:  # above the piano
            r = _first_ink_below(piano_ink, c.y1, x0, x1)
            d_p = (r - c.y1) if r is not None else (a["y_top"] - band_top - c.y1)
            r = _first_ink_above(neigh_ink, c.y0, x0, x1)
            d_n = (c.y0 - r) if r is not None else ((c.y0 + edge) if prev else float("inf"))
            side = "above"
        else:
            r = _first_ink_above(piano_ink, c.y0, x0, x1)
            d_p = (c.y0 - r) if r is not None else (c.y0 - (b["y_bottom"] - band_top))
            r = _first_ink_below(neigh_ink, c.y1, x0, x1)
            d_n = (r - c.y1) if r is not None else ((H - 1 - c.y1 + edge) if nxt else float("inf"))
            side = "below"
        return float(min(d_p, beside(piano_ink, c))), float(min(d_n, beside(neigh_ink, c))), side

    pending = [c for c in comps if c.cls == GAP]
    while pending:
        best = None
        for c in pending:
            d_p, d_n, side = distances(c)
            c.d_piano, c.d_neigh, c.neighbour_side = d_p, d_n, side
            key = min(d_p, d_n)
            if best is None or key < best[0]:
                best = (key, c)
        c = best[1]
        pending.remove(c)
        m = (labels == c.label) & ink
        if c.d_piano <= c.d_neigh:  # tie: keep (never cut the piano's own ink on a coin toss)
            c.cls, c.how = "gap->piano", f"{c.neighbour_side} the piano, {c.d_piano:.0f} px to piano ink vs {c.d_neigh:.0f} px to neighbour ink/line"
            piano_ink |= m
        else:
            c.cls, c.how = "gap->neighbour", f"{c.neighbour_side} the piano, {c.d_neigh:.0f} px to neighbour ink/line vs {c.d_piano:.0f} px to piano ink"
            neigh_ink |= m

    # erase: paint white over the dilated mask (+1 px) of every neighbour component and speck
    erase = np.zeros_like(work, dtype=bool)
    for c in comps:
        if c.cls in (NEIGHBOUR, "gap->neighbour", "speck"):
            erase |= labels == c.label
    erase = cv2.dilate(erase.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)
    erase[col_mask] = False
    band_rgb = np.array(page.crop((bx0, band_top, bx1 + 1, band_bot + 1)).convert("RGB"))
    out = band_rgb.copy()
    out[erase] = 255

    kept = piano_ink  # PIANO + BOTH + gap->piano ink, gap-crossing line columns excluded
    ys = np.where(kept.any(axis=1))[0]
    k_y0, k_y1 = (int(ys.min()), int(ys.max())) if len(ys) else (int(p_r0), int(p_r1))
    y0 = max(0, min(k_y0 - PAD, int(a["y_top"] - sp - band_top)))
    y1 = min(H - 1, max(k_y1 + PAD, int(b["y_bottom"] + sp - band_top)))
    crop = Image.fromarray(out[y0 : y1 + 1])
    box = {"x0": bx0, "y0": band_top + y0, "x1": bx1, "y1": band_top + y1}

    counts: dict[str, int] = {}
    for c in comps:
        counts[c.cls] = counts.get(c.cls, 0) + 1
    stats_out = {
        "band": {"x0": bx0, "y0": band_top, "x1": bx1, "y1": band_bot},
        "neighbour_above": prev["index"] if prev else None, "neighbour_below": nxt["index"] if nxt else None,
        "gap_line_columns": line_cols,
        "kernel": list(kernel),
        "components": len(comps),
        "erased": counts.get(NEIGHBOUR, 0) + counts.get("gap->neighbour", 0) + counts.get("speck", 0),
        "kept": counts.get(PIANO, 0) + counts.get(BOTH, 0) + counts.get("gap->piano", 0),
        "by_class": counts,
        "both": [c.as_dict() for c in comps if c.cls == BOTH],
        "gap_resolved": [c.as_dict() for c in comps if c.cls.startswith("gap->")],
        "edge_ink_top": bool(kept[y0].any()),
        "edge_ink_bottom": bool(kept[y1].any()),
        "edge_ink_cols": {"top": _runs(np.where(kept[y0])[0]), "bottom": _runs(np.where(kept[y1])[0])},
    }
    dbg = None
    if debug:
        stats_out["detail"] = [c.as_dict() for c in comps]
        tint = band_rgb.copy()
        for c in comps:
            m = (labels == c.label) & ink
            col = np.array(TINT.get(c.cls, (0, 0, 0)), dtype=np.uint8)
            tint[m] = (0.25 * tint[m] + 0.75 * col).astype(np.uint8)
        # final crop edges in blue, regions in faint lines
        tint[y0, :, :] = (30, 60, 230)
        tint[y1, :, :] = (30, 60, 230)
        dbg = Image.fromarray(tint)
    return crop, box, stats_out, dbg


if __name__ == "__main__":
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
    from fallback_cv import binarise, rotate
    from piano_cut_geometry import PC, PAGES_DIR, DEFAULT_PAGES

    for n in [int(x) for x in sys.argv[1:]] or DEFAULT_PAGES:
        geom = json.loads((PC / f"geom-p{n:02d}.json").read_text())
        label = json.loads((PC / f"label-p{n:02d}.json").read_text())
        gray = cv2.imread(str(PAGES_DIR / f"p{n:02d}.png"), cv2.IMREAD_GRAYSCALE)
        bw = binarise(gray)
        page = Image.open(PAGES_DIR / f"p{n:02d}.png").convert("RGB")
        if abs(geom["skew_deg"]) >= 0.1:
            bw = rotate(bw, geom["skew_deg"], 0)
            page = Image.fromarray(rotate(gray, geom["skew_deg"], 255)).convert("RGB")
        by_index = {s.get("index"): s for s in (label.get("parsed") or {}).get("systems", [])}
        for system in geom["systems"]:
            wanted = [i for i in (by_index.get(system["index"], {}).get("wanted_staves") or []) if i in system["staff_indices"]]
            if not wanted:
                continue
            crop, box, st, dbg = clean_crop(bw, page, geom, system, wanted, debug=True)
            dbg.save(PC / f"clean-debug-p{n:02d}-s{system['index']}.png")
            crop.save(PC / f"clean-preview-p{n:02d}-s{system['index']}.png")
            print(json.dumps({"page": n, "system": system["index"], "box": box,
                              **{k: v for k, v in st.items() if k not in ("both", "gap_resolved", "detail")}}))
            for g in st["detail"]:
                if g["class"] in (BOTH, PIANO) or g["class"].startswith("gap->") or "-v" in sys.argv:
                    print("   ", g["class"], g["bbox"], g["area"], g["how"])
