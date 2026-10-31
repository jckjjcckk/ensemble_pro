"""Backfill a Digital book's landmarks and playback, for books made before the import and Convert to Digital wrote them
(013 v4e `scores.landmarks`, migration 20261030160000; 014 `scores.playback`, migration 20261030180000).

    cd api && uv run python scripts/backfill_landmarks_playback.py                          # dry run, every owner
    cd api && uv run python scripts/backfill_landmarks_playback.py --owner admin1@muse.test --apply

A book is Digital when it has a `sources` row of kind `musicxml` that is not a split export (`meta.split_from`). Its
MusicXML is the converted file when it has one (`meta.transcribed_from`, newest first), else the imported one. A book
needs **landmarks** when `scores.landmarks` holds no entry of source `musicxml`, and **playback** when `scores.playback`
is empty. Both come from the same music21 code the import and the convert run (`import_musicxml.book_facts` →
`landmarks.from_musicxml`, `landmarks.save`; `playback.write_step`: `{score}/playback/score.mid` and `bars.json`,
uploaded with upsert, then the score row). No model call: no Spark, no spend.

Dry run by default: downloads and parses each book's file and says what it would write, writes nothing. `--apply`
writes. Idempotent: a book that has both is skipped; a file that prints no landmark leaves `scores.landmarks` as it is
(and is reported so on every run); a re-run uploads the same playback files over themselves. `--owner EMAIL`
(repeatable) keeps the books of those owners: a personal book's owner, or for a group's book the account that added it
(`scores.created_by`). Acts through the API's service role (api/.env); prints no key, no URL. Never deletes anything.
"""
from __future__ import annotations

import argparse
import asyncio
import io
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from music21 import converter  # noqa: E402

from app.librarian import landmarks, playback  # noqa: E402
from app.librarian.import_musicxml import book_facts  # noqa: E402
from app.librarian.musicxml_fix import unzip_mxl  # noqa: E402


class Ctx:
    """What `playback.write_step` uses of a JobContext: the service-role client, Storage upload, a timestamp."""

    def __init__(self, db):
        self.db = db

    def storage_upload(self, path: str, data: bytes, content_type: str) -> None:
        self.db.storage.from_("scores").upload(path, data, {"content-type": content_type, "upsert": "true"})

    @staticmethod
    def now() -> str:
        return datetime.now(timezone.utc).isoformat()


def book_source(sources: list[dict]) -> dict | None:
    """The book's own MusicXML among its `musicxml` sources: the converted file (newest) before the imported one, never
    a split export."""
    own = [s for s in sources if not (s.get("meta") or {}).get("split_from") and s.get("storage_paths")]
    own.sort(key=lambda s: (bool((s.get("meta") or {}).get("transcribed_from")), s.get("created_at") or ""), reverse=True)
    return own[0] if own else None


def needs(score: dict) -> list[str]:
    out = []
    if not any(isinstance(d, dict) and d.get("source") == "musicxml" for d in (score.get("landmarks") or [])):
        out.append("landmarks")
    if not (score.get("playback") or {}).get("midi"):
        out.append("playback")
    return out


def owner_of(score: dict, emails: dict[str, str], groups: dict[str, str]) -> tuple[str, str]:
    """(owner email, where): a personal book's owner, or for a group's book the account that added it."""
    if score.get("owner_user_id"):
        return emails.get(score["owner_user_id"], score["owner_user_id"]), "personal"
    return emails.get(score["created_by"], score["created_by"]), f"group {groups.get(score.get('ensemble_id'), '?')}"


def candidates(db, owners: set[str] | None) -> list[dict]:
    sources = db.table("sources").select("id,score_id,storage_paths,meta,created_at").eq("kind", "musicxml").execute().data or []
    by_score: dict[str, list[dict]] = {}
    for s in sources:
        by_score.setdefault(s["score_id"], []).append(s)
    if not by_score:
        return []
    ids = sorted(by_score)
    scores = []
    for i in range(0, len(ids), 100):
        scores += db.table("scores").select("id,title,owner_user_id,ensemble_id,created_by,landmarks,playback,created_at") \
            .in_("id", ids[i:i + 100]).execute().data or []
    emails = {p["id"]: p["email"] for p in db.table("profiles").select("id,email").execute().data or []}
    groups = {e["id"]: e["name"] for e in db.table("ensembles").select("id,name").execute().data or []}
    out = []
    for sc in sorted(scores, key=lambda r: r["created_at"]):
        src = book_source(by_score.get(sc["id"], []))
        if src is None:
            continue
        email, where = owner_of(sc, emails, groups)
        if owners and email.lower() not in owners:
            continue
        out.append({"score": sc, "source": src, "owner": email, "where": where, "needs": needs(sc)})
    return out


def parse(db, src: dict):
    data = db.storage.from_("scores").download(src["storage_paths"][0])
    if data[:2] == b"PK":                    # a compressed .mxl stored before 9b44938: read the score inside, in memory
        data = unzip_mxl(data)
    return converter.parse(io.BytesIO(data).read(), format="musicxml")


async def fill(db, c: dict, apply: bool) -> dict:
    sc, src = c["score"], c["source"]
    t0 = time.time()
    s = await asyncio.to_thread(parse, db, src)
    out: dict = {}
    if "landmarks" in c["needs"]:
        marks = (await asyncio.to_thread(book_facts, s))["landmarks"]
        out["landmarks"] = len(marks)
        if marks and apply:
            out["landmarks_saved"] = landmarks.save(db, sc["id"], marks, "musicxml")
    if "playback" in c["needs"]:
        if apply:
            r = await playback.write_step(Ctx(db), sc["id"], src["id"], s)
            out["playback"] = {k: r.get(k) for k in ("ok", "tracks", "bars", "midi_bytes", "reason") if r.get(k) is not None}
        else:
            data, bar_map = await asyncio.to_thread(playback.build, s)
            out["playback"] = {"tracks": len(bar_map["parts"]), "bars": len(bar_map["bars"]), "midi_bytes": len(data)}
    out["seconds"] = round(time.time() - t0, 1)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--apply", action="store_true", help="write (default: dry run)")
    ap.add_argument("--owner", action="append", metavar="EMAIL", help="only these owners' books (repeatable)")
    ap.add_argument("--score", action="append", metavar="ID", help="only these books (repeatable)")
    a = ap.parse_args(argv)
    from app.db import db as get_db
    db = get_db()
    owners = {e.lower() for e in a.owner} if a.owner else None
    books = candidates(db, owners)
    if a.score:
        books = [b for b in books if b["score"]["id"] in set(a.score)]
    todo = [b for b in books if b["needs"]]
    print(f"{'APPLY' if a.apply else 'DRY RUN'}: {len(books)} Digital books" + (f" of {', '.join(sorted(owners))}" if owners else "")
          + f", {len(todo)} need a backfill ({sum('landmarks' in b['needs'] for b in todo)} landmarks, "
            f"{sum('playback' in b['needs'] for b in todo)} playback)")
    per_owner: dict[str, int] = {}
    failed = 0
    for b in todo:
        per_owner[b["owner"]] = per_owner.get(b["owner"], 0) + 1
        head = f"- {b['owner']} ({b['where']}) | {b['score']['title'][:50]} | {b['score']['id']} | needs {'+'.join(b['needs'])}"
        try:
            r = asyncio.run(fill(db, b, a.apply))
        except Exception as e:  # noqa: BLE001  (one book's file never stops the others)
            failed += 1
            print(f"{head} | FAILED {type(e).__name__}: {str(e)[:160]}")
            continue
        lm = r.get("landmarks")
        lm_txt = "" if lm is None else (f" | landmarks {lm}" + ("" if lm else " (the file prints none; nothing to write)"))
        print(f"{head}{lm_txt}" + (f" | playback {r['playback']}" if "playback" in r else "") + f" | {r['seconds']} s")
    for owner, n in sorted(per_owner.items()):
        print(f"  {owner}: {n}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
