"""Mac side of the OMR run, end to end over one run directory. The box side comes first:

  scp api/experiments/omr/book_box.py omr:omr/folio005/scripts/
  ssh omr 'python3 -I ~/omr/folio005/scripts/book_box.py ~/muse/api/fixtures/pdf/goldberg-bga.pdf \
           ~/omr/folio005/p1-5/audiveris --pages 1-5'
  scp -r omr:omr/folio005/p1-5/audiveris RUN_DIR/          (and the 300 dpi scans into RUN_DIR/scan/page300-0N.png)

Then: uv run python experiments/omr/pipeline.py RUN_DIR [--cap 2.0] [--gate 0.6 --gate-tag tuplet=0.9]
      [--notes-gt gt.json] [--text-gt goldberg_bga_text_gt.json] [--skip-spark] [--refresh-verify]

Steps: audiveris_model (bar map + grade gate) -> spark_layers (A verify, B reread; skipped when verify.json and
reread.json exist, or --skip-spark) -> score (one file, global bar numbers) -> apply_edits -> review (flags,
page slices) -> render (Verovio, flattened onto white) -> compare -> run.json -> build_review (review.html).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent


def py(*args: str, extra: tuple[str, ...] = ()) -> str:
    cmd = (["uv", "run", *extra, "python"] if extra else [sys.executable]) + [str(a) for a in args]
    r = subprocess.run(cmd, capture_output=True, text=True)
    out = r.stdout + ("\n" + r.stderr if r.returncode else "")
    print(f"$ {' '.join(Path(c).name if '/' in c else c for c in cmd)}\n{out.strip()[-3000:]}\n")
    if r.returncode:
        raise SystemExit(f"step failed: {args[0]}")
    return r.stdout


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("run")
    ap.add_argument("--cap", default="2.0")
    ap.add_argument("--gate", default="0.6")
    ap.add_argument("--gate-tag", action="append", default=[])
    ap.add_argument("--notes-gt")
    ap.add_argument("--text-gt", default=str(HERE / "goldberg_bga_text_gt.json"))
    ap.add_argument("--skip-spark", action="store_true")
    ap.add_argument("--refresh-verify", action="store_true", help="re-run A after moving the gate (cached answers reused)")
    ap.add_argument("--title", default="Goldberg BGA pages 1 to 5: Audiveris 5.11 + Muse Spark")
    a = ap.parse_args()
    run = Path(a.run).resolve()
    aud = run / "audiveris"
    book_run = json.load(open(aud / "book_run.json"))

    gate_args = ["--gate", a.gate] + [x for t in a.gate_tag for x in ("--gate-tag", t)]
    py(HERE / "audiveris_model.py", aud / "book", aud / "movements.json", run / "model.json", *gate_args)
    if not a.skip_spark and not ((run / "verify.json").exists() and (run / "reread.json").exists()):
        py(HERE / "spark_layers.py", run, "--cap", a.cap)
    else:
        if a.refresh_verify:  # a moved gate: ask only the symbols it newly lets in (answers are cached)
            py(HERE / "spark_layers.py", run, "--only", "verify", "--cap", a.cap)
        py(HERE / "spark_layers.py", run, "--place-only")
    movements = sorted(aud.glob("*.mvt*.mxl"), key=lambda p: int(p.name.rsplit("mvt", 1)[1].split(".")[0])) or sorted(aud.glob("*.mxl"))
    py(HERE / "score.py", run / "model.json", run / "base.musicxml", *movements)
    py(HERE / "apply_edits.py", run)
    py(HERE / "review.py", run)
    model = json.load(open(run / "model.json"))
    slices = [run / "slices" / f"final-p{p['page']}.musicxml" for p in model["pages"]]
    rendered = py(HERE / "render.py", run / "render", *slices, extra=("--with", "verovio", "--with", "resvg-py"))
    notes = ["--notes-gt", a.notes_gt] if a.notes_gt else []
    py(HERE / "compare.py", run / "compare-final.json", "--score", run / "final.musicxml", "--text-gt", a.text_gt,
       "--reread", run / "reread.json", "--label", "final (A+B)", *notes)
    py(HERE / "compare.py", run / "compare-base.json", "--score", run / "base.musicxml", "--text-gt", a.text_gt,
       "--label", "Audiveris alone", *notes)

    spend = json.load(open(run / "spend.json")) if (run / "spend.json").exists() else {"total_usd": 0, "calls": []}
    timings = json.load(open(run / "spark_timings.json")) if (run / "spark_timings.json").exists() else {}
    final, base = json.load(open(run / "compare-final.json")), json.load(open(run / "compare-base.json"))
    flags = json.load(open(run / "flags.json"))
    fails = {ln.split(":")[0]: ln for ln in rendered.splitlines() if "FAILED" in ln or "TIMEOUT" in ln}
    names = {m["movement"]: m["name"] for m in model["movements"]}
    pages = {}
    for p in flags:
        mv = ", ".join(f"mvt {k}" + (f" ({names[k]})" if names.get(k) else "") for k in p["movements"])
        pages[str(p["page"])] = {"content": mv, "render_error": fails.get(f"final-p{p['page']}.musicxml")}
    summary = {
        "pages": f"{len(model['pages'])} (PDF pages {book_run['pdf_pages'][0]} to {book_run['pdf_pages'][-1]})",
        "bars": f"{len(model['measures'])} ({model['measures'][0]['number']} to {model['measures'][-1]['number']}), "
                + ", ".join(str(p["bars"]) for p in flags) + " per page",
        "movements (Audiveris)": "; ".join(f"{m['movement']}: {m['name'] or '-'} bars {m['first_number']}-{m['last_number']}" for m in model["movements"]),
        "Audiveris": f"{book_run['audiveris_s']} s for the book, exports {', '.join(book_run['exports'])}",
        "abnormal bars": sum(m["abnormal"] for m in model["measures"]),
        "flagged bars": sum(len(p["flags"]) for p in flags),
        "grade gate": f"{model['gate']['default']} {model['gate']['per_tag'] or ''}: {len(model['doubtful'])} asked, "
                      f"{len(model['gate_skipped'])} skipped (tuplets skipped: "
                      + ", ".join(f"m{d['number']} {d['grade']:.2f}" for d in model["gate_skipped"] if d["tag"] == "tuplet") + ")",
        "Spark": f"{len(spend['calls'])} calls, ${spend['total_usd']:.3f}; "
                 + "; ".join(f"{k} {v['calls']} calls ${v['cost_usd']} {v['wall_s']} s wall ({v['sum_latency_s']} s summed)" for k, v in timings.items()),
        "text F1 strict (Audiveris alone -> final)": f"{base['text_strict']['f1']} -> {final['text_strict']['f1']} "
                                                    f"(P {final['text_strict']['p']}, R {final['text_strict']['r']})",
        "text F1 near (±1 bar)": f"{base['text_near']['f1']} -> {final['text_near']['f1']}",
    }
    if "aria_notes" in final:
        fa, ba = final["aria_notes"], base["aria_notes"]
        summary["Aria notes (bars 1-32)"] = (f"pitch F1 {ba['pitch']['f1']} -> {fa['pitch']['f1']}, onset+pitch {ba['onset_pitch']['f1']} -> "
                                             f"{fa['onset_pitch']['f1']}, full {ba['full']['f1']} -> {fa['full']['f1']}, ornaments "
                                             f"{fa['ornaments']['tp']}/{fa['ornaments']['gold']} at P {fa['ornaments']['p']}")
    if "placement_methods" in final:
        summary["text placement (strict F1)"] = ", ".join(f"{k} {v['strict']['f1']}" for k, v in final["placement_methods"].items())
    json.dump({"title": a.title, "summary": summary, "pages": pages}, open(run / "run.json", "w"), indent=1)
    py(HERE / "build_review.py", run)
    for k, v in summary.items():
        print(f"{k}: {v}")


if __name__ == "__main__":
    main()
