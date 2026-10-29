"""One measured run of Convert to Digital's librarian agent v2 (feature 005) through the real stage: the real OMR box
over ssh, the real Muse Spark, an in-memory store (the tests' StoreDB), no Supabase, no job row.

  uv run python experiments/omr/v2_run.py RUN_DIR PDF [--pages 1-5] [--cap 6.0] [--title "..."] [--composer "..."]
                                           [--text-gt goldberg_bga_text_gt.json] [--run-id v2-goldberg]

Writes RUN_DIR/final.musicxml, result.json (the handler's result), meta.json (the source row's meta), charges.json
(every model call), kinds.json, front.json, enrich.json (Spark's items per system, normalised), verify.json,
log.json (every write, duplicate and skip), and summary.json: text F1 against the ground truth (compare.py, strict and
within a bar), duplicates, whether the tempo line sits on bar 1, spend and seconds per page. With OMR_KEEP=1 the box
keeps ~/omr/folio/<run-id>/out (the 300 dpi scans, for the eye checks).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
API = HERE.parents[1]
sys.path.insert(0, str(API))

from anthropic import AsyncAnthropic  # noqa: E402

from app.librarian import Job  # noqa: E402
from app.librarian import omr_convert as oc  # noqa: E402
from app.librarian import omr_enrich  # noqa: E402
from app.settings import settings  # noqa: E402
from tests.test_part_split import StoreCtx, StoreDB  # noqa: E402

SCORE = "22222222-2222-2222-2222-222222222222"


def pages_arg(spec: str | None) -> list[int] | None:
    if not spec:
        return None
    out: list[int] = []
    for part in spec.split(","):
        lo, _, hi = part.partition("-")
        out += range(int(lo), int(hi or lo) + 1)
    return out


def meta_client() -> AsyncAnthropic:
    base = settings.meta_api_base_url.rstrip("/")
    base = base[:-3] if base.endswith("/v1") else base
    return AsyncAnthropic(api_key=settings.meta_api_key, base_url=base, max_retries=1)


def capture(run: Path, store: dict):
    """Wrap the stage's steps so their answers land on disk (the handler returns counts only)."""
    for name in ("page_kinds", "front_matter", "reread", "verify", "verify_edits"):
        fn = getattr(oc, name)

        async def wrapped(*a, _fn=fn, _name=name, **kw):
            res = await _fn(*a, **kw)
            store[_name] = res
            return res
        setattr(oc, name, wrapped)
    items_fn = oc.apply_text

    def items_wrapped(*a, **kw):
        log, counts = items_fn(*a, **kw)
        store.setdefault("log", []).extend(log)
        return log, counts
    oc.apply_text = items_wrapped
    front_fn = oc.apply_front

    def front_wrapped(*a, **kw):
        log = front_fn(*a, **kw)
        store.setdefault("log", []).extend(log)
        return log
    oc.apply_front = front_wrapped
    verify_fn = oc.apply_verify

    def verify_wrapped(*a, **kw):
        log, flags = verify_fn(*a, **kw)
        store.setdefault("log", []).extend(log)
        return log, flags
    oc.apply_verify = verify_wrapped


def junk_written(xml: bytes) -> dict:
    """Words in the file that are only digits/punctuation (plate or page numbers, fingering) or hairpin characters."""
    import html
    words = [html.unescape(w.decode()) for w in re.findall(rb"<words[^>]*>([^<]*)</words>", xml)]
    bad = [w for w in words if not re.search(r"[^\W\d_]", w) or "<" in w or ">" in w]
    return {"count": len(bad), "words": bad[:20]}


def dropped_reasons(reread: list[dict]) -> dict:
    out: dict[str, int] = {}
    for r in reread:
        for d in r.get("dropped") or []:
            k = d["why"].split(" (")[0][:60]
            out[k] = out.get(k, 0) + 1
    return out


def tempo_on_bar_1(xml: bytes, first: int) -> dict:
    m = re.search(rb'<measure[^>]*number="%d".*?</measure>' % first, xml, re.S)
    if not m:
        return {"bar": first, "found": False}
    dirs = [d for d in re.findall(rb"<direction\b.*?</direction>", m.group(0), re.S) if b"<metronome" in d or b"font-weight=\"bold\"" in d]
    words = [w.decode() for d in dirs for w in re.findall(rb"<words[^>]*>([^<]*)</words>", d)]
    per_minute = [p.decode() for d in dirs for p in re.findall(rb"<per-minute>([^<]*)</per-minute>", d)]
    return {"bar": first, "found": bool(dirs), "words": words, "per_minute": per_minute,
            "metronomes_in_file": xml.count(b"<metronome"), "one_direction": len(dirs) == 1}


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("run")
    ap.add_argument("pdf")
    ap.add_argument("--pages")
    ap.add_argument("--cap", type=float, default=6.0)
    ap.add_argument("--title", default="")
    ap.add_argument("--composer", default="")
    ap.add_argument("--text-gt")
    ap.add_argument("--run-id", default="v2-run")
    a = ap.parse_args()
    run = Path(a.run).resolve()
    run.mkdir(parents=True, exist_ok=True)
    pdf = Path(a.pdf).read_bytes()
    pages = pages_arg(a.pages)

    db = StoreDB({f"{SCORE}/source.pdf": pdf})
    db.rows["scores"] = [{"id": SCORE, "owner_user_id": "u1", "ensemble_id": None, "title": a.title or Path(a.pdf).stem, "composer": a.composer or None,
                          "key_sig": None, "meter": None, "bars": None, "work": None, "tempo_bpm": None, "status": "ready"}]
    db.rows["sources"] = [{"id": "pdf1", "score_id": SCORE, "kind": "pdf", "storage_paths": [f"{SCORE}/source.pdf"], "created_by": "u1"}]
    db.rows["parts"], db.rows["members"] = [], []
    payload = {"score_id": SCORE, "max_cost_usd": a.cap}
    if pages:
        payload["pages"] = pages
    job = Job(a.run_id, "omr_convert", payload, None, "u1", 1, 1)
    ctx = StoreCtx(job, db, {})
    store: dict = {}
    capture(run, store)

    t0 = time.time()
    out = await oc.omr_convert(job, ctx, box=oc.SshBox(), client=meta_client(), model=settings.meta_model)
    wall = time.time() - t0
    xml = db.storage.files[oc.digital_path(SCORE)]
    (run / "final.musicxml").write_bytes(xml)
    if out.get("cover"):
        (run / "cover.png").write_bytes(db.storage.files[out["cover"]])
    row = next(r for r in db.rows["sources"] if r["id"] == out["source_id"])
    (run / "result.json").write_text(json.dumps(out, indent=1))
    (run / "meta.json").write_text(json.dumps(row["meta"], indent=1))
    (run / "charges.json").write_text(json.dumps([{"model": c.model, "input": c.input_tokens, "output": c.output_tokens, "usd": float(c.cost_usd)} for c in ctx.charges], indent=1))
    for name in ("page_kinds", "front_matter", "reread", "verify", "verify_edits", "log"):
        (run / f"{ {'page_kinds': 'kinds', 'front_matter': 'front'}.get(name, name) }.json").write_text(json.dumps(store.get(name), indent=1, default=str))
    (run / "score_row.json").write_text(json.dumps(db.rows["scores"][0], indent=1))

    first = min(int(n) for n in re.findall(rb'<measure[^>]*number="(\d+)"', xml))
    summary: dict = {"pages": out["pages"], "page_kinds": out["page_kinds"], "bars": out["bars"], "wall_s": round(wall, 1),
                     "seconds_per_page": round(wall / max(len(out["pages"]), 1), 1), "timings": out["timings"],
                     "spark_calls": out["spark_calls"], "spark_skipped": out["spark_skipped"], "cost_usd": out["cost_usd"],
                     "cost_per_page": out["cost_per_page"], "cost_per_step": row["meta"]["cost"]["per_step"],
                     "items": out["items"], "duplicates": out["items"]["duplicates"], "flagged": len(out["flagged_bars"]),
                     "verify": out["verify"], "engraving": {k: v for k, v in out["engraving"].items() if k != "layouts"},
                     "verify_no": [{"page": l.get("page"), "system": l.get("system"), "named": l.get("named"), "reason": l.get("reason")}
                                   for l in (store.get("verify_edits") or {}).get("log", []) if l.get("same") is False],
                     "junk_written": junk_written(xml), "dropped_by_reason": dropped_reasons(store.get("reread") or []),
                     "front_matter": out["front_matter"], "tempo_bar_1": tempo_on_bar_1(xml, first), "score_row": db.rows["scores"][0]}
    if a.text_gt:
        cmp = run / "compare.json"
        r = subprocess.run([sys.executable, str(HERE / "compare.py"), str(cmp), "--text-gt", a.text_gt, "--score", str(run / "final.musicxml"),
                            "--bars", f"{first}-{first + out['bars'] - 1}", "--label", "v2"], capture_output=True, text=True)
        print(r.stdout[-2000:], r.stderr[-800:] if r.returncode else "")
        if cmp.exists():
            c = json.loads(cmp.read_text())
            summary["text_strict"], summary["text_near"] = c.get("text_strict"), c.get("text_near")
    (run / "summary.json").write_text(json.dumps(summary, indent=1))
    for k, v in summary.items():
        print(f"{k}: {json.dumps(v) if not isinstance(v, (int, float, str)) else v}")


if __name__ == "__main__":
    asyncio.run(main())
