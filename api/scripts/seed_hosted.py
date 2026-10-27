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


# ---------------------------------------------------------------- the three fixture scores (Path A), idempotent by title
# Beethoven and Bach into the quartet's library, the Chopin into the pianist's own. The running API's worker imports them.
from pathlib import Path

FIX = Path(__file__).resolve().parents[2] / "web" / "public" / "fixtures"
SCORES = [
    ("beethoven-op18no1-mv1.musicxml", {"ensemble_id": eid, "title": "String Quartet No. 1 in F major", "composer": "Ludwig van Beethoven", "work": "Op. 18 No. 1, I. Allegro con brio", "folder": "Autumn programme"}, profiles["admin@muse.test"]),
    ("bach-bwv66-6.musicxml", {"ensemble_id": eid, "title": "Christ ist erstanden", "composer": "Johann Sebastian Bach", "work": "BWV 66.6, chorale", "folder": "Reading week"}, profiles["admin@muse.test"]),
    ("piano-chopin-mazurka06-2.musicxml", {"owner_user_id": profiles["piano@muse.test"], "title": "Mazurka in C♯ minor", "composer": "Frédéric Chopin", "work": "Op. 6 No. 2", "folder": "Chopin"}, profiles["piano@muse.test"]),
]
for fname, fields, by in SCORES:
    if d.table("scores").select("id").eq("title", fields["title"]).execute().data:
        print(f"  have   {fields['title']}")
        continue
    score = d.table("scores").insert({**fields, "status": "uploaded", "created_by": by}).execute().data[0]
    key = f"{score['id']}/source.musicxml"
    d.storage.from_("scores").upload(key, (FIX / fname).read_bytes(), {"content-type": "application/vnd.recordare.musicxml+xml", "upsert": "true"})
    src = d.table("sources").insert({"score_id": score["id"], "kind": "musicxml", "storage_paths": [key], "meta": {"filename": fname}, "created_by": by}).execute().data[0]
    d.table("jobs").insert({"kind": "import_musicxml", "score_id": score["id"], "created_by": by, "payload": {"score_id": score["id"], "source_id": src["id"]}}).execute()
    d.table("scores").update({"status": "processing", "progress": 0}).eq("id", score["id"]).execute()
    print(f"  queued {fields['title']}")
