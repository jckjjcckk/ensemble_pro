"""Path A end to end on the LOCAL stack: admin creates a score through RLS, uploads the Beethoven fixture to
the bucket, calls POST /scores/{id}/import on an API started here (worker inside), waits for the job, and
checks parts and measures. Run scripts/smoke_local.py first (it creates the demo users).

    cd api && uv run scripts/smoke_import.py
"""
import json
import os
import secrets
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
status = json.loads(subprocess.check_output(["supabase", "status", "-o", "json"], cwd=ROOT))
URL, ANON, SECRET = status["API_URL"], status["PUBLISHABLE_KEY"], status["SECRET_KEY"]
svc = httpx.Client(base_url=URL, headers={"apikey": SECRET, "Authorization": f"Bearer {SECRET}"}, timeout=30)
PASSWORD = secrets.token_urlsafe(12)
admin_id = next(u["id"] for u in svc.get("/auth/v1/admin/users?per_page=100").json()["users"] if u["email"] == "admin@muse.test")
svc.put(f"/auth/v1/admin/users/{admin_id}", json={"password": PASSWORD})
tok = httpx.post(f"{URL}/auth/v1/token?grant_type=password", headers={"apikey": ANON}, json={"email": "admin@muse.test", "password": PASSWORD}).json()["access_token"]
me = httpx.Client(base_url=URL, headers={"apikey": ANON, "Authorization": f"Bearer {tok}", "Prefer": "return=representation"}, timeout=30)

fails = 0
def check(c, what):
    global fails
    print(("  ok   " if c else "  FAIL ") + what)
    fails += 0 if c else 1

# the ensemble from smoke_local, or a fresh one
ens = me.get("/rest/v1/ensembles?name=eq.Smoke+Quartet").json()
ens = ens[0]["id"] if ens else me.post("/rest/v1/ensembles", json={"name": "Smoke Quartet", "created_by": admin_id}).json()[0]["id"]
svc.delete("/rest/v1/scores?title=eq.Op.+18+No.+1")
score = me.post("/rest/v1/scores", json={"ensemble_id": ens, "title": "Op. 18 No. 1", "composer": "Beethoven", "folder": "Autumn programme", "created_by": admin_id}).json()[0]["id"]
path = f"{score}/source.musicxml"
data = (ROOT / "web/public/fixtures/beethoven-op18no1-mv1.musicxml").read_bytes()
r = me.post(f"/storage/v1/object/scores/{path}", content=data, headers={"Content-Type": "application/vnd.recordare.musicxml+xml", "x-upsert": "true"})
check(r.status_code == 200, f"admin uploads the MusicXML through RLS ({r.status_code} {r.text[:80]})")

port = 8766
proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port)], cwd=ROOT / "api",
                        env=dict(os.environ, SUPABASE_URL=URL, SUPABASE_SECRET_KEY=SECRET), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    for _ in range(80):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.5).close(); break
        except OSError:
            time.sleep(0.25)
    api = httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=30, headers={"Authorization": f"Bearer {tok}"})
    r = api.post(f"/scores/{score}/import", json={"path": path})
    check(r.status_code == 200, f"POST /scores/{{id}}/import queues the job ({r.status_code} {r.text[:100]})")
    job = r.json()["job_id"]
    t0 = time.time(); row = {}
    while time.time() - t0 < 90:
        row = svc.get(f"/rest/v1/jobs?id=eq.{job}").json()[0]
        if row["status"] in ("done", "failed"):
            break
        time.sleep(1)
    check(row.get("status") == "done", f"job finished in {round(time.time()-t0)} s: {row.get('status')} {row.get('error') or ''} {json.dumps(row.get('result'))[:160]}")
    s = me.get(f"/rest/v1/scores?id=eq.{score}").json()[0]
    check(s["status"] == "ready" and s["bars"] == 313 and s["key_sig"] == "F major" and s["meter"] == "3/4" and s["tempo_bpm"] == 132, f"score facts: {s['status']} {s['bars']} bars {s['key_sig']} {s['meter']} {s['tempo_bpm']} bpm {s['duration_sec']} s, work={s['work']!r}")
    parts = me.get(f"/rest/v1/parts?score_id=eq.{score}&order=position").json()
    check([p["name"] for p in parts] == ["Violin I", "Violin II", "Viola", "Cello"], f"parts: {[(p['name'], p['difficulty']) for p in parts]}")
    n = me.get(f"/rest/v1/measures?score_id=eq.{score}&select=id", headers={"Prefer": "count=exact", "Range": "0-0"}).headers.get("content-range")
    check(n and n.endswith("/313"), f"313 stable measure rows ({n})")
    check(s["current_interpretation_id"] is not None, "score points at interpretation v1")
    # the job again: version bumps, measures stay the same rows
    before = {m["number"]: m["id"] for m in me.get(f"/rest/v1/measures?score_id=eq.{score}&select=number,id&number=lte.3").json()}
    r = api.post(f"/scores/{score}/import", json={"path": path}); job = r.json()["job_id"]
    t0 = time.time()
    while time.time() - t0 < 90 and svc.get(f"/rest/v1/jobs?id=eq.{job}").json()[0]["status"] not in ("done", "failed"):
        time.sleep(1)
    after = {m["number"]: m["id"] for m in me.get(f"/rest/v1/measures?score_id=eq.{score}&select=number,id&number=lte.3").json()}
    check(before == after, "reimport keeps the same measure ids")
    vs = me.get(f"/rest/v1/interpretations?score_id=eq.{score}&select=version&order=version").json()
    check([v["version"] for v in vs] == [1, 2], f"interpretation versions {[v['version'] for v in vs]}")
    # a player sees it with the right parts
    v2 = next(u["id"] for u in svc.get("/auth/v1/admin/users?per_page=100").json()["users"] if u["email"] == "violin2@muse.test")
    svc.put(f"/auth/v1/admin/users/{v2}", json={"password": PASSWORD})
    t2 = httpx.post(f"{URL}/auth/v1/token?grant_type=password", headers={"apikey": ANON}, json={"email": "violin2@muse.test", "password": PASSWORD}).json()["access_token"]
    pl = httpx.get(f"{URL}/rest/v1/parts?score_id=eq.{score}&select=name", headers={"apikey": ANON, "Authorization": f"Bearer {t2}"}).json()
    check(len(pl) == 4, f"violin2 sees the four parts ({len(pl)})")
finally:
    proc.terminate()
print("\n" + ("ALL PASS" if fails == 0 else f"{fails} FAILED"))
sys.exit(1 if fails else 0)
