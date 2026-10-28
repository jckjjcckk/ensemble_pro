"""Benchmark tool (experiments/benchmark, feature 016): manifest loader, metrics, budget stop, resume. No network,
no PDFs: images are faked and the model is a scripted function."""
from __future__ import annotations

import asyncio
import json
from collections import Counter
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from experiments.benchmark import corpus as C
from experiments.benchmark import metrics as M
from experiments.benchmark import models
from experiments.benchmark import runner as R
from experiments.benchmark import tasks as T

MANIFEST = Path(__file__).resolve().parent.parent / "experiments" / "benchmark" / "corpus" / "manifest.yaml"


# ---------------------------------------------------------------- manifest

def test_manifest_loads_ten_pages_at_most_five_per_file():
    corpus = C.load_manifest(MANIFEST)
    assert len(corpus.pages) == 10
    per_file = Counter(corpus.scores[p.score]["pdf"] for p in corpus.pages.values())
    assert max(per_file.values()) <= 5
    assert {p.id for p in corpus.pages_with("labels")} == {
        "rach1-gutheil-p01", "rach1-gutheil-p02", "rach1-gutheil-p03",
        "beethoven9-p172", "beethoven9-p173", "beethoven9-p174", "beethoven9-p175"}
    assert len(T.items(corpus, "closed")) == 11
    assert len(T.items(corpus, "text")) == 6


def _write_manifest(tmp_path: Path, pages: list[dict], geom: dict | None = None) -> Path:
    (tmp_path / "g.json").write_text(json.dumps(geom or {"image_px": [100, 100], "staves": [],
                                                         "systems": [{"index": 1, "staff_indices": [1, 2]}]}))
    m = {"version": 1, "scores": {"s": {"pdf": "s.pdf"}}, "pages": pages}
    path = tmp_path / "manifest.yaml"
    path.write_text(yaml.safe_dump(m))
    return path


def test_manifest_rejects_duplicates_too_many_pages_and_bad_staff_numbers(tmp_path):
    with pytest.raises(ValueError, match="duplicate"):
        C.load_manifest(_write_manifest(tmp_path, [{"id": "a", "score": "s", "page": 1}] * 2))
    with pytest.raises(ValueError, match="more than 5"):
        C.load_manifest(_write_manifest(tmp_path, [{"id": f"p{i}", "score": "s", "page": i} for i in range(6)]))
    with pytest.raises(ValueError, match="not in system"):
        C.load_manifest(_write_manifest(tmp_path, [{"id": "a", "score": "s", "page": 1, "geom": "g.json",
                                                    "gt": {"labels": {"instrument": "Piano", "systems": {1: [3]}}}}]))
    with pytest.raises(ValueError, match="needs frozen geometry"):
        C.load_manifest(_write_manifest(tmp_path, [{"id": "a", "score": "s", "page": 1, "gt": {"header": {"staves": 2}}}]))
    ok = C.load_manifest(_write_manifest(tmp_path, [{"id": "a", "score": "s", "page": 1, "geom": "g.json",
                                                     "gt": {"labels": {"instrument": "Piano", "systems": {1: "absent"}}}}]))
    assert ok.pages["a"].gt["labels"]["systems"][1] == "absent"


# ---------------------------------------------------------------- metrics

def test_prf_and_text_score_with_one_bar_fuzz():
    assert M.prf(0, 0, 3) == (0.0, 0.0, 0.0)
    assert M.prf(2, 4, 2) == (0.5, 1.0, 0.667)
    gt = {1: ["p", "dolce"], 9: ["cresc."]}
    # "cresc" written one bar late still counts; "Cresc." normalises; "f" is a false positive
    s = M.score_text({1: ["p dolce"], 8: ["cresc."], 9: ["f"]}, gt, range(1, 10))
    assert s == {"tp": 2, "pred": 4, "gold": 3}
    assert M.score_text({}, gt, [1]) == {"tp": 0, "pred": 0, "gold": 2}


def test_labels_score_absent_and_wrong():
    gt = {"instrument": "Piano", "systems": {1: [6, 7], 2: "absent"}}
    assert M.score_labels({"systems": [{"index": 1, "wanted_staves": [7, 6]}, {"index": 2, "wanted_staves": [], "status": "absent"}]}, gt)["page_ok"] == 1
    s = M.score_labels({"systems": [{"index": 1, "wanted_staves": [6, 7]}, {"index": 2, "wanted_staves": [18, 19], "status": "playing"}]}, gt)
    assert (s["systems_ok"], s["page_ok"], s["wrong"]) == (1, 0, {2: [18, 19]})
    assert M.score_labels({"systems": []}, gt)["systems_ok"] == 0


def test_header_score_drops_fake_boxes_and_counts_box_families():
    gt = {"staves": 3, "fake_boxes": [1], "instruments": [2, 3],
          "boxes": {2: ["flute"], 3: ["violin"], 4: ["violin"]}}
    reconciled = {"instruments": [
        {"label": "Page edge, no staff", "boxes": [1], "staves": 1, "family": "other"},
        {"label": "Flauti", "boxes": [2], "staves": 1, "family": "woodwind"},
        {"label": "Violini", "abbreviations": ["Vl."], "boxes": [3, 4], "staves": 2, "family": "strings"}]}
    s = M.score_header(reconciled, gt)
    assert (s["staves_ok"], s["instruments_ok"], s["box_ok"], s["box_n"]) == (1, 1, 3, 3)
    # a keyboard entry with an unknown name counts as piano
    assert M.entry_family({"label": "Harpsichord", "family": "keyboard"}) == "piano"


def test_closed_score_checks_value_for_dynamics():
    gt = {"accept": ["dynamic_marking"], "value": "mf"}
    assert M.score_closed({"verdict": "dynamic_marking", "value": "mf"}, gt)["right"] == 1
    assert M.score_closed({"verdict": "dynamic_marking", "value": "sf"}, gt)["right"] == 0
    assert M.score_closed({"verdict": "Rest"}, {"accept": ["rest"]})["right"] == 1


def test_omr_pitch_scores_merge_staves_and_skip_ties():
    gt = {"bars": {"1": {"upper": [{"midi": 79, "onset": "0", "grace": False, "tie_stop": False},
                                   {"midi": 79, "onset": "1", "grace": False, "tie_stop": True}],
                         "lower": [{"midi": 43, "onset": "0", "grace": False, "tie_stop": False},
                                   {"midi": None, "onset": "2", "grace": False, "tie_stop": False}]}}}
    gold = M.gold_omr_bars(gt, [1])
    assert gold[1]["pitch"] == Counter({79: 1, 43: 1})
    pred = {1: {"pitch": Counter({79: 1, 45: 1}), "onset_pitch": Counter({(Fraction(0), 79): 1})}}
    s = M.score_omr_bars(pred, gold, [1])
    assert (s["pitch_tp"], s["pitch_pred"], s["pitch_gold"], s["op_tp"]) == (1, 2, 2, 1)
    assert M.accuracy(s)["pitch_prf"] == (0.5, 0.5, 0.5)


def test_aggregate_json_fail_rate_and_cost():
    recs = [{"status": "ok", "cost_usd": 0.01, "latency_s": 2, "json_fail_first": True, "score": {"right": 1, "n": 1}},
            {"status": "json_fail", "cost_usd": 0.02, "latency_s": 4, "json_fail_first": True, "score": {"right": 0, "n": 1}},
            {"status": "error", "cost_usd": 0.0}]
    a = M.aggregate(recs)
    assert (a["calls"], a["errors"], a["json_fail_rate"], a["json_fail_final"]) == (2, 1, 1.0, 1)
    assert a["cost_usd"] == 0.03 and a["accuracy"]["closed_acc"] == 0.5


# ---------------------------------------------------------------- the model call (scripted)

def _res(text: str, stop: str = "end_turn", tin: int = 1000, tout: int = 1000):
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)], stop_reason=stop,
                           usage=SimpleNamespace(input_tokens=tin, output_tokens=tout))


def test_ask_retries_unparseable_once_and_charges_both():
    replies = iter([_res("not json"), _res('{"verdict": "rest"}')])

    async def call(**kw):
        return next(replies)

    ans = asyncio.run(models.ask("muse-spark-1.3", "sys", "q", b"img", "image/png", effort="low", max_tokens=8000, call=call))
    assert ans.parsed == {"verdict": "rest"} and ans.json_fail_first and len(ans.attempts) == 2
    assert ans.cost_usd == pytest.approx(2 * (1.25 + 4.25) / 1000)


def test_ask_records_refusal_without_retry():
    async def call(**kw):
        return _res("", stop="refusal")

    ans = asyncio.run(models.ask("claude-sonnet-5-5", "sys", "q", b"img", "image/png", effort="low", max_tokens=8000, call=call))
    assert ans.refusal and ans.parsed is None and len(ans.attempts) == 1


# ---------------------------------------------------------------- budget stop and resume

def _grid(**kw) -> R.Grid:
    base = dict(name="t", corpus=str(MANIFEST), tasks=["closed"], models=["muse-spark-1.3"], efforts=["low"],
                resolutions=["150dpi"], max_tokens=16000, omr={}, concurrency={"meta": 1, "anthropic": 1, "omr": 1})
    base.update(kw)
    return R.Grid(**base)


def _fake_build(c):
    return T.Request("sys", "q", b"img", "image/png", (100, 100), None)


def _scripted(cost: float, calls: list):
    async def ask(model, system, prompt, image, media_type, *, effort, max_tokens, require=None):
        calls.append(model)
        return models.Answer(parsed={"verdict": "rest"}, text='{"verdict": "rest"}', cost_usd=cost, latency_s=0.01)
    return ask


def test_budget_stops_cleanly_and_records_nothing_past_it(tmp_path):
    corpus = C.load_manifest(MANIFEST)
    grid = _grid()
    ledger = R.Ledger(tmp_path / "results.json", "t", {})
    calls: list = []
    p = R.plan(grid, corpus, ledger, build=_fake_build)
    assert len(p.pending) == 11
    budget = asyncio.run(R.run(grid, corpus, ledger, {"meta": 1.0, "anthropic": 1.0}, tmp_path, p=p,
                               ask=_scripted(0.4, calls), log=lambda *a: None))
    # the prior estimate lets the first call in; after it, the run's own mean (0.40) is the estimate:
    # 0.40 + 0.40 fits, a third would make 1.20 > 1.00
    assert len(calls) == 2 and len(ledger.records) == 2
    assert ledger.spent("meta") == pytest.approx(0.8)
    assert "meta" in budget.stopped
    saved = json.loads((tmp_path / "results.json").read_text())
    assert len(saved["records"]) == 2


def test_resume_never_repeats_a_call(tmp_path):
    corpus = C.load_manifest(MANIFEST)
    grid = _grid(models=["muse-spark-1.3", "claude-haiku-5-5"])
    calls: list = []
    ledger = R.Ledger(tmp_path / "results.json", "t", {})
    p = R.plan(grid, corpus, ledger, build=_fake_build)
    asyncio.run(R.run(grid, corpus, ledger, {"meta": 5, "anthropic": 5}, tmp_path, p=p, ask=_scripted(0.001, calls), log=lambda *a: None))
    assert len(calls) == 22
    # a fresh process: the ledger is read back, nothing is pending, nothing is called
    ledger2 = R.Ledger(tmp_path / "results.json", "t", {})
    p2 = R.plan(grid, corpus, ledger2, build=_fake_build)
    assert p2.pending == []
    asyncio.run(R.run(grid, corpus, ledger2, {"meta": 5, "anthropic": 5}, tmp_path, p=p2, ask=_scripted(0.001, calls), log=lambda *a: None))
    assert len(calls) == 22
    # an API error (no cost) is retried only on request
    any_id = next(iter(ledger2.records))
    ledger2.records[any_id].update({"status": "error", "cost_usd": 0.0})
    ledger2.save()
    assert R.plan(grid, corpus, R.Ledger(tmp_path / "results.json", "t", {}), build=_fake_build).pending == []
    again = R.plan(grid, corpus, R.Ledger(tmp_path / "results.json", "t", {}), retry_errors=True, build=_fake_build)
    assert [c.id for c in again.pending] == [any_id]


def test_grid_guards_spark_rules(tmp_path):
    g = tmp_path / "g.yaml"
    g.write_text(yaml.safe_dump({"tasks": ["omr"], "models": ["muse-spark-1.3"]}))
    with pytest.raises(ValueError, match="notes"):
        R.load_grid(g)
    g.write_text(yaml.safe_dump({"tasks": ["header"], "models": ["muse-spark-1.3"], "max_tokens": 4000}))
    with pytest.raises(ValueError, match="8k"):
        R.load_grid(g)
    g.write_text(yaml.safe_dump({"tasks": ["header"], "models": ["muse-spark-1.3"]}))
    assert R.load_grid(g).efforts == ["low"]
