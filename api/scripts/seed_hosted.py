"""Seed the demo world on whichever project api/.env points at (the hosted one, normally). Idempotent.

    cd api && PYTHONPATH=. uv run scripts/seed_hosted.py

Creates "Hart House Chamber Players" with admin@muse.test as admin (seat Viola) and violin1/violin2/cello as
players with their seats. piano@muse.test gets no ensemble: a personal library only. Display names are set on
the membership rows (profiles are private to their owner).
"""
from app.db import db

SEATS = {"admin": ("admin", "Viola", "Ada Okafor"), "violin1": ("player", "Violin I", "Lin Zhou"),
         "violin2": ("player", "Violin II", "Noor Haddad"), "cello": ("player", "Cello", "Inès Marchand")}
NAME = "Hart House Chamber Players"

d = db()
profiles = {p["email"]: p["id"] for p in d.table("profiles").select("id,email").execute().data}
for k in list(SEATS) + ["piano"]:
    assert f"{k}@muse.test" in profiles, f"{k}@muse.test has no profile; create the user in the dashboard first"
for email, pid in profiles.items():
    name = {"admin": "Ada Okafor", "piano": "CK Jiang", "violin1": "Lin Zhou", "violin2": "Noor Haddad", "cello": "Inès Marchand"}.get(email.split("@")[0])
    if name:
        d.table("profiles").update({"display_name": name}).eq("id", pid).execute()

ens = d.table("ensembles").select("id").eq("name", NAME).execute().data
if ens:
    eid = ens[0]["id"]
else:
    eid = d.table("ensembles").insert({"name": NAME, "created_by": profiles["admin@muse.test"]}).execute().data[0]["id"]
for k, (role, seat, name) in SEATS.items():
    d.table("members").upsert({"ensemble_id": eid, "user_id": profiles[f"{k}@muse.test"], "role": role, "part": seat, "display_name": name},
                              on_conflict="ensemble_id,user_id").execute()
roster = d.table("members").select("role,part,display_name").eq("ensemble_id", eid).order("part").execute().data
print(NAME, eid)
for m in roster:
    print(f"  {m['role']:6} {m['part']:10} {m['display_name']}")
