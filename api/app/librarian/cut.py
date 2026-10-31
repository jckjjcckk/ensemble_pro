"""Staff-level geometry and the cut for one instrument on a full-score page. No model calls.

Ported from the piano-cut experiment (`api/experiments/grounding/piano_cut_{geometry,build,clean}.py`, report in
`out/piano-cut/REPORT.md` and `CLEAN.md`): staves as row-profile peaks, systems by the left systemic line,
system barlines by two votes (staff cover and gap crossing), a numbered overlay for the model to label, a
cleaned crop of the wanted staves (band between the neighbours, their ink erased), and the geometric verify.
Pixel thresholds assume a staff spacing of about 6-8 px (150 dpi renders of the tuned scans, or a 19th-century
scan at its native resolution); `prepare_page` masks the dark page-edge shadows of a book scan before anything
else and upscales a page whose staff spacing is under SPACING_MIN. Lyrics under a vocal staff are kept or erased
as whole text lines (`text_lines`, the `voice` / `voice_above` flags of `clean_crop`). With the score header's staff
count (`page_geometry(expected_staves=)`) a short system is searched again in column strips for the staves the
page-wide profile missed, and a hole between two found staves is filled (`recover_staves`, HARDEN.md).

This is also page reading's geometry (feature 004): `page_measures` turns `page_geometry` into the page record that
`process_pages` stores (measures with boxes as page fractions and a confidence from the geometry). The raster steps
(binarise, deskew) came from the grounding experiment's `fallback_cv.py` by way of the old `geometry.py`, which this
replaced. The systemic line is looked for at the pair's own start as well as the page median (indented first
systems), and the barline votes widen with the staff spacing on large scans (`barline_tol`).
"""
from __future__ import annotations

import io
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

KERNEL = (7, 3)   # joining dilation (w, h) for the clean pass
PAD = 3           # px around kept ink
SPECK = 4         # ink px; smaller components outside the wanted region are noise


# ---------------------------------------------------------------- raster steps (from the grounding experiment's fallback_cv.py)

def binarise(gray: np.ndarray) -> np.ndarray:
    """Otsu OR adaptive mean: grey scans print staff lines lighter than Otsu's global threshold."""
    _, otsu = cv2.threshold(gray, 0, 1, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    adaptive = cv2.adaptiveThreshold(gray, 1, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 51, 18)
    return np.maximum(otsu, adaptive).astype(np.uint8)


def estimate_skew(bw: np.ndarray) -> float:
    """The rotation (-1.5..1.5 degrees, 0.1 steps) that maximises the row-projection energy."""
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


def vertical_cover(bw: np.ndarray, x: int, y0: int, y1: int, tol: int = 1) -> float:
    """Fraction of rows y0..y1 with ink within `tol` columns of x."""
    sl = bw[y0 : y1 + 1, max(0, x - tol) : x + tol + 1]
    return float((sl.max(axis=1) > 0).mean())


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
            span = staff_extent(np.where(band.sum(axis=0) >= 3)[0], sp)
            if span and span[1] - span[0] >= w * 0.5:
                for j in idxs:
                    used[j] = True
                staves.append({"index": len(staves) + 1, "y_top": y0, "y_bottom": y1, "lines": [int(round(c)) for c in lines],
                               "spacing": (lines[-1] - lines[0]) / 4, "x0": span[0], "x1": span[1]})
                i = idxs[-1] + 1
                continue
        i += 1
    return staves


def staff_extent(cols: np.ndarray, sp: float) -> tuple[int, int] | None:
    """x0, x1 of a staff from the columns where 3 or more of its rows carry a long run: the longest group of
    such columns (groups closer than 8 spaces are one). A full-height ink strip elsewhere on the page (the grey
    gutter texture of a book scan next to the masked edge band, 110 px wide at 150 dpi, which the opening keeps on
    every row) is its own group and no longer drags x0 to the page edge, where the systemic-line search then
    finds no line and every staff becomes its own system (Beethoven 9 p172, p174, p176 at 150 dpi)."""
    if not len(cols):
        return None
    groups: list[list[int]] = [[int(cols[0]), int(cols[0])]]
    for c in cols[1:]:
        if c - groups[-1][1] <= 8 * sp:
            groups[-1][1] = int(c)
        else:
            groups.append([int(c), int(c)])
    x0, x1 = max(groups, key=lambda g: g[1] - g[0])
    return x0, x1


# ---------------------------------------------------------------- staff recovery from the header (003, HARDEN.md)

def find_staves_strips(bw: np.ndarray, y0: int, y1: int, x0: int, x1: int, sp: float, n_strips: int = 12,
                       min_votes: int = 4) -> list[dict]:
    """Relaxed staff search in rows y0..y1, columns x0..x1: the row profile per column strip (a bowed staff is
    straight within a strip), peaks at >= 0.5 of the strip width after a short opening, groups of 5 peaks at
    k * sp (+-35%) from a start peak (4 of 5 allowed, the missing line interpolated). Clusters of groups across
    strips (same line rows within 0.35 sp for >= 3 lines) with >= min_votes strips are staves."""
    if y1 - y0 < 5 * sp or x1 - x0 < n_strips * 20:
        return []
    region = bw[y0: y1 + 1, x0: x1 + 1]
    sw = region.shape[1] // n_strips
    tol = 0.35 * sp
    groups: list[tuple[int, list[float | None]]] = []
    for k in range(n_strips):
        strip = region[:, k * sw: (k + 1) * sw]
        opened = cv2.morphologyEx(strip, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (max(12, sw // 3), 1)))
        frac = opened.sum(axis=1) / strip.shape[1]
        peaks = [int(r) for r in np.where(frac >= 0.5)[0] if frac[r] >= frac[max(0, r - 2): r + 3].max()]
        peaks = [p for i, p in enumerate(peaks) if i == 0 or p - peaks[i - 1] > 2]
        used: set[int] = set()
        for want in (5, 4):
            for p0 in peaks:
                if p0 in used:
                    continue
                lines: list[float | None] = [float(p0)]
                for j in range(1, 5):
                    cand = [p for p in peaks if p not in used and abs(p - (p0 + j * sp)) <= tol]
                    lines.append(float(min(cand, key=lambda p: abs(p - (p0 + j * sp)))) if cand else None)
                if sum(l is not None for l in lines) >= want:
                    used.update(int(l) for l in lines if l is not None)
                    groups.append((k, lines))
    clusters: list[list[tuple[int, list[float | None]]]] = []
    for g in groups:
        for cl in clusters:
            ref = cl[0][1]
            if sum(1 for a, b in zip(ref, g[1]) if a is not None and b is not None and abs(a - b) <= tol) >= 3:
                cl.append(g)
                break
        else:
            clusters.append([g])
    staves: list[dict] = []
    for cl in clusters:
        strips = {k for k, _ in cl}
        if len(strips) < min_votes:
            continue
        lines = []
        for j in range(5):
            vals = [l[j] for _, l in cl if l[j] is not None]
            lines.append(float(np.median(vals)) if vals else None)
        if any(l is None for l in lines):
            known = [(j, l) for j, l in enumerate(lines) if l is not None]
            step = (known[-1][1] - known[0][1]) / (known[-1][0] - known[0][0])
            lines = [l if l is not None else known[0][1] + (j - known[0][0]) * step for j, l in enumerate(lines)]
        ly = [int(round(l)) + y0 for l in lines]
        staves.append({"y_top": ly[0], "y_bottom": ly[-1], "lines": ly, "spacing": (ly[-1] - ly[0]) / 4,
                       "x0": x0, "x1": x1, "recovered": True, "fit": f"{len(strips)}/{n_strips} strips"})
    return staves


def recover_staves(bw: np.ndarray, staves: list[dict], systems: list[list[int]], expected: int) -> tuple[list[dict], list[list[int]], list[dict]]:
    """For every system short of `expected` (the header's staff count), search its vertical extent (between the
    neighbouring systems' edge staves) in column strips for staves the page-wide profile missed, and force them
    into that system; the header count is a maximum, a cut-away system stays short when nothing is found. Then
    hole filling on every system of 3 or more staves: two consecutive staves about two staff pitches apart are a
    hole (a system's staves are evenly spaced; a cut-away system is simply shorter), searched alone at 3 of 12
    strip votes and accepted only where the pitch predicts a staff (+-0.5 pitch), header count or not (Beethoven
    9 p176 has 17 staves against the header's 16). Returns the re-indexed staves, the systems as index lists into
    them, and the recovered staves."""
    h, w = bw.shape
    sp = float(np.median([s["spacing"] for s in staves])) if staves else 7.0
    recovered: list[dict] = []
    members: list[list[dict]] = [[staves[i] for i in sysd] for sysd in systems]
    for si, ss in enumerate(members):
        if len(ss) >= expected:
            continue
        above = members[si - 1][-1]["y_bottom"] + 1.5 * sp if si > 0 else 0
        below = members[si + 1][0]["y_top"] - 1.5 * sp if si + 1 < len(members) else h - 1
        x0, x1 = int(np.median([s["x0"] for s in ss])), int(np.median([s["x1"] for s in ss]))
        for f in find_staves_strips(bw, int(above), int(below), x0, x1, sp):
            if any(abs(f["y_top"] - s["y_top"]) < 2 * sp or (f["y_top"] < s["y_bottom"] and f["y_bottom"] > s["y_top"]) for s in ss):
                continue
            if len(ss) >= expected:
                break
            ss.append(f)
            recovered.append(f)
        ss.sort(key=lambda s: s["y_top"])
    for ss in members:
        if len(ss) < 3:
            continue
        x0, x1 = int(np.median([s["x0"] for s in ss])), int(np.median([s["x1"] for s in ss]))
        pitches = sorted(b["y_top"] - a["y_top"] for a, b in zip(ss, ss[1:]))
        pitch = float(np.median(pitches[: max(1, len(pitches) // 2 + 1)]))   # the typical (small) step
        for a, b in list(zip(ss, ss[1:])):
            n_missing = int(round((b["y_top"] - a["y_top"]) / pitch)) - 1
            if n_missing < 1:
                continue
            found = find_staves_strips(bw, int(a["y_bottom"] + sp), int(b["y_top"] - sp), x0, x1, sp, min_votes=3)
            for k in range(1, n_missing + 1):
                want = a["y_top"] + k * pitch
                cand = [f for f in found if abs(f["y_top"] - want) <= 0.5 * pitch and not any(abs(f["y_top"] - s["y_top"]) < 2 * sp for s in ss)]
                if cand:
                    f = min(cand, key=lambda f: abs(f["y_top"] - want))
                    f["fit"] += " (hole)"
                    ss.append(f)
                    recovered.append(f)
        ss.sort(key=lambda s: s["y_top"])
    all_staves = sorted((s for ss in members for s in ss), key=lambda s: s["y_top"])
    for i, s in enumerate(all_staves, start=1):
        s["index"] = i
    return all_staves, [[all_staves.index(s) for s in ss] for ss in members], recovered


def group_systems(bw: np.ndarray, staves: list[dict]) -> tuple[list[list[int]], str]:
    """Consecutive staves joined by the left systemic line; fallback: split at gaps > 2.5x the median gap.
    The line is looked for at the page's median staff start and at the pair's own start: an indented first system
    (a title or "Var. 1." in the margin: Goldberg p1-2, Rach 1 two-piano p3) starts well right of the median, and
    searched only at the median it fell apart into single staves. The window grows with the staff spacing (a
    10-11 px keyboard page draws its brace and systemic line further from the staff start than a 7 px full score)."""
    systems: list[list[int]] = []
    joined_any = False
    left = int(np.median([s["x0"] for s in staves])) if staves else 0
    for i, s in enumerate(staves):
        if systems:
            a = staves[systems[-1][-1]]
            sp = max(a["spacing"], s["spacing"])
            lo, hi = int(max(8, round(sp))), int(max(15, round(2 * sp)))
            xs = set(range(max(0, left - lo), left + hi))
            own = min(a["x0"], s["x0"])
            if abs(own - left) > lo:
                xs |= set(range(max(0, own - lo), own + hi))
            if any(vertical_cover(bw, x, a["y_bottom"], s["y_top"]) >= 0.97 for x in sorted(xs)):
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


def barline_tol(spacing: float) -> int:
    """Column tolerance of the barline votes: 4 px up to a 10-11 px staff spacing, 0.4 staff space above it. A barline
    on a 150-dpi render of a large-format scan (Beethoven 9 at 3150 px, spacing 15-16 px) drifts more than 4 px over a
    two-staff span and one in nine lost its votes (p172 read 8 bars of 9; 6 px finds it). Wider is not better on a
    keyboard page: at 5 px two stems meeting across a grand staff's gap vote as a barline (Goldberg p4 at 9.75 px)."""
    return max(4, int(round(spacing / 2.5)))


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


HEADER_SPACES = 12        # header zone (clef, key, start repeat) in staff spaces from the system start
MIN_MEASURE_SPACES = 1.5  # spans narrower than this between two barlines are slivers, not bars


def measure_spans(bars: list[tuple[int, int]], x0: int, x1: int, spacing: float) -> list[dict]:
    """The bars of one system from its barline clusters: (start edge, closing edge) pairs. Clusters inside the header
    zone (HEADER_SPACES from the system start: a start repeat, thick key strokes) merge into the system start; a
    system whose last barline stops short of the staves' end gets an open last bar; slivers are dropped."""
    header = x0 + HEADER_SPACES * spacing
    in_header = [b for b in bars if b[0] <= header]
    edges = [(x0, max([x0] + [b[1] for b in in_header]))] + [b for b in bars if b[0] > header]
    open_end = edges[-1][1] < x1 - 10
    if open_end:
        edges.append((x1, x1))
    spans = []
    for k, (a, b) in enumerate(zip(edges, edges[1:])):
        if b[0] - a[1] < MIN_MEASURE_SPACES * spacing:
            continue
        spans.append({"x0": int(a[0]), "x1": int(b[1]), "inner": (int(a[1]), int(b[0])), "closing": None if (open_end and k == len(edges) - 2) else (int(b[0]), int(b[1])),
                      "header_merged": k == 0 and len(in_header) >= 2})
    return spans


def count_measures(bars: list[tuple[int, int]], x0: int, x1: int, spacing: float) -> int:
    return len(measure_spans(bars, x0, x1, spacing))


# ---------------------------------------------------------------- page-edge shadows and the working scale

SHADOW_CORE = 100     # a shadow pixel is darker than the paper by at least this much (B9 scan: paper ~230, band ~55)
SHADOW_FADE = 40      # the band's blurred rim: darker than the paper by this much
SHADOW_MIN = 8        # px: thinner dark runs at an edge are rules, frames or a staff line, not a scan shadow
SHADOW_COVER = 0.9    # fraction of the edge's columns (rows) that must carry the band: "nearly uniform"
SHADOW_FADE_MAX = 40  # px: the rim never extends further than this past the solid core
SPACING_MIN = 6.0     # px: under this staff spacing the row profile cannot hold five peaks apart (3-row smoothing, 3-px NMS)


def mask_page_edges(gray: np.ndarray) -> tuple[np.ndarray, dict]:
    """Mask of the dark scan shadows touching a page edge (a book photographed on a dark table), plus a report per
    side. A side has a shadow when the run of pixels darker than paper - SHADOW_CORE from that edge is at least
    SHADOW_MIN px in SHADOW_COVER of its columns (rows): a wide, nearly uniform dark region touching the edge is not
    notation. The masked run follows each column (slanted on a skewed page) and extends through the blurred rim
    (darker than paper - SHADOW_FADE, at most SHADOW_FADE_MAX px past the core) plus 2 px. Left in, the bands lock
    the skew estimate to 0.0 and fit five "lines" at the page's spacing: a fake first and last staff."""
    h, w = gray.shape
    paper = float(np.median(gray))
    core, fade = gray < paper - SHADOW_CORE, gray < paper - SHADOW_FADE
    mask = np.zeros((h, w), dtype=bool)
    report: dict[str, dict] = {}

    def run_from_edge(a: np.ndarray) -> np.ndarray:
        first_false = np.argmin(a, axis=0)
        return np.where(a.all(axis=0), a.shape[0], np.where(a[0], first_false, 0))

    for side in ("top", "bottom", "left", "right"):
        c, f = (core, fade) if side in ("top", "bottom") else (core.T, fade.T)
        if side in ("bottom", "right"):
            c, f = c[::-1], f[::-1]
        run = run_from_edge(c)
        cover, median = float((run >= SHADOW_MIN).mean()), float(np.median(run))
        hit = median >= SHADOW_MIN and cover >= SHADOW_COVER
        report[side] = {"median_px": round(median), "cover": round(cover, 3), "shadow": hit}
        if not hit:
            continue
        # the band is nearly uniform: a column whose dark run goes on much further is a rule or a systemic line
        # that touches the band, not the band itself
        run = np.minimum(run, int(median + SHADOW_FADE_MAX))
        ext = np.minimum(c.shape[0], np.maximum(run, np.minimum(run_from_edge(f), run + SHADOW_FADE_MAX)) + 2)
        m = np.arange(c.shape[0])[:, None] < ext[None, :]
        if side in ("bottom", "right"):
            m = m[::-1]
        if side in ("left", "right"):
            m = m.T
        mask |= m
        report[side]["masked_px"] = round(float(np.median(ext)))
    return mask, report


def staff_spacing(bw: np.ndarray) -> float | None:
    """Median gap between neighbouring staff-line candidates of the row profile (find_staves' first step)."""
    h, w = bw.shape
    opened = cv2.morphologyEx(bw, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (max(20, w // 40), 1)))
    sm = np.convolve(opened.sum(axis=1) / w, np.ones(3) / 3, mode="same")
    centres: list[int] = []
    for r in np.where(sm > 0.2)[0]:
        if sm[r] >= sm[max(0, r - 3): min(h, r + 4)].max() and (not centres or r - centres[-1] > 3):
            centres.append(int(r))
    small = [b - a for a, b in zip(centres, centres[1:]) if 4 <= b - a <= 20]
    return float(np.median(small)) if small else None


def working_scale(bw: np.ndarray) -> tuple[int, float | None]:
    """Integer upscale that brings the staff spacing to at least SPACING_MIN px (1 when it already is, or when no
    spacing can be read). The tuned scans run at 6.25-7.75 px at 150 dpi and Beethoven 9 at its native resolution
    at 7.0-7.5, so none is scaled; a 100-dpi render or a low-resolution photograph would be."""
    sp = staff_spacing(bw)
    if sp is None or sp >= SPACING_MIN:
        return 1, sp
    return int(np.ceil(SPACING_MIN / sp)), sp


def prepare_page(gray: np.ndarray) -> tuple[np.ndarray, np.ndarray, dict]:
    """Mask the page-edge shadows, pick the working scale; (gray, bw, info) at the working scale, not deskewed."""
    mask, edges = mask_page_edges(gray)
    if mask.any():
        gray = gray.copy()
        gray[mask] = int(np.median(gray[~mask])) if (~mask).any() else 255
    bw = binarise(gray)
    bw[mask] = 0
    scale, sp = working_scale(bw)
    if scale > 1:
        gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        bw = binarise(gray)
        bw[cv2.resize(mask.astype(np.uint8), None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST) > 0] = 0
    return gray, bw, {"edge_shadows": edges, "spacing_native": sp, "scale": scale}


def page_geometry(png: bytes, expected_staves: int | None = None) -> tuple[dict[str, Any], np.ndarray, Image.Image]:
    """Geometry dict (staves, systems with barlines and bar counts), the deskewed binary page, the deskewed RGB page.
    Both pages are the working page: page-edge shadows masked, upscaled when the staff spacing is under SPACING_MIN
    (geom["prepare"] says what was done; geom["image_px"] is the working size). With `expected_staves` (the score
    header's count per full system) a system short of it is searched again for the staves the page-wide profile
    missed (`recover_staves`); they carry `recovered` and `fit`, and geom lists them under `recovered` with the
    per-system counts before under `staves_before_recovery`."""
    raw = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_GRAYSCALE)
    if raw is None:
        raise ValueError("page image could not be decoded")
    gray, bw, prep = prepare_page(raw)
    prep["native_px"] = [raw.shape[1], raw.shape[0]]
    h, w = gray.shape
    skew = estimate_skew(bw)
    if abs(skew) >= 0.1:
        bw, gray = rotate(bw, skew, 0), rotate(gray, skew, 255)
    staves = find_staves(bw)
    systems_idx, method = group_systems(bw, staves) if staves else ([], "none")
    before = [len(idxs) for idxs in systems_idx]
    recovered: list[dict] = []
    if expected_staves and any(len(idxs) < expected_staves for idxs in systems_idx):
        staves, systems_idx, recovered = recover_staves(bw, staves, systems_idx, int(expected_staves))
    systems = []
    for si, idxs in enumerate(systems_idx, start=1):
        ss = [staves[i] for i in idxs]
        x0, x1 = int(np.median([s["x0"] for s in ss])), int(np.median([s["x1"] for s in ss]))
        sp = float(np.median([s["spacing"] for s in ss]))
        bars = find_system_barlines(bw, ss, x0, x1, tol=barline_tol(sp))
        pad = int(sp * 1.5)
        systems.append({"index": si, "staff_indices": [s["index"] for s in ss],
                        "box": {"x0": x0, "y0": max(0, ss[0]["y_top"] - pad), "x1": x1, "y1": min(h - 1, ss[-1]["y_bottom"] + pad)},
                        "barlines": bars, "n_measures": count_measures(bars, x0, x1, sp)})
    geom = {"image_px": [w, h], "skew_deg": round(float(skew), 2), "grouping": method, "prepare": prep,
            "staves": [{k: (round(v, 2) if isinstance(v, float) else v) for k, v in s.items()} for s in staves], "systems": systems}
    if expected_staves:
        geom.update({"expected_staves": int(expected_staves), "staves_before_recovery": before,
                     "recovered": [{"index": r["index"], "y_top": r["y_top"], "y_bottom": r["y_bottom"], "fit": r["fit"]} for r in recovered]})
    return geom, bw, Image.fromarray(gray).convert("RGB")


NARROW_SPACES = 4.0   # bars narrower than this are flagged low
WIDE_FACTOR = 2.6     # a bar this many times the page's median width usually hides a missed barline


def barline_cover(bw: np.ndarray, staves: list[dict], xa: int, xb: int) -> float:
    """Fraction of the system's staves whose five-line span a barline cluster crosses (>= 90 % of the rows inked at one
    column, a px of drift either side). A system barline crosses every staff; a stem or a broken line does not."""
    hit = 0
    for s in staves:
        band = bw[s["y_top"]: s["y_bottom"] + 1, max(0, xa - 1): xb + 2]
        if band.size and (cv2.dilate(band, np.ones((1, 3), np.uint8)).mean(axis=0) >= 0.9).any():
            hit += 1
    return hit / max(1, len(staves))


def page_measures(png: bytes, expected_staves: int | None = None) -> dict[str, Any]:
    """The page record that page reading (feature 004) stores: systems and measures with boxes as fractions 0..1 of the
    page image, a confidence and a flag per measure from the geometry, numbered top-left to bottom-right. Built on
    `page_geometry` (edge shadows masked, working scale, the header's staff count driving the staff recovery), so page
    reading and the part cut see the same staves, systems and barlines. Fractions of the working page are fractions
    of the uploaded page: the working page is the upload scaled, deskewed about its centre (corners off by a few px
    on a 0.5 degree page, fine for tapping)."""
    geom, bw, _ = page_geometry(png, expected_staves=expected_staves)
    w, h = geom["image_px"]
    staves = {s["index"]: s for s in geom["staves"]}
    systems: list[dict] = []
    measures: list[dict] = []
    n = 1
    for sysd in geom["systems"]:
        ss = [staves[i] for i in sysd["staff_indices"]]
        sp = float(np.median([s["spacing"] for s in ss]))
        b = sysd["box"]
        x0, x1 = b["x0"], b["x1"]
        covers = [barline_cover(bw, ss, xa, xb) for xa, xb in sysd["barlines"]]
        systems.append({"index": sysd["index"], "box": {"x0": round(x0 / w, 5), "y0": round(b["y0"] / h, 5), "x1": round(x1 / w, 5), "y1": round(b["y1"] / h, 5)},
                        "staves": len(ss), "staff_indices": list(sysd["staff_indices"]),
                        "recovered": sum(1 for s in ss if s.get("recovered")),
                        "barlines": [{"x0": round(xa / w, 5), "x1": round(xb / w, 5), "width_px": int(xb - xa + 1), "cover": round(c, 3)}
                                     for (xa, xb), c in zip(sysd["barlines"], covers)]})
        cover_of = {tuple(bl): c for bl, c in zip(sysd["barlines"], covers)}
        for span in measure_spans(sysd["barlines"], x0, x1, sp):
            conf, flag = "high", None
            if span["closing"] is None:
                conf, flag = "medium", "no closing barline; bar runs to the end of the staves"
            elif cover_of.get(span["closing"], 1.0) < 1.0:
                conf, flag = "medium", "closing barline does not cross every staff"
            if span["header_merged"]:
                conf, flag = "medium", "bar start merged with repeat or key strokes"
            if (span["inner"][1] - span["inner"][0]) / sp < NARROW_SPACES:
                conf, flag = "low", "very narrow bar"
            measures.append({"provisional": n, "system": sysd["index"], "confidence": conf, "flag": flag,
                             "box": {"x0": round(span["x0"] / w, 5), "y0": round(b["y0"] / h, 5), "x1": round(span["x1"] / w, 5), "y1": round(b["y1"] / h, 5)}})
            n += 1
    widths = [m["box"]["x1"] - m["box"]["x0"] for m in measures]
    if len(widths) >= 4:
        med = float(np.median(widths))
        for m, wd in zip(measures, widths):
            if wd > WIDE_FACTOR * med and m["confidence"] == "high":
                m["confidence"], m["flag"] = "medium", "unusually wide bar, a barline may have been missed"
    log: list[str] = []
    prep = geom["prepare"]
    shadows = [side for side, r in prep["edge_shadows"].items() if r.get("shadow")]
    if shadows:
        log.append(f"Masked the page-edge shadow ({', '.join(shadows)})")
    if prep["scale"] > 1:
        log.append(f"Read at {prep['scale']}x (staff spacing {prep['spacing_native']:.1f} px)")
    if abs(geom["skew_deg"]) >= 0.1:
        log.append(f"Deskewed by {geom['skew_deg']:+.1f}°")
    if geom.get("recovered"):
        log.append(f"Recovered {len(geom['recovered'])} staves the page profile missed (header: {geom['expected_staves']} per system)")
    if not geom["staves"]:
        log.append("No staff lines found")
    else:
        log.append(f"{len(geom['staves'])} staves in {len(systems)} systems; measures per system {[sum(1 for m in measures if m['system'] == s['index']) for s in systems]}")
    doubtful = sum(1 for m in measures if m["confidence"] != "high")
    if doubtful:
        log.append(f"{doubtful} bars flagged by geometry")
    native = prep.get("native_px") or [w, h]
    return {"image_px": list(native), "working_px": [w, h], "skew_deg": geom["skew_deg"], "staves": len(geom["staves"]), "grouping": geom["grouping"],
            "expected_staves": geom.get("expected_staves"), "staves_before_recovery": geom.get("staves_before_recovery"),
            "systems": systems, "measures": measures, "log": log}


def _font(size: int):
    try:
        return ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", size)
    except Exception:  # noqa: BLE001
        return ImageFont.load_default()


def overlay_png(page: Image.Image, geom: dict) -> bytes:
    """The page with every staff boxed in blue (recovered ones orange) and tagged with its number, systems in grey."""
    im = page.convert("RGB").copy()
    d = ImageDraw.Draw(im, "RGBA")
    font = _font(26)
    for s in geom["systems"]:
        b = s["box"]
        d.rectangle([b["x0"], b["y0"], b["x1"], b["y1"]], outline=(120, 120, 120, 255), width=2)
    for st in geom["staves"]:
        pad = int(st["spacing"] * 1.2)
        colour = (235, 110, 0, 255) if st.get("recovered") else (0, 110, 220, 255)
        d.rectangle([st["x0"], st["y_top"] - pad, st["x1"], st["y_bottom"] + pad], outline=colour, width=2)
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


TEXT_H = (0.5, 2.6)   # word height in staff spaces (x-height ~1, ascenders and descenders to ~2.5)
TEXT_W_MAX = 20.0     # spaces; a longer component is a hairpin or a slur
TEXT_FILL_MIN = 0.15  # ink / bbox: letters 0.3-0.5, a hairpin or slur under 0.1
TEXT_GAP_MAX = 30.0   # spaces between two words of one line: lyric syllables sit a bar or more apart
TEXT_MIN_MEMBERS = 2
TEXT_PIECE_W_MIN = 1.0  # spaces: a piece carved out of a neighbour component on the lyric rows is at least a short word wide


def text_lines(comps: list[dict], sp: float) -> list[list[dict]]:
    """Text lines among the components: word-sized ones (TEXT_H, TEXT_W_MAX, TEXT_FILL_MIN) chained left to right
    when their rows overlap the line's rows by half the smaller height and the gap is under TEXT_GAP_MAX; a line
    needs TEXT_MIN_MEMBERS words; the flat marks between its first and last word (hyphens, extender lines, dots)
    join it."""
    words = [c for c in comps if TEXT_H[0] * sp <= c["y1"] - c["y0"] + 1 <= TEXT_H[1] * sp and c["x1"] - c["x0"] + 1 <= TEXT_W_MAX * sp
             and c["area"] / float((c["x1"] - c["x0"] + 1) * (c["y1"] - c["y0"] + 1)) >= TEXT_FILL_MIN]
    lines: list[list[dict]] = []
    for c in sorted(words, key=lambda c: c["x0"]):
        for line in lines:
            last = line[-1]
            ly0, ly1 = min(m["y0"] for m in line), max(m["y1"] for m in line)
            overlap = min(c["y1"], ly1) - max(c["y0"], ly0) + 1
            if overlap >= 0.5 * min(c["y1"] - c["y0"] + 1, ly1 - ly0 + 1) and c["x0"] - last["x1"] <= TEXT_GAP_MAX * sp and c["x0"] > last["x0"]:
                line.append(c)
                break
        else:
            lines.append([c])
    lines = [line for line in lines if len(line) >= TEXT_MIN_MEMBERS]
    taken = {c["label"] for line in lines for c in line}
    for line in lines:
        ly0, ly1 = min(m["y0"] for m in line) - 0.3 * sp, max(m["y1"] for m in line) + 0.3 * sp
        lx0, lx1 = line[0]["x0"], line[-1]["x1"]
        for c in comps:
            if c["label"] in taken or c["y1"] - c["y0"] + 1 >= TEXT_H[0] * sp:
                continue
            if c["y0"] >= ly0 and c["y1"] <= ly1 and c["x0"] >= lx0 and c["x1"] <= lx1:
                line.append(c)
                taken.add(c["label"])
    return lines


def clean_crop(bw: np.ndarray, page: Image.Image, geom: dict, system: dict, wanted: list[int], *,
               voice: bool = False, voice_above: bool = False) -> tuple[Image.Image, dict, dict]:
    """The wanted staves cut from the band between their neighbours, the neighbours' ink erased, fitted to the kept ink.
    Returns (crop, box in page px, stats). See CLEAN.md for the classes and the nearest-ink rule.

    voice: the target is a vocal staff: the band from its bottom line to the midpoint of the gap below is its own,
    a text line (text_lines) with a word there is kept whole ("lyric"), a text line under the staff with no word
    there lies in the lower half, the staff below's, and is erased whole ("lyric-neighbour"). voice_above: the
    staff above is vocal: a text line with a word in the upper half of the gap above is its lyrics, erased whole."""
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

    # lyrics under a vocal staff (feature 008): text lines decided by the band they sit in, never by nearest ink
    lyric_lines: list[dict] = []
    if voice or voice_above:
        nxt_top = (nxt["y_top"] - band_top) if nxt else H - 1
        own_lo, own_hi = bot_line + 0.3 * sp, (bot_line + nxt_top) / 2.0
        prev_bot = (prev["y_bottom"] - band_top) if prev else 0
        above_lo, above_hi = prev_bot + 0.3 * sp, (prev_bot + top_line) / 2.0
        for line in text_lines(comps, sp):
            words = [c for c in line if c["y1"] - c["y0"] + 1 >= TEXT_H[0] * sp]
            centres = [(c["y0"] + c["y1"]) / 2.0 for c in words]
            below = all(c["y0"] > bot_line for c in words)
            above = all(c["y1"] < top_line for c in words)
            if voice and below and any(own_lo <= y <= own_hi for y in centres):
                cls = "lyric"
            elif voice and below and nxt is not None and all(y > own_hi for y in centres):
                cls = "lyric-neighbour"
            elif voice_above and above and any(above_lo <= y <= above_hi for y in centres):
                cls = "lyric-neighbour"
            else:
                continue
            n = 0
            for c in line:
                if c["cls"] in ("piano", "both") and cls == "lyric-neighbour":
                    continue
                if (c["y1"] >= H - 2 and nxt is not None) or (c["y0"] <= 1 and prev is not None):
                    continue
                c["cls"] = cls
                n += 1
            lyric_lines.append({"class": cls, "words": len(words), "members": n,
                                "x": [int(line[0]["x0"]), int(max(c["x1"] for c in line))],
                                "rows": [int(min(c["y0"] for c in line)), int(max(c["y1"] for c in line))],
                                "baseline": int(np.median([c["y1"] for c in words]))})
    # a word of a kept lyric line glued to the neighbour's ink (a scratch or hairline running from the word down
    # to the staff below makes the joined component "neighbour"): the component's ink on the line's rows, from its
    # tallest ascender to its baseline, is re-labelled with a 3x3 kernel and a word-sized piece there is kept
    lyric_keep = np.zeros_like(ink)
    lyric_pieces: list[dict] = []
    for ll in [l for l in lyric_lines if l["class"] == "lyric"]:
        ly0, ly1 = int(ll["rows"][0] - 0.3 * sp), int(ll["baseline"] + 0.15 * sp)
        for c in comps:
            if c["cls"] not in ("neighbour", "gap") or c["y1"] < ly0 or c["y0"] > ly1 or (c["y0"] >= ly0 and c["y1"] <= ly1):
                continue
            m = (labels == c["label"]) & ink
            band_m = np.zeros_like(m)
            band_m[max(0, ly0): ly1 + 1] = m[max(0, ly0): ly1 + 1]
            core = band_m.astype(np.uint8)
            pn, pl, _, _ = cv2.connectedComponentsWithStats(cv2.dilate(core, np.ones((3, 3), np.uint8)), connectivity=8)
            for q in range(1, pn):
                ys_, xs_ = np.where((pl == q) & (core > 0))
                if len(ys_) < SPECK:
                    continue
                ph, pw = int(ys_.max() - ys_.min() + 1), int(xs_.max() - xs_.min() + 1)
                if TEXT_H[0] * sp <= ph <= TEXT_H[1] * sp and TEXT_PIECE_W_MIN * sp <= pw <= TEXT_W_MAX * sp and len(ys_) / float(ph * pw) >= TEXT_FILL_MIN:
                    py0, py1, px0, px1 = int(ys_.min()), int(ys_.max()), int(xs_.min()), int(xs_.max())
                    keep = np.zeros_like(band_m)
                    keep[max(0, py0 - 1): py1 + 2, max(0, px0 - 1): px1 + 2] = band_m[max(0, py0 - 1): py1 + 2, max(0, px0 - 1): px1 + 2]
                    lyric_keep |= keep
                    lyric_pieces.append({"bbox": [px0, py0, px1, py1], "area": int(keep.sum()), "of": c["cls"]})

    piano_ink = np.zeros_like(ink)
    neigh_ink = np.zeros_like(ink)
    for c in comps:
        m = (labels == c["label"]) & ink
        if c["cls"] in ("piano", "both", "lyric"):
            piano_ink |= m
        elif c["cls"] in ("neighbour", "lyric-neighbour"):
            neigh_ink |= m
    piano_ink |= lyric_keep
    neigh_ink &= ~lyric_keep
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
        if c["cls"] in ("neighbour", "lyric-neighbour", "gap->neighbour", "speck"):
            erase |= labels == c["label"]
    erase &= ~lyric_keep
    erase = cv2.dilate(erase.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)
    erase &= ~lyric_keep
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
                 "erased": counts.get("neighbour", 0) + counts.get("lyric-neighbour", 0) + counts.get("gap->neighbour", 0) + counts.get("speck", 0),
                 "kept": counts.get("piano", 0) + counts.get("both", 0) + counts.get("gap->piano", 0) + counts.get("lyric", 0),
                 "voice": voice, "voice_above": voice_above, "lyric_lines": lyric_lines, "lyric_pieces": lyric_pieces,
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
    tol = max(1, int(round(sp / 8)))   # a barline drifts a px or two over a staff on a 150-dpi render of a scan (B9: 0.83 cover at 1 px, 1.0 at 2)
    # A bowed scan's staff sags or rises across the page (PC3 p2: 8 px lower at the right end than the row profile puts
    # it), so the staff's own height is looked for up to a staff space above or below its measured place at each
    # barline. The band keeps the staff's height: a missing barline still fails, a stem never spans four spaces.
    shifts = sorted(range(-int(round(sp)), int(round(sp)) + 1), key=abs)
    for bx0, bx1 in system["barlines"]:
        cols = range(max(0, bx0 - 4 - ox), min(cbw.shape[1], bx1 + 5 - ox))
        present.append(any(vertical_cover(cbw, x, ya + d, yb + d, tol=tol) >= 0.9
                           for d in shifts if ya + d >= 0 and yb + d < cbw.shape[0] for x in cols))
    return {"staves_in_crop": {"value": inside, "expect": sorted(wanted), "pass": sorted(inside) == sorted(wanted)},
            "brace_or_bracket": {"value": brace, "pass": brace, "informational": True},
            "barlines_present": {"present": present, "missing": [bl for bl, ok in zip(system["barlines"], present) if not ok], "pass": all(present)},
            "bar_count": {"value": system["n_measures"], "pass": True, "informational": True}}


def cut_system(bw: np.ndarray, page: Image.Image, geom: dict, system: dict, wanted: list[int], *,
               voice: bool = False, voice_above: bool = False) -> tuple[Image.Image, dict, dict]:
    """Clean crop, or the plain crop when the clean pass cannot run on this page. Returns (crop, box, verify+stats).
    voice / voice_above: the target / the staff above it is a vocal staff (header family voice), for the lyric rule."""
    try:
        crop, box, stats = clean_crop(bw, page, geom, system, wanted, voice=voice, voice_above=voice_above)
        mode = "clean"
    except Exception as e:  # noqa: BLE001  (the clean pass is tuned on one scan; never lose the cut over it)
        box = plain_box(geom, system, wanted)
        crop = page.crop((box["x0"], box["y0"], box["x1"] + 1, box["y1"] + 1))
        stats, mode = {"error": f"{type(e).__name__}: {e}"}, "plain"
    checks = verify(crop, geom, system, wanted, box)
    checks["pass"] = all(c["pass"] for c in checks.values() if isinstance(c, dict) and not c.get("informational"))
    return crop, box, {"mode": mode, "clean": stats, **checks}
