"""The fixed corpus: manifest loader and validation, page renders, and the images each task sends.

Geometry is frozen in the 150 dpi frame (corpus/geom/); the Goldberg layout (Audiveris bounds) in its 300 dpi
frame. The resolution axis changes only the pixels the model sees: a page is rendered at the asked resolution,
deskewed by the frozen angle, and the frozen boxes are scaled onto it, so staff and bar numbers never move.
"""

from __future__ import annotations

import io
import json
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

HERE = Path(__file__).resolve().parent
API = HERE.parent.parent
FIXTURES = Path(os.environ.get("FOLIO_PDF_DIR", API / "fixtures" / "pdf"))
CACHE = HERE / "cache"
MAX_PAGES_PER_FILE = 5
RESOLUTIONS = {"native": "native", "150dpi": 150, "300dpi": 300}
MAX_IMAGE_BYTES = 3_600_000  # base64 of this stays under the 5 MB per-image API limit


@dataclass
class Page:
    id: str
    score: str
    page: int
    content: str = ""
    geom_path: str | None = None
    layout_path: str | None = None
    gt: dict[str, Any] = field(default_factory=dict)


@dataclass
class Corpus:
    root: Path
    version: int
    scores: dict[str, dict[str, Any]]
    pages: dict[str, Page]

    def pdf(self, page: Page) -> Path:
        return FIXTURES / self.scores[page.score]["pdf"]

    def title(self, page: Page) -> str:
        return self.scores[page.score].get("title", page.score)

    def load(self, rel: str) -> dict:
        return json.loads((self.root / rel).read_text())

    def geom(self, page: Page) -> dict:
        if not page.geom_path:
            raise ValueError(f"{page.id} has no frozen geometry")
        return self.load(page.geom_path)

    def header(self, page: Page) -> dict | None:
        rel = self.scores[page.score].get("header")
        return self.load(rel) if rel else None

    def pages_with(self, task: str) -> list[Page]:
        return [p for p in self.pages.values() if task in p.gt]


def load_manifest(path: str | Path) -> Corpus:
    """Read and validate the manifest. Raises ValueError on: duplicate page ids, a page of an unknown score, more
    than MAX_PAGES_PER_FILE pages from one file, a header/labels task without geometry, a GT staff number that is
    not in that system of the frozen geometry, a missing referenced file."""
    path = Path(path)
    data = yaml.safe_load(path.read_text())
    root = path.parent
    scores = data.get("scores") or {}
    pages: dict[str, Page] = {}
    per_file: dict[str, int] = {}
    for raw in data.get("pages") or []:
        pid = raw["id"]
        if pid in pages:
            raise ValueError(f"duplicate page id {pid}")
        if raw["score"] not in scores:
            raise ValueError(f"{pid}: unknown score {raw['score']}")
        pdf = scores[raw["score"]]["pdf"]
        per_file[pdf] = per_file.get(pdf, 0) + 1
        if per_file[pdf] > MAX_PAGES_PER_FILE:
            raise ValueError(f"more than {MAX_PAGES_PER_FILE} pages from {pdf}")
        p = Page(id=pid, score=raw["score"], page=int(raw["page"]), content=raw.get("content", ""),
                 geom_path=raw.get("geom"), layout_path=raw.get("layout"), gt=raw.get("gt") or {})
        for rel in (p.geom_path, p.layout_path, (p.gt.get("omr") or {}).get("file"), scores[p.score].get("header")):
            if rel and not (root / rel).exists():
                raise ValueError(f"{pid}: missing file {rel}")
        if ("header" in p.gt or "labels" in p.gt) and not p.geom_path:
            raise ValueError(f"{pid}: header/labels ground truth needs frozen geometry")
        if "labels" in p.gt:
            geom = json.loads((root / p.geom_path).read_text())
            systems = {s["index"]: set(s["staff_indices"]) for s in geom["systems"]}
            for k, v in p.gt["labels"]["systems"].items():
                if int(k) not in systems:
                    raise ValueError(f"{pid}: labels GT names system {k}, geometry has {sorted(systems)}")
                if v != "absent" and not set(int(x) for x in v) <= systems[int(k)]:
                    raise ValueError(f"{pid}: labels GT staves {v} not in system {k} {sorted(systems[int(k)])}")
        if ("text" in p.gt or "closed" in p.gt) and not p.layout_path:
            raise ValueError(f"{pid}: text/closed ground truth needs a layout")
        pages[pid] = p
    return Corpus(root=root, version=int(data.get("version", 1)), scores=scores, pages=pages)


# ---------------------------------------------------------------- renders

def page_png_path(page: Page, res: str) -> Path:
    return CACHE / "pages" / f"{page.id}@{res}.png"


def ensure_pages(corpus: Corpus, wanted: list[tuple[Page, str]]) -> None:
    """Render every (page, resolution) not yet in the cache, in one subprocess (PyMuPDF lives in render.py's env)."""
    jobs = [{"pdf": str(corpus.pdf(p)), "page": p.page, "dpi": RESOLUTIONS[r], "out": str(page_png_path(p, r))}
            for p, r in wanted if not page_png_path(p, r).exists()]
    if not jobs:
        return
    for j in jobs:
        if not Path(j["pdf"]).exists():
            raise FileNotFoundError(f"{j['pdf']} (fixtures are gitignored; set FOLIO_PDF_DIR or copy them)")
    CACHE.mkdir(parents=True, exist_ok=True)
    spec = CACHE / "render-jobs.json"
    spec.write_text(json.dumps(jobs))
    subprocess.run(["uv", "run", "--quiet", str(HERE / "render.py"), str(spec)], check=True, cwd=API)


def load_page(page: Page, res: str):
    from PIL import Image

    return Image.open(page_png_path(page, res)).convert("L")


def deskewed(page: Page, res: str, skew_deg: float):
    import numpy as np
    from PIL import Image

    from app.librarian.geometry import rotate

    im = load_page(page, res)
    if abs(skew_deg) >= 0.1:
        im = Image.fromarray(rotate(np.array(im), skew_deg, 255))
    return im.convert("RGB")


def encode(im) -> tuple[bytes, str]:
    """PNG, or JPEG q90 when the PNG would pass the per-image size limit."""
    buf = io.BytesIO()
    im.save(buf, format="PNG", optimize=True)
    if buf.tell() <= MAX_IMAGE_BYTES:
        return buf.getvalue(), "image/png"
    buf = io.BytesIO()
    im.convert("RGB").save(buf, format="JPEG", quality=90)
    return buf.getvalue(), "image/jpeg"


def _font(size: int):
    from PIL import ImageFont

    for cand in ("/System/Library/Fonts/Helvetica.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(cand, max(8, size))
        except OSError:
            continue
    return ImageFont.load_default()


def overlay(page: Page, res: str, geom: dict):
    """app.librarian.cut.overlay_png's drawing (staff boxes in blue, yellow number tags, systems in grey) on the
    page rendered at `res`, the frozen 150 dpi boxes scaled to it."""
    from PIL import ImageDraw

    im = deskewed(page, res, float(geom.get("skew_deg") or 0))
    k = im.width / geom["image_px"][0]
    d = ImageDraw.Draw(im, "RGBA")
    font = _font(round(26 * k))
    lw = max(2, round(2 * k))
    for s in geom["systems"]:
        b = s["box"]
        d.rectangle([b["x0"] * k, b["y0"] * k, b["x1"] * k, b["y1"] * k], outline=(120, 120, 120, 255), width=lw)
    for st in geom["staves"]:
        pad = st["spacing"] * 1.2
        x0, y0, x1, y1 = st["x0"] * k, (st["y_top"] - pad) * k, st["x1"] * k, (st["y_bottom"] + pad) * k
        d.rectangle([x0, y0, x1, y1], outline=(0, 110, 220, 255), width=lw)
        tx, ty = x0 + 4 * k, y0 - 2 * k
        d.rectangle([tx, ty, tx + 46 * k, ty + 30 * k], fill=(255, 235, 60, 230), outline=(0, 0, 0, 255))
        d.text((tx + 6 * k, ty + 1 * k), str(st["index"]), fill=(0, 0, 0, 255), font=font)
    return im


def system_crop(page: Page, res: str, layout: dict, system_id: int):
    """005's reread crop: one system from the Audiveris bounds with every measure boxed and numbered, scaled from
    the layout's 300 dpi frame to the render at `res`. Returns (image, measure ids)."""
    from PIL import ImageDraw

    im = load_page(page, res).convert("RGB")
    k = im.width / layout["frame_px"][0]
    il = layout["interline"] * k
    s = next(x for x in layout["systems"] if x["id"] == system_id)
    x0, x1 = max(0, s["left"] * k - 2 * il), min(im.width, s["right"] * k + il)
    y0, y1 = max(0, s["top"] * k - 4 * il), min(im.height, s["bottom"] * k + 4 * il)
    crop = im.crop((int(x0), int(y0), int(x1), int(y1)))
    d = ImageDraw.Draw(crop)
    font = _font(int(1.6 * il))
    ids = []
    for m in layout["measures"]:
        if m["system"] != system_id:
            continue
        ids.append(m["id"])
        bx = (m["left"] * k - x0, m["top"] * k - y0 - 3, m["right"] * k - x0, m["bottom"] * k - y0 + 3)
        d.rectangle(bx, outline=(0, 90, 220), width=2)
        label = str(m["id"])
        tw = d.textlength(label, font=font)
        lx, ly = bx[0] + 4, bx[1] - 1.8 * il
        d.rectangle((lx - 3, ly - 2, lx + tw + 3, ly + 1.7 * il), fill=(255, 230, 0))
        d.text((lx, ly), label, fill=(0, 0, 0), font=font)
    return crop, ids


def symbol_crop(page: Page, res: str, layout: dict, symbol: dict, ctx: float = 6.0):
    """005's verifier crop: a 6-interline window around the symbol, the symbol boxed in red."""
    from PIL import ImageDraw

    im = load_page(page, res).convert("RGB")
    k = im.width / layout["frame_px"][0]
    x, y, w, h = (v * k for v in symbol["bounds"])
    c = ctx * layout["interline"] * k
    x0, y0 = max(0, x - c), max(0, y - c)
    crop = im.crop((int(x0), int(y0), int(min(im.width, x + w + c)), int(min(im.height, y + h + c))))
    pad = max(2, 3 * k)
    ImageDraw.Draw(crop).rectangle((x - x0 - pad, y - y0 - pad, x + w - x0 + pad, y + h - y0 + pad),
                                   outline=(220, 0, 0), width=max(2, round(3 * k)))
    return crop
