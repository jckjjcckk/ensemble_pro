"""Voice notes (013) end to end against the LOCAL Supabase stack (`supabase start`) and an API pointed at it.

    cd api && uv run scripts/smoke_voice_local.py

Two throwaway accounts (voiceadmin, voiceviola @muse.test), one group, one 60-bar book. Sends three of CK's eval takes
(api/fixtures/voice/audio/wav, gitignored) through POST /scores/{id}/voice: Voice Transcribe and Spark are real Meta
calls (about $0.004 a take, META_* read from api/.env). Checks that a player cannot send a take, that only the admin
sees proposals, that accepting one makes it reach the player and that a dismiss deletes. Never run against hosted.
"""
import json, os, secrets, socket, subprocess, sys, time, pathlib
import httpx
WT = pathlib.Path(__file__).resolve().parents[2]
ROOT = WT
st = json.loads(subprocess.check_output(["supabase", "status", "-o", "json"], cwd=ROOT))
URL, ANON, SECRET = st["API_URL"], st["PUBLISHABLE_KEY"], st["SECRET_KEY"]
assert "127.0.0.1" in URL or "localhost" in URL
PW = secrets.token_urlsafe(12)
svc = httpx.Client(base_url=URL, headers={"apikey": SECRET, "Authorization": f"Bearer {SECRET}"}, timeout=20)
fails = 0
def check(c, what):
    global fails; print(("  ok   " if c else "  FAIL ") + what); fails += (not c)
def rest(cl, m, path, **kw):
    h = {"Prefer": "return=representation"}; h.update(kw.pop("headers", {}))
    return cl.request(m, f"/rest/v1/{path}", headers=h, **kw)
existing = {u["email"]: u for u in svc.get("/auth/v1/admin/users?per_page=200").json()["users"]}
uid, tok = {}, {}
for n in ("voiceadmin", "voiceviola"):
    e = f"{n}@muse.test"
    if e in existing:
        uid[n] = existing[e]["id"]; svc.put(f"/auth/v1/admin/users/{uid[n]}", json={"password": PW})
    else:
        uid[n] = svc.post("/auth/v1/admin/users", json={"email": e, "password": PW, "email_confirm": True}).json()["id"]
    tok[n] = httpx.post(f"{URL}/auth/v1/token?grant_type=password", headers={"apikey": ANON}, json={"email": e, "password": PW}).json()["access_token"]
cl = {n: httpx.Client(base_url=URL, headers={"apikey": ANON, "Authorization": f"Bearer {t}"}, timeout=20) for n, t in tok.items()}
rest(svc, "DELETE", "ensembles?name=eq.Voice+Smoke")
ens = rest(cl["voiceadmin"], "POST", "ensembles", json={"name": "Voice Smoke", "created_by": uid["voiceadmin"]}).json()[0]["id"]
rest(cl["voiceadmin"], "POST", "members", json={"ensemble_id": ens, "user_id": uid["voiceviola"], "role": "player", "part": "Viola", "display_name": "Lin Chen"})
score = rest(cl["voiceadmin"], "POST", "scores", json={"ensemble_id": ens, "title": "Voice Smoke", "composer": "Test", "created_by": uid["voiceadmin"], "status": "ready"}).json()[0]["id"]
r = rest(cl["voiceadmin"], "POST", "measures", json=[{"score_id": score, "number": n} for n in range(1, 61)])
check(r.status_code == 201, f"60 bars ({r.status_code})")
rest(svc, "POST", "parts", json=[{"score_id": score, "name": p, "position": i} for i, p in enumerate(["Violin I", "Violin II", "Viola", "Cello"])])

env = {k: v for k, v in os.environ.items() if not k.startswith(("ANTHROPIC", "SUPABASE", "META"))}
for k in ("META_API_KEY", "META_API_BASE_URL"):     # from the environment, else this checkout's api/.env
    if os.environ.get(k):
        env[k] = os.environ[k]
if "META_API_KEY" not in env:
    for line in (ROOT / "api/.env").read_text().splitlines():
        if line.startswith(("META_API_KEY=", "META_API_BASE_URL=")):
            k, v = line.split("=", 1); env[k] = v.strip().strip('"')
# WORKER=0: the route runs each take itself; no worker loop to pick up anything else queued on the stack.
env.update(SUPABASE_URL=URL, SUPABASE_SECRET_KEY=SECRET, LLM_PROVIDER="meta", ANTHROPIC_API_KEY="", WORKER="0")
s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port)], cwd=WT / "api", env=env,
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    api = httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=60)
    for _ in range(60):
        try: api.get("/health"); break
        except Exception: time.sleep(0.5)
    audio_dir = pathlib.Path(os.environ.get("FOLIO_VOICE_DIR", ROOT / "api/fixtures/voice/audio"))
    wav = lambda n: (audio_dir / f"wav/{n}.wav").read_bytes()
    H = lambda n: {"Authorization": f"Bearer {tok[n]}", "Content-Type": "audio/wav"}
    r = api.post(f"/scores/{score}/voice", content=wav("v02"), headers=H("voiceviola"))
    check(r.status_code == 403, f"a player cannot send a take ({r.status_code})")
    r = api.post(f"/scores/{score}/voice", content=b"nope", headers=H("voiceadmin"))
    check(r.status_code == 400, f"not a WAV → 400 ({r.status_code})")
    jobs = {}
    for take in ("v02", "v28", "v14"):
        t0 = time.monotonic()
        r = api.post(f"/scores/{score}/voice", content=wav(take), headers=H("voiceadmin"))
        check(r.status_code == 202, f"{take}: 202 ({r.status_code} {r.text[:120]})")
        jid = r.json()["job_id"]
        for _ in range(120):
            j = rest(cl["voiceadmin"], "GET", f"jobs?id=eq.{jid}").json()
            if j and j[0]["status"] in ("done", "failed"): break
            time.sleep(0.25)
        j = j[0]; jobs[take] = j
        print(f"    {take}: {j['status']} in {time.monotonic() - t0:.1f}s | {j['result'].get('transcript')!r} | proposed {j['result'].get('proposed')} | usd {j['result'].get('cost_usd')} | {j.get('error') or ''}")
        check(j["status"] == "done", f"{take}: the admin reads their own job, done")
        audio = j["payload"]["audio_path"]
        for who in ("voiceviola", "voiceadmin"):
            r = cl[who].get(f"/storage/v1/object/scores/{audio}")
            check(r.status_code >= 400, f"{take}: the take is gone once transcribed ({who}: {r.status_code})")
        check(rest(cl["voiceviola"], "GET", f"jobs?id=eq.{jid}").json() == [], f"{take}: the player cannot read the job (transcript)")
    mine = rest(cl["voiceadmin"], "GET", f"annotations?score_id=eq.{score}&select=id,kind,body,status,audience,audience_part,payload").json()
    for a in mine: print("    ", a["kind"], a["body"], a["status"], a["audience"], a["audience_part"] or "")
    check(len(mine) >= 2 and all(a["status"] == "proposed" for a in mine), "the admin sees the proposals, all proposed")
    check(rest(cl["voiceviola"], "GET", f"annotations?score_id=eq.{score}").json() == [], "the player sees no proposal")
    ens_mark = [a for a in mine if a["audience"] == "ensemble"]
    if ens_mark:
        mid = ens_mark[0]["payload"]["mark_id"]
        r = rest(cl["voiceadmin"], "PATCH", f"annotations?score_id=eq.{score}&payload->>mark_id=eq.{mid}", json={"status": "live"})
        check(r.status_code == 200 and r.json() and r.json()[0]["status"] == "live", "the admin accepts a mark (status live)")
        seen = rest(cl["voiceviola"], "GET", f"annotations?score_id=eq.{score}").json()
        check(len(seen) == 1 and seen[0]["payload"]["mark_id"] == mid, "the player sees exactly the accepted ensemble mark")
        check(not ({"transcript", "quote"} & set(seen[0]["payload"])), "the accepted mark carries no transcript or quote")
    cut = [a for a in mine if a["kind"] == "cut"]
    if cut:
        r = rest(cl["voiceadmin"], "DELETE", f"annotations?id=eq.{cut[0]['id']}")
        check(r.status_code in (200, 204), "the admin dismisses a proposal (delete)")
    usage = rest(svc, "GET", f"usage_events?user_id=eq.{uid['voiceadmin']}&select=kind").json()
    check({u["kind"] for u in usage} >= {"voice", "spark"}, "both calls charged to the admin")
finally:
    proc.terminate()
    rest(svc, "DELETE", "ensembles?name=eq.Voice+Smoke")
print("FAILS", fails)
sys.exit(1 if fails else 0)
