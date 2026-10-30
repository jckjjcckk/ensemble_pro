"""Voice notes (013): a push-to-talk take to proposed marks. No network: a fake transcriber, a scripted Spark answer,
the fake database and an in-memory bucket."""
from __future__ import annotations

import io
import json
import wave
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app import librarian, worker
from app.librarian import Job, ScoreFailure
from app.librarian.transcribe_voice import Score, pcm_wav, transcribe_voice
from app.llm import Completion
from app.main import app
from app.routes import voice as voice_routes
from app.spend import Charge, require_budget
from tests.test_part_cut import Ctx
from tests.test_part_split import OWNER, Bucket, StoreDB

SCORE = "22222222-2222-2222-2222-222222222222"
GROUP = "33333333-3333-3333-3333-333333333333"
PATH = f"{SCORE}/voice/u1.wav"


def wav(seconds: float = 1.0, rate: int = 16000, channels: int = 1) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\0\0" * int(seconds * rate) * channels)
    return buf.getvalue()


class VoiceBucket(Bucket):
    def remove(self, paths: list[str]) -> None:
        for p in paths:
            self.files.pop(p, None)

    def list(self, prefix: str) -> list[dict]:
        return []


def book(audio: bytes | None = None) -> StoreDB:
    db = StoreDB({})
    db.storage = VoiceBucket({PATH: audio or wav()})
    db.rows["scores"] = [{"id": SCORE, "owner_user_id": "u9", "ensemble_id": GROUP, "current_interpretation_id": "i1"}]
    db.rows["measures"] = [{"id": f"m{n}", "score_id": SCORE, "number": n, "part": None} for n in range(1, 241)]
    db.rows["parts"] = [{"score_id": SCORE, "name": n, "position": i} for i, n in enumerate(["Violin I", "Violin II", "Viola", "Cello"])]
    db.rows["members"] = [{"id": "mem-lin", "ensemble_id": GROUP, "user_id": "u2", "role": "player", "display_name": "Lin Chen", "part": "Viola"},
                          {"id": "mem-ck", "ensemble_id": GROUP, "user_id": "u1", "role": "admin", "display_name": "CK", "part": None}]
    db.rows["measure_placements"] = [{"interpretation_id": "i1", "measure_id": "m57", "rehearsal_mark": "F"},
                                     {"interpretation_id": "i1", "measure_id": "m9", "rehearsal_mark": "A"}]
    return db


class VoiceCtx(Ctx):
    def __init__(self, job: Job, db: StoreDB, answer: object):
        super().__init__(job, db, {})
        self.answer, self.prompts = answer, []

    def storage_download(self, path):
        return self.db.storage.download(path)

    async def complete(self, user_text, **kw):
        self.prompts.append((user_text, kw))
        c = Completion(json.dumps(self.answer), Charge("meta", "muse-spark-1.3", "spark", Decimal("0.003"), 900, 120))
        self.charge(c.charge)
        return c


def heard(text: str):
    async def fake(audio: bytes, keywords: list[str]) -> dict:
        fake.keywords = keywords
        return {"transcript": text, "audioDurationMs": 4000}
    return fake


async def run(text: str, answer: object, db: StoreDB | None = None):
    db = db or book()
    job = Job("j1", "transcribe_voice", {"score_id": SCORE, "ensemble_id": None, "utterance_id": "u1", "audio_path": PATH}, None, "u1", 1, 3)
    ctx = VoiceCtx(job, db, answer)
    asr = heard(text)
    out = await transcribe_voice(job, ctx, transcribe=asr)
    return out, ctx, db, asr


def mark(**k) -> dict:
    return {"position": "bar", "bar_from": None, "bar_to": None, "audience": ["ensemble"], "kind": "text", **k}


SAID = "Second violins, from forty-two to forty-eight we're cutting that. Firsts and seconds, softer at bar sixty."


async def test_a_take_becomes_proposed_rows_one_per_audience_sharing_a_mark_id():
    answer = [mark(position="range", bar_from=42, bar_to=48, audience=["part:Violin II"], kind="cut", text="Cut 42–48",
                   quote="Second violins, from forty-two to forty-eight we're cutting that."),
              mark(bar_from=60, bar_to=60, audience=["part:Violin I", "part:Violin II"], kind="dynamic", text="p at bar 60",
                   quote="Firsts and seconds, softer at bar sixty.")]
    out, ctx, db, asr = await run(SAID, answer)
    rows = db.rows["annotations"]
    assert out["proposed"] == 2 and out["rows"] == 3 and out["unplaced"] == [] and out["refused"] == []
    assert all(r["status"] == "proposed" and r["author_id"] == "u1" and r["payload"]["source"] == "voice" for r in rows)
    cut = [r for r in rows if r["kind"] == "cut"][0]
    assert (cut["measure_from"], cut["measure_to"], cut["audience"], cut["audience_part"]) == ("m42", "m48", "part", "Violin II")
    assert (cut["payload"]["bar"], cut["payload"]["bar_to"]) == (42, 48)      # Realtime inserts carry no joined bar numbers
    soft = [r for r in rows if r["kind"] == "dynamic"]
    assert {r["audience_part"] for r in soft} == {"Violin I", "Violin II"} and len({r["payload"]["mark_id"] for r in soft}) == 1
    assert cut["payload"]["mark_id"] != soft[0]["payload"]["mark_id"]
    assert [c.kind for c in ctx.charges] == ["voice", "spark"] and ctx.charges[0].units == 4.0
    # What was said stays the sender's: no row carries the take's transcript or any quote; the job result does.
    assert all(set(r["payload"]) == {"source", "utterance_id", "mark_id", "position", "bar", "bar_to"} for r in rows)
    assert not any("forty" in json.dumps(r) for r in rows)
    assert out["transcript"] == SAID and out["quotes"][cut["payload"]["mark_id"]].startswith("Second violins")
    assert PATH not in db.storage.files                                          # the take is gone once transcribed
    assert ctx.prompts[0][1]["provider"] == "meta" and ctx.prompts[0][1]["effort"] == "low"
    assert "Lin" in ctx.prompts[0][0] and "Rehearsal letters: A, F." in ctx.prompts[0][0]
    assert {"Violin II", "violins", "firsts", "seconds", "Lin", "letter F"} <= set(asr.keywords)
    assert {"fermata", "sforzando", "pizzicato", "double bar"} <= set(asr.keywords)
    assert "Groups: Strings: Violin I, Violin II, Viola, Cello." in ctx.prompts[0][0]


def test_the_glossary_leaves_out_the_short_generic_words():
    """v4e eval: "pizz" and "cut" split "pizzicato" into "pizz cut"; piano, mute, bar, letter are covered elsewhere."""
    from app.librarian.transcribe_voice import MUSIC_TERMS
    assert not {"pizz", "cut", "piano", "mute", "bar", "letter", "forte", "mezzo"} & set(MUSIC_TERMS)
    assert len(set(MUSIC_TERMS)) == len(MUSIC_TERMS) and {"fermata", "sforzando"} <= set(MUSIC_TERMS)


async def test_a_named_player_is_their_member_row_and_the_ensemble_swallows_parts():
    answer = [mark(bar_from=30, bar_to=30, audience=["member:Lin"], text="Harmonic, bar 30", quote="Lin, bar thirty"),
              mark(bar_from=31, bar_to=31, audience=["ensemble", "part:Viola"], text="mf at 31", kind="dynamic", quote="everyone")]
    out, _, db, _ = await run("Lin, bar thirty, that harmonic. And everyone mezzo forte at thirty-one.", answer)
    lin, tutti = db.rows["annotations"]
    assert (lin["audience"], lin["audience_member_id"]) == ("member", "mem-lin")
    assert (tutti["audience"], tutti["audience_part"]) == ("ensemble", None) and out["rows"] == 2


async def test_a_letter_is_placed_by_the_scores_rehearsal_marks_and_a_landmark_without_one_is_unplaced():
    answer = [mark(position="mark", audience=["part:Viola"], text="rit. before F, a tempo at F", quote="Viola, ritard in the bar before letter F"),
              mark(position="mark", audience=["part:Cello"], text="Breath at the double bar", kind="breath", quote="cellos, breathe at the double bar")]
    out, _, db, _ = await run("Viola, ritard in the bar before letter F. And cellos, breathe at the double bar.", answer)
    (rit,) = db.rows["annotations"]
    assert (rit["measure_from"], rit["measure_to"]) == ("m56", "m56")
    assert out["proposed"] == 1 and out["unplaced"][0]["text"] == "Breath at the double bar"


async def test_the_books_landmarks_are_in_the_facts_and_a_converted_books_musicxml_wins():
    """013 v4e: the facts list the landmarks with bars (a boundary between two bars); page ones give way to the
    MusicXML's once the book is converted; a digital book's rehearsal letters come from its MusicXML."""
    db = book()
    db.rows["measure_placements"] = []
    db.rows["scores"][0]["landmarks"] = [
        {"kind": "double_bar", "label": "double bar", "bar": 64, "bar_after": 65, "source": "musicxml"},
        {"kind": "key_change", "label": "3 flats", "bar": 97, "bar_after": None, "source": "musicxml"},
        {"kind": "rehearsal", "label": "B", "bar": 33, "bar_after": None, "source": "musicxml"},
        {"kind": "tempo", "label": "Adagio", "bar": 120, "bar_after": None, "source": "page"},
        {"kind": "segno", "label": "segno", "bar": 400, "bar_after": None, "source": "musicxml"}]       # past the last bar
    answer = [mark(position="bar", bar_from=63, bar_to=63, audience=["part:Cello"], kind="breath", text="Breath at 63",
                   quote="Cellos, breathe in the bar before the double bar.")]
    out, ctx, db, _ = await run("Cellos, breathe in the bar before the double bar.", answer, db)
    prompt = ctx.prompts[0][0]
    assert "Landmarks: double bar between bars 64 and 65; key change at bar 97 (3 flats)." in prompt
    assert "Adagio" not in prompt and "segno" not in prompt and "Rehearsal letters: B." in prompt
    assert [(r["measure_from"], r["audience_part"]) for r in db.rows["annotations"]] == [("m63", "Cello")]


async def test_a_book_without_the_column_or_landmarks_says_none_listed():
    _, ctx, _, _ = await run("Bar nine, mezzo forte.", {"none": True})
    assert "Landmarks: none listed." in ctx.prompts[0][0]


async def test_range_to_the_end_and_global_marks_get_bars():
    answer = [mark(position="range", bar_from=200, bar_to=None, text="cresc. 200 to the end", kind="dynamic", quote="from two hundred to the end"),
              mark(position="global", text="Lighter at the very end", quote="lighter at the very end")]
    _, _, db, _ = await run("Everyone, crescendo from two hundred to the end, and lighter at the very end.", answer)
    a, b = db.rows["annotations"]
    assert (a["measure_from"], a["measure_to"]) == ("m200", "m240") and (b["measure_from"], b["measure_to"]) == ("m240", "m240")


async def test_checks_refuse_invented_quotes_and_bars_outside_the_score():
    answer = [mark(bar_from=12, bar_to=12, text="mf", quote="something nobody said"),
              mark(bar_from=900, bar_to=900, text="mf at 900", quote="bar nine hundred")]
    out, _, db, _ = await run("Everyone mezzo forte at bar nine hundred.", answer)
    assert out["proposed"] == 0 and not db.rows.get("annotations")
    assert out["refused"] == ["a mark on words that were not said", "bar 900 is not in this book (bars 1–240)"]


async def test_nothing_to_mark_and_silence_write_nothing():
    out, ctx, db, _ = await run("Okay, from the top.", {"none": True})
    assert out["proposed"] == 0 and out["refused"] == [] and not db.rows.get("annotations")
    out, ctx, db, _ = await run("", [])
    assert out["transcript"] == "" and ctx.prompts == [] and [c.kind for c in ctx.charges] == ["voice"]


def test_refusals_read_as_words():
    from app.librarian.transcribe_voice import plain
    assert plain("audience 'part:Alto'") == "Alto is not a part in this book"
    assert plain("audience 'member:Ana'") == "Ana is not in this group"
    assert plain("kind 'tempo'") == "a mark Muse could not read"


async def test_a_retry_after_transcription_reuses_the_transcript_without_the_audio():
    db = book()
    db.rows["jobs"] = [{"id": "j1", "result": {"utterance_id": "u1", "transcript": "Bar three, four beats. Count it."}}]
    db.storage.files.clear()                                                     # deleted on the first attempt
    answer = [mark(bar_from=3, bar_to=3, text="4 beats at bar 3", quote="Bar three, four beats.")]
    out, ctx, db, asr = await run("never heard again", answer, db)
    assert not hasattr(asr, "keywords") and [c.kind for c in ctx.charges] == ["spark"]
    assert out["transcript"] == "Bar three, four beats. Count it." and out["proposed"] == 1


def test_only_mono_16_bit_speech_rates_pass():
    assert pcm_wav(wav(2.0))[1] == pytest.approx(2.0)
    for bad in (wav(rate=44100), wav(channels=2), b"RIFF0000WAVEnot really"):
        with pytest.raises(ScoreFailure):
            pcm_wav(bad)
    with pytest.raises(ScoreFailure):
        pcm_wav(wav(seconds=151))


def test_a_book_without_bars_cannot_take_notes():
    db = book()
    db.rows["measures"] = []
    with pytest.raises(ScoreFailure):
        Score(db, SCORE, None)


# ---------- the route ----------

@pytest.fixture
def client(monkeypatch):
    def use(db: StoreDB) -> TestClient:
        monkeypatch.setattr(voice_routes, "db", lambda: db)
        monkeypatch.setattr(worker, "db", lambda: db)
        monkeypatch.setattr(librarian, "_db", lambda: db)
        monkeypatch.setattr(voice_routes, "run_one", lambda row: None)     # the job itself is tested above
        app.dependency_overrides[require_budget] = lambda: OWNER
        return TestClient(app)
    yield use
    app.dependency_overrides.clear()


def test_the_groups_admin_sends_a_take_and_gets_a_running_job(client):
    db = book()
    r = client(db).post(f"/scores/{SCORE}/voice", content=wav(3.0), headers={"Content-Type": "audio/wav"})
    assert r.status_code == 202, r.text
    job = db.rows["jobs"][0]
    assert r.json() == {"job_id": job["id"], "utterance_id": job["payload"]["utterance_id"]}
    assert job["kind"] == "transcribe_voice" and job["status"] == "running" and job.get("score_id") is None
    assert job["payload"]["audio_path"] in db.storage.files and db.storage.types[job["payload"]["audio_path"]] == "audio/wav"


def test_a_player_or_a_stranger_cannot(client):
    db = book()
    db.rows["members"][1]["role"] = "player"
    assert client(db).post(f"/scores/{SCORE}/voice", content=wav(), headers={"Content-Type": "audio/wav"}).status_code == 403
    db.rows["members"] = []
    assert client(db).post(f"/scores/{SCORE}/voice", content=wav(), headers={"Content-Type": "audio/wav"}).status_code == 403


def test_the_owner_of_a_personal_book_can_and_not_a_wav_is_refused(client):
    db = book()
    db.rows["scores"][0].update(ensemble_id=None, owner_user_id="u1")
    c = client(db)
    assert c.post(f"/scores/{SCORE}/voice", content=b"not audio", headers={"Content-Type": "audio/wav"}).status_code == 400
    assert c.post(f"/scores/{SCORE}/voice", content=wav(), headers={"Content-Type": "audio/wav"}).status_code == 202
