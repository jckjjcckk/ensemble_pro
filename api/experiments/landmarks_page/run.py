"""013 v4e eval: the per-page Spark read (`labels.label_page`, item 8) on a few scanned pages with printed landmarks.

    cd api && uv run python -m experiments.landmarks_page.run [tag]     # tag names the results file (default r1)

The app's own path, no database: `import_pdf.render_page` (150 dpi), `cut.page_measures` (geometry, no header), then
`label_page` with Muse Spark 1.3 (forced Meta, effort low, as the app's page read) and the page's landmarks at the bars
the count gives (`process_pages.landmarks_at_bars`, first bar from the page's own first_measure_number). The annotated
PNG Spark saw is written to results/ so a reader can check which box each landmark was pointed at. Every call is
logged in spend.jsonl; the task's cap is $3 (the run stops before a call that could pass it). Pages: 3-5 per file
(the standing experiment budget rule), never a whole score.
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from decimal import Decimal
from pathlib import Path

import pymupdf

from app.librarian import Job, JobContext
from app.librarian.cut import page_measures
from app.librarian.import_pdf import render_page
from app.librarian.labels import annotated_png, label_page
from app.librarian.process_pages import landmarks_at_bars
from app.llm import Completion, complete

HERE = Path(__file__).resolve().parent
PDFS = HERE.parents[1] / "fixtures" / "pdf"
RESULTS = HERE / "results"
LEDGER = HERE / "spend.jsonl"
CAP_USD = Decimal("3.00")
PER_CALL_CEILING = Decimal("0.05")

# (file, 1-based page in the PDF): pages chosen by eye for tempo words, double bars, repeats and section titles
PAGES = [("goldberg-bga-p1-5.pdf", 2), ("goldberg-bga-p1-5.pdf", 3),
         ("chopin-polonaises-ekier-test-p4-7.pdf", 2), ("chopin-polonaises-ekier-test-p4-7.pdf", 3),
         ("chopin-polonaises-ekier-test-p4-7.pdf", 4)]


def spent() -> Decimal:
    if not LEDGER.exists():
        return Decimal(0)
    return sum((Decimal(str(json.loads(l)["usd"])) for l in LEDGER.read_text().splitlines() if l.strip()), Decimal(0))


class EvalCtx(JobContext):
    """Spark through the app's `llm.complete`, forced to Meta; every call on the ledger; no database."""

    def __init__(self, tag: str, uid: str):
        super().__init__(Job("eval", "process_pages", {}, None, None, 1, 1))
        self.tag, self.uid = tag, uid

    async def complete(self, user_text: str, **kw) -> Completion:
        if spent() + PER_CALL_CEILING > CAP_USD:
            raise SystemExit(f"cap: ${spent()} spent of ${CAP_USD}")
        kw["provider"] = "meta"
        t0 = time.monotonic()
        c = await complete(user_text, **kw)
        with LEDGER.open("a") as f:
            f.write(json.dumps({"tag": self.tag, "uid": self.uid, "model": c.charge.model, "usd": float(c.charge.cost_usd),
                                "input_tokens": c.charge.input_tokens, "output_tokens": c.charge.output_tokens,
                                "seconds": round(time.monotonic() - t0, 2), "at": self.now()}) + "\n")
        return c


async def one(tag: str, name: str, page_no: int) -> dict:
    doc = pymupdf.open(PDFS / name)
    png, w, h, dpi = render_page(doc[page_no - 1])
    geo = page_measures(png)
    uid = f"{Path(name).stem}-p{page_no}"
    (RESULTS / f"{uid}-annotated.png").write_bytes(annotated_png(png, geo))
    labels = await label_page(EvalCtx(tag, uid), png, geo, effort="low")
    first = labels.first_measure_number
    number_of = {m["provisional"]: first + i for i, m in enumerate(geo["measures"])}
    log: list[str] = []
    marks = landmarks_at_bars(labels, number_of, page_no, log)
    return {"uid": uid, "boxes": len(geo["measures"]), "systems": len(geo["systems"]), "first_measure_number": first,
            "confidence": labels.confidence, "raw_landmarks": labels.raw.get("landmarks"), "kept": labels.landmarks,
            "dropped": labels.landmarks_dropped, "at_bars": marks, "log": log, "usd": float(labels.cost_usd)}


async def main(tag: str) -> None:
    RESULTS.mkdir(exist_ok=True)
    out = []
    for name, page_no in PAGES:
        r = await one(tag, name, page_no)
        out.append(r)
        print(f"{r['uid']}: {r['boxes']} boxes, first bar {r['first_measure_number']} ({r['confidence']}), ${r['usd']:.4f}")
        for d in r["kept"]:
            print(f"   box {d['provisional']:>2}  {d['kind']:<12} {d['text']}")
        for d in r["dropped"]:
            print(f"   DROPPED {d}")
    (RESULTS / f"{tag}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(f"ledger total ${spent():.4f}")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "r1"))
