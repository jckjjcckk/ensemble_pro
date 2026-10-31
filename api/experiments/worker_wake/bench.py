"""Insert -> pickup latency of the job worker against hosted Supabase, before and after the Realtime wake (app/wake.py).

A probe is a `jobs` row of kind `wake_probe`: no score, no owner (RLS shows it to nobody), no model call, no cost. This
process registers a handler for it that only records the moment; yoga's stable worker has none, so a probe yoga
claims first fails at once with "no handler" and touches nothing else. Pickup is `locked_at - created_at`, both the
database's own clock (`claim_job` stamps `locked_at`).

    cd api && PYTHONPATH=. uv run python -m experiments.worker_wake.bench yoga  [n]   no local worker: yoga's 2 s poll alone
    cd api && PYTHONPATH=. uv run python -m experiments.worker_wake.bench poll  [n]   a local worker, poll only (WORKER_WAKE=0)
    cd api && PYTHONPATH=. uv run python -m experiments.worker_wake.bench wake  [n]   a local worker with the Realtime wake

Yoga keeps polling throughout; each probe's row says who claimed it. A real job the local worker happens to claim is
put back in the queue untouched (status queued, attempt given back) for yoga, never run here.
"""
from __future__ import annotations

import asyncio
import json
import os
import random
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

os.environ["LLM_PROVIDER"] = "meta"     # nothing here calls a model; if anything ever did, it is Spark

from app import worker
from app.db import db
from app.librarian import HANDLERS
from app.settings import settings
from app.wake import Wake

HERE = Path(__file__).resolve().parent
KIND = "wake_probe"


def ts(s: str) -> float:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


async def probe_handler(job, ctx):
    return {"by": "local", "ran_at": time.time()}


async def guarded_run_one(row: dict) -> None:
    if row.get("kind") != KIND:
        db().table("jobs").update({"status": "queued", "attempts": max(0, int(row.get("attempts") or 1) - 1), "locked_at": None}) \
            .eq("id", row["id"]).eq("status", "running").execute()
        print(f"  put back a real job ({row.get('kind')}) for yoga", flush=True)
        return
    await REAL_RUN_ONE(row)


REAL_RUN_ONE = worker.run_one


async def main(mode: str, n: int) -> None:
    stop = asyncio.Event()
    tasks, w = [], None
    if mode in ("poll", "wake"):
        HANDLERS[KIND] = probe_handler
        worker.run_one = guarded_run_one
        worker.load_handlers = lambda: None          # the probe handler only: nothing else is loaded, nothing else runs
        worker.requeue_stale = lambda: None          # yoga's business
        wake = None
        if mode == "wake":
            w = Wake(settings.supabase_url, settings.supabase_secret_key)
            wake = w.event
            tasks.append(asyncio.create_task(w.run(stop)))
            for _ in range(100):
                await asyncio.sleep(0.1)
                if w.subscribed_at:
                    break
            assert w.subscribed_at, "the wake never subscribed"
        tasks.append(asyncio.create_task(worker.loop(stop, wake=wake)))
        await asyncio.sleep(1.0)

    rows = []
    for i in range(n):
        await asyncio.sleep(random.uniform(2.0, 4.5))             # random phase against every 2 s poll
        t0 = time.time()
        ins = await asyncio.to_thread(lambda: db().table("jobs").insert({"kind": KIND, "max_attempts": 1, "payload": {"probe": mode, "i": i}}).execute().data[0])
        t_ins = time.time()
        row = None
        for _ in range(100):
            await asyncio.sleep(0.05)
            row = await asyncio.to_thread(lambda: db().table("jobs").select("id,status,created_at,locked_at,result,error").eq("id", ins["id"]).single().execute().data)
            if row["locked_at"] and row["status"] in ("done", "failed"):
                break
        pickup = ts(row["locked_at"]) - ts(row["created_at"]) if row and row["locked_at"] else None
        by = "local" if (row.get("result") or {}).get("by") == "local" else ("yoga" if "no handler" in (row.get("error") or "") else "?")
        ran = (row.get("result") or {}).get("ran_at")
        rows.append({"i": i, "id": ins["id"], "pickup_s": pickup, "by": by, "insert_http_s": t_ins - t0,
                     "client_insert_to_run_s": (ran - t0) if ran else None})
        print(f"  {mode} #{i:02d} pickup {pickup if pickup is None else round(pickup, 3)} s by {by}", flush=True)

    stop.set()
    await asyncio.gather(*tasks, return_exceptions=True)
    picks = [r["pickup_s"] for r in rows if r["pickup_s"] is not None]
    summary = {"mode": mode, "n": len(rows), "median_s": statistics.median(picks), "mean_s": statistics.fmean(picks),
               "p90_s": sorted(picks)[int(0.9 * (len(picks) - 1))], "max_s": max(picks), "min_s": min(picks),
               "won_local": sum(r["by"] == "local" for r in rows), "won_yoga": sum(r["by"] == "yoga" for r in rows),
               "wake_events": w.events if w else None, "wake_connects": w.connects if w else None}
    local = [r["pickup_s"] for r in rows if r["by"] == "local" and r["pickup_s"] is not None]
    if local:
        summary["local_median_s"] = statistics.median(local)
    print(json.dumps(summary, indent=1))
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    (HERE / "results" / f"{stamp}-{mode}.json").write_text(json.dumps({"summary": summary, "rows": rows}, indent=1))
    with open(HERE / "spend.jsonl", "a") as f:
        f.write(json.dumps({"ts": datetime.now(timezone.utc).isoformat(), "run": f"{stamp}-{mode}", "probes": len(rows),
                            "provider": "none", "usd": 0.0, "note": "wake_probe rows only; no model call"}) + "\n")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 15))
