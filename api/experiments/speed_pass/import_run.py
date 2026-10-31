"""Speed pass: a PDF import end to end (`import_pdf` renders, `process_pages` reads) on an in-memory store with real
Spark, timed. Run from an `api/` folder (this checkout, or a worktree of an older commit for the "before"): the working
directory comes first on sys.path, so `app` is that folder's.

    uv run python /abs/experiments/speed_pass/import_run.py fixtures/pdf/goldberg-bga-p1-5.pdf --tag goldberg-after-r1
"""
from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import os
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, os.getcwd())
HERE = Path(__file__).resolve().parent

from app.librarian import Job  # noqa: E402
from app.librarian.import_pdf import import_pdf  # noqa: E402
from app.librarian.process_pages import process_pages  # noqa: E402
from app.llm import _client  # noqa: E402
from app.settings import settings  # noqa: E402
from tests.test_part_cut import Ctx as BaseCtx, FakeDB  # noqa: E402

_spec = importlib.util.spec_from_file_location("speed_pass_ledger", HERE / "ledger.py")
ledger = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ledger)


class Ctx(BaseCtx):
    def __init__(self, *a, tag: str, **k):
        super().__init__(*a, **k)
        self.tag = tag

    def charge(self, c):
        self.charges.append(c)
        ledger.log(source="script", tag=self.tag, model=c.model, input_tokens=c.input_tokens, output_tokens=c.output_tokens, usd=float(c.cost_usd))
        return {}

    def storage_upload(self, path, data, content_type):
        self.pages[path] = data


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--tag", required=True)
    a = ap.parse_args()
    score, key = str(uuid.uuid4()), "src.pdf"
    db = FakeDB()
    db.rows["scores"] = [{"id": score, "title": Path(a.pdf).stem, "composer": None, "work": None}]
    db.rows["sources"] = [{"id": "src1", "score_id": score, "kind": "pdf", "storage_paths": [key], "created_by": "u1"}]
    files = {key: Path(a.pdf).read_bytes()}
    tag = f"import {a.tag}"
    t0 = time.time()
    j1 = Job(str(uuid.uuid4()), "import_pdf", {"score_id": score, "source_id": "src1"}, score, "u1", 1, 3)
    await import_pdf(j1, Ctx(j1, db, files, tag=tag))
    t1 = time.time()
    j2 = Job(str(uuid.uuid4()), "process_pages", {"score_id": score, "source_id": "src1"}, score, "u1", 1, 3)
    ctx = Ctx(j2, db, files, tag=tag)
    out = await process_pages(j2, ctx, client=_client("meta"), model=settings.meta_model)
    t2 = time.time()
    state = db.rows["interpretations"][-1]["params"]["state"]
    sc = db.rows["scores"][0]
    rec = {"tag": a.tag, "render_s": round(t1 - t0, 1), "read_s": round(t2 - t1, 1), "wall_s": round(t2 - t0, 1), "question": out.get("question"),
           "status": sc.get("status"), "bars": sc.get("bars"), "key": sc.get("key_sig"), "meter": sc.get("meter"),
           "parts": [r["name"] for r in db.rows.get("parts", [])], "landmarks": sc.get("landmarks"),
           "efforts": {k: p.get("effort") for k, p in state["pages"].items()}, "fallbacks": {k: p.get("fallback") for k, p in state["pages"].items() if p.get("fallback")},
           "cost_usd": round(sum(float(c.cost_usd) for c in ctx.charges), 4), "calls": len(ctx.charges)}
    out_dir = HERE / "results" / "import"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{a.tag}.json").write_text(json.dumps(rec, indent=1, default=str))
    print(json.dumps({k: v for k, v in rec.items() if k != "landmarks"}, default=str))
    print("landmarks", [(m["kind"], m["bar"], m.get("trust")) for m in rec["landmarks"] or []])


if __name__ == "__main__":
    asyncio.run(main())
