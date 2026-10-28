"""Audiveris over a page set as ONE book, one MusicXML file per movement, no collisions. Runs on the OMR box
(stdlib only: `python3 -I book_box.py ...`); Audiveris stays a separate process (AGPL), nothing imports it.

Why one book: bar numbering, the time signature and the key carry across pages only inside a book (a lone
continuation page has no time signature in its header, Audiveris keeps the last one in book.xml).

The multi-movement collision, found in the 5.11 bytecode: Audiveris splits a book into movements (a new
movement where a system is indented) and exports each as `<radix>.mvt<id>.mxl`, where id is the score's
index in `book.getScores()`. With `-sheets`, the CLI hands `export` a fresh score list instead of the book's
own (CLI$ProcessingTask: `if (sheetIds != null) scores = new ArrayList<>()`), so every id is null, every
movement is written to `<radix>.mvtnull.mxl` and only the last survives (the opus export dies on the same
duplicate name). The p1-3 run caught the overwrites through a FIFO. The fix is to never pass `-sheets`:
the selected PDF pages are cut into their own PDF first (pdfseparate + pdfunite, same file stem), so the
book holds exactly the page set, the ids are 1..K and the files are `<radix>.mvt1.mxl` .. `mvtK.mxl` (or
`<radix>.mxl` for a single movement). It also makes the page cap structural: the book cannot reach a page
outside the set. (Rewriting book.xml into a single movement was tried and rejected: the export duplicated
the first page of every sheet, dropped the second, and lost the 2/4 of Var. 2.)

Usage (box):
  python3 -I book_box.py PDF OUT_DIR --pages 1-5
Writes OUT_DIR/input/<stem>.pdf (the page set), OUT_DIR/<stem>.omr, OUT_DIR/<stem>.mvt{1..K}.mxl,
OUT_DIR/book/ (the unzipped book), OUT_DIR/movements.json, OUT_DIR/book_run.json, OUT_DIR/audiveris.log.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

AUDIVERIS = os.environ.get("AUDIVERIS", str(Path.home() / ".local" / "bin" / "audiveris"))
TESSDATA = os.environ.get("TESSDATA_PREFIX", str(Path.home() / "omr" / "tessdata"))
MAX_PAGES = 5  # experiment cap: never a full score


def page_range(spec: str) -> list[int]:
    lo, _, hi = spec.partition("-")
    pages = list(range(int(lo), int(hi or lo) + 1))
    if not pages or len(pages) > MAX_PAGES:
        sys.exit(f"--pages {spec}: 1 to {MAX_PAGES} pages")
    return pages


def detected_movements(book_xml: bytes, pdf_pages: list[int]) -> list[dict]:
    """Every sheet page of the book in order: the PDF page it came from, Audiveris's movement-start flag, the
    movement index (1-based, = the K of `mvtK.mxl`), the name OCR read for the movement (the score's logical
    part name, e.g. "Var. 1."), and how many measures Audiveris counted on it."""
    root = ET.fromstring(book_xml)
    names: dict[tuple[int, int], str | None] = {}
    for sc in root.findall("score"):
        refs = sc.findall("page")
        if refs:
            lp = sc.find("logical-part")
            names[(int(refs[0].get("sheet-number")), int(refs[0].get("sheet-page-id")))] = (
                lp.get("name") if lp is not None else None)
    out, movement = [], 0
    for sh in root.findall("sheet"):
        sheet = int(sh.get("number"))
        for pg in sh.findall("page"):
            key = (sheet, int(pg.get("id")))
            start = pg.get("movement-start") == "true" or movement == 0
            movement += start
            out.append({"sheet": sheet, "pdf_page": pdf_pages[sheet - 1], "page": key[1], "movement_start": start,
                        "movement": movement, "name": names.get(key) if start else None,
                        "measures": int(pg.get("delta-measure-id", 0))})
    return out


def cut_pdf(pdf: Path, pages: list[int], dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        singles = []
        for p in pages:
            one = Path(tmp) / f"p{p:04d}.pdf"
            subprocess.run(["pdfseparate", "-f", str(p), "-l", str(p), str(pdf), str(one)], check=True)
            singles.append(str(one))
        if len(singles) == 1:
            shutil.copy(singles[0], dest)
        else:
            subprocess.run(["pdfunite", *singles, str(dest)], check=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("out")
    ap.add_argument("--pages", required=True, help="PDF page range, e.g. 1-5 (at most 5 pages)")
    a = ap.parse_args()
    pdf = Path(a.pdf).expanduser().resolve()
    out = Path(a.out).expanduser().resolve()
    pages = page_range(a.pages)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    stem = pdf.stem
    sub = out / "input" / f"{stem}.pdf"
    cut_pdf(pdf, pages, sub)

    cmd = [AUDIVERIS, "-batch", "-transcribe", "-export", "-output", str(out), str(sub)]  # never -sheets, see above
    t0 = time.perf_counter()
    with open(out / "audiveris.log", "w") as fh:
        rc = subprocess.run(cmd, stdout=fh, stderr=subprocess.STDOUT, env=dict(os.environ, TESSDATA_PREFIX=TESSDATA)).returncode
    seconds = round(time.perf_counter() - t0, 1)
    if rc != 0:
        sys.exit(f"audiveris exited {rc}; see {out / 'audiveris.log'}")

    omr = out / f"{stem}.omr"
    with zipfile.ZipFile(omr) as z:
        movements = detected_movements(z.read("book.xml"), pages)
        z.extractall(out / "book")
    (out / "movements.json").write_text(json.dumps(movements, indent=1))
    k = max(m["movement"] for m in movements)
    expected = [f"{stem}.mxl"] if k == 1 else [f"{stem}.mvt{i}.mxl" for i in range(1, k + 1)]
    exports = sorted((p.name for p in out.glob(f"{stem}*.mxl")), key=lambda n: (len(n), n))
    log_lines = [ln.split("|", 1)[-1].strip() for ln in (out / "audiveris.log").read_text().splitlines() if "exported to" in ln]
    rec = {"pdf": str(pdf), "pdf_pages": pages, "cmd": cmd, "audiveris_s": seconds, "tessdata": TESSDATA,
           "movements": k, "exports": exports, "export_log": log_lines,
           "measures": sum(m["measures"] for m in movements)}
    (out / "book_run.json").write_text(json.dumps(rec, indent=1))
    if exports != expected or len(log_lines) != len(expected):
        sys.exit(f"expected exports {expected}, got {exports}; log {log_lines}")
    print(json.dumps({k_: rec[k_] for k_ in ("audiveris_s", "movements", "exports", "measures")}))


if __name__ == "__main__":
    main()
