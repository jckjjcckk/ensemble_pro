"""Page reading at effort minimal (speed pass 2026-10-30): the guard that reads a doubtful page again at low, the low
trust of a minimal read's landmarks, and the voice facts leaving out the double bars only a minimal read saw."""
from __future__ import annotations

import json
from decimal import Decimal

from app.agent.fake import fake_client
from app.librarian import landmarks
from app.librarian.labels import PageLabels, doubtful_names, generic_name
from app.librarian.process_pages import page_doubts, process_pages
from app.llm import Completion
from app.spend import Charge
from tests.test_part_cut import HEADER
from tests.test_signature import LABELS, SCORE, PagesCtx, job, pages_world, sig

DOUBLE_BAR = [{"kind": "double_bar", "text": "double bar", "provisional_measure": 2}]


class EffortCtx(PagesCtx):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.efforts: list[str] = []

    async def complete(self, user_text: str, **kw) -> Completion:
        self.efforts.append(kw.get("effort"))
        c = Completion(json.dumps(self.labels.pop(0)), Charge("meta", "muse-spark-1.3", "spark", Decimal("0.004"), 1000, 200))
        self.charge(c.charge)
        return c


def test_generic_and_duplicated_names():
    pool = ["Horns I, II", "Horns III, IV", "Piano"]
    assert generic_name("Horn", pool) and not generic_name("Horn I", pool) and not generic_name("Piano", pool)
    assert doubtful_names([(1, ["Horn", "Piano"])], pool) == ["system 1: 'Horn' is a family name and the book has several such parts"]
    assert doubtful_names([(2, ["Oboe", "Oboe"])], []) == ["system 2: 'Oboe' is given to two parts"]
    assert doubtful_names([(1, ["Flute", "Oboe"])], pool) == []
    # the corpus' false alarms before the bare-name rule: a qualifier, or a name the earlier pages already use
    assert not generic_name("Bass Trombone", ["Tromboni ten. I. II", "Trombone basso"])
    assert not generic_name("Flutes", ["Flutes", "Flauti", "Flauto piccolo"])
    assert generic_name("Horns", ["Horns I, II", "Horns III, IV"])


def test_page_doubts_counts_a_question_as_a_doubt():
    labels = PageLabels.from_dict({"systems": [{"index": 1, "parts": ["Flute"], "staves_per_part": [1]}]})
    why = page_doubts(labels, [{"index": 1, "staves": 6}], [], None)
    assert why and "6 staves" in why[0]


async def test_a_doubted_minimal_page_is_read_again_at_low_and_its_landmarks_are_trusted():
    db, pages = pages_world(2)
    page1 = {**LABELS, "landmarks": DOUBLE_BAR}
    dup = {**LABELS, "systems": [{"index": 1, "parts": ["Flute", "Flute", "Horn", "Piano", "Violin I"], "staves_per_part": [1, 1, 1, 2, 1]}],
           "landmarks": DOUBLE_BAR}
    p = {"score_id": SCORE, "source_id": "src1"}
    ctx = EffortCtx(job(p), db, pages, labels=[page1, dup, {**LABELS, "landmarks": DOUBLE_BAR}])
    c, _ = fake_client([sig(), HEADER])
    out = await process_pages(job(p), ctx, client=c, model="muse-spark-1.3")
    assert not out.get("question") and db.rows["scores"][0]["status"] == "ready"
    assert ctx.efforts == ["minimal", "minimal", "low"]                     # page 2 named Flute twice: read again at low
    state = db.rows["interpretations"][-1]["params"]["state"]
    assert state["pages"]["1"]["effort"] == "minimal" and state["pages"]["2"]["effort"] == "low"
    assert "'Flute' is given to two parts" in state["pages"]["2"]["fallback"][0]
    marks = db.rows["scores"][0]["landmarks"]
    by_bar = {m["bar"]: m for m in marks if m["kind"] == "double_bar"}
    assert by_bar[2]["trust"] == "low" and "trust" not in by_bar[6]           # page 1 kept its minimal read; page 2 is low's
    facts = landmarks.for_facts(marks)
    assert [m["bar"] for m in facts if m["kind"] == "double_bar"] == [6]


def test_for_facts_keeps_a_low_trust_double_bar_a_trusted_read_also_saw():
    marks = [{"kind": "double_bar", "label": "double bar", "bar": 8, "bar_after": 9, "source": "page", "trust": "low"},
             {"kind": "double_bar", "label": "double bar", "bar": 8, "bar_after": 9, "source": "page"},
             {"kind": "double_bar", "label": "double bar", "bar": 20, "bar_after": 21, "source": "page", "trust": "low"},
             {"kind": "tempo", "label": "Adagio", "bar": 20, "source": "page", "trust": "low"}]
    facts = landmarks.for_facts(marks)
    assert [(m["kind"], m["bar"]) for m in facts] == [("double_bar", 8), ("tempo", 20)]
    assert "trust" not in facts[0]
