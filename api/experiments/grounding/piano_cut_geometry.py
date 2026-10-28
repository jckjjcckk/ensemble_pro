# /// script
# requires-python = ">=3.12"
# dependencies = ["opencv-python-headless", "numpy", "pillow", "pymupdf"]
# ///
"""Piano-cut experiment, step 1: geometry on orchestral full-score pages.

Rasterises the chosen pages of the Rachmaninoff 1 Gutheil full score at 150 dpi greyscale, finds every staff,
groups staves into systems, finds the barlines that cross the whole system, and draws a numbered overlay
(one box per staff, index at the left margin) for Spark to label.

Usage (from api/):  uv run experiments/grounding/piano_cut_geometry.py [--score <pdf stem>] [page_number ...]
Score: `--score` or PIANO_CUT_SCORE (see common.py); default Rach 1 writes to out/piano-cut/, any other score
to out/piano-cut/<stem>/.
Writes out/piano-cut/pages/p<NN>.png, out/piano-cut/geom-p<NN>.json, out/piano-cut/overlay-p<NN>.png

Changes from fallback_cv.py for orchestral pages
  - Staff detection: the row-darkness threshold is relative to the staff's own width, not the page width, and
    staves narrower than half the page (cut-away pages have none, but headers do) are dropped.
  - Systems: consecutive staves are in one system when the left systemic line (a vertical dark run near the
    left end of the staves) crosses the gap between them. fallback_cv gated this on a small gap and tested a
    barline crossing, which fails on orchestral pages (barlines are broken between instrument groups, the gap
    above the piano is large). Fallback when no systemic line is found anywhere: split at gaps larger than
    2.5x the median staff gap.
  - Barlines: a column is a system barline when its dilated vertical run covers >= 90% of each staff's own
    five-line span for at least 80% of the staves in the system (stems never cross 15 staves). The grand-staff
    notion is dropped.
  - Staff recovery from the score header (header.json, score_header.py): when a system has fewer staves than
    the header's total, the system's vertical extent is searched again in column strips. A bowed Breitkopf
    staff smears each line over 6-8 rows across the page width, so the page-wide row profile has no peaks at
    the staff spacing, but within a ~110 px strip the lines are straight. Each strip votes for 5 (or 4 of 5)
    peaks at the known spacing; a staff is accepted when enough strips agree, its lines are the medians, and
    it is forced into the short system. Recovered staves are marked "recovered" in the json and drawn orange.
    Hole filling (2026-10-28): two consecutive staves about two pitches apart are a hole; the hole alone is
    searched at 3 votes and a staff accepted where the pitch predicts one, header count or not (B9 p176 has
    17 staves against the header's 16).
  - Page preparation (2026-10-28, the Beethoven 9 choir defects): the render is at the scan's native resolution
    when the page is one embedded raster below 150 dpi (render_dpi); the dark page-edge shadows of the book
    scan are masked before anything else (mask_page_edges: left in, they lock the skew estimate to 0.0 and fit
    five "lines" each, a fake first and last staff); the page is upscaled when the staff spacing is under
    SPACING_MIN (working_scale). pages/p<NN>.png is rewritten as the working page when either applies, so every
    later step reads the same frame; the geom json carries "prepare".
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from common import PIANO_CUT_OUT, PIANO_CUT_PDF, dump
from fallback_cv import binarise, estimate_skew, rotate, vertical_cover

PDF = PIANO_CUT_PDF
PC = PIANO_CUT_OUT
PAGES_DIR = PC / "pages"
DEFAULT_PAGES = [1, 2, 7, 15, 16, 43]


RENDER_DPI = 150


def render_dpi(page) -> int:
    """150 dpi, unless the page is one embedded raster scan smaller than that: then its own resolution (rounded,
    pymupdf takes an int), so the render invents no pixels (Beethoven 9: a 1513x1920 scan on a 1513x1920 pt page
    renders 3153x4000 at 150 dpi, every pixel interpolated). The geometry decides afterwards whether to work at a
    larger scale (working_scale)."""
    images = page.get_images()
    if len(images) == 1:
        iw, ih = images[0][2], images[0][3]
        native = 72.0 * max(iw / page.rect.width, ih / page.rect.height)
        if native < RENDER_DPI:
            return int(round(native))
    return RENDER_DPI


def rasterise(n: int) -> Path:
    out = PAGES_DIR / f"p{n:02d}.png"
    if out.exists():
        return out
    import pymupdf

    PAGES_DIR.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open(PDF)
    pix = doc[n - 1].get_pixmap(dpi=render_dpi(doc[n - 1]), colorspace=pymupdf.csGRAY)
    Image.frombytes("L", (pix.width, pix.height), pix.samples).save(out)
    return out


# ---------------------------------------------------------------- page-edge shadows and the working scale

SHADOW_CORE = 100   # a shadow pixel is darker than the paper by at least this much (B9 scan: paper ~230, band ~55)
SHADOW_FADE = 40    # the band's blurred rim: darker than the paper by this much (B9: 95-155 over ~12 rows at native)
SHADOW_MIN = 8      # px: thinner dark runs at an edge are rules, frames or a staff line, not a scan shadow
SHADOW_COVER = 0.9  # fraction of the edge's columns (rows) that must carry the band: "nearly uniform"
SHADOW_FADE_MAX = 40  # px: the rim never extends further than this past the solid core
SPACING_MIN = 6.0   # px: under this staff spacing the row profile cannot hold five peaks apart (3-row smoothing, 3-px NMS)


def mask_page_edges(gray: np.ndarray) -> tuple[np.ndarray, dict]:
    """Boolean mask of the dark scan shadows that touch a page edge (the book's edge and gutter in a 19th-century
    scan photographed on a dark table), plus a report per side.

    A side has a shadow when, from that edge inwards, the run of pixels darker than paper - SHADOW_CORE is at
    least SHADOW_MIN px in at least SHADOW_COVER of the columns (rows for the left and right sides): a wide,
    nearly uniform dark region touching the edge is not notation. The masked run follows each column (the band's
    inner edge is slanted on a skewed page) and extends through the blurred rim (darker than paper - SHADOW_FADE,
    at most SHADOW_FADE_MAX px past the core) plus 2 px, so the gradient leaves no row-profile peaks behind. A
    printed rule or frame is thinner than SHADOW_MIN; a staff never reaches the edge in SHADOW_COVER of the
    columns."""
    h, w = gray.shape
    paper = float(np.median(gray))
    core = gray < paper - SHADOW_CORE
    fade = gray < paper - SHADOW_FADE
    mask = np.zeros((h, w), dtype=bool)
    report: dict[str, dict] = {}

    def run_from_edge(a: np.ndarray) -> np.ndarray:
        """Per column of a (rows from the edge inwards): length of the True run starting at row 0."""
        first_false = np.argmin(a, axis=0)  # 0 when a[0] is False or the whole column is True
        return np.where(a.all(axis=0), a.shape[0], np.where(a[0], first_false, 0))

    for side in ("top", "bottom", "left", "right"):
        c, f = (core, fade) if side in ("top", "bottom") else (core.T, fade.T)
        if side in ("bottom", "right"):
            c, f = c[::-1], f[::-1]
        run = run_from_edge(c)
        cover = float((run >= SHADOW_MIN).mean())
        median = float(np.median(run))
        hit = median >= SHADOW_MIN and cover >= SHADOW_COVER
        report[side] = {"median_px": round(median), "cover": round(cover, 3), "shadow": hit}
        if not hit:
            continue
        # the band is nearly uniform: a column whose dark run goes on much further is a rule or a systemic line
        # that touches the band, not the band itself
        run = np.minimum(run, int(median + SHADOW_FADE_MAX))
        ext = np.minimum(run_from_edge(f), run + SHADOW_FADE_MAX)
        ext = np.minimum(c.shape[0], np.maximum(run, ext) + 2)
        m = np.arange(c.shape[0])[:, None] < ext[None, :]
        if side in ("bottom", "right"):
            m = m[::-1]
        if side in ("left", "right"):
            m = m.T
        mask |= m
        report[side]["masked_px"] = round(float(np.median(ext)))
    return mask, report


def staff_spacing(bw: np.ndarray) -> float | None:
    """Median gap between neighbouring staff-line candidates of the row profile (find_staves' first step), or None."""
    h, w = bw.shape
    opened = cv2.morphologyEx(bw, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (max(20, w // 40), 1)))
    sm = np.convolve(opened.sum(axis=1) / w, np.ones(3) / 3, mode="same")
    centres: list[int] = []
    for r in np.where(sm > 0.2)[0]:
        if sm[r] >= sm[max(0, r - 3) : min(h, r + 4)].max() and (not centres or r - centres[-1] > 3):
            centres.append(int(r))
    small = [b - a for a, b in zip(centres, centres[1:]) if 4 <= b - a <= 20]
    return float(np.median(small)) if small else None


def working_scale(bw: np.ndarray) -> tuple[int, float | None]:
    """Integer upscale that brings the staff spacing to at least SPACING_MIN px (1 when it already is, or when no
    spacing can be read). The detector's row profile (3-row smoothing, 3-px non-maximum suppression, gaps 4..20)
    holds five peaks apart down to ~6 px; the tuned scans run at 6.25-7.75 px (150 dpi), Beethoven 9 at its native
    resolution at 7.0-7.5, so none of them is scaled. A 100-dpi render of a large-format score or a low-resolution
    photograph would be."""
    sp = staff_spacing(bw)
    if sp is None or sp >= SPACING_MIN:
        return 1, sp
    return int(np.ceil(SPACING_MIN / sp)), sp


def prepare_page(gray: np.ndarray) -> tuple[np.ndarray, np.ndarray, dict]:
    """Mask the page-edge shadows, pick the working scale, return (gray, bw, info) at the working scale. The
    shadows are masked before anything else: left in, their row-projection energy locks the skew estimate to 0.0
    (B9 p172 native: 10 of 16 staves) and their rows fit five 'lines' at the page's spacing (a fake first and
    last staff on every B9 page, header 18 instead of 16)."""
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
    info = {"edge_shadows": edges, "spacing_native": sp, "scale": scale, "spacing_min": SPACING_MIN}
    return gray, bw, info


def find_staves(bw: np.ndarray) -> list[dict]:
    """Staves as dicts: y_top, y_bottom, lines, spacing, x0, x1.

    Local maxima of the long-run dark fraction per row (> 0.2 of the page width) are line candidates (a locally
    warped staff smears each line over several rows; a long slur adds a spurious row). The global line spacing is the median of the small gaps, and a staff is five candidates sitting at
    k * spacing (+-30%) from a start line, skipping any extra candidate in between. A staff must be at least
    half the page wide, so title text and header rules do not count."""
    h, w = bw.shape
    opened = cv2.morphologyEx(bw, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (max(20, w // 40), 1)))
    frac = opened.sum(axis=1) / w
    # line candidates: local maxima of the row profile (radius 3) above 0.2. A run-merge would fuse the lines
    # of a locally warped staff (p. 1 timpani: each line smeared over 6 rows, adjacent runs touching).
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
    staves = []
    i = 0
    while i < len(centres):
        if used[i]:
            i += 1
            continue
        lines = [centres[i]]
        idxs = [i]
        for k in range(1, 5):
            # anchor on the first line, step by the spacing observed so far (staves vary 7.0-7.5 px here)
            step = sp if k == 1 else (sp + (lines[-1] - lines[0]) / (k - 1)) / 2
            target = lines[0] + k * step
            cand = [(abs(centres[j] - target), j) for j in range(i + 1, len(centres))
                    if not used[j] and abs(centres[j] - target) <= 0.4 * sp]
            if not cand:
                break
            _, j = min(cand)
            lines.append(centres[j])
            idxs.append(j)
        if len(lines) == 5:
            y0, y1 = int(round(lines[0])), int(round(lines[-1]))
            # horizontal extent: columns where at least 3 of the staff's rows carry a long run, so a label or a
            # stray run on one row does not drag x0 into the margin, and a line that drifts a row or two on a
            # warped scan still counts
            band = opened[max(0, y0 - 2) : y1 + 3]
            cols = np.where(band.sum(axis=0) >= 3)[0]
            if len(cols) == 0:
                i += 1
                continue
            x0, x1 = int(cols.min()), int(cols.max())
            if x1 - x0 >= w * 0.5:
                for j in idxs:
                    used[j] = True
                staves.append({"y_top": y0, "y_bottom": y1, "lines": [int(round(c)) for c in lines],
                               "spacing": (lines[-1] - lines[0]) / 4, "x0": x0, "x1": x1})
                i = idxs[-1] + 1
                continue
        i += 1
    return staves


def find_staves_strips(bw: np.ndarray, y0: int, y1: int, x0: int, x1: int, sp: float, n_strips: int = 12,
                       min_votes: int = 4) -> list[dict]:
    """Relaxed staff search in rows y0..y1, columns x0..x1: the row profile per column strip (a bowed staff is
    straight within a strip), peaks at >= 0.5 of the strip width after a short opening, groups of 5 peaks at
    k * sp (+-35%) from a start peak (4 of 5 allowed, the missing line interpolated). Clusters of groups across
    strips (same line rows within 0.35 sp for >= 3 lines) with >= min_votes strips are staves."""
    if y1 - y0 < 5 * sp or x1 - x0 < n_strips * 20:
        return []
    region = bw[y0 : y1 + 1, x0 : x1 + 1]
    sw = region.shape[1] // n_strips
    tol = 0.35 * sp
    groups: list[tuple[int, list[float | None]]] = []  # (strip, lines)
    for k in range(n_strips):
        strip = region[:, k * sw : (k + 1) * sw]
        opened = cv2.morphologyEx(strip, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (max(12, sw // 3), 1)))
        frac = opened.sum(axis=1) / strip.shape[1]
        peaks = [int(r) for r in np.where(frac >= 0.5)[0] if frac[r] >= frac[max(0, r - 2) : r + 3].max()]
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
    staves: list[dict] = []
    clusters: list[list[tuple[int, list[float | None]]]] = []
    for g in groups:
        for cl in clusters:
            ref = cl[0][1]
            same = sum(1 for a, b in zip(ref, g[1]) if a is not None and b is not None and abs(a - b) <= tol)
            if same >= 3:
                cl.append(g)
                break
        else:
            clusters.append([g])
    for cl in clusters:
        strips = {k for k, _ in cl}
        if len(strips) < min_votes:
            continue
        lines = []
        for j in range(5):
            vals = [l[j] for _, l in cl if l[j] is not None]
            lines.append(float(np.median(vals)) if vals else None)
        if any(l is None for l in lines):  # interpolate the missing line from the found ones
            known = [(j, l) for j, l in enumerate(lines) if l is not None]
            step = (known[-1][1] - known[0][1]) / (known[-1][0] - known[0][0])
            lines = [l if l is not None else known[0][1] + (j - known[0][0]) * step for j, l in enumerate(lines)]
        ly = [int(round(l)) + y0 for l in lines]
        staves.append({"y_top": ly[0], "y_bottom": ly[-1], "lines": ly, "spacing": (ly[-1] - ly[0]) / 4,
                       "x0": x0, "x1": x1, "recovered": True, "fit": f"{len(strips)}/{n_strips} strips"})
    return staves


def expected_staves() -> int | None:
    path = PC / "header.json"
    if not path.exists():
        return None
    try:
        return int(json.loads(path.read_text()).get("expected_staves") or 0) or None
    except (ValueError, TypeError):
        return None


def recover_staves(bw: np.ndarray, staves: list[dict], systems: list[list[int]], expected: int) -> tuple[list[dict], list[list[int]], list[dict]]:
    """For every system short of `expected`, search its vertical extent (between the neighbouring systems' edge
    staves) for staves the page-wide profile missed, and force them into that system. Returns the re-sorted
    staves, the systems as index lists into them, and the recovered staves."""
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
        found = find_staves_strips(bw, int(above), int(below), x0, x1, sp)
        for f in found:
            if any(abs(f["y_top"] - s["y_top"]) < 2 * sp or (f["y_top"] < s["y_bottom"] and f["y_bottom"] > s["y_top"]) for s in ss):
                continue
            if len(ss) >= expected:
                break
            ss.append(f)
            recovered.append(f)
        ss.sort(key=lambda s: s["y_top"])
    # hole filling, every system of 3 or more staves: two consecutive staves about two staff pitches apart (the
    # staves of a system are evenly spaced; a cut-away system is simply shorter, with no hole). The hole alone is
    # searched with a lower vote threshold and a staff accepted only where the pitch predicts one (+-0.5 pitch).
    # The header count does not cap this: a hole with strip evidence is a staff, header or not (Beethoven 9 p176
    # has 17 staves, Violoncello and Contrabbasso apart, against the 16 of p172; p173 at native resolution: 1-px
    # lines, 3 of 12 strips see the Viola staff).
    for ss in members:
        if len(ss) < 3:
            continue
        x0, x1 = int(np.median([s["x0"] for s in ss])), int(np.median([s["x1"] for s in ss]))
        pitches = sorted(b["y_top"] - a["y_top"] for a, b in zip(ss, ss[1:]))
        pitch = float(np.median(pitches[: max(1, len(pitches) // 2 + 1)]))  # the typical (small) step
        for a, b in list(zip(ss, ss[1:])):
            gap = b["y_top"] - a["y_top"]
            n_missing = int(round(gap / pitch)) - 1
            if n_missing < 1:
                continue
            found = find_staves_strips(bw, int(a["y_bottom"] + sp), int(b["y_top"] - sp), x0, x1, sp, min_votes=3)
            for k in range(1, n_missing + 1):
                want = a["y_top"] + k * pitch
                cand = [f for f in found if abs(f["y_top"] - want) <= 0.5 * pitch
                        and not any(abs(f["y_top"] - s["y_top"]) < 2 * sp for s in ss)]
                if cand:
                    f = min(cand, key=lambda f: abs(f["y_top"] - want))
                    f["fit"] += " (hole)"
                    ss.append(f)
                    recovered.append(f)
        ss.sort(key=lambda s: s["y_top"])
    all_staves = sorted((s for ss in members for s in ss), key=lambda s: s["y_top"])
    for i, s in enumerate(all_staves, start=1):
        s["index"] = i
    new_systems = [[all_staves.index(s) for s in ss] for ss in members]
    return all_staves, new_systems, recovered


def systemic_line_joins(bw: np.ndarray, a: dict, b: dict, left: int) -> bool:
    """True when a vertical dark run near the left end of the staves crosses the whole gap between a and b."""
    xa, xb = max(0, left - 8), left + 14
    return any(vertical_cover(bw, x, a["y_bottom"], b["y_top"]) >= 0.97 for x in range(xa, xb + 1))


def group_systems(bw: np.ndarray, staves: list[dict]) -> tuple[list[list[int]], str]:
    systems: list[list[int]] = []
    joined_any = False
    left = int(np.median([s["x0"] for s in staves])) if staves else 0
    for i, s in enumerate(staves):
        if systems and systemic_line_joins(bw, staves[systems[-1][-1]], s, left):
            systems[-1].append(i)
            joined_any = True
        else:
            systems.append([i])
    if joined_any or len(staves) < 2:
        return systems, "systemic-line"
    # fallback: split at gaps much larger than the median staff gap
    gaps = [staves[i + 1]["y_top"] - staves[i]["y_bottom"] for i in range(len(staves) - 1)]
    med = float(np.median(gaps))
    systems = [[0]]
    for i, g in enumerate(gaps):
        if g > 2.5 * med:
            systems.append([i + 1])
        else:
            systems[-1].append(i + 1)
    return systems, "gap-fallback"


def find_system_barlines(bw: np.ndarray, staves: list[dict], x0: int, x1: int, min_cover: float = 0.9,
                         tol: int = 4) -> list[tuple[int, int]]:
    """System barlines: columns whose dark run (within +-tol px, the scan's barlines drift a few px over the
    page height) covers each staff's five-line span for >= 60% of the staves AND crosses the gap between
    adjacent staves for >= 30% of the adjacent pairs. Stems aligned across every staff (a tutti chord) pass the
    first test and fail the second; barlines broken between instrument groups pass both."""
    kernel = np.ones((1, 2 * tol + 1), np.uint8)
    staff_votes = np.zeros(x1 - x0 + 1, dtype=int)
    for s in staves:
        band = cv2.dilate(bw[s["y_top"] : s["y_bottom"] + 1, x0 : x1 + 1], kernel)
        staff_votes += (band.mean(axis=0) >= min_cover).astype(int)
    pair_votes = np.zeros(x1 - x0 + 1, dtype=int)
    for a, b in zip(staves, staves[1:]):
        band = cv2.dilate(bw[a["y_top"] : b["y_bottom"] + 1, x0 : x1 + 1], kernel)
        pair_votes += (band.mean(axis=0) >= min_cover).astype(int)
    ok = staff_votes >= max(1, int(np.ceil(0.6 * len(staves))))
    if len(staves) > 1:
        ok &= pair_votes >= max(1, int(np.ceil(0.3 * (len(staves) - 1))))
    xs = np.where(ok)[0] + x0
    clusters: list[list[int]] = []
    for x in xs:
        if clusters and x - clusters[-1][-1] <= 14:
            clusters[-1].append(int(x))
        else:
            clusters.append([int(x)])
    # a real barline passes the +-tol window for >= 2*tol columns; a one-column cluster is a marginal stem
    return [(c[0], c[-1]) for c in clusters if c[-1] - c[0] + 1 >= tol + 1]


def count_measures(bars: list[tuple[int, int]], x0: int, x1: int, spacing: float) -> int:
    """Measures between consecutive barlines, with the header zone merged into the system start (as fallback_cv)."""
    header = x0 + 12 * spacing
    edges = [b for b in bars if b[0] > header]
    edges = [(x0, max([x0] + [b[1] for b in bars if b[0] <= header]))] + edges
    if edges[-1][1] < x1 - 10:
        edges = edges + [(x1, x1)]
    return sum(1 for a, b in zip(edges, edges[1:]) if b[0] - a[1] >= 1.5 * spacing)


def overlay(page_png: Path, geom: dict, out_png: Path) -> None:
    im = Image.open(page_png).convert("RGB")
    d = ImageDraw.Draw(im, "RGBA")
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 26)
    except Exception:
        font = ImageFont.load_default()
    for sysd in geom["systems"]:
        b = sysd["box"]
        d.rectangle([b["x0"], b["y0"], b["x1"], b["y1"]], outline=(120, 120, 120, 255), width=2)
    for st in geom["staves"]:
        pad = int(st["spacing"] * 1.2)
        colour = (235, 110, 0, 255) if st.get("recovered") else (0, 110, 220, 255)
        d.rectangle([st["x0"], st["y_top"] - pad, st["x1"], st["y_bottom"] + pad], outline=colour, width=2)
        # number tag just inside the left end of the staff
        tx = st["x0"] + 4
        ty = st["y_top"] - pad - 2
        d.rectangle([tx, ty, tx + 46, ty + 30], fill=(255, 235, 60, 230), outline=(0, 0, 0, 255))
        d.text((tx + 6, ty + 1), str(st["index"]), fill=(0, 0, 0, 255), font=font)
    im.save(out_png)


def run_page(n: int) -> dict:
    png = rasterise(n)
    raw = cv2.imread(str(png), cv2.IMREAD_GRAYSCALE)
    gray, bw, prep = prepare_page(raw)
    if gray.shape != raw.shape or any(e.get("shadow") for e in prep["edge_shadows"].values()):
        # every later step (labels, build, clean) reads pages/p<NN>.png: it must be the working page, shadows
        # masked and at the working scale. Re-running on it is a no-op (no shadow left, spacing in range).
        prep["native_px"] = [raw.shape[1], raw.shape[0]]
        Image.fromarray(gray).save(png)
    h, w = gray.shape
    skew = estimate_skew(bw)
    if abs(skew) >= 0.1:
        bw = rotate(bw, skew, 0)
    staves = find_staves(bw)
    for i, s in enumerate(staves, start=1):
        s["index"] = i
    systems, method = group_systems(bw, staves)
    expected = expected_staves()
    before = [len(sysd) for sysd in systems]
    recovered: list[dict] = []
    if expected and any(len(sysd) < expected for sysd in systems):
        staves, systems, recovered = recover_staves(bw, staves, systems, expected)
    out_systems = []
    for si, idxs in enumerate(systems, start=1):
        ss = [staves[i] for i in idxs]
        x0, x1 = int(np.median([s["x0"] for s in ss])), int(np.median([s["x1"] for s in ss]))
        y_top, y_bot = ss[0]["y_top"], ss[-1]["y_bottom"]
        bars = find_system_barlines(bw, ss, x0, x1)
        sp = float(np.median([s["spacing"] for s in ss]))
        pad = int(sp * 1.5)
        out_systems.append({
            "index": si, "staff_indices": [staves[i]["index"] for i in idxs],
            "box": {"x0": x0, "y0": max(0, y_top - pad), "x1": x1, "y1": min(h - 1, y_bot + pad)},
            "barlines": bars, "n_measures": count_measures(bars, x0, x1, sp),
        })
    geom = {"page": n, "image": png.name, "image_px": [w, h], "skew_deg": skew, "grouping": method, "prepare": prep,
            "expected_staves": expected, "staves_before_recovery": before,
            "recovered": [{"index": r["index"], "y_top": r["y_top"], "y_bottom": r["y_bottom"], "fit": r["fit"]} for r in recovered],
            "staves": [{k: (round(v, 2) if isinstance(v, float) else v) for k, v in s.items()} for s in staves],
            "systems": out_systems}
    dump(PC / f"geom-p{n:02d}.json", geom)
    overlay(png, geom, PC / f"overlay-p{n:02d}.png")
    hdr = PC / "header.json"
    if hdr.exists() and out_systems:
        hj = json.loads(hdr.read_text())
        if hj.get("page") == n:  # re-validate the header against the (possibly recovered) first system
            hj["validation"] = {**hj.get("validation", {}), "geometry_staves_system1": len(out_systems[0]["staff_indices"]),
                                "header_staves": expected, "match": len(out_systems[0]["staff_indices"]) == expected}
            dump(hdr, hj)
    shadows = [k for k, e in prep["edge_shadows"].items() if e.get("shadow")]
    print(f"p{n:02d}: {w}x{h}" + (f" (scale x{prep['scale']}, spacing {prep['spacing_native']})" if prep["scale"] > 1 else "")
          + (f" shadows masked {shadows}" if shadows else "")
          + f" skew {skew:+.1f} staves {len(staves)} grouping {method} systems "
          f"{[(len(s['staff_indices']), s['n_measures']) for s in out_systems]}"
          + (f" expected {expected} before {before} recovered {[(r['index'], r['fit']) for r in recovered]}" if expected else " (no header)"))
    return geom


if __name__ == "__main__":
    PC.mkdir(parents=True, exist_ok=True)
    for p in [int(a) for a in sys.argv[1:]] or DEFAULT_PAGES:
        run_page(p)
