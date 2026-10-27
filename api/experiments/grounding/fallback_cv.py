# /// script
# requires-python = ">=3.12"
# dependencies = ["opencv-python-headless", "numpy", "pillow"]
# ///
"""Fallback engine: staff-line and barline geometry with OpenCV.

Usage (from api/):  uv run experiments/grounding/fallback_cv.py [page ...]
Writes out/cv-<page>.json in the same shape as the Spark output (measures with pixel boxes).

Method
  1. Binarise (Otsu), estimate skew from the longest horizontal runs, deskew.
  2. Staff lines = rows whose dark fraction over the page width is high; group into 5-line staves.
  3. Grand staves = consecutive staves whose gap is crossed by at least one vertical line away from the left edge
     (a piano's barlines run through the gap between its two staves; between two pianos they stop).
  4. Systems = grand staves whose left systemic line is continuous across them (two pianos: four staves).
     If no left line joins them, grand staves are their own systems.
  5. Barlines = columns where a vertical dark run covers >= 92% of every grand staff's span in the system.
     Adjacent columns are merged (double / repeat barlines count once).
  6. Measures = spans between consecutive barlines; the first measure of a system starts at the systemic line.
     Barline clusters inside the header zone (12 staff spaces from the systemic line: start repeats, clef and
     key-signature strokes) are merged into the system start.
"""

from __future__ import annotations

import json
import sys

import cv2
import numpy as np

from common import OUT, PAGE_NAMES, PAGES, dump


def binarise(gray: np.ndarray) -> np.ndarray:
    """Otsu OR adaptive: grey scans print staff lines lighter than Otsu's global threshold."""
    _, otsu = cv2.threshold(gray, 0, 1, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    adaptive = cv2.adaptiveThreshold(gray, 1, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 51, 18)
    return np.maximum(otsu, adaptive).astype(np.uint8)


def estimate_skew(bw: np.ndarray) -> float:
    """Angle in degrees that maximises the sharpest row projection (staff lines become horizontal)."""
    h, w = bw.shape
    best, best_score = 0.0, -1.0
    small = cv2.resize(bw, (w // 2, h // 2), interpolation=cv2.INTER_AREA)
    for ang in np.arange(-1.5, 1.51, 0.1):
        m = cv2.getRotationMatrix2D((small.shape[1] / 2, small.shape[0] / 2), ang, 1.0)
        rot = cv2.warpAffine(small, m, (small.shape[1], small.shape[0]), flags=cv2.INTER_NEAREST)
        prof = rot.sum(axis=1).astype(float)
        score = float((prof**2).sum())
        if score > best_score:
            best, best_score = float(ang), score
    return best


def rotate(img: np.ndarray, ang: float, border: int) -> np.ndarray:
    h, w = img.shape
    m = cv2.getRotationMatrix2D((w / 2, h / 2), ang, 1.0)
    return cv2.warpAffine(img, m, (w, h), flags=cv2.INTER_NEAREST, borderValue=border)


def find_staves(bw: np.ndarray) -> list[dict]:
    """Return staves as dicts: y_top, y_bottom, lines (5 row indices), x0, x1 (horizontal extent)."""
    h, w = bw.shape
    # keep only long-ish horizontal runs so note heads and text do not count
    opened = cv2.morphologyEx(bw, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (max(20, w // 40), 1)))
    frac = opened.sum(axis=1) / w
    thr = 0.25
    rows = np.where(frac > thr)[0]
    # merge consecutive rows into line centres
    lines = []
    for r in rows:
        if lines and r - lines[-1][-1] <= 2:
            lines[-1].append(int(r))
        else:
            lines.append([int(r)])
    centres = [float(np.mean(g)) for g in lines]
    # group centres into staves of 5 with near-equal spacing
    staves = []
    i = 0
    while i < len(centres):
        group = [centres[i]]
        j = i + 1
        while j < len(centres) and len(group) < 5:
            gap = centres[j] - group[-1]
            if group and len(group) >= 2:
                sp = (group[-1] - group[0]) / (len(group) - 1)
                if abs(gap - sp) > 0.35 * sp:
                    break
            elif gap > 30:
                break
            group.append(centres[j])
            j += 1
        if len(group) == 5:
            y0, y1 = int(round(group[0])), int(round(group[-1]))
            band = opened[y0 : y1 + 1]
            cols = np.where(band.sum(axis=0) > 0)[0]
            staves.append({"y_top": y0, "y_bottom": y1, "lines": [int(round(c)) for c in group],
                           "spacing": (group[-1] - group[0]) / 4, "x0": int(cols.min()), "x1": int(cols.max())})
            i = j
        else:
            i += 1
    return staves


def vertical_cover(bw: np.ndarray, x: int, y0: int, y1: int, tol: int = 1) -> float:
    """Fraction of rows in [y0, y1] that have a dark pixel within +-tol columns of x."""
    sl = bw[y0 : y1 + 1, max(0, x - tol) : x + tol + 1]
    return float((sl.max(axis=1) > 0).mean())


def group_staves(bw: np.ndarray, staves: list[dict]) -> list[list[int]]:
    """Group consecutive staves into grand staves when barlines cross the gap between them.

    A piano's two staves share barlines that run through the gap; two pianos (or two instruments) do not.
    The left systemic line is excluded from the test (it joins every staff of a system).
    """
    groups: list[list[int]] = []
    for i, s in enumerate(staves):
        if groups:
            prev = staves[groups[-1][-1]]
            gap = s["y_top"] - prev["y_bottom"]
            if 0 < gap < 14 * s["spacing"]:
                x0 = int(max(prev["x0"], s["x0"]) + 12 * s["spacing"])
                x1 = int(min(prev["x1"], s["x1"]))
                band = bw[prev["y_bottom"] : s["y_top"] + 1, x0 : x1 + 1]
                band = cv2.dilate(band, np.ones((1, 3), np.uint8))
                if band.size and (band.mean(axis=0) >= 0.97).any():
                    groups[-1].append(i)
                    continue
        groups.append([i])
    return groups


def find_barlines(bw: np.ndarray, spans: list[tuple[int, int]], x0: int, x1: int, min_cover: float = 0.92) -> list[tuple[int, int]]:
    """Columns in [x0, x1] whose vertical run covers every span; merged into (xa, xb) clusters."""
    h, w = bw.shape
    ok = np.ones(x1 - x0 + 1, dtype=bool)
    for (ya, yb) in spans:
        band = bw[ya : yb + 1, x0 : x1 + 1]
        # tolerate 1px wobble: a row counts if a dark pixel is within +-1 column
        band = cv2.dilate(band, np.ones((1, 3), np.uint8))
        cover = band.mean(axis=0)
        ok &= cover >= min_cover
    xs = np.where(ok)[0] + x0
    clusters: list[list[int]] = []
    for x in xs:
        if clusters and x - clusters[-1][-1] <= 14:
            clusters[-1].append(int(x))
        else:
            clusters.append([int(x)])
    return [(c[0], c[-1]) for c in clusters]


def run_page(page: str, first_measure: int = 1) -> dict:
    gray = cv2.imread(str(PAGES / f"{page}.png"), cv2.IMREAD_GRAYSCALE)
    h, w = gray.shape
    bw = binarise(gray)
    skew = estimate_skew(bw)
    if abs(skew) >= 0.1:
        bw = rotate(bw, skew, 0)
    staves = find_staves(bw)
    groups = group_staves(bw, staves)
    # systems: grand staves joined by a left systemic line across the gap (two pianos). Otherwise one grand staff each.
    systems: list[list[int]] = []
    for g in groups:
        if systems:
            prev = staves[systems[-1][-1]]
            cur = staves[g[0]]
            xa = max(0, min(prev["x0"], cur["x0"]) - 4)
            joined = any(vertical_cover(bw, x, prev["y_bottom"], cur["y_top"]) > 0.97 for x in range(xa, xa + 44))
            if joined and cur["y_top"] - prev["y_bottom"] < 14 * cur["spacing"]:
                systems[-1].extend(g)
                continue
        systems.append(list(g))

    out_systems, measures = [], []
    n = first_measure
    for si, idxs in enumerate(systems, start=1):
        ss = [staves[i] for i in idxs]
        y_top, y_bot = ss[0]["y_top"], ss[-1]["y_bottom"]
        x0, x1 = min(s["x0"] for s in ss), max(s["x1"] for s in ss)
        # grand-staff spans inside this system (for two pianos: two spans; for piano: one)
        spans = []
        for g in groups:
            if g[0] in idxs:
                spans.append((staves[g[0]]["y_top"], staves[g[-1]]["y_bottom"]))
        bars = find_barlines(bw, spans, x0, x1)
        pad = int(ss[0]["spacing"] * 1.5)
        box = {"x0": x0, "y0": max(0, y_top - pad), "x1": x1, "y1": min(h - 1, y_bot + pad)}
        out_systems.append({"index": si, "box": box, "staves": len(ss), "barlines": bars})
        # measures between consecutive barlines; drop slivers narrower than 1.5 staff spaces
        header = x0 + 12 * ss[0]["spacing"]
        edges = [b for b in bars if b[0] > header]
        edges = [(x0, max([x0] + [b[1] for b in bars if b[0] <= header]))] + edges
        if edges[-1][1] < x1 - 10:
            edges = edges + [(x1, x1)]
        for (a, b) in zip(edges, edges[1:]):
            if b[0] - a[1] < 1.5 * ss[0]["spacing"]:
                continue
            measures.append({"number": n, "system": si, "box": {"x0": a[0], "y0": box["y0"], "x1": b[1], "y1": box["y1"]},
                             "uncertain": False})
            n += 1
        out_systems[-1]["n_measures"] = sum(1 for m in measures if m["system"] == si)
    result = {"page": page, "engine": "opencv-geometry", "skew_deg": skew, "image_px": [w, h],
              "staves": [{"y_top": s["y_top"], "y_bottom": s["y_bottom"], "x0": s["x0"], "x1": s["x1"]} for s in staves],
              "systems": out_systems, "measures": measures}
    dump(OUT / f"cv-{page}.json", result)
    print(page, "skew", skew, "staves", len(staves), "systems", [s["n_measures"] for s in out_systems], "measures", len(measures))
    for s in out_systems:
        print("  sys", s["index"], s["box"], "bars", s["barlines"])
    return result


if __name__ == "__main__":
    for p in sys.argv[1:] or PAGE_NAMES:
        run_page(p)
