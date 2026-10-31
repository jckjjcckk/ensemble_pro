"""The box side of Convert to Digital (feature 005): Audiveris over one PDF as ONE book, plus the 300 dpi scans the
Spark passes crop from. Stdlib only; `omr_convert` copies this file to the OMR box and runs it there with
`python3 -I`. Audiveris stays a separate process (AGPL): nothing in Folio imports it.

This is `api/experiments/omr/book_box.py` made a product step:
  - Audiveris reads the PDF itself (the benchmark: pitch F1 0.972 from the PDF against 0.908 from a render), one
    book per run, never `-sheets` (with `-sheets` the CLI hands `export` a fresh score list, every movement is
    named `mvtnull` and only the last survives; see book_box.py). A page subset is cut into its own PDF first
    (pdfseparate + pdfunite), so the book holds exactly the page set.
  - The page set may be the whole PDF (no `--pages`) or any list of pages; there is no 5-page cap here (the
    experiment cap lives in book_box.py; the product's cap is `omr_convert.MAX_PAGES`).
  - `pdftoppm -r 300 -gray` renders every page of the set to `scan/p{i}.png` (i = position in the set, 1-based):
    the same 300 dpi frame Audiveris works in (within 1 px), which the crops need.

  - `--parallel N` (off unless `omr_convert` passes `OMR_PARALLEL_PAGES`): every page of the set is its own
    one-page book, N Audiveris processes at once (about 1 GB each), stitched into the same layout as a whole-book run:
    `book/sheet#i` is page i's sheet, `book.xml` lists them in order, and every page starts a "movement" of its own
    (`movements.json`, exports renamed `<stem>.mvtK.mxl` in page order), so `omr_book.load_run` and `omr_score.merge`
    read it unchanged and number the bars +1 per stack exactly as before. What it loses: a movement that crosses a
    page is two export files (a tie or slur over the page turn is cut), each page's export restates its clef, key
    and time, and a page Audiveris reads alone has no time signature unless it prints one.

Usage (box):  python3 -I omr_box.py BOOK.pdf OUT_DIR [--pages 1,2,3 | --pages 1-5] [--max-pages 40] [--parallel 5]
Writes OUT_DIR/{book/ (book.xml, sheet#N/sheet#N.xml), <stem>.mvtK.mxl or <stem>.mxl, movements.json,
book_run.json, audiveris.log, scan/p{i}.png} and prints book_run.json's summary as one JSON line.
Exit codes: 0 ok, 2 bad arguments or unreadable PDF, 3 Audiveris failed, 4 exports missing, 5 over --max-pages.
"""

from __future__ import annotations

import argparse
import json
import os
import re
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


def pdf_page_count(pdf: Path) -> int:
    out = subprocess.run(["pdfinfo", str(pdf)], capture_output=True, text=True, check=True).stdout
    m = re.search(r"^Pages:\s+(\d+)", out, re.M)
    if not m:
        raise ValueError("pdfinfo found no page count")
    return int(m.group(1))


def parse_pages(spec: str | None, count: int) -> list[int]:
    """'1-5', '1,3,4' or None (every page). Pages outside the PDF are an error."""
    if not spec:
        return list(range(1, count + 1))
    pages: list[int] = []
    for part in spec.split(","):
        lo, _, hi = part.strip().partition("-")
        pages += range(int(lo), int(hi or lo) + 1)
    if not pages or any(p < 1 or p > count for p in pages) or len(set(pages)) != len(pages):
        raise ValueError(f"pages {spec}: must be distinct pages between 1 and {count}")
    return pages


def detected_movements(book_xml: bytes, pdf_pages: list[int]) -> list[dict]:
    """Every sheet page of the book in order (as book_box.py): the PDF page it came from, Audiveris's
    movement-start flag, the movement index (1-based, = the K of `mvtK.mxl`), the movement name OCR read, and
    how many measures Audiveris counted on it."""
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


# Java's TimSort refuses a comparator that is not a total order; Audiveris has one, and a page that trips it fails whole
# ("Comparison method violates its general contract!", the Moscheles edition's p. 13, E2E night 2026-10-31). The legacy
# merge sort accepts it. Only a run that failed that way is read again with it, so every page that passes stays exactly
# as the benchmark read it.
TIMSORT_REFUSAL = "Comparison method violates its general contract"
LEGACY_SORT = "-Djava.util.Arrays.useLegacyMergeSort=true"


def run_audiveris(book_pdf: Path, out: Path) -> tuple[int, float]:
    cmd = [AUDIVERIS, "-batch", "-transcribe", "-export", "-output", str(out), str(book_pdf)]  # never -sheets
    env = dict(os.environ, TESSDATA_PREFIX=TESSDATA)
    t1 = time.perf_counter()
    with open(out / "audiveris.log", "w") as fh:
        rc = subprocess.run(cmd, stdout=fh, stderr=subprocess.STDOUT, env=env).returncode
    if rc != 0 and TIMSORT_REFUSAL in (out / "audiveris.log").read_text(errors="replace"):
        for left in [*out.glob(f"{book_pdf.stem}*.omr"), *out.glob(f"{book_pdf.stem}*.mxl")]:
            left.unlink()
        env["JAVA_TOOL_OPTIONS"] = (env.get("JAVA_TOOL_OPTIONS", "") + " " + LEGACY_SORT).strip()
        with open(out / "audiveris.log", "a") as fh:
            fh.write(f"=== again with {LEGACY_SORT} (rc {rc}: {TIMSORT_REFUSAL})\n")
            fh.flush()
            rc = subprocess.run(cmd, stdout=fh, stderr=subprocess.STDOUT, env=env).returncode
    return rc, round(time.perf_counter() - t1, 1)


def parallel_pages(book_pdf: Path, n: int, out: Path, stem: str, pages: list[int], workers: int) -> tuple[int, float, list[dict], list[str]]:
    """Audiveris on each page alone, `workers` at once, stitched into out/book, out/<stem>.mvtK.mxl (see the module
    docstring). Returns (rc, seconds, movements, error tail)."""
    from concurrent.futures import ThreadPoolExecutor
    pp = out / "pp"
    jobs = []
    for i in range(1, n + 1):
        d = pp / str(i)
        (d / "input").mkdir(parents=True)
        one = d / "input" / f"{stem}.pdf"
        subprocess.run(["pdfseparate", "-f", str(i), "-l", str(i), str(book_pdf), str(one)], check=True)
        jobs.append((one, d))
    t1 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        results = list(ex.map(lambda j: run_audiveris(*j), jobs))
    seconds = round(time.perf_counter() - t1, 1)
    with open(out / "audiveris.log", "w") as fh:
        for i, (rc, secs) in enumerate(results, start=1):
            fh.write(f"=== page {i}: rc {rc}, {secs} s\n" + (pp / str(i) / "audiveris.log").read_text(errors="replace"))
    for i, (rc, _) in enumerate(results, start=1):
        if rc != 0 or not (pp / str(i) / f"{stem}.omr").exists():
            return rc or 3, seconds, [], (pp / str(i) / "audiveris.log").read_text(errors="replace").splitlines()[-5:]
    book = ET.Element("book")
    movements: list[dict] = []
    k = 0
    for i in range(1, n + 1):
        d = pp / str(i)
        with zipfile.ZipFile(d / f"{stem}.omr") as z:
            sub = ET.fromstring(z.read("book.xml"))
            z.extractall(d / "book")
        local = detected_movements(ET.tostring(sub), [pages[i - 1]])
        src = d / "book" / "sheet#1"
        if src.exists():
            dst = out / "book" / f"sheet#{i}"
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
            if (dst / "sheet#1.xml").exists():
                (dst / "sheet#1.xml").rename(dst / f"sheet#{i}.xml")
            for binary in dst.glob("BINARY.png"):
                binary.unlink()
        for sh in sub.findall("sheet"):
            sh.set("number", str(i))
            first = True
            for pg in sh.findall("page"):
                if first:
                    pg.set("movement-start", "true")      # each page is a movement of its own: its own export file
                    first = False
            book.append(sh)
        for sc in sub.findall("score"):
            for ref in sc.findall("page"):
                ref.set("sheet-number", str(i))
            book.append(sc)
        mk = max((m["movement"] for m in local), default=0)
        exports = [d / f"{stem}.mxl"] if mk == 1 else [d / f"{stem}.mvt{j}.mxl" for j in range(1, mk + 1)]
        for j, f in enumerate(exports, start=1):
            if not f.exists():
                return 4, seconds, [], [f"page {i}: export {f.name} missing"]
            shutil.move(str(f), str(out / f"{stem}.mvt{k + j}.mxl"))
        k += mk
    (out / "book").mkdir(exist_ok=True)
    data = ET.tostring(book)
    (out / "book" / "book.xml").write_bytes(data)
    movements = detected_movements(data, pages)
    shutil.rmtree(pp, ignore_errors=True)
    return 0, seconds, movements, []


def render_scans(book_pdf: Path, n: int, scan_dir: Path) -> None:
    scan_dir.mkdir(parents=True, exist_ok=True)
    for i in range(1, n + 1):
        subprocess.run(["pdftoppm", "-r", "300", "-gray", "-png", "-f", str(i), "-l", str(i), "-singlefile",
                        str(book_pdf), str(scan_dir / f"p{i}")], check=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("out")
    ap.add_argument("--pages", help="PDF pages, e.g. 1-5 or 1,2,7; every page when omitted")
    ap.add_argument("--max-pages", type=int, default=0, help="refuse a page set longer than this (exit 5), before Audiveris")
    ap.add_argument("--parallel", type=int, default=0, help="Audiveris on each page alone, this many at once, stitched")
    a = ap.parse_args()
    pdf = Path(a.pdf).expanduser().resolve()
    out = Path(a.out).expanduser().resolve()
    try:
        count = pdf_page_count(pdf)
        pages = parse_pages(a.pages, count)
    except (ValueError, subprocess.CalledProcessError) as e:
        print(json.dumps({"error": f"unreadable PDF: {e}"}))
        sys.exit(2)
    if a.max_pages and len(pages) > a.max_pages:
        print(json.dumps({"error": "too many pages", "pages": len(pages), "max_pages": a.max_pages}))
        sys.exit(5)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    stem = pdf.stem
    t0 = time.perf_counter()
    if pages == list(range(1, count + 1)):
        book_pdf = out / "input" / f"{stem}.pdf"
        book_pdf.parent.mkdir(parents=True)
        shutil.copy(pdf, book_pdf)
    else:
        book_pdf = out / "input" / f"{stem}.pdf"
        cut_pdf(pdf, pages, book_pdf)
    render_scans(book_pdf, len(pages), out / "scan")
    render_s = round(time.perf_counter() - t0, 1)

    cmd = [AUDIVERIS, "-batch", "-transcribe", "-export", "-output", str(out), str(book_pdf)]  # never -sheets
    parallel = a.parallel if a.parallel > 1 and len(pages) > 1 else 0
    if parallel:
        rc, seconds, movements, tail = parallel_pages(book_pdf, len(pages), out, stem, pages, parallel)
        if rc != 0:
            print(json.dumps({"error": f"audiveris exited {rc} (per page)", "log_tail": tail, "audiveris_s": seconds}))
            sys.exit(3 if rc != 4 else 4)
    else:
        rc, seconds = run_audiveris(book_pdf, out)
        omr = out / f"{stem}.omr"
        if rc != 0 or not omr.exists():
            tail = (out / "audiveris.log").read_text(errors="replace").splitlines()[-5:]
            print(json.dumps({"error": f"audiveris exited {rc}", "log_tail": tail, "audiveris_s": seconds}))
            sys.exit(3)
        with zipfile.ZipFile(omr) as z:
            movements = detected_movements(z.read("book.xml"), pages)
            z.extractall(out / "book")
    for binary in (out / "book").glob("sheet#*/BINARY.png"):   # the scans are rendered above; keep the pull small
        binary.unlink()
    (out / "movements.json").write_text(json.dumps(movements, indent=1))
    k = max((m["movement"] for m in movements), default=0)
    expected = [f"{stem}.mxl"] if k == 1 else [f"{stem}.mvt{i}.mxl" for i in range(1, k + 1)]
    exports = sorted((p.name for p in out.glob(f"{stem}*.mxl")), key=lambda n: (len(n), n))
    rec = {"pdf_pages": pages, "pdf_page_count": count, "cmd": cmd, "audiveris_s": seconds, "render_s": render_s, "parallel": parallel,
           "tessdata": TESSDATA, "movements": k, "exports": exports, "measures": sum(m["measures"] for m in movements)}
    (out / "book_run.json").write_text(json.dumps(rec, indent=1))
    if not k or exports != expected:
        print(json.dumps({"error": f"expected exports {expected}, got {exports}", "audiveris_s": seconds}))
        sys.exit(4)
    print(json.dumps({key: rec[key] for key in ("audiveris_s", "render_s", "movements", "exports", "measures", "pdf_pages")}))


if __name__ == "__main__":
    main()
