"""Summarise a v2_run.py convert run for the speed pass and copy its charges into the ledger (once per run dir).

    uv run python -m experiments.speed_pass.convert_sum <run_dir> <tag>
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from . import ledger


def main(run: Path, tag: str) -> dict:
    s = json.loads((run / "summary.json").read_text())
    res = json.loads((run / "result.json").read_text())
    ve = json.loads((run / "verify_edits.json").read_text()) or {}
    charges = json.loads((run / "charges.json").read_text())
    marker = run / ".logged"
    if not marker.exists():
        for c in charges:
            ledger.log(source="v2_run charges", tag=tag, run=run.name, model=c["model"], input_tokens=c["input"],
                       output_tokens=c["output"], usd=c["usd"])
        marker.write_text("1")
    decisions = {f"p{l['page']}s{l['system']}": l.get("same") for l in ve.get("log", []) if l.get("asked")}
    out = {"run": run.name, "wall_s": s["wall_s"], "timings": s["timings"], "cost_usd": s["cost_usd"], "calls": s["spark_calls"],
           "bars": s["bars"], "flagged": s["flagged"], "text_strict": s.get("text_strict"),
           "verify": {"asked": res["verify"].get("asked"), "reverted": res["verify"].get("reverted"), "missing": res["verify"].get("missing")},
           "verify_decisions": decisions, "items": s["items"]["written"], "per_step": s["cost_per_step"]}
    print(json.dumps(out, indent=1))
    return out


if __name__ == "__main__":
    main(Path(sys.argv[1]), sys.argv[2])
