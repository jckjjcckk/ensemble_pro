"""Step 1, once: render every page as the app does (150 dpi, `import_pdf.render_page`; Beethoven 9's pages are the
grounding experiment's 150 dpi renders, the full PDF is not on this machine), read each book's score header with the
app's `labels.read_header` (one Spark call per book, Messages, effort low), then `cut.page_measures` with the header's
staff count. Pages, header and geometry are frozen in results/prep/, so every variant labels the same boxes.

    cd api && uv run python -m experiments.pageread_speed.prepare
"""
from __future__ import annotations

import asyncio
import json

import pymupdf

from app.librarian import Job, JobContext
from app.librarian.cut import page_measures
from app.librarian.import_pdf import render_page
from app.librarian.labels import annotated_png, read_header
from app.llm import _client

from .common import BOOKS, MODEL, RESULTS, guard, log

PREP = RESULTS / "prep"


class Ctx(JobContext):
    def __init__(self, uid: str):
        super().__init__(Job("eval", "process_pages", {}, None, None, 1, 1))
        self.uid = uid

    def charge(self, c) -> None:  # every header attempt on the ledger
        log(tag="prep-header", uid=self.uid, api="messages", effort="low", model=c.model, usd=float(c.cost_usd),
            input_tokens=c.input_tokens, output_tokens=c.output_tokens)


def page_png(src) -> bytes:
    kind, path, n = src
    if kind == "png":
        return path.read_bytes()
    return render_page(pymupdf.open(path)[n - 1])[0]


async def main() -> None:
    PREP.mkdir(parents=True, exist_ok=True)
    for book, (_, title, _, use_header, pages) in BOOKS.items():
        pngs = {}
        for pid, src in pages:
            f = PREP / f"{pid}.png"
            if not f.exists():
                f.write_bytes(page_png(src))
            pngs[pid] = f.read_bytes()
        hf = PREP / f"{book}-header.json"
        if use_header and not hf.exists():
            guard()
            pid0 = pages[0][0]
            h = await read_header(Ctx(book), pngs[pid0], _client("meta"), MODEL, page=1, title=title)
            h.pop("overlay_png", None)
            hf.write_text(json.dumps(h, indent=1))
        header = json.loads(hf.read_text()) if hf.exists() else None
        expected = (header or {}).get("expected_staves")
        for pid, _ in pages:
            geo = page_measures(pngs[pid], expected_staves=expected)
            (PREP / f"{pid}-geo.json").write_text(json.dumps(geo))
            (PREP / f"{pid}-annotated.png").write_bytes(annotated_png(pngs[pid], geo))
            print(f"{pid}: expected {expected}, {len(geo['systems'])} systems, staves {[s['staves'] for s in geo['systems']]}, "
                  f"{len(geo['measures'])} boxes, recovered {[s['recovered'] for s in geo['systems']]}")


if __name__ == "__main__":
    asyncio.run(main())
