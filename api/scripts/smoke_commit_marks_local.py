"""`commit_marks` (013, accepting a voice proposal in one transaction) against the LOCAL Supabase stack.

    cd api && uv run scripts/smoke_commit_marks_local.py

No model calls. Two throwaway accounts (voiceadmin, voiceviola @muse.test), one group, one 60-bar book, a proposed mark
for two parts written directly. Checks that a batch with one bad write changes nothing, that a player cannot accept
the admin's proposal, and that a good batch (edit bars, keep one audience, drop one, add a player) lands whole, with
the bars in each row's payload, which is what a reader's Realtime copy draws from. Never run against hosted.
"""
import json, secrets, subprocess, sys, pathlib, uuid
import httpx

ROOT = pathlib.Path(__file__).resolve().parents[2]
st = json.loads(subprocess.check_output(["supabase", "status", "-o", "json"], cwd=ROOT))
URL, ANON, SECRET = st["API_URL"], st["PUBLISHABLE_KEY"], st["SECRET_KEY"]
assert "127.0.0.1" in URL or "localhost" in URL
PW = secrets.token_urlsafe(12)
svc = httpx.Client(base_url=URL, headers={"apikey": SECRET, "Authorization": f"Bearer {SECRET}"}, timeout=20)
fails = 0


def check(c, what):
    global fails
    print(("  ok   " if c else "  FAIL ") + what)
    fails += (not c)


def rest(cl, m, path, **kw):
    h = {"Prefer": "return=representation"}
    h.update(kw.pop("headers", {}))
    return cl.request(m, f"/rest/v1/{path}", headers=h, **kw)


existing = {u["email"]: u for u in svc.get("/auth/v1/admin/users?per_page=200").json()["users"]}
uid, tok = {}, {}
for n in ("voiceadmin", "voiceviola"):
    e = f"{n}@muse.test"
    if e in existing:
        uid[n] = existing[e]["id"]
        svc.put(f"/auth/v1/admin/users/{uid[n]}", json={"password": PW})
    else:
        uid[n] = svc.post("/auth/v1/admin/users", json={"email": e, "password": PW, "email_confirm": True}).json()["id"]
    tok[n] = httpx.post(f"{URL}/auth/v1/token?grant_type=password", headers={"apikey": ANON},
                        json={"email": e, "password": PW}).json()["access_token"]
cl = {n: httpx.Client(base_url=URL, headers={"apikey": ANON, "Authorization": f"Bearer {t}"}, timeout=20) for n, t in tok.items()}
admin, viola = cl["voiceadmin"], cl["voiceviola"]

rest(svc, "DELETE", "ensembles?name=eq.Commit+Smoke")
try:
    ens = rest(admin, "POST", "ensembles", json={"name": "Commit Smoke", "created_by": uid["voiceadmin"]}).json()[0]["id"]
    lin = rest(admin, "POST", "members", json={"ensemble_id": ens, "user_id": uid["voiceviola"], "role": "player",
                                               "part": "Viola", "display_name": "Lin Chen"}).json()[0]["id"]
    score = rest(admin, "POST", "scores", json={"ensemble_id": ens, "title": "Commit Smoke", "composer": "Test",
                                                "created_by": uid["voiceadmin"], "status": "ready"}).json()[0]["id"]
    bars = {m["number"]: m["id"] for m in rest(admin, "POST", "measures", json=[{"score_id": score, "number": n} for n in range(1, 61)]).json()}

    mark = str(uuid.uuid4())
    utt = str(uuid.uuid4())
    a, b = str(uuid.uuid4()), str(uuid.uuid4())
    base = {"score_id": score, "kind": "cut", "measure_from": bars[42], "measure_to": bars[48], "author_id": uid["voiceadmin"],
            "body": "Cut 42–48", "status": "proposed", "audience": "part",
            "payload": {"source": "voice", "utterance_id": utt, "mark_id": mark, "position": "", "bar": 42, "bar_to": 48}}
    r = rest(admin, "POST", "annotations", json=[{**base, "id": a, "audience_part": "Viola"}, {**base, "id": b, "audience_part": "Cello"}])
    check(r.status_code == 201, "the admin holds a proposed cut for Viola and Cello")

    def rows():
        return {x["id"]: x for x in rest(admin, "GET", f"annotations?score_id=eq.{score}").json()}

    def commit(who, **kw):
        body = {"p_score": score, "p_layer": None, "p_remove": [], "p_update": [], "p_insert": []}
        body.update(kw)
        return rest(who, "POST", "rpc/commit_marks", json=body)

    before = rows()

    # A batch with one write that cannot happen changes nothing.
    r = commit(admin, p_update=[{"id": a, "status": "live", "bar_from": 44, "bar_to": 48, "body": "Cut 44–48"},
                                {"id": str(uuid.uuid4()), "status": "live", "bar_from": 44, "bar_to": 48}])
    check(r.status_code >= 400, f"a batch naming a missing row is refused ({r.status_code})")
    check(rows() == before, "  and nothing in it was written")
    r = commit(admin, p_remove=[b], p_insert=[{"id": str(uuid.uuid4()), "kind": "cut", "bar_from": 44, "bar_to": 48,
                                                "status": "live", "body": "x", "audience": "part", "payload": {}}])
    check(r.status_code >= 400, f"a batch with an invalid new row is refused ({r.status_code})")
    check(rows() == before, "  and its remove did not happen")

    # A player cannot accept the admin's proposal (cannot see it, and may not write a part's cut).
    r = commit(viola, p_update=[{"id": a, "status": "live", "bar_from": 42, "bar_to": 48}])
    check(r.status_code >= 400, f"a player's accept is refused ({r.status_code})")
    r = commit(viola, p_insert=[{"id": str(uuid.uuid4()), "kind": "cut", "bar_from": 1, "bar_to": 2, "status": "live",
                                 "audience": "ensemble", "payload": {}}])
    check(r.status_code >= 400, f"a player cannot write a cut for everyone through it ({r.status_code})")
    check(rows() == before, "  and nothing changed")

    # Accept with edits: bars 44–48, Viola kept, Cello dropped, Lin added.
    new = str(uuid.uuid4())
    r = commit(admin, p_remove=[b],
               p_update=[{"id": a, "status": "live", "bar_from": 44, "bar_to": 48, "body": "Cut 44–48"}],
               p_insert=[{"id": new, "kind": "cut", "bar_from": 44, "bar_to": 48, "status": "live", "body": "Cut 44–48",
                          "audience": "member", "audience_member_id": lin, "payload": base["payload"]}])
    check(r.status_code == 200 and len(r.json()) == 2, f"the accept lands ({r.status_code})")
    after = rows()
    check(b not in after, "  the dropped audience's row is gone")
    ra, rn = after.get(a, {}), after.get(new, {})
    check(ra.get("status") == "live" and ra.get("measure_from") == bars[44] and ra.get("measure_to") == bars[48], "  the kept row is live on bars 44–48")
    check(ra.get("payload", {}).get("bar") == 44 and ra.get("payload", {}).get("bar_to") == 48, "  and its payload says 44–48 (what Realtime draws)")
    check(ra.get("payload", {}).get("mark_id") == mark, "  the rest of its payload is kept")
    check(rn.get("audience") == "member" and rn.get("payload", {}).get("bar") == 44 and rn.get("ensemble_id") is None, "  the added player's row is in the book's layer, bars in its payload")
    seen = {x["id"] for x in rest(viola, "GET", f"annotations?score_id=eq.{score}").json()}
    check(seen == {a, new}, "the Viola player now sees both rows meant for them")

    # Moving a live mark's bars rewrites its payload too.
    r = commit(admin, p_update=[{"id": a, "bar_from": 45, "bar_to": 50}])
    check(r.status_code == 200 and rows()[a]["payload"]["bar"] == 45 and rows()[a]["payload"]["bar_to"] == 50, "an edit of bars only rewrites payload.bar / bar_to")
finally:
    rest(svc, "DELETE", "ensembles?name=eq.Commit+Smoke")
print("FAILS", fails)
sys.exit(1 if fails else 0)
