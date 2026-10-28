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
  7. Bar-awareness (CLEAN.md, "Bar-aware cleanup"): the system's barlines split the staves into bars; a bar
     whose own ink inside the staff lines (staff lines removed) is under REST_FLOOR sp² per staff is resting.
     A component in the gap or margin over resting bars only is the neighbour's (unless it continues a kept
     text line), and a floating piece of a kept component (joined to the staff only through a barline) over
     resting bars only is erased too. "piano" in the code means the target instrument, whatever --instrument
     asked for.

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

REST_FLOOR = 1.25  # staff-space units of own ink per staff, per bar, under which the bar counts as resting

# "piano" here means the target instrument (whatever --instrument asked for); the names predate the second instrument.
PIANO, NEIGHBOUR, BOTH, GAP, REST_BAR = "piano", "neighbour", "both", "gap", "rest-bar"
TINT = {PIANO: (40, 160, 70), NEIGHBOUR: (220, 50, 50), BOTH: (190, 40, 190),
        "gap->piano": (0, 150, 200), "gap->neighbour": (240, 140, 0), "speck": (160, 160, 160),
        REST_BAR: (160, 60, 0), "piece": (120, 0, 60)}


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
    rest: list[int] | None = None  # bar numbers (0-based) when the component lies over/under resting bars only

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


def _bars(system: dict, ss: list[dict], bx0: int, W: int, tol: int = 5) -> list[tuple[int, int]]:
    """Bar column ranges in band coordinates: between consecutive system barlines (the barline clusters
    +-tol excluded), the first from the staves' left end (so the clef and key signature are bar 1's ink) and
    the last to their right end."""
    x0 = int(min(s["x0"] for s in ss)) - bx0
    x1 = int(max(s["x1"] for s in ss)) - bx0
    out: list[tuple[int, int]] = []
    prev = x0
    for b0, b1 in system["barlines"]:
        if b0 - tol - bx0 > prev + 3:
            out.append((prev, b0 - tol - bx0))
        prev = max(prev, b1 + tol - bx0)
    if x1 > prev + 3:
        out.append((prev, min(W - 1, x1)))
    return [(max(0, a), min(W - 1, b)) for a, b in out]


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

    # bar-awareness: per bar of the system, does the target have ink of its own inside its staff region
    # (top line of its first staff - 2 px to bottom line of its last staff + 2 px)? Staff lines are taken out
    # (long horizontal runs, +-1 row for the jagged deskewed lines); what remains is counted in staff-space
    # units. Whole and half rests hang on a line and vanish with it, so a rests-only bar measures ~0 (<= 1.3
    # on 18 systems of two scans); the sparsest playing bar measured 7.0, a bar holding only the clef and key
    # signature 4.0. Floor: REST_FLOOR * number of staves. A quarter rest keeps its ink and counts as playing
    # (the conservative side). Marks over or under a resting bar that lie outside the staff lines belong to the
    # neighbour: see the classification below.
    bars = _bars(system, ss, bx0, W)
    r0, r1 = max(0, top_line - 2), min(H - 1, bot_line + 2)
    # the staff region's edge rows per column: a bowed Breitkopf staff sags 1-6 px under the geometry's
    # (page-wide) bottom line at the system's right end, so the outer line is traced column by column (the
    # lowest / highest long run, >= 4 spaces, within a space of the nominal line) and the region follows it
    long_runs = cv2.morphologyEx(bw[band_top : band_bot + 1, bx0 : bx1 + 1], cv2.MORPH_OPEN, np.ones((1, int(4 * sp)), np.uint8)) > 0
    lo, hi = max(0, bot_line - 3), min(H - 1, int(bot_line + sp))
    seg = long_runs[lo : hi + 1]
    r1_col = np.where(seg.any(axis=0), lo + (seg.shape[0] - 1 - np.argmax(seg[::-1], axis=0)), bot_line) + 2
    lo, hi = max(0, int(top_line - sp)), min(H - 1, top_line + 3)
    seg = long_runs[lo : hi + 1]
    r0_col = np.where(seg.any(axis=0), lo + np.argmax(seg, axis=0), top_line) - 2
    r0_min, r1_max = int(max(0, r0_col.min())), int(min(H - 1, r1_col.max()))
    reg = bw[band_top + r0 : band_top + r1 + 1, bx0 : bx1 + 1]
    opened = cv2.morphologyEx(reg, cv2.MORPH_OPEN, np.ones((1, max(8, int(1.5 * sp))), np.uint8))
    own = (reg > 0) & (cv2.dilate(opened, np.ones((3, 1), np.uint8)) == 0)
    floor = REST_FLOOR * len(ss)
    bar_ink = [float(own[:, xa : xb + 1].sum()) / (sp * sp) for xa, xb in bars]
    resting = [v < floor for v in bar_ink]

    def bars_under(x0: int, x1: int) -> list[int]:
        return [k for k, (xa, xb) in enumerate(bars) if x1 >= xa and x0 <= xb]

    def under_resting(x0: int, x1: int) -> list[int] | None:
        """Bar indices when the x range overlaps at least one bar and every bar it overlaps is resting."""
        ks = bars_under(x0, x1)
        return ks if ks and all(resting[k] for k in ks) else None

    dil = cv2.dilate(work, np.ones((kernel[1], kernel[0]), np.uint8))
    n, labels, stats, _ = cv2.connectedComponentsWithStats(dil, connectivity=8)
    ink = work > 0
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
        strict = y1 >= r0_min and y0 <= r1_max  # touches the staff lines themselves (within 2 px), not just the 1-space margin
        touch_top = prev is not None and (y0 <= 1 or y0 <= n_top_r1)
        touch_bot = nxt is not None and (y1 >= H - 2 or y1 >= n_bot_r0)
        near = y0 <= r1_max + 2 and y1 >= r0_min - 2  # within 2 px of the staff rows
        rest = None if (strict or near) else under_resting(x0, x1)
        if rest is not None and not touch_top and not touch_bot and area >= SPECK:
            # in the margin or the gap, over/under bars where the target has only rests: the neighbour's
            # (the Vn I hairpin that starts 6 px under the piano's bass staff while the piano rests), unless
            # it continues a kept text line ("con brio" after "Allegro"): decided after the gap resolution
            c.rest = rest
        elif overlaps_piano and (touch_top or touch_bot):
            c.cls, c.how = BOTH, "overlaps the piano region and reaches the neighbour's"
        elif overlaps_piano:
            c.cls, c.how = PIANO, "overlaps the piano region"
        elif touch_top or touch_bot:
            c.cls, c.how = NEIGHBOUR, "reaches the band edge or within 1 space of the neighbour's outer line"
        elif area < SPECK:
            c.cls, c.how = "speck", f"< {SPECK} ink px outside the piano region"
        comps.append(c)

    # kept components that touch the staff lines (PIANO, BOTH) may still carry the neighbour's ink joined to
    # them: Horn II's ledger notes with their "sf" hanging into the gap above a resting piano bar, joined to the
    # piano's staff through the barline. Split each such component: its ink minus the vertical barline runs
    # (>= 5 spaces tall at a barline column; stems and clef strokes are shorter) is re-joined with the same
    # kernel, and a piece with no ink inside the staff rows is floating: it hangs in the gap on its own. A
    # floating piece over/under resting bars only is erased. A piece with ink inside the staff rows is the
    # target's (a clef's tail under the staff, a ledger chord on its stem, the sagging line of a bowed staff),
    # never touched.
    pieces: list[dict] = []
    piece_erase = np.zeros_like(work, dtype=bool)
    rows = np.arange(H)[:, None]
    outside_rows = (rows < r0_col[None, :]) | (rows > r1_col[None, :])
    for c in comps:
        if c.cls not in (PIANO, BOTH) or not any(resting):
            continue
        m = (labels == c.label) & ink
        if not (m & outside_rows).any():
            continue
        runs = cv2.morphologyEx(m.astype(np.uint8), cv2.MORPH_OPEN, np.ones((int(5 * sp), 1), np.uint8)) > 0
        m_cut = m & ~(runs & at_barline[None, :])
        pd = cv2.dilate(m_cut.astype(np.uint8), np.ones((kernel[1], kernel[0]), np.uint8))
        pn, pl, _, _ = cv2.connectedComponentsWithStats(pd, connectivity=8)
        for q in range(1, pn):
            pm = (pl == q) & m_cut
            if (pm & ~outside_rows).any():  # attached: has ink inside the staff rows
                continue
            ys_, xs_ = np.where(pm)
            if len(ys_) < SPECK:
                continue
            py0, py1, px0, px1 = int(ys_.min()), int(ys_.max()), int(xs_.min()), int(xs_.max())
            rest = under_resting(px0, px1)
            if rest is None or py1 - py0 + 1 <= 2:  # a 1-2 px strip is line residue
                continue
            piece_erase |= pm
            pieces.append({"bbox": [px0, py0, px1, py1], "area": int(len(ys_)), "of": c.cls,
                           "how": f"floating {'above' if py1 < top_line else 'below'} the staff lines over resting bar(s) {[k + 1 for k in rest]}"})

    # masks of classified ink, for the nearest-ink resolution of gap components
    piano_ink = np.zeros_like(work, dtype=bool)
    neigh_ink = np.zeros_like(work, dtype=bool)
    for c in comps:
        m = (labels == c.label) & ink
        if c.cls in (PIANO, BOTH):
            piano_ink |= m & ~piece_erase
        elif c.cls in (NEIGHBOUR, REST_BAR):
            neigh_ink |= m
    neigh_ink |= piece_erase
    margin = int(round(sp))
    reach = int(round(1.5 * sp))

    def beside(mask: np.ndarray, c: Comp, reach: int = reach) -> float:
        """Horizontal distance to ink of `mask` on the component's own rows, left or right within `reach`
        (1.5 spaces), when that ink covers at least half of the component's rows: the previous or next word of
        a text line ("a" and "tempo" are 6 px apart, "tempo" is joined to the piano's stems, "a" is not)."""
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

    pending = [c for c in comps if c.cls == GAP and c.rest is None]
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

    # resting-bar components last: one that continues a kept text line (the next word within 2.5 spaces on its
    # own rows, nearer than any neighbour word) is kept, chains propagate ("Allegro" over bar 1 keeps "con",
    # "con" keeps "brio"); the rest are the neighbour's
    word_reach = int(round(2.5 * sp))  # Breitkopf's bold tempo text spaces its words ~12 px apart
    rest_pending = [c for c in comps if c.cls == GAP and c.rest is not None]
    while rest_pending:
        chained = []
        for c in rest_pending:
            d_p, d_n = beside(piano_ink, c, word_reach), beside(neigh_ink, c, word_reach)
            if d_p < float("inf") and d_p <= d_n:
                chained.append((d_p, d_n, c))
        if not chained:
            break
        d_p, d_n, c = min(chained, key=lambda t: t[0])
        rest_pending.remove(c)
        c.cls, c.how = "gap->piano", (f"over resting bar(s) {[k + 1 for k in c.rest]} but continues a kept text line "
                                      f"({d_p:.0f} px beside kept ink, {d_n:.0f} px beside neighbour ink)")
        piano_ink |= (labels == c.label) & ink
    for c in rest_pending:
        side = "above" if c.y1 < top_line else "below"
        c.cls, c.how = REST_BAR, (f"{side} the target over resting bar(s) {[k + 1 for k in c.rest]} "
                                  f"({', '.join(f'{bar_ink[k]:.1f}' for k in c.rest)} sp² of own ink, floor {floor:.1f})")
        neigh_ink |= (labels == c.label) & ink

    # erase: paint white over the dilated mask (+1 px) of every neighbour component and speck
    erase = np.zeros_like(work, dtype=bool)
    for c in comps:
        if c.cls in (NEIGHBOUR, REST_BAR, "gap->neighbour", "speck"):
            erase |= labels == c.label
    erase |= piece_erase
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
        "erased": counts.get(NEIGHBOUR, 0) + counts.get("gap->neighbour", 0) + counts.get("speck", 0) + counts.get(REST_BAR, 0),
        "kept": counts.get(PIANO, 0) + counts.get(BOTH, 0) + counts.get("gap->piano", 0),
        "by_class": counts,
        "bars": [{"x": [int(xa), int(xb)], "ink_sp2": round(v, 1), "resting": r} for (xa, xb), v, r in zip(bars, bar_ink, resting)],
        "rest_floor_sp2": round(floor, 2),
        "rest_bars": [k + 1 for k, r in enumerate(resting) if r],
        "erased_rest_bar": counts.get(REST_BAR, 0),
        "erased_pieces": len(pieces),
        "pieces": pieces,
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
        for k, (xa, xb) in enumerate(bars):  # resting bars shaded
            if resting[k]:
                tint[:, xa : xb + 1] = (0.85 * tint[:, xa : xb + 1] + 0.15 * np.array((120, 120, 120))).astype(np.uint8)
        for c in comps:
            m = (labels == c.label) & ink
            col = np.array(TINT.get(c.cls, (0, 0, 0)), dtype=np.uint8)
            tint[m] = (0.25 * tint[m] + 0.75 * col).astype(np.uint8)
        col = np.array(TINT["piece"], dtype=np.uint8)
        tint[piece_erase] = (0.25 * tint[piece_erase] + 0.75 * col).astype(np.uint8)
        # final crop edges in blue, regions in faint lines
        tint[y0, :, :] = (30, 60, 230)
        tint[y1, :, :] = (30, 60, 230)
        dbg = Image.fromarray(tint)
    return crop, box, stats_out, dbg


if __name__ == "__main__":
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
    from common import PIANO_CUT_RUN as RUN
    from fallback_cv import binarise, rotate
    from piano_cut_geometry import PC, PAGES_DIR, DEFAULT_PAGES

    for n in [int(x) for x in sys.argv[1:] if x != "-v"] or DEFAULT_PAGES:
        geom = json.loads((PC / f"geom-p{n:02d}.json").read_text())
        label = json.loads((RUN / f"label-p{n:02d}.json").read_text())
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
            dbg.save(RUN / f"clean-debug-p{n:02d}-s{system['index']}.png")
            crop.save(RUN / f"clean-preview-p{n:02d}-s{system['index']}.png")
            print(json.dumps({"page": n, "system": system["index"], "box": box,
                              **{k: v for k, v in st.items() if k not in ("both", "gap_resolved", "detail")}}))
            for g in st["detail"]:
                if g["class"] in (BOTH, PIANO) or g["class"].startswith("gap->") or "-v" in sys.argv:
                    print("   ", g["class"], g["bbox"], g["area"], g["how"])
