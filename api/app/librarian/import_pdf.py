"""A PDF imported from the browser reads itself (feature 002, Path B without the ordering step).

Meta model: none in this job (PyMuPDF rasterises); the `process_pages` job it queues reads the pages with
**Muse Spark 1.3** (feature 004).

The browser uploads the file to `{score_id}/source.pdf`, inserts a `sources` row of kind `pdf` with
`storage_paths = [key]` and calls `POST /scores/{id}/import`, which queues this job. Here: open the PDF, render
every page in the file's own order to a greyscale PNG at 150 dpi (the call the experiments and the Beethoven 9
seeds used, so the geometry's pixel thresholds hold), upload each as `{score_id}/pages/{n}.png` (1-based, the
convention `process_pages.page_paths` already reads for a `pdf` source), commit `page_order = [1..n]` and
`page_count = n` on the source, and queue `process_pages` for it. Nobody orders pages and nobody confirms: the
score stays `processing` until `process_pages` writes `ready` (or parks on a question, or fails).

A file that cannot be read for a reason the musician can fix (not a PDF, locked, empty, too long) fails at once
with a sentence in `scores.failure_reason` (`ScoreFailure`); the worker does not retry it.
"""
from __future__ import annotations

import time
from typing import Any

import pymupdf

from ..settings import settings
from . import Job, JobContext, ScoreFailure, handler

DPI = 150
# The geometry is tuned on pages about 1300-1450 px wide (letter / A4 at 150 dpi) and shrinks wider ones itself.
# A pocket score would come out too small to find staff lines, so it is scaled up to the floor. The ceiling only
# keeps a poster-sized page in memory: Beethoven 9's 1500 pt pages render at 3125 px, exactly as the seeds did.
MIN_WIDTH_PX, MAX_WIDTH_PX = 1100, 3200


def render_page(page: "pymupdf.Page") -> tuple[bytes, int, int, float]:
    """One page as a greyscale PNG. Returns (png, width, height, effective dpi)."""
    w_pt = page.rect.width or 612.0
    dpi = float(DPI)
    w_px = w_pt * dpi / 72.0
    if w_px < MIN_WIDTH_PX:
        dpi = MIN_WIDTH_PX * 72.0 / w_pt
    elif w_px > MAX_WIDTH_PX:
        dpi = MAX_WIDTH_PX * 72.0 / w_pt
    if float(dpi).is_integer():
        pix = page.get_pixmap(dpi=int(dpi), colorspace=pymupdf.csGRAY)   # the same call the experiments used
    else:
        z = dpi / 72.0
        pix = page.get_pixmap(matrix=pymupdf.Matrix(z, z), colorspace=pymupdf.csGRAY)
    return pix.tobytes("png"), pix.width, pix.height, round(dpi, 2)


def open_pdf(data: bytes) -> "pymupdf.Document":
    if b"%PDF-" not in data[:1024]:
        raise ScoreFailure("This file is not a PDF. Export the score as a PDF and import that file.")
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception as e:  # noqa: BLE001  (pymupdf raises FileDataError and RuntimeError subclasses)
        raise ScoreFailure("This PDF is damaged and could not be opened. Download or export it again and import the new copy.") from e
    if doc.needs_pass:
        raise ScoreFailure("This PDF is locked with a password. Save a copy without the password and import that.")
    if doc.page_count == 0:
        raise ScoreFailure("This PDF has no pages.")
    limit = settings.pdf_max_pages
    if doc.page_count > limit:
        raise ScoreFailure(f"This PDF has {doc.page_count} pages; Folio reads up to {limit} at a time for now. "
                           "Import one movement or section as its own PDF.")
    return doc


@handler("import_pdf")
async def import_pdf(job: Job, ctx: JobContext) -> dict[str, Any]:
    t0 = time.time()
    score_id = job.payload["score_id"]
    source_id = job.payload["source_id"]
    rows = ctx.db.table("sources").select("*").eq("id", source_id).limit(1).execute().data
    if not rows or rows[0]["score_id"] != score_id or rows[0]["kind"] != "pdf" or not rows[0].get("storage_paths"):
        raise RuntimeError(f"source {source_id} is not a pdf source of score {score_id}")
    src = rows[0]
    key = src["storage_paths"][0]

    await ctx.progress(0.0, "Opening the PDF")
    try:
        data = ctx.storage_download(key)
    except Exception as e:  # noqa: BLE001
        raise ScoreFailure("The PDF did not finish uploading. Import it again.") from e
    doc = open_pdf(data)
    n = doc.page_count
    sizes: list[list[int]] = []
    dpis: set[float] = set()
    for i in range(1, n + 1):
        await ctx.progress(0.04 * (i - 1) / n, f"Preparing page {i} of {n}")
        png, w, h, dpi = render_page(doc[i - 1])
        ctx.storage_upload(f"{score_id}/pages/{i}.png", png, "image/png")
        sizes.append([w, h])
        dpis.add(dpi)
    doc.close()
    render_s = round(time.time() - t0, 2)

    meta = {**(src.get("meta") or {}), "render": {"engine": f"pymupdf {pymupdf.VersionBind}", "dpi": sorted(dpis), "px": sizes, "seconds": render_s}}
    ctx.db.table("sources").update({"page_order": list(range(1, n + 1)), "page_count": n, "meta": meta}).eq("id", source_id).execute()

    # Hand straight on to the reading. A retried import must not queue a second reading of the same source.
    pending = [r for r in ctx.db.table("jobs").select("id,status").eq("kind", "process_pages").eq("payload->>source_id", source_id).execute().data or []
               if r.get("status") in ("queued", "running")]
    if pending:
        follow = pending[0]["id"]
    else:
        follow = ctx.db.table("jobs").insert({"kind": "process_pages", "status": "queued", "score_id": score_id, "created_by": job.created_by,
                                              "payload": {"score_id": score_id, "source_id": source_id}}).execute().data[0]["id"]
    await ctx.progress(0.04, f"Reading {n} pages")
    return {"pages": n, "dpi": sorted(dpis), "process_job_id": follow, "render_seconds": render_s}
