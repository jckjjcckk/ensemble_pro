"""Step 6 of the speed pass: two queued jobs on the LOCAL Supabase stack, the real worker loop and `claim_job`, at
WORKER_CONCURRENCY 2 and then 1. The jobs are of a kind only this script handles (`speed_sleep`: 3 s, no model call);
the script refuses to run while any other job is queued locally (the loop would claim it), and deletes its jobs.

    uv run python -m experiments.speed_pass.worker_local
"""
from __future__ import annotations

import asyncio
import os
import time

from .ledger import local

URL, KEY = local()
os.environ["SUPABASE_URL"], os.environ["SUPABASE_SECRET_KEY"] = URL, KEY

from app import worker  # noqa: E402
from app.db import db  # noqa: E402
from app.librarian import HANDLERS  # noqa: E402


async def sleepy(job, ctx):
    await asyncio.sleep(3)
    return {"slept": 3}


async def one(concurrency: int) -> dict:
    others = db().table("jobs").select("id,kind").eq("status", "queued").execute().data
    assert not others, f"other jobs are queued locally: {others}"
    ids = [db().table("jobs").insert({"kind": "speed_sleep", "status": "queued", "payload": {"n": i}}).execute().data[0]["id"] for i in range(2)]
    stop = asyncio.Event()
    t0 = time.monotonic()
    task = asyncio.create_task(worker.loop(stop, concurrency=concurrency))
    while True:
        rows = db().table("jobs").select("id,status,started_at,finished_at,result").in_("id", ids).execute().data
        if all(r["status"] in ("done", "failed") for r in rows):
            break
        await asyncio.sleep(0.2)
    wall = time.monotonic() - t0
    stop.set()
    await task
    db().table("jobs").delete().in_("id", ids).execute()
    rows.sort(key=lambda r: r["started_at"])
    overlap = rows[1]["started_at"] < rows[0]["finished_at"]
    return {"concurrency": concurrency, "wall_s": round(wall, 1), "status": [r["status"] for r in rows],
            "started": [r["started_at"][11:23] for r in rows], "finished": [r["finished_at"][11:23] for r in rows], "overlap": overlap}


async def main() -> None:
    worker.load_handlers()
    HANDLERS["speed_sleep"] = sleepy
    worker.load_handlers = lambda: None
    for n in (2, 1):
        print(await one(n))


if __name__ == "__main__":
    asyncio.run(main())
