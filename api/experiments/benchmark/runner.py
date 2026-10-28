"""Grid expansion, the ledger (results.json), the budget guard, the run loop and the report.

A grid cell is (task, model, effort, resolution) for the model tasks and (omr, engine, -, resolution) for the
engines; a call is a cell on one item (a page, a system, a symbol). Every call has a stable id
`task|item|model|effort|resolution`. The ledger keeps one record per id and is written after every call, so a
run can stop anywhere and resume: an id with a record is never called again (an `error` record, which cost
nothing, is retried only with --retry-errors). The budget is per provider over the whole run (resumed calls
included): a call starts only when what the run has spent, plus what is in flight, plus this call's estimate
stays within the budget; the first call that would not fit stops that provider cleanly (in-flight calls finish,
nothing more starts).
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

import yaml

from . import corpus as C
from . import metrics as M
from . import models
from . import omr as O
from . import tasks as T

HERE = Path(__file__).resolve().parent
RUNS = HERE / "runs"
SPEND = HERE / "spend.json"
SPARK_MIN_TOKENS = 8000  # Spark's reasoning counts against max_tokens; JSON needs at least 8k (005, 008)


# ---------------------------------------------------------------- grid

@dataclass
class Grid:
    name: str
    corpus: str
    tasks: list[str]
    models: list[str]
    efforts: list[str]
    resolutions: list[str]
    max_tokens: int = 16000
    omr: dict[str, Any] = field(default_factory=dict)
    concurrency: dict[str, int] = field(default_factory=lambda: {"meta": 4, "anthropic": 6, "omr": 2})


def load_grid(path: str | Path) -> Grid:
    raw = yaml.safe_load(Path(path).read_text())
    g = Grid(name=raw.get("name") or Path(path).stem, corpus=raw.get("corpus", "corpus/manifest.yaml"),
             tasks=list(raw.get("tasks") or []), models=list(raw.get("models") or []),
             efforts=list(raw.get("efforts") or ["low"]),  # Spark's rule: effort low unless the grid says otherwise
             resolutions=list(raw.get("resolutions") or ["150dpi"]), max_tokens=int(raw.get("max_tokens", 16000)),
             omr=raw.get("omr") or {}, concurrency={"meta": 4, "anthropic": 6, "omr": 2, **(raw.get("concurrency") or {})})
    for t in g.tasks:
        if t in T.NOTES_TASKS or t not in T.MODEL_TASKS:
            raise ValueError(f"task {t!r} is not a model task (notes go to the OMR engines only)")
    for r in g.resolutions:
        if r not in C.RESOLUTIONS:
            raise ValueError(f"unknown resolution {r!r}")
    for r in g.omr.get("resolutions") or []:
        if r not in C.RESOLUTIONS and r != "pdf":  # "pdf": the engine rasterises the PDF page itself
            raise ValueError(f"unknown OMR input {r!r}")
    for e in g.efforts:
        if e not in ("low", "medium", "high"):
            raise ValueError(f"unknown effort {e!r}")
    if any(models.provider_of(m) == "meta" for m in g.models) and g.max_tokens < SPARK_MIN_TOKENS:
        raise ValueError(f"max_tokens {g.max_tokens} < {SPARK_MIN_TOKENS}: Spark's JSON needs the 8k budget")
    for e in g.omr.get("engines") or []:
        if e not in O.ENGINES:
            raise ValueError(f"unknown engine {e!r}")
    return g


@dataclass(frozen=True)
class Call:
    task: str
    item: T.Item
    model: str          # model id, or the engine for omr
    effort: str         # "-" for omr
    res: str

    @property
    def id(self) -> str:
        return f"{self.task}|{self.item.id}|{self.model}|{self.effort}|{self.res}"

    @property
    def provider(self) -> str:
        return "omr" if self.task == "omr" else models.provider_of(self.model)

    @property
    def cell(self) -> tuple[str, str, str, str]:
        return (self.task, self.model, self.effort, self.res)


EFFORT_RANK = {"low": 0, "medium": 1, "high": 2, "-": 0}


def expand(grid: Grid, corpus: C.Corpus) -> list[Call]:
    """Every call of the grid, cheapest-first (effort low first) so a budget stop leaves whole low cells."""
    calls: list[Call] = []
    for task in grid.tasks:
        for item in T.items(corpus, task):
            for m in grid.models:
                for e in grid.efforts:
                    for r in grid.resolutions:
                        calls.append(Call(task, item, m, e, r))
    for pid in grid.omr.get("pages") or []:
        page = corpus.pages[pid]
        for eng in grid.omr.get("engines") or []:
            for r in grid.omr.get("resolutions") or grid.resolutions:
                calls.append(Call("omr", T.Item("omr", pid, page), eng, "-", r))
    calls.sort(key=lambda c: (EFFORT_RANK[c.effort], c.task == "omr", c.res, c.model, c.task, c.item.id))
    ids = [c.id for c in calls]
    if len(ids) != len(set(ids)):
        raise ValueError("grid expands to duplicate call ids")
    return calls


# ---------------------------------------------------------------- ledger and budget

class Ledger:
    """results.json: {"run", "grid", "records": {call id: record}}, rewritten atomically after every call."""

    def __init__(self, path: Path, run: str, grid: dict):
        self.path = path
        self.data = json.loads(path.read_text()) if path.exists() else {"run": run, "grid": grid, "records": {}}
        self.data["grid"] = grid

    @property
    def records(self) -> dict[str, dict]:
        return self.data["records"]

    def done(self, call_id: str, retry_errors: bool = False) -> bool:
        r = self.records.get(call_id)
        return r is not None and not (retry_errors and r.get("status") == "error")

    def add(self, rec: dict) -> None:
        self.records[rec["id"]] = rec
        self.save()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=1, ensure_ascii=False, default=str))
        os.replace(tmp, self.path)

    def spent(self, provider: str) -> float:
        return round(sum(float(r.get("cost_usd") or 0) for r in self.records.values() if r.get("provider") == provider), 6)


class Budget:
    def __init__(self, limits: dict[str, float], ledger: Ledger):
        self.limits, self.ledger = limits, ledger
        self.inflight: dict[str, float] = defaultdict(float)
        self.stopped: dict[str, str] = {}

    def try_reserve(self, provider: str, est: float) -> bool:
        if provider not in self.limits:
            return True
        if provider in self.stopped:
            return False
        if self.ledger.spent(provider) + self.inflight[provider] + est > self.limits[provider]:
            self.stopped[provider] = (f"budget stop: spent ${self.ledger.spent(provider):.4f} + in flight "
                                      f"${self.inflight[provider]:.4f} + next ${est:.4f} > ${self.limits[provider]:.2f}")
            return False
        self.inflight[provider] += est
        return True

    def release(self, provider: str, est: float) -> None:
        if provider in self.limits:
            self.inflight[provider] = max(0.0, self.inflight[provider] - est)


def estimate(call: Call, ledger: Ledger, image_px: tuple[int, int]) -> float:
    """Mean cost of this (task, model, effort) so far in the run, else the prior in models.estimate_usd."""
    if call.provider == "omr":
        return 0.0
    same = [float(r["cost_usd"]) for r in ledger.records.values()
            if r.get("task") == call.task and r.get("model") == call.model and r.get("effort") == call.effort
            and r.get("status") in ("ok", "json_fail") and r.get("cost_usd")]
    if same:
        return sum(same) / len(same)
    return models.estimate_usd(call.model, call.task, call.effort, image_px)


def update_spend_file(run: str, ledger: Ledger, path: Path = SPEND) -> dict:
    """Cumulative spend across runs: each run's totals recomputed from its ledger, the grand total their sum."""
    data = json.loads(path.read_text()) if path.exists() else {"runs": {}}
    data["runs"][run] = {"meta_usd": ledger.spent("meta"), "anthropic_usd": ledger.spent("anthropic"),
                         "calls": len(ledger.records), "updated": time.strftime("%Y-%m-%dT%H:%M:%S")}
    data["total"] = {k: round(sum(r[k] for r in data["runs"].values()), 6) for k in ("meta_usd", "anthropic_usd")}
    path.write_text(json.dumps(data, indent=1))
    return data


# ---------------------------------------------------------------- the calls

AskFn = Callable[..., Awaitable[models.Answer]]


async def model_call(call: Call, corpus: C.Corpus, req: T.Request, grid: Grid, ask: AskFn) -> dict:
    rec = base_record(call)
    rec.update({"image_px": list(req.image_px), "image_bytes": len(req.image), "media_type": req.media_type})
    try:
        ans = await ask(call.model, req.system, req.prompt, req.image, req.media_type, effort=call.effort,
                        max_tokens=grid.max_tokens, require=req.require)
    except Exception as e:  # noqa: BLE001 - transport/API errors are recorded (cost 0) and can be retried
        rec.update({"status": "error", "error": f"{type(e).__name__}: {str(e)[:400]}", "cost_usd": 0.0})
        return rec
    rec.update({"cost_usd": ans.cost_usd, "latency_s": ans.latency_s, "attempts": ans.attempts,
                "json_fail_first": ans.json_fail_first, "raw_text": ans.text[:4000]})
    if ans.parsed is not None:
        rec["status"] = "ok"
        rec["answer"] = ans.parsed
        try:
            rec["score"] = T.score(corpus, call.item, ans.parsed)
        except Exception as e:  # noqa: BLE001 - a well-formed but odd answer scores zero, the reason is kept
            rec["score"], rec["score_error"] = T.zero_score(corpus, call.item), f"{type(e).__name__}: {e}"
    else:
        rec["status"] = "refusal" if ans.refusal else "json_fail"
        rec["score"] = T.zero_score(corpus, call.item)
    return rec


def omr_call(call: Call, corpus: C.Corpus, run_dir: Path, engine_fn=None) -> dict:
    rec = base_record(call)
    page = call.item.page
    png = None if call.res == "pdf" else C.page_png_path(page, call.res)
    pdf = (corpus.scores[page.score]["pdf"], page.page) if call.res == "pdf" else None
    key = f"{run_dir.name}/{page.id}@{call.res}-{call.model}"
    try:
        out = (engine_fn or O.run_engine)(call.model, png, key, run_dir / "omr" / f"{page.id}@{call.res}-{call.model}", pdf=pdf)
    except O.EngineStub as e:
        rec.update({"status": "stub", "error": str(e), "cost_usd": 0.0})
        return rec
    except Exception as e:  # noqa: BLE001
        rec.update({"status": "error", "error": f"{type(e).__name__}: {str(e)[:400]}", "cost_usd": 0.0})
        return rec
    rec.update({"cost_usd": 0.0, "latency_s": out.get("wall_s"), "engine_s": out.get("engine_s"),
                "files": [str(Path(f).relative_to(run_dir)) if str(f).startswith(str(run_dir)) else f for f in out.get("files", [])],
                "warnings": out.get("warnings"), "status": "ok" if out.get("status") == "ok" else "engine_fail",
                "json_fail_first": False})
    rec.update(score_omr(corpus, page, out.get("files") or []))
    return rec


def score_omr(corpus: C.Corpus, page: C.Page, files: list[str]) -> dict:
    """Pitch scores of an engine's exports against the page's GT bars ({} when the page has no OMR GT).
    Bars are matched by the engine's own measure numbers, so a missed barline costs the merged bars."""
    gt = page.gt.get("omr")
    if not gt:
        return {}
    bars = range(gt["bars"][0], gt["bars"][1] + 1)
    pred: dict = {}
    for f in files:
        pred.update(O.mxl_bars(f))
    out: dict = {"score": M.score_omr_bars(pred, M.gold_omr_bars(corpus.load(gt["file"]), bars), bars)}
    if files:
        out["bars_found"] = sorted(b for b in pred if b in bars)
    return out


def rescore(corpus: C.Corpus, ledger: Ledger, run_dir: Path) -> int:
    """Recompute every score from the stored answers and exports (after a metric change; no calls)."""
    items = {(t, i.id): i for t in T.MODEL_TASKS for i in T.items(corpus, t)}
    n = 0
    for r in ledger.records.values():
        if r["task"] == "omr":
            if r.get("status") == "ok":
                r.update(score_omr(corpus, corpus.pages[r["page"]], [str(run_dir / f) for f in r.get("files") or []]))
                n += 1
            continue
        item = items.get((r["task"], r["item"]))
        if item is None:
            continue
        if r.get("status") == "ok":
            try:
                r["score"] = T.score(corpus, item, r["answer"])
                r.pop("score_error", None)
            except Exception as e:  # noqa: BLE001
                r["score"], r["score_error"] = T.zero_score(corpus, item), f"{type(e).__name__}: {e}"
        elif r.get("status") in ("json_fail", "refusal"):
            r["score"] = T.zero_score(corpus, item)
        n += 1
    ledger.save()
    return n


def base_record(call: Call) -> dict:
    return {"id": call.id, "task": call.task, "item": call.item.id, "page": call.item.page.id, "model": call.model,
            "provider": call.provider, "effort": call.effort, "resolution": call.res, "ts": time.strftime("%Y-%m-%dT%H:%M:%S")}


# ---------------------------------------------------------------- the run

@dataclass
class Plan:
    calls: list[Call]
    pending: list[Call]
    requests: dict[tuple[str, str, str], T.Request]
    estimates: dict[str, float]


def plan(grid: Grid, corpus: C.Corpus, ledger: Ledger, *, retry_errors: bool = False, build=None) -> Plan:
    """Expand, drop what the ledger has, render pages and build every image the pending calls need."""
    calls = expand(grid, corpus)
    pending = [c for c in calls if not ledger.done(c.id, retry_errors)]
    if build is None:
        C.ensure_pages(corpus, [(corpus.pages[pid], r) for pid, r in sorted({(c.item.page.id, c.res) for c in pending if c.res != "pdf"})])
        build = lambda c: T.build(corpus, c.item, c.res)  # noqa: E731
    requests: dict[tuple[str, str, str], T.Request] = {}
    for c in pending:
        if c.task != "omr" and (c.task, c.item.id, c.res) not in requests:
            requests[(c.task, c.item.id, c.res)] = build(c)
    est = {c.id: (0.0 if c.task == "omr" else estimate(c, ledger, requests[(c.task, c.item.id, c.res)].image_px)) for c in pending}
    return Plan(calls, pending, requests, est)


async def run(grid: Grid, corpus: C.Corpus, ledger: Ledger, limits: dict[str, float], run_dir: Path, *,
              p: Plan, ask: AskFn = models.ask, engine_fn=None, log=print) -> Budget:
    budget = Budget(limits, ledger)
    sems = {k: asyncio.Semaphore(max(1, int(v))) for k, v in grid.concurrency.items()}
    lock = asyncio.Lock()
    counter = {"n": 0}

    async def one(c: Call) -> None:
        async with sems[c.provider]:
            async with lock:
                if ledger.done(c.id):  # a resumed id, or a duplicate in flight
                    return
                est = estimate(c, ledger, p.requests[(c.task, c.item.id, c.res)].image_px) if c.task != "omr" else 0.0
                if not budget.try_reserve(c.provider, est):
                    return
            try:
                if c.task == "omr":
                    rec = await asyncio.to_thread(omr_call, c, corpus, run_dir, engine_fn)
                else:
                    rec = await model_call(c, corpus, p.requests[(c.task, c.item.id, c.res)], grid, ask)
            finally:
                budget.release(c.provider, est)
            async with lock:
                ledger.add(rec)
                counter["n"] += 1
                acc = M.accuracy(rec.get("score") or {}) if rec.get("score") else {}
                log(f"[{counter['n']}/{len(p.pending)}] {c.id} {rec['status']} ${float(rec.get('cost_usd') or 0):.4f} "
                    f"{rec.get('latency_s')}s {json.dumps(acc) if acc else ''}")

    await asyncio.gather(*(one(c) for c in p.pending))
    for prov, why in budget.stopped.items():
        log(f"{prov}: {why}")
    return budget


# ---------------------------------------------------------------- report

def cell_rows(ledger: Ledger) -> list[dict]:
    by: dict[tuple, list[dict]] = defaultdict(list)
    for r in ledger.records.values():
        by[(r["task"], r["model"], r["effort"], r["resolution"])].append(r)
    rows = []
    for (task, model, effort, res), recs in sorted(by.items(), key=lambda kv: (kv[0][0], kv[0][1], EFFORT_RANK.get(kv[0][2], 9), kv[0][3])):
        agg = M.aggregate(recs)
        rows.append({"task": task, "model": model, "effort": effort, "resolution": res, **agg,
                     "status": dict(sorted(_count(r.get("status") for r in recs).items()))})
    return rows


def _count(xs) -> dict:
    out: dict = defaultdict(int)
    for x in xs:
        out[x] += 1
    return out


def fmt_acc(task: str, acc: dict) -> str:
    if task == "header":
        return f"staves {acc.get('staves_ok')}, instruments {acc.get('instruments_ok')}, boxes {acc.get('box_acc')}"
    if task == "labels":
        return f"systems {acc.get('label_acc')}, pages {acc.get('pages_ok')}"
    if task == "text":
        p, r, f = acc.get("text_prf", (None,) * 3)
        return f"text F1 {f} (P {p} R {r})"
    if task == "closed":
        return f"right {acc.get('closed_acc')}"
    if task == "omr":
        if "pitch_prf" not in acc:
            return "no GT"
        return f"pitch F1 {acc['pitch_prf'][2]}, onset+pitch F1 {acc['onset_pitch_prf'][2]}"
    return json.dumps(acc)


def write_report(ledger: Ledger, run_dir: Path, limits: dict[str, float], stopped: dict[str, str] | None = None,
                 spend: dict | None = None) -> str:
    rows = cell_rows(ledger)
    lines = [f"# Benchmark run `{ledger.data['run']}`", "",
             f"Updated {time.strftime('%Y-%m-%d %H:%M')}. {len(ledger.records)} calls in the ledger. "
             f"Spend this run: Meta ${ledger.spent('meta'):.4f} of ${limits.get('meta', 0):.2f}, "
             f"Claude ${ledger.spent('anthropic'):.4f} of ${limits.get('anthropic', 0):.2f}.", ""]
    if stopped:
        lines += [f"- {k}: {v}" for k, v in stopped.items()] + [""]
    lines += ["| task | model | effort | res | items | accuracy | $ total | $ / item | s / item | JSON fail (1st try) | unparsed | errors |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        if r["task"] == "omr":
            continue
        n = r["calls"] or 1
        lines.append(f"| {r['task']} | {r['model']} | {r['effort']} | {r['resolution']} | {r['calls']} | {fmt_acc(r['task'], r['accuracy'])} "
                     f"| {r['cost_usd']:.4f} | {r['cost_usd'] / n:.4f} | {r['latency_s_mean']} | {r['json_fail_rate']} | {r['json_fail_final']} | {r['errors']} |")
    omr_rows = [r for r in rows if r["task"] == "omr"]
    if omr_rows:
        lines += ["", "| OMR engine | input | pages | status | accuracy (Goldberg p1, bars 1-28) | p1 bars found | s / page |", "|---|---|---|---|---|---|---|"]
        for r in omr_rows:
            recs = [x for x in ledger.records.values() if x["task"] == "omr" and x["model"] == r["model"] and x["resolution"] == r["resolution"]]
            lat = [float(x["latency_s"]) for x in recs if x.get("latency_s")]
            acc = M.accuracy(_sum_scores(recs))
            found = [len(x["bars_found"]) for x in recs if x.get("bars_found") is not None]
            lines.append(f"| {r['model']} | {r['resolution']} | {len(recs)} | {', '.join(f'{k} {v}' for k, v in r['status'].items())} "
                         f"| {fmt_acc('omr', acc) if r['model'] != 'homr' else '-'} | {found[0] if found else '-'} "
                         f"| {round(sum(lat) / len(lat), 1) if lat else '-'} |")
    if spend:
        lines += ["", f"Cumulative spend (spend.json, all runs): Meta ${spend['total']['meta_usd']:.4f}, Claude ${spend['total']['anthropic_usd']:.4f}."]
    text = "\n".join(lines) + "\n"
    (run_dir / "results.md").write_text(text)
    return text


def _sum_scores(recs: list[dict]) -> dict:
    t: dict = defaultdict(int)
    for r in recs:
        for k, v in (r.get("score") or {}).items():
            if isinstance(v, (int, float)):
                t[k] += v
    return dict(t)
