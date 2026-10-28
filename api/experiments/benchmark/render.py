# /// script
# requires-python = ">=3.12"
# dependencies = ["pymupdf>=1.24"]
# ///
"""Render PDF pages to greyscale PNGs. The one step that needs PyMuPDF, so it runs in its own environment
(`uv run experiments/benchmark/render.py`, PEP 723 deps) and the benchmark calls it as a subprocess.

Usage: render.py JOBS.json   where JOBS.json is [{"pdf": path, "page": 1-based, "dpi": float|"native", "out": path}]
"native" renders at the dpi where the page width in pixels equals the width of the page's largest embedded image
(the scan's own resolution). Prints one JSON line per job: {"out", "dpi", "px": [w, h]}.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pymupdf


def native_dpi(page) -> float:
    imgs = page.get_images(full=True)
    if not imgs:
        return 150.0
    w = max(i[2] for i in imgs)
    return round(72.0 * w / page.rect.width, 2)


def main() -> None:
    jobs = json.loads(Path(sys.argv[1]).read_text())
    docs: dict[str, pymupdf.Document] = {}
    for j in jobs:
        doc = docs.setdefault(j["pdf"], pymupdf.open(j["pdf"]))
        page = doc[int(j["page"]) - 1]
        dpi = native_dpi(page) if j["dpi"] == "native" else float(j["dpi"])
        if float(dpi).is_integer():  # the same call the experiments used, so frozen 150 dpi geometry lines up
            pix = page.get_pixmap(dpi=int(dpi), colorspace=pymupdf.csGRAY)
        else:  # PyMuPDF wants an integer dpi=, so a fractional (native) dpi goes through a matrix
            z = dpi / 72.0
            pix = page.get_pixmap(matrix=pymupdf.Matrix(z, z), colorspace=pymupdf.csGRAY)
        out = Path(j["out"])
        out.parent.mkdir(parents=True, exist_ok=True)
        pix.save(str(out))
        print(json.dumps({"out": str(out), "dpi": dpi, "px": [pix.width, pix.height]}))


if __name__ == "__main__":
    main()
