"""Folio benchmark (feature 016): accuracy and cost per combination on a fixed ten-page corpus.

Usage (from api/):
  uv run experiments/benchmark/run.py --grid grid.yaml --budget-meta 5 --budget-claude 5 [--dry-run]
      [--run NAME] [--retry-errors] [--report-only]

--grid resolves against the current directory, then experiments/benchmark/. The run's ledger and report go to
experiments/benchmark/runs/<NAME>/ (NAME defaults to the grid's `name`); running the same NAME again resumes:
calls with a record are never repeated. --dry-run renders and builds every image, then prints the call count per
cell and the estimated cost per provider without calling anything. Budgets are USD per provider for the whole run.
Needs api/.env (META_API_KEY, ANTHROPIC_API_KEY), the PDFs in api/fixtures/pdf (or FOLIO_PDF_DIR), and for OMR
the ssh alias `omr`.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))  # api/, so `app` and `experiments.benchmark` import

from experiments.benchmark import corpus as C  # noqa: E402
from experiments.benchmark import runner as R  # noqa: E402


def resolve(p: str) -> Path:
    path = Path(p)
    return path if path.exists() else HERE / p


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--grid", required=True)
    ap.add_argument("--budget-meta", type=float, required=True, help="USD for Muse Spark over the whole run")
    ap.add_argument("--budget-claude", type=float, required=True, help="USD for Claude over the whole run")
    ap.add_argument("--run", help="run name (folder under runs/); default: the grid's name")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--retry-errors", action="store_true", help="call again ids whose record is an API error (no cost)")
    ap.add_argument("--report-only", action="store_true", help="rewrite results.md from results.json, no calls")
    ap.add_argument("--rescore", action="store_true", help="recompute scores from stored answers (after a metric change), no calls")
    ap.add_argument("--only", action="append", metavar="FIELD=VALUE",
                    help="run a slice of the grid (task, page, item, model, effort, res); repeatable; the rest stays pending")
    a = ap.parse_args()

    grid_path = resolve(a.grid)
    grid = R.load_grid(grid_path)
    corpus = C.load_manifest(resolve(grid.corpus) if not Path(grid.corpus).is_absolute() else grid.corpus)
    name = a.run or grid.name
    run_dir = R.RUNS / name
    ledger = R.Ledger(run_dir / "results.json", name, {**grid.__dict__})
    limits = {"meta": a.budget_meta, "anthropic": a.budget_claude}

    if a.rescore:
        print(f"rescored {R.rescore(corpus, ledger, run_dir)} records")
    if a.report_only or a.rescore:
        print(R.write_report(ledger, run_dir, limits, spend=R.update_spend_file(name, ledger)))
        return

    p = R.plan(grid, corpus, ledger, retry_errors=a.retry_errors)
    n_pending = len(p.pending)
    if a.only:
        want = dict(kv.split("=", 1) for kv in a.only)
        fields = {"task": lambda c: c.task, "page": lambda c: c.item.page.id, "model": lambda c: c.model,
                  "effort": lambda c: c.effort, "res": lambda c: c.res, "item": lambda c: c.item.id}
        p.pending = [c for c in p.pending if all(fields[k](c) == v for k, v in want.items())]
    cells = Counter(c.cell for c in p.pending)
    est = Counter()
    for c in p.pending:
        est[c.provider] += p.estimates[c.id]
    print(f"grid {grid_path.name}: {len(p.calls)} calls in {len(Counter(c.cell for c in p.calls))} cells; "
          f"{len(p.calls) - n_pending} already in {run_dir / 'results.json'}; {len(p.pending)} to run"
          + (f" ({n_pending - len(p.pending)} left pending by --only)" if a.only else ""))
    for prov in ("meta", "anthropic", "omr"):
        n = sum(1 for c in p.pending if c.provider == prov)
        if n:
            lim = limits.get(prov)
            spent = ledger.spent(prov) if prov != "omr" else 0.0
            print(f"  {prov:9s} {n:4d} calls, estimated ${est[prov]:.3f}" +
                  (f" (spent ${spent:.4f}; budget ${lim:.2f}; {'fits' if spent + est[prov] <= lim else 'would stop at the budget'})" if lim is not None else " (free)"))
    if a.dry_run:
        for cell, n in sorted(cells.items()):
            print(f"    {'|'.join(cell)}: {n}")
        return

    run_dir.mkdir(parents=True, exist_ok=True)
    budget = asyncio.run(R.run(grid, corpus, ledger, limits, run_dir, p=p))
    spend = R.update_spend_file(name, ledger)
    print(R.write_report(ledger, run_dir, limits, stopped=budget.stopped, spend=spend))


if __name__ == "__main__":
    main()
