"""The one-live-job index on hosted (`jobs_one_live`, migration 20261031120000): with a conversion of a book running, a
second `omr_convert` row for the same book is refused by Postgres (23505) even when it skips the route. The probe row is
inserted `running` (no worker claims a running row) and deleted at once should the index ever let it in.

    PYTHONPATH=. uv run python -m experiments.e2e_night.live_index <slug>
"""
import json
import sys

from app.db import db

from .common import load, save

slug = sys.argv[1]
s = load(slug)
d = db()
live = [j for j in d.table("jobs").select("id,status,payload").eq("kind", "omr_convert").in_("status", ["queued", "running"]).execute().data
        if (j.get("payload") or {}).get("score_id") == s["score_id"]]
out = {"live": [j["id"] for j in live]}
if not live:
    sys.exit("no live conversion of this book to test against")
try:
    row = d.table("jobs").insert({"kind": "omr_convert", "status": "running", "score_id": None, "max_attempts": 1,
                                  "payload": {"score_id": s["score_id"], "probe": "e2e-night live index"}}).execute().data[0]
    out["inserted"] = row["id"]
    d.table("jobs").delete().eq("id", row["id"]).execute()
    out["result"] = "ACCEPTED (index missing): probe deleted"
except Exception as e:  # noqa: BLE001
    msg = str(e)
    out["result"] = "refused" if ("23505" in msg or "jobs_one_live" in msg) else f"other error: {msg[:200]}"
    out["error"] = msg[:300]
s.setdefault("index_probe", []).append(out)
save(slug, s)
print(json.dumps(out, indent=1))
