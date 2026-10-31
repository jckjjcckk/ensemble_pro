"""The book's label memory (008, 006 agentic memory rule): seed, provenance, normalisation, unknown labels."""
from __future__ import annotations

from app.librarian.label_memory import LabelMemory, load, norm, same_label, same_part, save
from tests.test_part_cut import FakeDB

PC3_HEADER = {"page": 1, "instruments": [
    {"label": "Klarinetten in B I. II.", "abbreviations": ["Klar."], "staves": 1},
    {"label": "Hörner in Es I. II.", "abbreviations": ["Cor."], "staves": 1},
    {"label": "Klavier", "abbreviations": ["Klav."], "staves": 2},
    {"label": "Violine I", "abbreviations": ["Vl. I"], "staves": 1},
    {"label": "Violine II", "abbreviations": ["Vl. II"], "staves": 1}]}
BOOK_PARTS = ["Clarinets in B I, II", "Horns in E-flat I, II", "Piano", "Violin I", "Violin II"]


def test_norm():
    assert norm("Klav.") == "klav" and norm("  Vl.  I ") == "vl i" and norm("Violoncello u. Kontrabaß") == "violoncello u kontrabaß" and norm(None) == ""


def test_seed_from_the_header_names_the_books_parts():
    m = LabelMemory()
    assert m.seed_from_header(PC3_HEADER, BOOK_PARTS) == 10 and m.changed
    assert m.entries["klavier"]["part"] == "Piano" and m.entries["klav"]["part"] == "Piano"
    assert m.entries["klav"]["origin"] == "header-abbreviation" and m.entries["klavier"]["source"] == "model" and m.entries["klavier"]["page"] == 1
    assert m.entries["violine i"]["part"] == "Violin I" and m.entries["vl ii"]["part"] == "Violin II"
    assert m.seed_from_header(PC3_HEADER, BOOK_PARTS) == 0          # seeding again learns nothing


def test_normalisation_resolves_abbreviations_and_synonyms():
    m = LabelMemory()
    m.learn("Klavier", "Piano", "model", "header", page=1)
    m.learn("Violine I", "Violin I", "model", "header", page=1)
    m.learn("Violine II", "Violin II", "model", "header", page=1)
    for printed in ("Klav.", "Klav", "KLAVIER", "Pfte.", "Pianoforte", "Klavier."):
        assert (m.resolve(printed) or {}).get("part") == "Piano", printed
    assert m.resolve("Viol. I")["part"] == "Violin I" and m.resolve("Vl. II")["part"] == "Violin II"
    assert same_label("Klav.", "Klavier") and not same_label("Klav.", "Klarinetten") and not same_label("Vl. I", "Violine II")


def test_a_new_label_does_not_resolve():
    m = LabelMemory()
    m.seed_from_header(PC3_HEADER, BOOK_PARTS)
    assert m.resolve("Org.") is None and m.resolve("Tromp.") is None and m.resolve("") is None


def test_two_parts_for_one_label_leave_it_unresolved():
    m = LabelMemory()
    m.learn("Violine", "Violin I", "model", "header")         # the header gave the unnumbered name to the firsts,
    m.learn("Violinen", "Violin II", "model", "page")         # a page to the seconds
    assert m.resolve("Viol.") is None                          # both match, two parts: unresolved, so it asks
    assert m.resolve("Violine")["part"] == "Violin I"          # the exact label still resolves


def test_a_human_answer_overrides_the_model_and_the_model_never_overrides_a_human():
    m = LabelMemory()
    m.learn("Klav.", "Piano", "model", "header-abbreviation", page=1)
    assert not m.learn("Klav.", "Celesta", "model", "page", page=3)            # a second model read does not move a model entry
    assert m.learn("Klav.", "Celesta", "human", "answer", page=2, staves=[19, 20])
    e = m.resolve("Klav.")
    assert e["part"] == "Celesta" and e["source"] == "human" and e["page"] == 2 and e["staves"] == [19, 20]
    assert not m.learn("Klav.", "Piano", "model", "header-abbreviation", page=1)   # the header cannot take it back
    assert m.resolve("Klav")["source"] == "human"
    other = LabelMemory({"klav": {"label": "Klav.", "part": "Piano", "source": "model", "origin": "header"}})
    other.merge(m)
    assert other.entries["klav"]["source"] == "human"                            # merging keeps the human's word


def test_a_human_entry_wins_a_fuzzy_tie():
    m = LabelMemory()
    m.learn("Klavier", "Piano", "model", "header", page=1)
    m.learn("Klav", "Piano", "human", "answer", page=2)
    assert m.resolve("Klav.")["source"] == "human"
    assert m.resolve("Pfte.")["source"] == "human"


def test_same_part():
    assert same_part("Pianoforte", "Piano") and same_part("Klavier", "Piano") and same_part("Piano", "piano")
    assert not same_part("Piano I", "Piano") and not same_part("Violin I", "Violin II") and not same_part("Horn", "Piano")


def test_context_lists_the_users_answers_first():
    m = LabelMemory()
    m.learn("Klavier", "Piano", "model", "header", page=1)
    m.learn("Klav.", "Piano", "human", "answer", page=2)
    m.learn("Fl.", "Flute", "model", "header", page=1)
    ctx = m.context(["Piano"])
    assert ctx.index('"Klav." is Piano (confirmed by the user on page 2)') < ctx.index('"Klavier" is Piano (read from the first page)')
    assert "Fl." not in ctx and m.context(["Oboe"]) == ""


def test_load_and_save_on_the_score_row():
    db = FakeDB()
    db.rows["scores"] = [{"id": "s1"}]
    m = load(db, "s1")
    assert m.entries == {}
    m.learn("Klav.", "Piano", "human", "answer", page=2)
    db.rows["scores"][0]["label_memory"] = {"entries": {"fl": {"label": "Fl.", "part": "Flute", "source": "model", "origin": "header"}}}   # another job meanwhile
    assert save(db, "s1", m) and not m.changed
    assert set(db.rows["scores"][0]["label_memory"]["entries"]) == {"klav", "fl"}
    assert not save(db, "s1", m)                                                  # nothing new, no write


def test_a_missing_column_never_fails_the_job():
    class Broken:
        def table(self, name):
            raise RuntimeError("column scores.label_memory does not exist")
    m = load(Broken(), "s1")
    assert m.entries == {}
    m.learn("Klav.", "Piano", "human", "answer")
    assert save(Broken(), "s1", m) is False and m.changed


# ---------------------------------------------------------------- layouts (follow-up, 2026-10-31)

def test_a_layout_is_kept_by_staff_count_with_the_humans_word_first():
    m = LabelMemory()
    assert m.learn_layout(3, [], "Violin", [1], "model", "page", page=1) and m.learn_layout(3, [], "Piano", [2, 3], "model", "page", page=1)
    assert m.layout_part(3, [], "Pianoforte")["positions"] == [2, 3] and m.layout_part(2, [], "Piano") is None
    assert m.full_layout(3) == {"parts": ["Violin", "Piano"], "staves_per_part": [1, 2], "source": "model", "page": 1}
    assert not m.learn_layout(3, [], "Piano", [2, 3], "model", "page", page=4)          # known: the first read stands
    assert m.learn_layout(3, [], "Piano", [1, 2], "model", "page", page=5)               # a second read disagrees: disputed
    assert m.layout_part(3, [], "Piano") is None and m.full_layout(3) is None
    assert m.learn_layout(3, [], "Piano", [2, 3], "human", "answer", page=6, system=2)   # the admin settles it
    e = m.layout_part(3, [], "Piano")
    assert e["source"] == "human" and e["page"] == 6 and e["system"] == 2 and not e.get("disputed")
    assert not m.learn_layout(3, [], "Piano", [1, 2], "model", "page", page=7)           # a model read never moves the human
    assert m.learn_layout(3, [], "Cello", [1], "human", "answer", page=8)                # a human takes staff 1 from the violin
    assert m.full_layout(3)["parts"] == ["Cello", "Piano"] and m.full_layout(3)["source"] == "human"


def test_a_labelled_system_takes_only_the_layout_of_the_same_labels_in_order():
    m = LabelMemory()
    m.learn_layout(4, ["Vl. I", "Vl. II", "Vla.", "Vc."], "Viola", [3], "human", "answer", page=2)
    assert m.layout_part(4, ["Vl.I", "Vl. II", "Vla", "Vc"], "Viola")["positions"] == [3]          # the same labels, normalised
    assert m.layout_part(4, ["Vc.", "Vla.", "Vl. II", "Vl. I"], "Viola") is None                  # another order
    assert m.layout_part(4, [], "Viola")["positions"] == [3]                                      # a bare system of that count
    assert m.full_layout(4) is None                                                               # one part is not the whole system


def test_layouts_survive_the_row_and_merge_under_the_same_rule():
    db = FakeDB()
    db.rows["scores"] = [{"id": "s1"}]
    m = load(db, "s1")
    m.learn_layout(1, [], "Pianoforte", [1], "human", "answer", page=12, system=4)
    db.rows["scores"][0]["label_memory"] = {"entries": {}, "layouts": {"2": {"staves": 2, "labels": [], "parts": {
        "Pianoforte": {"positions": [1, 2], "source": "model", "origin": "page", "page": 8}}}, "bad": {"staves": 2, "parts": {"X": {"positions": [5], "source": "model"}}}}}
    assert save(db, "s1", m)
    again = load(db, "s1")
    assert set(again.layouts) == {"1", "2"} and again.layout_part(1, [], "Piano")["source"] == "human"
    assert again.layout_part(2, [], "Pianoforte")["positions"] == [1, 2]
