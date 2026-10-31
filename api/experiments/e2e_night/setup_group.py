"""The demo group for the night: "Hart House Quartet", admin1 its admin, two players with seats Violin I and Cello.
Service role, idempotent (as scripts/seed_hosted.py does). CK named muse2@muse.test for the cellist; the hosted project
has no such account, and test2@muse.test was created with admin1 and test1 at 09:06 UTC, so test2 takes the seat.

    cd api && PYTHONPATH=. uv run python -m experiments.e2e_night.setup_group
"""
from app.db import db

from .common import GROUP

SEATS = [("admin1@muse.test", "admin", None, "admin1"), ("test1@muse.test", "player", "Violin I", "test1"),
         ("test2@muse.test", "player", "Cello", "test2")]

d = db()
ids = {p["email"]: p["id"] for p in d.table("profiles").select("id,email").execute().data}
for email, *_ in SEATS:
    assert email in ids, f"{email} has no profile"
ens = d.table("ensembles").select("id,join_code").eq("name", GROUP).execute().data
if ens:
    eid = ens[0]["id"]
else:
    eid = d.table("ensembles").insert({"name": GROUP, "created_by": ids["admin1@muse.test"]}).execute().data[0]["id"]
for email, role, part, name in SEATS:
    d.table("members").upsert({"ensemble_id": eid, "user_id": ids[email], "role": role, "part": part, "display_name": name},
                              on_conflict="ensemble_id,user_id").execute()
for m in d.table("members").select("role,part,display_name,user_id").eq("ensemble_id", eid).execute().data:
    print(f"  {m['role']:6} {str(m['part']):9} {m['display_name']}")
print(GROUP, "ready")
