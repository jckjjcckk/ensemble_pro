"""This task's Meta ledger ($8 cap for the whole speed pass, 2026-10-30). Two sources go into spend.jsonl:

- calls an experiment script makes itself (`log`), and
- calls the app made on the LOCAL stack (`sync_local`): every charge the handlers record lands in the local
  `usage_events` table, which is copied here row by row with a tag, so nothing the app spent is missed.

    uv run python -m experiments.speed_pass.ledger sync <tag>     # copy new local usage_events rows
    uv run python -m experiments.speed_pass.ledger total
"""
from __future__ import annotations

import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
LEDGER = HERE / "spend.jsonl"
CAP_USD = 8.0
ROOT = HERE.parents[2]
# The task started 2026-10-30 23:00 PT: local usage_events before this are other sessions' spend, not this cap's.
SINCE = "2026-10-31T06:00:00+00:00"


def rows() -> list[dict]:
    return [json.loads(l) for l in LEDGER.read_text().splitlines() if l.strip()] if LEDGER.exists() else []


def spent() -> float:
    return sum(r.get("usd", 0.0) for r in rows())


def guard(next_usd: float = 0.05) -> None:
    if spent() + next_usd > CAP_USD:
        raise SystemExit(f"STOP: ${spent():.4f} spent + ${next_usd:.4f} would pass the ${CAP_USD} cap")


def log(**row) -> None:
    row = {"ts": dt.datetime.now().isoformat(timespec="seconds"), **row}
    with LEDGER.open("a") as f:
        f.write(json.dumps(row) + "\n")


def local() -> tuple[str, str]:
    out = subprocess.check_output(["supabase", "status", "-o", "json"], cwd=ROOT, stderr=subprocess.DEVNULL).decode()
    st = json.loads(out[out.index("{"):])
    assert "127.0.0.1" in st["API_URL"] or "localhost" in st["API_URL"], "local stack only"
    return st["API_URL"], st["SECRET_KEY"]


def sync_local(tag: str) -> float:
    """Copy local usage_events rows not yet in the ledger (by id). Returns the dollars added."""
    url, key = local()
    seen = {r.get("event_id") for r in rows()}
    h = {"apikey": key, "Authorization": f"Bearer {key}"}
    got = httpx.get(f"{url}/rest/v1/usage_events", params={"select": "*", "order": "created_at", "limit": "10000", "created_at": f"gte.{SINCE}"},
                    headers=h, timeout=30).json()
    add = 0.0
    for e in got:
        if e["id"] in seen or e["provider"] != "meta":
            continue
        usd = float(e["cost_usd"])
        log(source="local_usage_events", tag=tag, event_id=e["id"], job_id=e.get("job_id"), kind=e["kind"], model=e["model"],
            input_tokens=e["input_tokens"], output_tokens=e["output_tokens"], units=e["units"], usd=usd, at=e["created_at"])
        add += usd
    return add


if __name__ == "__main__":
    if sys.argv[1] == "sync":
        print(f"+${sync_local(sys.argv[2]):.4f}, total ${spent():.4f} of ${CAP_USD}")
    else:
        print(f"${spent():.4f} of ${CAP_USD}")
