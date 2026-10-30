"""The book's landmarks (013 voice notes, prompt v4e part a): the stored list, and how the facts say it."""
from __future__ import annotations

from app.librarian import landmarks as L
from app.librarian.voice_prompt import ScoreFacts, build_prompt, landmark_lines
from tests.test_part_cut import FakeDB

SCORE = "11111111-1111-1111-1111-111111111111"


def lm(kind, label, bar, after=None, source="musicxml"):
    return {"kind": kind, "label": label, "bar": bar, "bar_after": after, "source": source}


BOOK_B = [lm("key_change", "F major", 75), lm("double_bar", "double bar", 150, 151), lm("tempo", "Allegro", 1),
          lm("tempo", "Andante", 151), lm("tempo", "Allegro (Tempo I)", 211), lm("section", "Cadenza", 268),
          lm("coda", "Coda", 281), lm("tempo", "poco rit.", 279)]


def test_clean_keeps_valid_landmarks_in_bar_order_and_drops_the_rest():
    raw = BOOK_B + [lm("key_change", "F major", 75), {"kind": "glissando", "label": "x", "bar": 3, "source": "page"},
                    {"kind": "tempo", "label": "Presto", "bar": "12", "source": "page"},
                    {"kind": "tempo", "label": " ", "bar": 12, "source": "page"},
                    lm("double_bar", "", 64, 64), lm("segno", "", 17, None, "elsewhere"), True]
    out = L.clean(raw)
    assert [d["bar"] for d in out] == sorted(d["bar"] for d in out) and len(out) == len(BOOK_B) + 1
    assert next(d for d in out if d["bar"] == 64) == lm("double_bar", "double bar", 64, None)   # bar_after must be later


def test_the_facts_say_boundaries_between_bars_and_headings_as_ranges():
    lines = landmark_lines(L.clean(BOOK_B), 312)
    assert lines == ["Allegro bars 1-150", "key change at bar 75 (F major)", "double bar between bars 150 and 151",
                     "Andante bars 151-210", "Allegro (Tempo I) bars 211-312", "Cadenza at bar 268", "poco rit. at bar 279",
                     "coda bars 281-312"]


def test_a_book_without_landmarks_says_none_listed_and_old_evals_have_no_line():
    assert "Landmarks: none listed." in ScoreFacts(["Cello"], [], landmarks=[]).as_text()
    assert "Landmarks" not in ScoreFacts(["Cello"], []).as_text()


def test_prompt_v4e_lists_the_landmarks_and_resolves_places_named_from_them():
    _, user = build_prompt("Piano, the bar before the double bar, rit.", ScoreFacts(["Piano"], [], 1, 312, landmarks=BOOK_B))
    assert "Landmarks: Allegro bars 1-150; key change at bar 75 (F major); double bar between bars 150 and 151;" in user
    assert "When the score facts list a\n  landmark with its bars, a place named from it resolves to bars" in user
    assert 'a landmark the\n  facts do not list stays "mark".' in user


def test_save_replaces_one_source_and_musicxml_replaces_the_page_reading():
    db = FakeDB()
    db.rows["scores"] = [{"id": SCORE, "landmarks": []}]
    assert L.save(db, SCORE, [lm("tempo", "Adagio", 9, source="page")], "page")
    assert L.save(db, SCORE, [lm("tempo", "Lento", 9, source="page"), lm("segno", "segno", 17, source="page")], "page")
    assert [d["label"] for d in L.load(db, SCORE)] == ["Lento", "segno"]
    assert L.for_facts(L.load(db, SCORE)) == L.load(db, SCORE)
    assert L.save(db, SCORE, [lm("tempo", "Adagio molto", 1, source="anything")], "musicxml")
    assert L.load(db, SCORE) == [lm("tempo", "Adagio molto", 1)]


def test_for_facts_prefers_the_digital_version():
    both = [lm("tempo", "Adagio", 1, source="page"), lm("tempo", "Adagio", 1), lm("segno", "segno", 17)]
    assert {d["source"] for d in L.for_facts(both)} == {"musicxml"}


def test_a_missing_column_never_fails_the_job():
    class NoColumn:
        def table(self, name):
            raise RuntimeError("column scores.landmarks does not exist")
    assert L.load(NoColumn(), SCORE) == [] and L.save(NoColumn(), SCORE, BOOK_B, "musicxml") is False
