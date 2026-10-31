"""scripts/backfill_landmarks_playback.py: a Digital book made before 2026-10-30 gets the landmarks and playback the
import writes today, from the same music21 code. Dry run writes nothing; --apply writes; a second run finds nothing;
--owner keeps one owner's books; a split export is never the book's file. Offline: the fake database and bucket of
test_part_split, the fixture MusicXML in web/public/fixtures."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from tests.test_part_split import BACH, FIXTURES, QUARTET, StoreDB

spec = importlib.util.spec_from_file_location("backfill", Path(__file__).resolve().parents[1] / "scripts" / "backfill_landmarks_playback.py")
backfill = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backfill)

OLD, CHORALE, DONE, OTHER = ("a" * 8 + "-0000-0000-0000-" + "0" * 12, "b" * 8 + "-0000-0000-0000-" + "0" * 12,
                             "c" * 8 + "-0000-0000-0000-" + "0" * 12, "d" * 8 + "-0000-0000-0000-" + "0" * 12)


@pytest.fixture
def world(monkeypatch):
    files = {f"{OLD}/source.musicxml": (FIXTURES / QUARTET).read_bytes(),
             f"{OLD}/parts/violin-i.musicxml": b"not the book",
             f"{CHORALE}/source.musicxml": (FIXTURES / BACH).read_bytes(),
             f"{DONE}/source.musicxml": (FIXTURES / BACH).read_bytes(),
             f"{OTHER}/source.musicxml": (FIXTURES / BACH).read_bytes()}
    db = StoreDB(files)
    db.rows["profiles"] = [{"id": "u1", "email": "admin1@muse.test"}, {"id": "u2", "email": "admin@muse.test"}]
    db.rows["ensembles"] = [{"id": "e1", "name": "Quartet"}]
    db.rows["scores"] = [
        {"id": OLD, "title": "Op. 18", "owner_user_id": None, "ensemble_id": "e1", "created_by": "u1", "landmarks": [], "playback": None, "created_at": "1"},
        {"id": CHORALE, "title": "Chorale", "owner_user_id": "u1", "ensemble_id": None, "created_by": "u1", "landmarks": [], "playback": None, "created_at": "2"},
        {"id": DONE, "title": "Done", "owner_user_id": "u1", "ensemble_id": None, "created_by": "u1",
         "landmarks": [{"kind": "fine", "label": "Fine", "bar": 3, "source": "musicxml"}], "playback": {"midi": "x"}, "created_at": "3"},
        {"id": OTHER, "title": "CK's", "owner_user_id": "u2", "ensemble_id": None, "created_by": "u2", "landmarks": [], "playback": None, "created_at": "4"},
    ]
    db.rows["sources"] = [
        {"id": "s-old", "score_id": OLD, "kind": "musicxml", "storage_paths": [f"{OLD}/source.musicxml"], "meta": {}, "created_at": "1"},
        {"id": "s-split", "score_id": OLD, "kind": "musicxml", "storage_paths": [f"{OLD}/parts/violin-i.musicxml"],
         "meta": {"split_from": "s-old", "instruments": ["Violin I"]}, "created_at": "9"},
        {"id": "s-ch", "score_id": CHORALE, "kind": "musicxml", "storage_paths": [f"{CHORALE}/source.musicxml"], "meta": {}, "created_at": "2"},
        {"id": "s-done", "score_id": DONE, "kind": "musicxml", "storage_paths": [f"{DONE}/source.musicxml"], "meta": {}, "created_at": "3"},
        {"id": "s-other", "score_id": OTHER, "kind": "musicxml", "storage_paths": [f"{OTHER}/source.musicxml"], "meta": {}, "created_at": "4"},
        {"id": "s-pdf", "score_id": OTHER, "kind": "pdf", "storage_paths": [f"{OTHER}/source.pdf"], "meta": {}, "created_at": "4"},
    ]
    import app.db
    monkeypatch.setattr(app.db, "db", lambda: db)
    return db


def score(db, sid):
    return next(r for r in db.rows["scores"] if r["id"] == sid)


def test_the_book_file_is_the_converted_one_and_never_a_split_export():
    rows = [{"id": "imp", "storage_paths": ["a"], "meta": {}, "created_at": "1"},
            {"id": "split", "storage_paths": ["b"], "meta": {"split_from": "imp"}, "created_at": "5"},
            {"id": "conv", "storage_paths": ["c"], "meta": {"transcribed_from": "pdf"}, "created_at": "2"}]
    assert backfill.book_source(rows)["id"] == "conv"
    assert backfill.book_source(rows[:2])["id"] == "imp"
    assert backfill.book_source(rows[1:2]) is None


def test_dry_run_writes_nothing(world, capsys):
    before = json.dumps(world.rows["scores"], sort_keys=True)
    assert backfill.main([]) == 0
    out = capsys.readouterr().out
    assert "DRY RUN: 4 Digital books, 3 need a backfill (3 landmarks, 3 playback)" in out
    assert json.dumps(world.rows["scores"], sort_keys=True) == before
    assert not [k for k in world.storage.files if "/playback/" in k]
    assert "admin1@muse.test (group Quartet) | Op. 18" in out and "landmarks 1" in out


def test_apply_writes_what_the_import_writes_and_a_second_run_finds_nothing(world, capsys):
    assert backfill.main(["--apply", "--owner", "admin1@muse.test"]) == 0
    old = score(world, OLD)
    assert [(d["kind"], d["bar"], d["source"]) for d in old["landmarks"]] == [("repeat", 114, "musicxml")]
    assert old["playback"]["midi"] == f"{OLD}/playback/score.mid" and old["playback"]["source_id"] == "s-old"
    assert old["playback"]["parts"] == ["Violin I", "Violin II", "Viola", "Cello"]
    assert world.storage.types[f"{OLD}/playback/score.mid"] == "audio/midi"
    assert json.loads(world.storage.files[f"{OLD}/playback/bars.json"])["bars"][0]["bar"] in (0, 1)
    ch = score(world, CHORALE)
    assert ch["landmarks"] == [] and ch["playback"]["midi"]           # a chorale prints no landmark: nothing written there
    assert score(world, OTHER)["playback"] is None                     # another owner's book is left alone
    capsys.readouterr()
    backfill.main(["--apply", "--owner", "admin1@muse.test"])
    out = capsys.readouterr().out
    assert "1 need a backfill (1 landmarks, 0 playback)" in out and "the file prints none" in out
