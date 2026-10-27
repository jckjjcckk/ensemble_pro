"""Staff-and-barline geometry: where the measures are on a scanned page. No model call, about 30 ms a page.

Lifted from the grounding experiment (`api/experiments/grounding/fallback_cv.py`), which passed the tap test
28/28 and 13/13 where SAM 3.1 + Spark grounding did not. The one public function is `measures_on_page`.

Method
  1. Binarise (Otsu OR adaptive mean: grey scans print staff lines lighter than Otsu's global threshold),
     estimate skew by maximising the row-projection energy, deskew.
  2. Staff lines = rows with long horizontal runs; group them into 5-line staves.
  3. Grand staves = consecutive staves whose gap is crossed by a vertical line away from the left edge
     (a piano's barlines run through the gap between its two staves; between two pianos they stop).
  4. Systems = grand staves joined by a continuous left systemic line.
  5. Barlines = columns whose vertical dark run covers >= 92 % of every grand staff in the system; adjacent
     columns merge into one cluster (double and repeat barlines count once).
  6. Measures = spans between consecutive barlines, numbered top-left to bottom-right. Clusters inside the
     header zone (12 staff spaces from the systemic line: start repeats, clef and key strokes) merge into the
     system start.

Confidence per measure comes from the geometry itself, as the experiment README recommends: the width and
coverage of the closing barline, header-zone merges, bars that are far narrower or wider than the page's
median, and systems that end without a barline. Spark's labelling (labels.py) is only a second opinion.

Boxes are returned as fractions 0..1 of the page image, so the client never needs the raster size. They are
in the deskewed frame: on a 0.5° page the far corners sit up to 4 px off, fine for tapping.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from statistics import median
from typing import Any

import cv2
import numpy as np

# Pixel-tuned thresholds below assume a page about 1300-1450 px wide (150 dpi letter / A4). Wider scans are
# shrunk to WORK_WIDTH before analysis; boxes are fractions so the caller never sees the working size.
WORK_WIDTH = 1400
MIN_COVER = 0.92          # a barline must cover this much of every grand staff in its system
HEADER_SPACES = 12        # header zone (clef, key, start repeat) in staff spaces from the systemic line
MIN_MEASURE_SPACES = 1.5  # slivers narrower than this are dropped
NARROW_SPACES = 4.0       # bars narrower than this are flagged


@dataclass
class Box:
    x0: float
    y0: float
    x1: float
    y1: float

    def to_px(self, w: int, h: int) -> dict[str, int]:
        return {"x0": int(round(self.x0 * w)), "y0": int(round(self.y0 * h)), "x1": int(round(self.x1 * w)), "y1": int(round(self.y1 * h))}

    def as_dict(self) -> dict[str, float]:
        return {k: round(v, 5) for k, v in asdict(self).items()}


@dataclass
class Barline:
    x0: float              # fraction; cluster start
    x1: float              # fraction; cluster end
    width_px: int          # in the working raster
    cover: float           # min over grand staves of the best column's coverage


@dataclass
class System:
    index: int             # 1-based on the page
    box: Box
    staves: int
    grand_staves: int
    barlines: list[Barline] = field(default_factory=list)


@dataclass
class Measure:
    provisional: int       # 1-based, top-left to bottom-right on this page
    system: int
    box: Box
    confidence: str        # high | medium | low
    flag: str | None = None


@dataclass
class PageGeometry:
    image_px: tuple[int, int]
    skew_deg: float
    staves: int
    systems: list[System]
    measures: list[Measure]
    log: list[str]

    @property
    def readable(self) -> bool:
        return bool(self.measures)

    def as_dict(self) -> dict[str, Any]:
        return {
            "image_px": list(self.image_px), "skew_deg": round(self.skew_deg, 2), "staves": self.staves,
            "systems": [{"index": s.index, "box": s.box.as_dict(), "staves": s.staves, "grand_staves": s.grand_staves,
                         "barlines": [{"x0": round(b.x0, 5), "x1": round(b.x1, 5), "width_px": b.width_px, "cover": round(b.cover, 3)} for b in s.barlines]}
                        for s in self.systems],
            "measures": [{"provisional": m.provisional, "system": m.system, "box": m.box.as_dict(), "confidence": m.confidence, "flag": m.flag}
                         for m in self.measures],
            "log": self.log,
        }


# ---------------------------------------------------------------- raster steps (unchanged from the experiment)

def binarise(gray: np.ndarray) -> np.ndarray:
    _, otsu = cv2.threshold(gray, 0, 1, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    adaptive = cv2.adaptiveThreshold(gray, 1, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 51, 18)
    return np.maximum(otsu, adaptive).astype(np.uint8)


def estimate_skew(bw: np.ndarray) -> float:
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
    h, w = bw.shape
    opened = cv2.morphologyEx(bw, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (max(20, w // 40), 1)))
    frac = opened.sum(axis=1) / w
    rows = np.where(frac > 0.25)[0]
    lines: list[list[int]] = []
    for r in rows:
        if lines and r - lines[-1][-1] <= 2:
            lines[-1].append(int(r))
        else:
            lines.append([int(r)])
    centres = [float(np.mean(g)) for g in lines]
    staves = []
    i = 0
    while i < len(centres):
        group = [centres[i]]
        j = i + 1
        while j < len(centres) and len(group) < 5:
            gap = centres[j] - group[-1]
            if len(group) >= 2:
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
            staves.append({"y_top": y0, "y_bottom": y1, "spacing": (group[-1] - group[0]) / 4, "x0": int(cols.min()), "x1": int(cols.max())})
            i = j
        else:
            i += 1
    return staves


def vertical_cover(bw: np.ndarray, x: int, y0: int, y1: int, tol: int = 1) -> float:
    sl = bw[y0 : y1 + 1, max(0, x - tol) : x + tol + 1]
    return float((sl.max(axis=1) > 0).mean())


def group_staves(bw: np.ndarray, staves: list[dict]) -> list[list[int]]:
    groups: list[list[int]] = []
    for i, s in enumerate(staves):
        if groups:
            prev = staves[groups[-1][-1]]
            gap = s["y_top"] - prev["y_bottom"]
            if 0 < gap < 14 * s["spacing"]:
                x0 = int(max(prev["x0"], s["x0"]) + HEADER_SPACES * s["spacing"])
                x1 = int(min(prev["x1"], s["x1"]))
                band = bw[prev["y_bottom"] : s["y_top"] + 1, x0 : x1 + 1]
                band = cv2.dilate(band, np.ones((1, 3), np.uint8))
                if band.size and (band.mean(axis=0) >= 0.97).any():
                    groups[-1].append(i)
                    continue
        groups.append([i])
    return groups


def find_barlines(bw: np.ndarray, spans: list[tuple[int, int]], x0: int, x1: int) -> list[tuple[int, int, float]]:
    """Clusters (xa, xb, min_cover) of columns whose vertical run covers every grand staff span."""
    ok = np.ones(x1 - x0 + 1, dtype=bool)
    cover_min = np.ones(x1 - x0 + 1, dtype=float)
    for (ya, yb) in spans:
        band = bw[ya : yb + 1, x0 : x1 + 1]
        band = cv2.dilate(band, np.ones((1, 3), np.uint8))
        cover = band.mean(axis=0)
        ok &= cover >= MIN_COVER
        cover_min = np.minimum(cover_min, cover)
    xs = np.where(ok)[0]
    clusters: list[list[int]] = []
    for x in xs:
        if clusters and x - clusters[-1][-1] <= 14:
            clusters[-1].append(int(x))
        else:
            clusters.append([int(x)])
    return [(c[0] + x0, c[-1] + x0, float(cover_min[c].max())) for c in clusters]


# ---------------------------------------------------------------- the library function

def decode_page(png_bytes: bytes) -> np.ndarray:
    gray = cv2.imdecode(np.frombuffer(png_bytes, np.uint8), cv2.IMREAD_GRAYSCALE)
    if gray is None:
        raise ValueError("page image could not be decoded")
    return gray


def measures_on_page(png_bytes: bytes) -> PageGeometry:
    """Systems and measures on one page image, boxes as fractions, confidence and flag from the geometry."""
    gray = decode_page(png_bytes)
    H, W = gray.shape
    scale = 1.0
    if W > WORK_WIDTH * 1.3:
        scale = WORK_WIDTH / W
        gray = cv2.resize(gray, (WORK_WIDTH, int(round(H * scale))), interpolation=cv2.INTER_AREA)
    h, w = gray.shape
    log: list[str] = []

    bw = binarise(gray)
    skew = estimate_skew(bw)
    if abs(skew) >= 0.1:
        bw = rotate(bw, skew, 0)
        log.append(f"Deskewed by {skew:+.1f}°")
    staves = find_staves(bw)
    if not staves:
        return PageGeometry((W, H), skew, 0, [], [], log + ["No staff lines found"])
    groups = group_staves(bw, staves)

    systems_idx: list[list[int]] = []
    for g in groups:
        if systems_idx:
            prev = staves[systems_idx[-1][-1]]
            cur = staves[g[0]]
            xa = max(0, min(prev["x0"], cur["x0"]) - 4)
            joined = any(vertical_cover(bw, x, prev["y_bottom"], cur["y_top"]) > 0.97 for x in range(xa, xa + 44))
            if joined and cur["y_top"] - prev["y_bottom"] < 14 * cur["spacing"]:
                systems_idx[-1].extend(g)
                continue
        systems_idx.append(list(g))

    systems: list[System] = []
    measures: list[Measure] = []
    raw: list[tuple[int, float, float, bool, bool, int]] = []  # (system, px x0, px x1, header_merged, open_end, width_px-of-right-bar)
    n = 1
    for si, idxs in enumerate(systems_idx, start=1):
        ss = [staves[i] for i in idxs]
        y_top, y_bot = ss[0]["y_top"], ss[-1]["y_bottom"]
        x0, x1 = min(s["x0"] for s in ss), max(s["x1"] for s in ss)
        spans = [(staves[g[0]]["y_top"], staves[g[-1]]["y_bottom"]) for g in groups if g[0] in idxs]
        bars = find_barlines(bw, spans, x0, x1)
        pad = int(ss[0]["spacing"] * 1.5)
        by0, by1 = max(0, y_top - pad), min(h - 1, y_bot + pad)
        sys_box = Box(x0 / w, by0 / h, x1 / w, by1 / h)
        systems.append(System(si, sys_box, len(ss), len(spans),
                              [Barline(a / w, b / w, b - a + 1, c) for (a, b, c) in bars]))

        spacing = ss[0]["spacing"]
        header = x0 + HEADER_SPACES * spacing
        in_header = [b for b in bars if b[0] <= header]
        edges: list[tuple[int, int, float]] = [(x0, max([x0] + [b[1] for b in in_header]), 1.0)] + [b for b in bars if b[0] > header]
        open_end = edges[-1][1] < x1 - 10
        if open_end:
            edges.append((x1, x1, 0.0))
        header_merged = len(in_header) >= 2  # systemic line plus a start repeat or a thick key stroke
        first = True
        for (a, b) in zip(edges, edges[1:]):
            if b[0] - a[1] < MIN_MEASURE_SPACES * spacing:
                continue
            conf, flag = "high", None
            right_width, right_cover = b[1] - b[0] + 1, b[2]
            is_last = b is edges[-1]
            if is_last and open_end:
                conf, flag = "medium", "no closing barline; bar runs to the end of the staves"
            elif right_cover < 0.97:
                conf, flag = "medium", "closing barline partly broken"
            elif right_width <= 1 and not is_last:
                conf, flag = "medium", "thin closing barline, could be a stem"
            if first and header_merged:
                conf, flag = "medium", "bar start merged with repeat or key strokes"
            width_spaces = (b[0] - a[1]) / spacing
            if width_spaces < NARROW_SPACES:
                conf, flag = "low", "very narrow bar"
            measures.append(Measure(n, si, Box(a[0] / w, by0 / h, b[1] / w, by1 / h), conf, flag))
            raw.append((si, a[0], b[1], header_merged, open_end, right_width))
            first = False
            n += 1

    # page-relative width check: a bar far wider than the median usually hides a missed barline
    widths = [m.box.x1 - m.box.x0 for m in measures]
    if len(widths) >= 4:
        med = median(widths)
        for m, wd in zip(measures, widths):
            if wd > 2.6 * med and m.confidence == "high":
                m.confidence, m.flag = "medium", "unusually wide bar, a barline may have been missed"

    per_system = [sum(1 for m in measures if m.system == s.index) for s in systems]
    log.append(f"{len(staves)} staves in {len(systems)} systems; measures per system {per_system}")
    doubtful = sum(1 for m in measures if m.confidence != "high")
    if doubtful:
        log.append(f"{doubtful} bars flagged by geometry")
    return PageGeometry((W, H), skew, len(staves), systems, measures, log)
