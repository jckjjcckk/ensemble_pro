"""Staff-level geometry and the cut for one instrument on a full-score page. No model calls.

Ported from the piano-cut experiment (`api/experiments/grounding/piano_cut_{geometry,build,clean}.py`, report in
`out/piano-cut/REPORT.md` and `CLEAN.md`): staves as row-profile peaks, systems by the left systemic line,
system barlines by two votes (staff cover and gap crossing), a numbered overlay for the model to label, a
cleaned crop of the wanted staves (band between the neighbours, their ink erased), and the geometric verify.
Pixel thresholds assume ~150 dpi (page about 1200-1450 px wide).
"""
from __future__ import annotations

import io
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .geometry import binarise, estimate_skew, rotate, vertical_cover

KERNEL = (7, 3)   # joining dilation (w, h) for the clean pass
PAD = 3           # px around kept ink
SPECK = 4         # ink px; smaller components outside the wanted region are noise


# ---------------------------------------------------------------- geometry

def find_staves(bw: np.ndarray) -> list[dict]:
    """Staves (y_top, y_bottom, lines, spacing, x0, x1) from local maxima of the long-run row profile."""
    h, w = bw.shape
    opened = cv2.morphologyEx(bw, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (max(20, w // 40), 1)))
    frac = opened.sum(axis=1) / w
    sm = np.convolve(frac, np.ones(3) / 3, mode="same")
    centres: list[float] = []
    for r in np.where(sm > 0.2)[0]:
        lo, hi = max(0, r - 3), min(h, r + 4)
        if sm[r] >= sm[lo:hi].max() and (not centres or r - centres[-1] > 3):
            centres.append(float(r))
    small_gaps = [b - a for a, b in zip(centres, centres[1:]) if 4 <= b - a <= 20]
    if not small_gaps:
        return []
    sp = float(np.median(small_gaps))
    used = [False] * len(centres)
    staves: list[dict] = []
    i = 0
    while i < len(centres):
        if used[i]:
            i += 1
            continue
        lines, idxs = [centres[i]], [i]
        for k in range(1, 5):
            step = sp if k == 1 else (sp + (lines[-1] - lines[0]) / (k - 1)) / 2
            target = lines[0] + k * step
            cand = [(abs(centres[j] - target), j) for j in range(i + 1, len(centres)) if not used[j] and abs(centres[j] - target) <= 0.4 * sp]
            if not cand:
                break
            _, j = min(cand)
            lines.append(centres[j])
            idxs.append(j)
        if len(lines) == 5:
            y0, y1 = int(round(lines[0])), int(round(lines[-1]))
            band = opened[max(0, y0 - 2): y1 + 3]
            cols = np.where(band.sum(axis=0) >= 3)[0]
            if len(cols) and cols.max() - cols.min() >= w * 0.5:
                for j in idxs:
                    used[j] = True
                staves.append({"index": len(staves) + 1, "y_top": y0, "y_bottom": y1, "lines": [int(round(c)) for c in lines],
                               "spacing": (lines[-1] - lines[0]) / 4, "x0": int(cols.min()), "x1": int(cols.max())})
                i = idxs[-1] + 1
                continue
        i += 1
    return staves


def group_systems(bw: np.ndarray, staves: list[dict]) -> tuple[list[list[int]], str]:
    """Consecutive staves joined by the left systemic line; fallback: split at gaps > 2.5x the median gap."""
    systems: list[list[int]] = []
    joined_any = False
    left = int(np.median([s["x0"] for s in staves])) if staves else 0
    for i, s in enumerate(staves):
        if systems:
            a = staves[systems[-1][-1]]
            if any(vertical_cover(bw, x, a["y_bottom"], s["y_top"]) >= 0.97 for x in range(max(0, left - 8), left + 15)):
                systems[-1].append(i)
                joined_any = True
                continue
        systems.append([i])
    if joined_any or len(staves) < 2:
        return systems, "systemic-line"
    gaps = [staves[i + 1]["y_top"] - staves[i]["y_bottom"] for i in range(len(staves) - 1)]
    med = float(np.median(gaps))
    systems = [[0]]
    for i, g in enumerate(gaps):
        systems.append([i + 1]) if g > 2.5 * med else systems[-1].append(i + 1)
    return systems, "gap-fallback"


def find_system_barlines(bw: np.ndarray, staves: list[dict], x0: int, x1: int, min_cover: float = 0.9, tol: int = 4) -> list[tuple[int, int]]:
    """Columns that cover >= 60% of the staves' five-line spans and cross >= 30% of the gaps between them."""
    kernel = np.ones((1, 2 * tol + 1), np.uint8)
    staff_votes = np.zeros(x1 - x0 + 1, dtype=int)
    for s in staves:
        band = cv2.dilate(bw[s["y_top"]: s["y_bottom"] + 1, x0: x1 + 1], kernel)
        staff_votes += (band.mean(axis=0) >= min_cover).astype(int)
    pair_votes = np.zeros(x1 - x0 + 1, dtype=int)
    for a, b in zip(staves, staves[1:]):
        band = cv2.dilate(bw[a["y_top"]: b["y_bottom"] + 1, x0: x1 + 1], kernel)
        pair_votes += (band.mean(axis=0) >= min_cover).astype(int)
    ok = staff_votes >= max(1, int(np.ceil(0.6 * len(staves))))
    if len(staves) > 1:
        ok &= pair_votes >= max(1, int(np.ceil(0.3 * (len(staves) - 1))))
    clusters: list[list[int]] = []
    for x in np.where(ok)[0] + x0:
        if clusters and x - clusters[-1][-1] <= 14:
            clusters[-1].append(int(x))
        else:
            clusters.append([int(x)])
    return [(c[0], c[-1]) for c in clusters if c[-1] - c[0] + 1 >= tol + 1]


def count_measures(bars: list[tuple[int, int]], x0: int, x1: int, spacing: float) -> int:
    header = x0 + 12 * spacing
    edges = [(x0, max([x0] + [b[1] for b in bars if b[0] <= header]))] + [b for b in bars if b[0] > header]
    if edges[-1][1] < x1 - 10:
        edges.append((x1, x1))
    return sum(1 for a, b in zip(edges, edges[1:]) if b[0] - a[1] >= 1.5 * spacing)


def page_geometry(png: bytes) -> tuple[dict[str, Any], np.ndarray, Image.Image]:
    """Geometry dict (staves, systems with barlines and bar counts), the deskewed binary page, the deskewed RGB page."""
    gray = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_GRAYSCALE)
    if gray is None:
        raise ValueError("page image could not be decoded")
    h, w = gray.shape
    bw = binarise(gray)
    skew = estimate_skew(bw)
    if abs(skew) >= 0.1:
        bw, gray = rotate(bw, skew, 0), rotate(gray, skew, 255)
    staves = find_staves(bw)
    systems_idx, method = group_systems(bw, staves) if staves else ([], "none")
    systems = []
    for si, idxs in enumerate(systems_idx, start=1):
        ss = [staves[i] for i in idxs]
        x0, x1 = int(np.median([s["x0"] for s in ss])), int(np.median([s["x1"] for s in ss]))
        bars = find_system_barlines(bw, ss, x0, x1)
        sp = float(np.median([s["spacing"] for s in ss]))
        pad = int(sp * 1.5)
        systems.append({"index": si, "staff_indices": [s["index"] for s in ss],
                        "box": {"x0": x0, "y0": max(0, ss[0]["y_top"] - pad), "x1": x1, "y1": min(h - 1, ss[-1]["y_bottom"] + pad)},
                        "barlines": bars, "n_measures": count_measures(bars, x0, x1, sp)})
    geom = {"image_px": [w, h], "skew_deg": round(float(skew), 2), "grouping": method,
            "staves": [{k: (round(v, 2) if isinstance(v, float) else v) for k, v in s.items()} for s in staves], "systems": systems}
    return geom, bw, Image.fromarray(gray).convert("RGB")


def _font(size: int):
    try:
        return ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", size)
    except Exception:  # noqa: BLE001
        return ImageFont.load_default()


def overlay_png(page: Image.Image, geom: dict) -> bytes:
    """The page with every staff boxed in blue and tagged with its number, systems in grey."""
    im = page.convert("RGB").copy()
    d = ImageDraw.Draw(im, "RGBA")
    font = _font(26)
    for s in geom["systems"]:
        b = s["box"]
        d.rectangle([b["x0"], b["y0"], b["x1"], b["y1"]], outline=(120, 120, 120, 255), width=2)
    for st in geom["staves"]:
        pad = int(st["spacing"] * 1.2)
        d.rectangle([st["x0"], st["y_top"] - pad, st["x1"], st["y_bottom"] + pad], outline=(0, 110, 220, 255), width=2)
        tx, ty = st["x0"] + 4, st["y_top"] - pad - 2
        d.rectangle([tx, ty, tx + 46, ty + 30], fill=(255, 235, 60, 230), outline=(0, 0, 0, 255))
        d.text((tx + 6, ty + 1), str(st["index"]), fill=(0, 0, 0, 255), font=font)
    return to_png(im)


def to_png(im: Image.Image) -> bytes:
    buf = io.BytesIO()
    im.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


# ---------------------------------------------------------------- the cut

def neighbours(geom: dict, system: dict, wanted: list[int]) -> tuple[dict | None, dict | None]:
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


def plain_box(geom: dict, system: dict, wanted: list[int]) -> dict:
    """Wanted staves plus ~1.5 spaces, clipped to the neighbours; the fallback when the clean pass cannot run."""
    staves = {s["index"]: s for s in geom["staves"]}
    w, h = geom["image_px"]
    ss = [staves[i] for i in sorted(wanted)]
    sp = float(np.median([s["spacing"] for s in ss]))
    prev, nxt = neighbours(geom, system, wanted)
    y0 = ss[0]["y_top"] - 6 * sp
    y0 = max(y0, prev["y_bottom"] + 1.5 * sp) if prev else min(y0, system["box"]["y0"] - 4 * sp)
    y1 = ss[-1]["y_bottom"] + 6 * sp
    if nxt:
        y1 = min(y1, nxt["y_top"] - 1.5 * sp)
    return {"x0": 0, "y0": int(max(0, y0)), "x1": int(min(w - 1, system["box"]["x1"] + 2 * sp)), "y1": int(min(h - 1, y1))}


def _first_ink(mask: np.ndarray, y: int, x0: int, x1: int, below: bool) -> int | None:
    strip = mask[y + 1:, x0: x1 + 1] if below else mask[:y, x0: x1 + 1]
    rows = np.where(strip.any(axis=1))[0]
    if not len(rows):
        return None
    return y + 1 + int(rows[0]) if below else int(rows[-1])


def clean_crop(bw: np.ndarray, page: Image.Image, geom: dict, system: dict, wanted: list[int]) -> tuple[Image.Image, dict, dict]:
    """The wanted staves cut from the band between their neighbours, the neighbours' ink erased, fitted to the kept ink.
    Returns (crop, box in page px, stats). See CLEAN.md for the classes and the nearest-ink rule."""
    staves = {s["index"]: s for s in geom["staves"]}
    h, w = bw.shape
    ss = [staves[i] for i in sorted(wanted)]
    a, b = ss[0], ss[-1]
    sp = float(np.median([s["spacing"] for s in ss]))
    prev, nxt = neighbours(geom, system, wanted)
    edge = int(round(0.5 * sp))
    band_top = prev["y_bottom"] + edge if prev else max(0, int(a["y_top"] - 12 * sp))
    band_bot = nxt["y_top"] - edge if nxt else min(h - 1, int(b["y_bottom"] + 12 * sp))
    bx0, bx1 = 0, int(min(w - 1, system["box"]["x1"] + 2 * sp))
    work = bw[band_top: band_bot + 1, bx0: bx1 + 1].copy()
    H, W = work.shape
    p_r0, p_r1 = a["y_top"] - sp - band_top, b["y_bottom"] + sp - band_top
    top_line, bot_line = a["y_top"] - band_top, b["y_bottom"] - band_top

    # barline columns that run from a band edge to the wanted staves join every staff into one component: mask them
    wide = cv2.dilate(work, np.ones((1, 3), np.uint8))
    at_barline = np.zeros(W, dtype=bool)
    for lx0, lx1 in system["barlines"]:
        at_barline[max(0, lx0 - 4 - bx0): min(W, lx1 + 5 - bx0)] = True
    col_mask = np.zeros_like(work, dtype=bool)
    if prev is not None and top_line > 6:
        gap = wide[: top_line - 1]
        for c in np.where((gap.mean(axis=0) >= 0.85) & gap[:3].any(axis=0) & gap[-3:].any(axis=0) & at_barline)[0]:
            col_mask[: top_line - 1, max(0, c - 1): c + 2] = True
    if nxt is not None and H - bot_line > 7:
        gap = wide[bot_line + 2:]
        for c in np.where((gap.mean(axis=0) >= 0.85) & gap[:3].any(axis=0) & gap[-3:].any(axis=0) & at_barline)[0]:
            col_mask[bot_line + 2:, max(0, c - 1): c + 2] = True
    work[col_mask] = 0

    dil = cv2.dilate(work, np.ones((KERNEL[1], KERNEL[0]), np.uint8))
    n, labels, stats, _ = cv2.connectedComponentsWithStats(dil, connectivity=8)
    ink = work > 0
    n_top_r1 = (prev["y_bottom"] + sp - band_top) if prev else None
    n_bot_r0 = (nxt["y_top"] - sp - band_top) if nxt else None
    comps: list[dict] = []
    for l in range(1, n):
        x, y, cw, ch = (int(stats[l][k]) for k in (cv2.CC_STAT_LEFT, cv2.CC_STAT_TOP, cv2.CC_STAT_WIDTH, cv2.CC_STAT_HEIGHT))
        sub = (labels[y: y + ch, x: x + cw] == l) & ink[y: y + ch, x: x + cw]
        ys, xs = np.where(sub)
        if not len(ys):
            continue
        c = {"label": l, "y0": y + int(ys.min()), "y1": y + int(ys.max()), "x0": x + int(xs.min()), "x1": x + int(xs.max()), "area": int(len(ys)), "cls": "gap"}
        over = c["y1"] >= p_r0 and c["y0"] <= p_r1
        touch = (prev is not None and (c["y0"] <= 1 or c["y0"] <= n_top_r1)) or (nxt is not None and (c["y1"] >= H - 2 or c["y1"] >= n_bot_r0))
        c["cls"] = "both" if over and touch else "piano" if over else "neighbour" if touch else "speck" if c["area"] < SPECK else "gap"
        comps.append(c)

    piano_ink = np.zeros_like(ink)
    neigh_ink = np.zeros_like(ink)
    for c in comps:
        m = (labels == c["label"]) & ink
        if c["cls"] in ("piano", "both"):
            piano_ink |= m
        elif c["cls"] == "neighbour":
            neigh_ink |= m
    margin, reach = int(round(sp)), int(round(1.5 * sp))

    def beside(mask: np.ndarray, c: dict) -> float:
        hh = c["y1"] - c["y0"] + 1
        best = float("inf")
        left = mask[c["y0"]: c["y1"] + 1, max(0, c["x0"] - reach): c["x0"]]
        if left.size and left.any(axis=1).sum() >= 0.5 * hh:
            best = min(best, left.shape[1] - int(np.where(left.any(axis=0))[0].max()))
        right = mask[c["y0"]: c["y1"] + 1, c["x1"] + 1: min(W, c["x1"] + 1 + reach)]
        if right.size and right.any(axis=1).sum() >= 0.5 * hh:
            best = min(best, int(np.where(right.any(axis=0))[0].min()) + 1)
        return best

    def distances(c: dict) -> tuple[float, float]:
        x0, x1 = max(0, c["x0"] - margin), min(W - 1, c["x1"] + margin)
        if c["y1"] < p_r0:
            r = _first_ink(piano_ink, c["y1"], x0, x1, True)
            d_p = (r - c["y1"]) if r is not None else (a["y_top"] - band_top - c["y1"])
            r = _first_ink(neigh_ink, c["y0"], x0, x1, False)
            d_n = (c["y0"] - r) if r is not None else ((c["y0"] + edge) if prev else float("inf"))
        else:
            r = _first_ink(piano_ink, c["y0"], x0, x1, False)
            d_p = (c["y0"] - r) if r is not None else (c["y0"] - (b["y_bottom"] - band_top))
            r = _first_ink(neigh_ink, c["y1"], x0, x1, True)
            d_n = (r - c["y1"]) if r is not None else ((H - 1 - c["y1"] + edge) if nxt else float("inf"))
        return float(min(d_p, beside(piano_ink, c))), float(min(d_n, beside(neigh_ink, c)))

    pending = [c for c in comps if c["cls"] == "gap"]
    while pending:
        for c in pending:
            c["d_p"], c["d_n"] = distances(c)
        c = min(pending, key=lambda c: min(c["d_p"], c["d_n"]))
        pending.remove(c)
        m = (labels == c["label"]) & ink
        if c["d_p"] <= c["d_n"]:
            c["cls"] = "gap->piano"
            piano_ink |= m
        else:
            c["cls"] = "gap->neighbour"
            neigh_ink |= m

    erase = np.zeros_like(ink)
    for c in comps:
        if c["cls"] in ("neighbour", "gap->neighbour", "speck"):
            erase |= labels == c["label"]
    erase = cv2.dilate(erase.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)
    erase[col_mask] = False
    out = np.array(page.crop((bx0, band_top, bx1 + 1, band_bot + 1)).convert("RGB")).copy()
    out[erase] = 255
    ys = np.where(piano_ink.any(axis=1))[0]
    k_y0, k_y1 = (int(ys.min()), int(ys.max())) if len(ys) else (int(p_r0), int(p_r1))
    y0 = max(0, min(k_y0 - PAD, int(a["y_top"] - sp - band_top)))
    y1 = min(H - 1, max(k_y1 + PAD, int(b["y_bottom"] + sp - band_top)))
    counts: dict[str, int] = {}
    for c in comps:
        counts[c["cls"]] = counts.get(c["cls"], 0) + 1
    stats_out = {"components": len(comps), "by_class": counts,
                 "erased": counts.get("neighbour", 0) + counts.get("gap->neighbour", 0) + counts.get("speck", 0),
                 "kept": counts.get("piano", 0) + counts.get("both", 0) + counts.get("gap->piano", 0),
                 "edge_ink_top": bool(piano_ink[y0].any()), "edge_ink_bottom": bool(piano_ink[y1].any())}
    return Image.fromarray(out[y0: y1 + 1]), {"x0": bx0, "y0": band_top + y0, "x1": bx1, "y1": band_top + y1}, stats_out


def verify(crop: Image.Image, geom: dict, system: dict, wanted: list[int], box: dict) -> dict:
    """Geometric checks on the crop as shipped: wanted staves inside and no others, a brace or bracket
    (informational), every system barline present through the wanted staves."""
    staves = {s["index"]: s for s in geom["staves"]}
    inside = [s["index"] for s in geom["staves"] if s["y_top"] >= box["y0"] and s["y_bottom"] <= box["y1"]]
    ss = [staves[i] for i in sorted(wanted)]
    a, b = ss[0], ss[-1]
    sp = float(np.median([s["spacing"] for s in ss]))
    cbw = binarise(np.array(crop.convert("L")))
    oy, ox = box["y0"], box["x0"]
    ya, yb = a["y_top"] - oy, b["y_bottom"] - oy
    x_left = int(min(s["x0"] for s in ss)) - ox
    brace = any(vertical_cover(cbw, x, ya, yb, tol=2) >= 0.9 for x in range(max(0, x_left - int(5 * sp)), max(0, x_left - 1)))
    present = []
    for bx0, bx1 in system["barlines"]:
        cols = range(max(0, bx0 - 4 - ox), min(cbw.shape[1], bx1 + 5 - ox))
        present.append(any(vertical_cover(cbw, x, ya, yb, tol=1) >= 0.9 for x in cols))
    return {"staves_in_crop": {"value": inside, "expect": sorted(wanted), "pass": sorted(inside) == sorted(wanted)},
            "brace_or_bracket": {"value": brace, "pass": brace, "informational": True},
            "barlines_present": {"present": present, "missing": [bl for bl, ok in zip(system["barlines"], present) if not ok], "pass": all(present)},
            "bar_count": {"value": system["n_measures"], "pass": True, "informational": True}}


def cut_system(bw: np.ndarray, page: Image.Image, geom: dict, system: dict, wanted: list[int]) -> tuple[Image.Image, dict, dict]:
    """Clean crop, or the plain crop when the clean pass cannot run on this page. Returns (crop, box, verify+stats)."""
    try:
        crop, box, stats = clean_crop(bw, page, geom, system, wanted)
        mode = "clean"
    except Exception as e:  # noqa: BLE001  (the clean pass is tuned on one scan; never lose the cut over it)
        box = plain_box(geom, system, wanted)
        crop = page.crop((box["x0"], box["y0"], box["x1"] + 1, box["y1"] + 1))
        stats, mode = {"error": f"{type(e).__name__}: {e}"}, "plain"
    checks = verify(crop, geom, system, wanted, box)
    checks["pass"] = all(c["pass"] for c in checks.values() if isinstance(c, dict) and not c.get("informational"))
    return crop, box, {"mode": mode, "clean": stats, **checks}
