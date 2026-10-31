"""Step 4 of the speed pass: the live part_cut handler on fixture pages, real Spark, an in-memory store (the tests'
FakeDB), no Supabase. Run from an `api/` folder: this one, or a worktree of an older commit for the "before" timing
(the script puts the working directory first on sys.path, so `app` is that folder's).

    uv run python /abs/experiments/speed_pass/part_cut_run.py PDF --pages 1-5 --instrument Piano --tag rach-after \\
        [--labels minimal] [--rechecks minimal] [--shadow]

--shadow: every label and recheck call made at minimal is also asked at low on the identical prompt and image (beside
it, not used for any decision), so the two efforts are compared on the same inputs. Writes
results/part_cut/<tag>.json: the result, the commits, the label and recheck pairs, timings, and logs every charge to
the speed pass ledger.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, os.getcwd())
HERE = Path(__file__).resolve().parent

import pymupdf  # noqa: E402

import app.librarian.part_cut as pc  # noqa: E402
from app.librarian import Job, JobContext  # noqa: E402
from app.librarian.import_pdf import render_page  # noqa: E402
from app.llm import _client  # noqa: E402
from app.settings import settings  # noqa: E402

import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location("speed_pass_ledger", HERE / "ledger.py")
ledger = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ledger)
from tests.test_part_cut import FakeDB  # noqa: E402

OUT = HERE / "results" / "part_cut"


class Ctx(JobContext):
    def __init__(self, job: Job, db: FakeDB, pages: dict[str, bytes], tag: str):
        super().__init__(job)
        self._db, self.pages, self.uploads, self.charges, self.tag = db, pages, {}, [], tag

    @property
    def db(self):
        return self._db

    def charge(self, c):
        self.charges.append(c)
        ledger.log(source="script", tag=self.tag, model=c.model, input_tokens=c.input_tokens, output_tokens=c.output_tokens, usd=float(c.cost_usd))
        return {}

    def storage_download(self, path):
        return self.pages[path]

    def storage_upload(self, path, data, content_type):
        self.uploads[path] = data


def kind_of(kw: dict) -> str:
    if kw.get("require") == "systems":
        return "label"
    if kw.get("require") == "instruments":
        return "header"
    if kw.get("max_tokens") == getattr(pc, "RECHECK_MAX_TOKENS", 4000):
        return "recheck"
    return "other"


def recheck_verdict(said: dict) -> str:
    m = said.get("matches")
    if isinstance(m, str):
        m = m.strip().lower() in ("true", "yes", "y")
    return "yes" if m else "no"


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf", help="a PDF, or a folder of page PNGs (with --pngs)")
    ap.add_argument("--pngs", help="glob of page PNGs inside the folder, in name order (the saved 008 pages)")
    ap.add_argument("--pages", default="1-5")
    ap.add_argument("--instrument", default="Piano")
    ap.add_argument("--tag", required=True)
    ap.add_argument("--labels")
    ap.add_argument("--rechecks")
    ap.add_argument("--shadow", action="store_true")
    a = ap.parse_args()
    if a.labels and hasattr(pc, "LABEL_EFFORT"):
        pc.LABEL_EFFORT = a.labels
    if a.rechecks and hasattr(pc, "RECHECK_EFFORT"):
        pc.RECHECK_EFFORT = a.rechecks
    lo, _, hi = a.pages.partition("-")
    nums = list(range(int(lo), int(hi or lo) + 1))
    score = str(uuid.uuid4())
    if a.pngs:
        files = sorted(Path(a.pdf).glob(a.pngs))
        nums = list(range(1, len(files) + 1))
        pngs = {f"{score}/pages/{i}.png": f.read_bytes() for i, f in enumerate(files, start=1)}
    else:
        doc = pymupdf.open(a.pdf)
        pngs = {f"{score}/pages/{i}.png": render_page(doc[n - 1])[0] for i, n in enumerate(nums, start=1)}
    db = FakeDB()
    db.rows["sources"] = [{"id": "src1", "score_id": score, "kind": "images", "created_by": "u1", "storage_paths": list(pngs),
                           "page_order": list(range(1, len(nums) + 1)), "page_count": len(nums)}]
    db.rows["scores"] = [{"id": score, "title": Path(a.pdf).stem, "composer": None, "current_interpretation_id": None}]
    db.rows["interpretations"], db.rows["measure_placements"], db.rows["parts"] = [], [], []
    instruments = [x.strip() for x in a.instrument.split(",") if x.strip()]
    job = Job(str(uuid.uuid4()), "part_cut", {"score_id": score, "instruments": instruments, "max_cost_usd": 1.5}, score, "u1", 1, 3)
    db.rows["jobs"] = [{"id": job.id, "result": {}}]
    ctx = Ctx(job, db, pngs, f"step4 part_cut {a.tag}")

    calls: list[dict] = []
    pairs: list[dict] = []
    real = pc.ask_model

    async def wrapped(ctx_, client, model, prompt, png, **kw):
        k = kind_of(kw)
        t0 = time.monotonic()
        if a.shadow and kw.get("effort") == "minimal" and k in ("label", "recheck"):
            mn, low = await asyncio.gather(real(ctx_, client, model, prompt, png, **kw),
                                           real(ctx_, client, model, prompt, png, **{**kw, "effort": "low"}), return_exceptions=True)
            pairs.append({"kind": k, "prompt_head": prompt[:120], "minimal": None if isinstance(mn, BaseException) else {x: y for x, y in mn.items() if not x.startswith("_")},
                          "low": None if isinstance(low, BaseException) else {x: y for x, y in low.items() if not x.startswith("_")}})
            if isinstance(mn, BaseException):
                raise mn
            out = mn
        else:
            out = await real(ctx_, client, model, prompt, png, **kw)
        calls.append({"kind": k, "effort": kw.get("effort", "low"), "secs": round(time.monotonic() - t0, 2), "api": out.get("_api")})
        return out
    pc.ask_model = wrapped

    t0 = time.time()
    out = await pc.part_cut(job, ctx, client=_client("meta"), model=settings.meta_model)
    wall = time.time() - t0
    sc = ctx.result["agent"]["scratch"]
    commits = {k: {"staves": v["staves"], "rechecks": [{"block": r["block"], "verdict": r["verdict"]} for r in v.get("rechecks") or []]}
               for k, v in sc["commits"].items()}
    proposals = {n: [{"system": q["system"], "staves": q["staves"], "status": q.get("status"), "margin_labels": q.get("margin_labels"),
                      "remembered": bool(q.get("remembered"))} for q in p["proposal"]] for n, p in sc["pages"].items()}
    by_kind: dict[str, dict] = {}
    for c in calls:
        d = by_kind.setdefault(c["kind"], {"n": 0, "secs": 0.0})
        d["n"] += 1
        d["secs"] = round(d["secs"] + c["secs"], 1)
    rec = {"tag": a.tag, "pdf": a.pdf, "pages": nums, "instruments": instruments, "wall_s": round(wall, 1),
           "status": ctx.result["agent"]["status"], "turns": ctx.result["agent"].get("turn"), "questions": out.get("questions"),
           "question": out.get("question"), "systems_cut": out.get("systems_cut"), "absent": out.get("absent"),
           "cost_usd": round(sum(float(c.cost_usd) for c in ctx.charges), 4), "calls": by_kind, "call_log": calls,
           "efforts": {"labels": getattr(pc, "LABEL_EFFORT", "low"), "rechecks": getattr(pc, "RECHECK_EFFORT", "low")},
           "label_fallbacks": sc.get("label_fallbacks"), "commits": commits, "proposals": proposals, "pairs": pairs,
           "log": sc["log"]}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{a.tag}.json").write_text(json.dumps(rec, indent=1, default=str))
    print(json.dumps({k: rec[k] for k in ("tag", "wall_s", "status", "turns", "questions", "systems_cut", "absent", "cost_usd", "calls",
                                          "efforts", "label_fallbacks", "commits")}, indent=1, default=str))
    print(f"ledger ${ledger.spent():.4f}")


if __name__ == "__main__":
    asyncio.run(main())
