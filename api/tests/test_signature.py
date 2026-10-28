"""The signature read (feature 004): canonical key and meter strings, Spark's closed answer turned into them, the crop
and the call, and process_pages writing them to the score. Scripted model, fake database, PIL-drawn page."""
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from app.agent.fake import fake_client, text
from app.librarian import Job
from app.librarian.import_musicxml import import_musicxml
from app.librarian.process_pages import process_pages
from app.librarian.signature import (
    MAX_TOKENS,
    canonical_key,
    canonical_meter,
    interpret,
    key_from_signature,
    read_signature,
)
from app.llm import Completion
from app.spend import Charge
from tests.test_part_cut import Ctx, FakeDB, synth_page

SCORE = "11111111-1111-1111-1111-111111111111"
FIXTURES = Path(__file__).resolve().parents[2] / "web" / "public" / "fixtures"


def sig(accidental="sharps", count=3, mode="minor", name="F# minor", kconf="high", symbol="common", num=None, den=None, tconf="high"):
    return text(json.dumps({"key": {"accidental": accidental, "count": count, "mode": mode, "name": name, "confidence": kconf},
                            "time": {"symbol": symbol, "numerator": num, "denominator": den, "confidence": tconf}, "notes": ""}))


@pytest.mark.parametrize("raw, want", [
    ("f# minor", "F# minor"), ("F sharp minor", "F# minor"), ("E♭ major", "E- major"), ("Eb", "E- major"), ("e- major", "E- major"),
    ("B-flat minor", "B- minor"), ("Bb minor", "B- minor"), ("b minor", "B minor"), ("fis-moll", "F# minor"), ("C major", "C major"),
    ("D", "D major"), ("c# minor", "C# minor"), ("H minor", None), ("", None), (None, None), ("3 sharps", None),
])
def test_canonical_key(raw, want):
    assert canonical_key(raw) == want


@pytest.mark.parametrize("acc, n, mode, want", [
    ("sharps", 3, "minor", "F# minor"), ("sharps", 3, "major", "A major"), ("flats", 3, "major", "E- major"), ("flats", 1, "minor", "D minor"),
    ("none", 0, "major", "C major"), ("none", 0, "minor", "A minor"), ("sharps", 2, "major", "D major"), ("flats", 6, "minor", "E- minor"),
    ("sharps", 7, "major", "C# major"), ("sharps", 1, "unsure", None), ("none", 2, "major", None), ("sharps", 9, "major", None), ("mixed", 2, "major", None),
])
def test_key_from_signature(acc, n, mode, want):
    assert key_from_signature(acc, n, mode) == want


@pytest.mark.parametrize("args, want", [
    ({"text": "3/4"}, "3/4"), ({"text": "C"}, "4/4"), ({"text": "¢"}, "2/2"), ({"symbol": "common"}, "4/4"), ({"symbol": "cut"}, "2/2"),
    ({"symbol": "digits", "numerator": 6, "denominator": 8}, "6/8"), ({"numerator": "3", "denominator": "2"}, "3/2"),
    ({"symbol": "none", "numerator": 4, "denominator": 4}, None), ({"numerator": 3, "denominator": 3}, None), ({"text": "three four"}, None),
])
def test_canonical_meter(args, want):
    t = args.pop("text", None)
    assert canonical_meter(t, **args) == want


def test_interpret_writes_null_when_spark_is_unsure_never_a_guess():
    ok = interpret(json.loads(sig()["text"]))
    assert (ok["key_sig"], ok["meter"], ok["why"]) == ("F# minor", "4/4", [])
    low = interpret(json.loads(sig(kconf="low", tconf="low")["text"]))
    assert (low["key_sig"], low["meter"]) == (None, None) and len(low["why"]) == 2
    unsure = interpret(json.loads(sig(mode="unsure", name="")["text"]))
    assert unsure["key_sig"] is None and unsure["meter"] == "4/4"
    contradiction = interpret(json.loads(sig(name="A major")["text"]))      # counted 3 sharps minor, named A major
    assert contradiction["key_sig"] is None and "named" in contradiction["why"][0]
    none = interpret(json.loads(sig(accidental="flats", count=2, mode="major", name="B-flat major", symbol="none")["text"]))
    assert (none["key_sig"], none["meter"]) == ("B- major", None)
    digits = interpret(json.loads(sig(symbol="digits", num=6, den=8)["text"]))
    assert digits["meter"] == "6/8"
    assert interpret({}) == {"key_sig": None, "meter": None, "why": ["key: low confidence", "time: low confidence"]}


def job(payload: dict) -> Job:
    return Job("job1", "process_pages", payload, SCORE, "u1", 1, 3)


async def test_read_signature_asks_a_closed_question_on_the_first_system():
    c, t = fake_client([sig()])
    db = FakeDB()
    ctx = Ctx(job({"score_id": SCORE}), db, {})
    out = await read_signature(ctx, synth_page(), c, "muse-spark-1.3", title="Concerto")
    assert (out["key_sig"], out["meter"]) == ("F# minor", "4/4")
    assert out["crop"]["staves"] == 6 and out["crop"]["mode"] == "clean" and out["crop_png"].startswith(b"\x89PNG")
    assert out["cost_usd"] > 0 and len(ctx.charges) == 1
    body = t.calls[0]
    assert body["max_tokens"] >= 8000 == MAX_TOKENS and body["output_config"] == {"effort": "low"}
    assert "strict JSON only" in body["system"]
    content = body["messages"][0]["content"]
    assert content[0]["type"] == "image" and "sharps" in content[1]["text"] and "(Concerto)" in content[1]["text"]
    # the crop is the first system, not the page: narrower and shorter than the 1300 x 1700 page, and not widened
    box = out["crop"]["box_px"]
    assert box["y1"] - box["y0"] < 1700 and box["x0"] >= 0 and box["x1"] < 1300


async def test_read_signature_survives_no_json_and_a_blank_page():
    import io

    from PIL import Image
    c, _ = fake_client([text("I think it is in F sharp minor."), text("still prose")])
    ctx = Ctx(job({"score_id": SCORE}), FakeDB(), {})
    out = await read_signature(ctx, synth_page(), c, "muse-spark-1.3")
    assert (out["key_sig"], out["meter"]) == (None, None) and "no JSON" in out["error"] and len(ctx.charges) == 2
    buf = io.BytesIO()
    Image.new("L", (800, 1000), 255).save(buf, format="PNG")
    c, t = fake_client([])
    out = await read_signature(ctx, buf.getvalue(), c, "muse-spark-1.3")
    assert out["error"] == "no system found on page 1" and t.calls == []


LABELS = {"first_measure_number": 1, "is_pickup": False, "confidence": "high",
          "systems": [{"index": 1, "parts": ["Flute", "Oboe", "Horn", "Piano", "Violin I"], "staves_per_part": [1, 1, 1, 2, 1]}],
          "rehearsal_marks": [], "doubtful_measures": [], "title": "", "composer": "Test", "key_signature": "G major", "time_signature": "3/4",
          "parts_difficulty": [{"part": "Piano", "difficulty": 3}], "brief": "A test page. Nothing hard."}


class PagesCtx(Ctx):
    """Ctx whose labelling call (ctx.complete) answers from a list, so process_pages runs with no network."""
    def __init__(self, *a, labels: list[dict], **k):
        super().__init__(*a, **k)
        self.labels = list(labels)

    async def complete(self, user_text: str, **kw) -> Completion:
        c = Completion(json.dumps(self.labels.pop(0)), Charge("meta", "muse-spark-1.3", "spark", Decimal("0.008"), 1000, 200))
        self.charge(c.charge)
        return c


def pages_world(n: int = 1) -> tuple[FakeDB, dict]:
    db = FakeDB()
    db.rows["scores"] = [{"id": SCORE, "title": "Synth", "composer": None, "work": None}]
    db.rows["sources"] = [{"id": "src1", "score_id": SCORE, "kind": "images", "created_by": "u1",
                           "storage_paths": [f"{SCORE}/pages/{i}.png" for i in range(1, n + 1)], "page_order": list(range(1, n + 1)), "page_count": n}]
    return db, {f"{SCORE}/pages/{i}.png": synth_page() for i in range(1, n + 1)}


async def test_process_pages_writes_the_signature_read_not_the_labels_guess():
    db, pages = pages_world(2)
    ctx = PagesCtx(job({"score_id": SCORE, "source_id": "src1"}), db, pages, labels=[LABELS, LABELS])
    c, t = fake_client([sig(accidental="flats", count=3, mode="major", name="E-flat major", symbol="digits", num=3, den=4)])
    out = await process_pages(job({"score_id": SCORE, "source_id": "src1"}), ctx, client=c, model="muse-spark-1.3")
    score = db.rows["scores"][0]
    assert (score["key_sig"], score["meter"], score["status"], score["bars"]) == ("E- major", "3/4", "ready", 8)
    interp = db.rows["interpretations"][0]
    assert interp["summary"]["key_sig"] == "E- major" and interp["summary"]["signature"]["crop_key"] == f"{SCORE}/signature/p001-s1.png"
    assert interp["summary"]["log"][0] == "Page 1, first system: E- major, 3/4"
    assert f"{SCORE}/signature/p001-s1.png" in ctx.uploads and len(t.calls) == 1
    assert out["cost_usd"] == pytest.approx(0.016 + interp["summary"]["signature"]["cost_usd"])
    # an unsure read leaves both blank, even though the page labels said G major and 3/4
    db, pages = pages_world(1)
    ctx = PagesCtx(job({"score_id": SCORE, "source_id": "src1"}), db, pages, labels=[LABELS])
    c, _ = fake_client([sig(kconf="low", tconf="low")])
    await process_pages(job({"score_id": SCORE, "source_id": "src1"}), ctx, client=c, model="muse-spark-1.3")
    assert (db.rows["scores"][0]["key_sig"], db.rows["scores"][0]["meter"]) == (None, None)
    assert "left blank" in db.rows["interpretations"][0]["summary"]["log"][0]


async def test_process_pages_reads_the_signature_once_across_a_question():
    db, pages = pages_world(2)
    other = {**LABELS, "systems": [{"index": 1, "parts": ["Organ"], "staves_per_part": [6]}]}   # page 2 brings a new part: a question
    ctx = PagesCtx(job({"score_id": SCORE, "source_id": "src1"}), db, pages, labels=[LABELS, other])
    c, t = fake_client([sig()])
    out = await process_pages(job({"score_id": SCORE, "source_id": "src1"}), ctx, client=c, model="muse-spark-1.3")
    assert out.get("question") and len(t.calls) == 1
    assert (db.rows["scores"][0]["key_sig"], db.rows["scores"][0]["meter"]) == ("F# minor", "4/4")   # on the cover while parked
    ctx = PagesCtx(job({"score_id": SCORE, "source_id": "src1", "answer": "Organ"}), db, pages, labels=[])
    c, t = fake_client([])                                                                             # no second signature call
    out = await process_pages(job({"score_id": SCORE, "source_id": "src1", "answer": "Organ"}), ctx, client=c, model="muse-spark-1.3")
    assert t.calls == [] and db.rows["scores"][0]["status"] == "ready" and db.rows["scores"][0]["key_sig"] == "F# minor"


@pytest.mark.parametrize("fixture, key_sig, meter, parts", [
    ("bach-bwv66-6.musicxml", "F# minor", "4/4", ["Soprano", "Alto", "Tenor", "Bass"]),
    ("piano-chopin-mazurka06-2.musicxml", "C# minor", "3/4", ["Piano"]),
])
async def test_import_writes_canonical_key_and_meter(fixture, key_sig, meter, parts):
    db = FakeDB()
    path = f"{SCORE}/source.musicxml"
    db.rows["scores"] = [{"id": SCORE, "title": None, "composer": None, "work": None}]
    db.rows["sources"] = [{"id": "x1", "score_id": SCORE, "kind": "musicxml", "storage_paths": [path], "meta": {"filename": fixture}}]
    ctx = Ctx(Job("j", "import_musicxml", {"score_id": SCORE, "source_id": "x1"}, SCORE, "u1", 1, 3), db, {path: (FIXTURES / fixture).read_bytes()})
    await import_musicxml(ctx.job, ctx)
    score = db.rows["scores"][0]
    assert (score["key_sig"], score["meter"]) == (key_sig, meter)
    assert [r["name"] for r in db.rows["parts"]] == parts
