"""Smoke test for item 1 against the LOCAL Supabase stack (`supabase start`) and a FastAPI pointed at it.

    cd api && uv run scripts/smoke_local.py

Creates the five demo accounts (admin, piano, violin1, violin2, cello @muse.test) with a throwaway password,
builds one ensemble and one score with the service key, then signs in as each user through the anon key and
checks what RLS lets them see and do. Then starts the API with the local keys and checks /me, the 401/403
paths, and the 402 when a budget is spent. Never run it against the hosted project.
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
URL = status["API_URL"]
ANON = status["PUBLISHABLE_KEY"]
SECRET = status["SECRET_KEY"]
PASSWORD = secrets.token_urlsafe(12)
EMAILS = ["admin", "piano", "violin1", "violin2", "cello"]
SEATS = {"violin1": "Violin I", "violin2": "Violin II", "admin": "Viola", "cello": "Cello"}

fails = 0


def check(cond, what):
    global fails
    print(("  ok   " if cond else "  FAIL ") + what)
    if not cond:
        fails += 1


svc = httpx.Client(base_url=URL, headers={"apikey": SECRET, "Authorization": f"Bearer {SECRET}"}, timeout=20)


def rest(client, method, path, **kw):
    headers = {"Prefer": "return=representation"}
    headers.update(kw.pop("headers", {}))
    return client.request(method, f"/rest/v1/{path}", headers=headers, **kw)


# ---------------------------------------------------------------- users (admin API, idempotent)
print("users")
existing = {u["email"]: u for u in svc.get("/auth/v1/admin/users?per_page=100").json()["users"]}
users = {}
for name in EMAILS:
    email = f"{name}@muse.test"
    if email in existing:
        uid = existing[email]["id"]
        svc.put(f"/auth/v1/admin/users/{uid}", json={"password": PASSWORD})
    else:
        r = svc.post("/auth/v1/admin/users", json={"email": email, "password": PASSWORD, "email_confirm": True})
        r.raise_for_status()
        uid = r.json()["id"]
    users[name] = uid
profiles = rest(svc, "GET", "profiles?select=id").json()
check(set(p["id"] for p in profiles) >= set(users.values()), "profile row created for every auth user")


def session(name):
    r = httpx.post(f"{URL}/auth/v1/token?grant_type=password", headers={"apikey": ANON},
                   json={"email": f"{name}@muse.test", "password": PASSWORD})
    r.raise_for_status()
    tok = r.json()["access_token"]
    return httpx.Client(base_url=URL, headers={"apikey": ANON, "Authorization": f"Bearer {tok}"}, timeout=20), tok


# ---------------------------------------------------------------- world (as the admin, through RLS)
print("world")
rest(svc, "DELETE", "ensembles?name=eq.Smoke+Quartet")
rest(svc, "DELETE", "scores?title=eq.Smoke+Op.+18")
admin, admin_tok = session("admin")
r = rest(admin, "POST", "ensembles", json={"name": "Smoke Quartet", "created_by": users["admin"]})
check(r.status_code == 201, f"admin creates an ensemble ({r.status_code})")
ens = r.json()[0]["id"]
roster = rest(admin, "GET", f"members?ensemble_id=eq.{ens}").json()
check(len(roster) == 1 and roster[0]["role"] == "admin", "creator became the first admin")
for name in ["violin1", "violin2", "cello"]:
    r = rest(admin, "POST", "members", json={"ensemble_id": ens, "user_id": users[name], "role": "player", "part": SEATS[name]})
    check(r.status_code == 201, f"admin adds {name} as player")
r = rest(admin, "PATCH", f"members?ensemble_id=eq.{ens}&user_id=eq.{users['admin']}", json={"part": "Viola"})
check(r.status_code == 200, "admin sets own seat")

r = rest(admin, "POST", "scores", json={"ensemble_id": ens, "title": "Smoke Op. 18", "composer": "Beethoven", "created_by": users["admin"], "status": "ready"})
check(r.status_code == 201, f"admin adds a score to the ensemble ({r.status_code})")
score = r.json()[0]["id"]
r = rest(admin, "POST", "measures", json=[{"score_id": score, "number": n} for n in range(1, 6)])
check(r.status_code == 201, "admin creates measure identities")
measures = {m["number"]: m["id"] for m in r.json()}
r = rest(admin, "POST", "annotations", json={"score_id": score, "kind": "cut", "measure_from": measures[2], "measure_to": measures[3], "audience": "ensemble", "author_id": users["admin"]})
check(r.status_code == 201, f"admin writes a cut for the ensemble ({r.status_code} {r.text[:80]})")
r = rest(admin, "POST", "annotations", json={"score_id": score, "kind": "bowing", "measure_from": measures[4], "measure_to": measures[4], "audience": "part", "audience_part": "Violin II", "author_id": users["admin"]})
check(r.status_code == 201, "admin writes a bowing for Violin II only")

# ---------------------------------------------------------------- players
print("players")
v2, v2_tok = session("violin2")
v1, _ = session("violin1")
piano, piano_tok = session("piano")
check(len(rest(v2, "GET", f"scores?id=eq.{score}").json()) == 1, "violin2 sees the ensemble score")
check(len(rest(piano, "GET", f"scores?id=eq.{score}").json()) == 0, "piano (not a member) does not")
check(len(rest(piano, "GET", f"ensembles?id=eq.{ens}").json()) == 0, "piano does not see the ensemble")
kinds = sorted(a["kind"] for a in rest(v2, "GET", f"annotations?score_id=eq.{score}").json())
check(kinds == ["bowing", "cut"], f"violin2 sees the cut and the Violin II bowing ({kinds})")
kinds = sorted(a["kind"] for a in rest(v1, "GET", f"annotations?score_id=eq.{score}").json())
check(kinds == ["cut"], f"violin1 sees the cut but not the Violin II bowing ({kinds})")
r = rest(v2, "POST", "annotations", json={"score_id": score, "kind": "cut", "measure_from": measures[1], "measure_to": measures[1], "audience": "ensemble", "author_id": users["violin2"]})
check(r.status_code in (401, 403), f"player cannot cut for the ensemble ({r.status_code})")
me_member = rest(v2, "GET", f"members?ensemble_id=eq.{ens}&user_id=eq.{users['violin2']}").json()[0]["id"]
r = rest(v2, "POST", "annotations", json={"score_id": score, "kind": "text", "body": "breathe", "measure_from": measures[1], "measure_to": measures[1], "audience": "member", "audience_member_id": me_member, "author_id": users["violin2"]})
check(r.status_code == 201, f"player writes a note to themself ({r.status_code} {r.text[:80]})")
own = r.json()[0]["id"]
check(len(rest(v1, "GET", f"annotations?id=eq.{own}").json()) == 0, "violin1 does not see violin2's private note")
check(len(rest(admin, "GET", f"annotations?id=eq.{own}").json()) == 1, "admin sees every note on the score")
r = rest(v2, "PATCH", f"scores?id=eq.{score}", json={"title": "Hacked"})
check(r.status_code != 200 or r.json() == [], "player cannot edit the score")
r = rest(v2, "POST", "members", json={"ensemble_id": ens, "user_id": users["piano"], "role": "admin"})
check(r.status_code in (401, 403), "player cannot add members")
r = rest(piano, "POST", "scores", json={"owner_user_id": users["piano"], "title": "Smoke solo", "created_by": users["piano"]})
check(r.status_code == 201, "piano adds a score to their own library")
solo = r.json()[0]["id"]
check(len(rest(v1, "GET", f"scores?id=eq.{solo}").json()) == 0, "nobody else sees a personal score")
check(rest(v2, "GET", "spend").status_code in (401, 403) or rest(v2, "GET", "spend").json() == [], "spend table is invisible to users")
check(len(rest(v2, "GET", "profiles").json()) == 1, "a user sees only their own profile")
r = rest(v2, "PATCH", f"profiles?id=eq.{users['violin2']}", json={"budget_usd": 999})
check(r.status_code != 200 or r.json() == [], "a user cannot raise their own budget")

# storage
print("storage")
r = v2.post(f"/storage/v1/object/scores/{score}/evil.txt", content=b"x", headers={"Content-Type": "text/plain"})
check(r.status_code in (400, 401, 403), f"player cannot upload into the score folder ({r.status_code})")
r = admin.post(f"/storage/v1/object/scores/{score}/parts.txt", content=b"x", headers={"Content-Type": "text/plain"})
check(r.status_code == 200, f"admin can upload into the score folder ({r.status_code} {r.text[:80]})")
r = v2.get(f"/storage/v1/object/authenticated/scores/{score}/parts.txt")
check(r.status_code == 200, f"player can read the score's file ({r.status_code})")
r = piano.get(f"/storage/v1/object/authenticated/scores/{score}/parts.txt")
check(r.status_code in (400, 403, 404), f"non-member cannot read it ({r.status_code})")

# jobs + charge
print("jobs and spend")
j = rest(svc, "POST", "jobs", json={"kind": "noop", "score_id": score, "created_by": users["admin"]}).json()[0]
claimed = svc.post("/rest/v1/rpc/claim_job", json={}).json()
check(claimed and claimed["id"] == j["id"] and claimed["status"] == "running" and claimed["attempts"] == 1, "worker claims the queued job")
empty = svc.post("/rest/v1/rpc/claim_job", json={}).json()
check(empty is None or empty.get("id") is None, f"nothing left to claim ({empty})")
check(len(rest(v2, "GET", f"jobs?id=eq.{j['id']}").json()) == 1, "a member sees the score's job")
before = rest(svc, "GET", "spend?select=spent_usd").json()[0]["spent_usd"]
tot = svc.post("/rest/v1/rpc/charge_usage", json={"p_user_id": users["admin"], "p_provider": "meta", "p_model": "muse-spark-1.3", "p_kind": "spark", "p_input_tokens": 100, "p_output_tokens": 10, "p_units": 0, "p_cost_usd": 0.0005}).json()[0]
check(abs(float(tot["shared_spent"]) - float(before) - 0.0005) < 1e-6, f"charge_usage adds to the shared counter ({tot})")

# ---------------------------------------------------------------- the API, pointed at the local stack
print("api")
port = 8765
env = dict(os.environ, SUPABASE_URL=URL, SUPABASE_SECRET_KEY=SECRET)
proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port)], cwd=ROOT / "api", env=env,
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    for _ in range(60):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.5).close()
            break
        except OSError:
            time.sleep(0.25)
    api = httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=20)
    check(api.get("/me").status_code == 401, "no token → 401")
    check(api.get("/me", headers={"Authorization": "Bearer nope"}).status_code == 401, "junk token → 401")
    r = api.get("/me", headers={"Authorization": f"Bearer {v2_tok}"})
    body = r.json()
    check(r.status_code == 200 and body["email"] == "violin2@muse.test", f"/me answers for a real session ({r.status_code})")
    check(any(m["ensemble_name"] == "Smoke Quartet" and m["role"] == "player" and m["part"] == "Violin II" for m in body.get("memberships", [])), "/me lists the membership with role and seat")
    check(body["budget"]["can_call_models"] is True, "/me says models may be called")
    # unknown user: a valid session whose profile row is gone
    rest(svc, "DELETE", f"profiles?id=eq.{users['piano']}")
    r = api.get("/me", headers={"Authorization": f"Bearer {piano_tok}"})
    check(r.status_code == 403, f"valid token without a profile → 403 ({r.status_code})")
    rest(svc, "POST", "profiles", json={"id": users["piano"], "email": "piano@muse.test", "display_name": "piano"})
    # budget spent → 402 on a model route, before any provider call
    rest(svc, "PATCH", f"profiles?id=eq.{users['violin2']}", json={"spent_usd": 10, "budget_usd": 10})
    r = api.post("/llm/probe", json={}, headers={"Authorization": f"Bearer {v2_tok}"})
    check(r.status_code == 402, f"user budget spent → 402 ({r.status_code})")
    rest(svc, "PATCH", f"profiles?id=eq.{users['violin2']}", json={"spent_usd": 0})
    rest(svc, "PATCH", "spend?id=eq.1", json={"spent_usd": 60, "cap_usd": 60})
    r = api.post("/llm/probe", json={}, headers={"Authorization": f"Bearer {v2_tok}"})
    check(r.status_code == 402, f"shared cap spent → 402 ({r.status_code})")
    rest(svc, "PATCH", "spend?id=eq.1", json={"spent_usd": 0})
    r = api.get("/me", headers={"Authorization": f"Bearer {v2_tok}"})
    check(r.json()["budget"]["can_call_models"] is True, "budgets reset")
finally:
    proc.terminate()

print(f"\n{'ALL PASS' if fails == 0 else f'{fails} FAILED'}")
sys.exit(1 if fails else 0)
