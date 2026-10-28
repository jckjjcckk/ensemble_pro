"""Run one librarian handler against the LOCAL Supabase stack, without the web app.

    cd api && uv run -m app.librarian.run seed --pages p1.png p2.png [--title "Goldberg Aria"]
    cd api && uv run -m app.librarian.run process_pages --score <id> [--answer "Piano I, Piano II"]
    cd api && uv run -m app.librarian.run show --score <id>

`seed` creates a score in admin@muse.test's personal library (the demo user `scripts/smoke_local.py` makes),
uploads the PNGs as `{id}/pages/{n}.png` (bucket-relative, as the contract says) and records an `images` source with `page_order` 1..n.
`process_pages` (or any registered kind) inserts a job row, builds the JobContext with `app.worker.context_for`,
runs the handler like the worker would, writes the outcome to the job row and prints it. `show` prints the
score, its current interpretation summary, parts and placements.

Supabase URL and key come from `supabase status` so this can never touch the hosted project; other settings
(META_API_KEY ...) still come from `api/.env`. LLM_PROVIDER defaults to `meta` here, since the handlers name
Muse Spark; pass `--provider anthropic` to use the experimenting provider.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def point_at_local_stack(provider: str, allow_remote: bool) -> None:
    """Overwrite the already-built settings object: `app.settings` reads api/.env when the package is imported
    (the `-m` import of app.librarian happens before main runs), so environment variables set here would be
    too late. The hosted project's URL in .env must never win."""
    from .. import settings as settings_module
    from ..settings import Settings
    status = json.loads(subprocess.check_output(["supabase", "status", "-o", "json"], cwd=ROOT, stderr=subprocess.DEVNULL))
    os.environ["SUPABASE_URL"] = status["API_URL"]
    os.environ["SUPABASE_SECRET_KEY"] = status["SECRET_KEY"]
    os.environ["LLM_PROVIDER"] = provider
    fresh = Settings()
    for name in Settings.model_fields:
        setattr(settings_module.settings, name, getattr(fresh, name))
    s = settings_module.settings
    if not allow_remote and not any(h in s.supabase_url for h in ("127.0.0.1", "localhost")):
        sys.exit(f"refusing to run against {s.supabase_url}: this runner is for the local stack")
    if s.llm_provider == "meta" and not s.meta_api_key:
        sys.exit("META_API_KEY is empty in api/.env")
    print(f"supabase {s.supabase_url}  provider {s.llm_provider} ({s.meta_model if s.llm_provider == 'meta' else s.anthropic_model})", file=sys.stderr)


def admin_user(db) -> dict:
    rows = db.table("profiles").select("id,email").eq("email", "admin@muse.test").limit(1).execute().data
    if not rows:
        sys.exit("no admin@muse.test profile: run `uv run scripts/smoke_local.py` once to create the demo users")
    return rows[0]


def cmd_seed(a) -> None:
    from ..db import db
    d = db()
    admin = admin_user(d)
    score = d.table("scores").insert({"owner_user_id": admin["id"], "created_by": admin["id"], "title": a.title, "status": "processing", "progress": 0}).execute().data[0]
    paths = []
    for i, p in enumerate(a.pages, start=1):
        path = f"{score['id']}/pages/{i}.png"
        d.storage.from_("scores").upload(path, Path(p).read_bytes(), {"content-type": "image/png", "upsert": "true"})
        paths.append(path)
    src = d.table("sources").insert({"score_id": score["id"], "kind": "images", "storage_paths": paths, "page_order": list(range(1, len(paths) + 1)),
                                     "page_count": len(paths), "created_by": admin["id"]}).execute().data[0]
    print(json.dumps({"score_id": score["id"], "source_id": src["id"], "pages": paths}, indent=2))


async def cmd_run(a) -> None:
    from ..db import db
    from ..librarian import HANDLERS, Job, load_handlers
    from ..worker import context_for
    load_handlers()
    fn = HANDLERS.get(a.kind)
    if fn is None:
        sys.exit(f"no handler for {a.kind!r}; have {sorted(HANDLERS)}")
    d = db()
    score = d.table("scores").select("id,created_by").eq("id", a.score).single().execute().data
    payload = {"score_id": a.score}
    if a.source:
        payload["source_id"] = a.source
    if a.answer:
        payload["answer"] = a.answer
    if a.payload:
        payload.update(json.loads(a.payload))
    job_row = d.table("jobs").insert({"kind": a.kind, "status": "running", "attempts": 1, "score_id": a.score, "created_by": score["created_by"],
                                      "payload": payload, "started_at": "now()", "locked_at": "now()"}).execute().data[0]
    ctx = context_for(job_row["id"])
    job = Job.from_row(job_row)
    try:
        out = await fn(job, ctx)
        result = {**ctx.result, **(out or {})}
        d.table("jobs").update({"status": "done", "progress": 1.0, "result": result, "finished_at": ctx.now()}).eq("id", job.id).execute()
        print(json.dumps({"job_id": job.id, "status": "done", "result": result}, indent=2, default=str))
    except Exception as e:  # noqa: BLE001
        err = f"{type(e).__name__}: {e}"
        d.table("jobs").update({"status": "failed", "error": err, "finished_at": ctx.now()}).eq("id", job.id).execute()
        d.table("scores").update({"status": "failed", "failure_reason": err[:300]}).eq("id", a.score).execute()
        raise


def cmd_show(a) -> None:
    from ..db import db
    d = db()
    score = d.table("scores").select("*").eq("id", a.score).single().execute().data
    print("score:", json.dumps({k: score[k] for k in ("title", "status", "progress", "pages", "bars", "key_sig", "meter", "brief", "composer", "work", "current_interpretation_id")}, indent=2))
    iid = score["current_interpretation_id"]
    interps = d.table("interpretations").select("id,version,engine,status,cost_usd,latency_ms,summary").eq("score_id", a.score).order("version").execute().data
    for it in interps:
        print(f"interpretation v{it['version']} {it['engine']} {it['status']} ${float(it['cost_usd']):.4f} {it['latency_ms']} ms" + (" (current)" if it["id"] == iid else ""))
        print("  summary:", json.dumps(it["summary"], indent=2, ensure_ascii=False))
    parts = d.table("parts").select("name,position,difficulty").eq("score_id", a.score).order("position").execute().data
    print("parts:", parts)
    if iid:
        pl = d.table("measure_placements").select("page,system,confidence,flag,rehearsal_mark,box,measures(number)").eq("interpretation_id", iid).execute().data
        pl.sort(key=lambda r: r["measures"]["number"])
        print(f"placements: {len(pl)}")
        for r in pl:
            b = r["box"]
            print(f"  m{r['measures']['number']:>3} p{r['page']} s{r['system']} {r['confidence']:<6} [{b['x0']:.3f},{b['y0']:.3f},{b['x1']:.3f},{b['y1']:.3f}]"
                  + (f"  {r['rehearsal_mark']}" if r["rehearsal_mark"] else "") + (f"  {r['flag']}" if r["flag"] else ""))


def main() -> None:
    ap = argparse.ArgumentParser(prog="app.librarian.run", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--provider", default="meta", choices=["meta", "anthropic"])
    ap.add_argument("--allow-remote", action="store_true", help=argparse.SUPPRESS)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("seed", help="create a score with these page PNGs in admin@muse.test's library")
    s.add_argument("--pages", nargs="+", required=True)
    s.add_argument("--title", default="Scanned pages")
    s.set_defaults(fn=cmd_seed)
    sh = sub.add_parser("show", help="print the score, interpretations, parts and placements")
    sh.add_argument("--score", required=True)
    sh.set_defaults(fn=cmd_show)
    for kind in ("process_pages", "import_musicxml", "transcribe_voice", "brief", "part_cut", "part_split", "omr_convert", "engrave"):
        r = sub.add_parser(kind, help=f"run the {kind} handler on a score")
        r.add_argument("--score", required=True)
        r.add_argument("--source")
        r.add_argument("--answer", help="payload.answer for a follow-up job, e.g. 'Piano I, Piano II'")
        r.add_argument("--payload", help="extra payload as JSON, e.g. part_cut: '{\"instrument\": \"Piano\", \"pages\": [1, 2]}'")
        r.set_defaults(fn=cmd_run, kind=kind)
    a = ap.parse_args()
    point_at_local_stack(a.provider, a.allow_remote)
    out = a.fn(a)
    if asyncio.iscoroutine(out):
        asyncio.run(out)


if __name__ == "__main__":
    main()
