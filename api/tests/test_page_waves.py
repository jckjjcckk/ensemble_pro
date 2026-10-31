"""Page reading in two waves (feature 004): the first page with music alone, then the rest at once under a bound; the parts
assigned in page order whatever order the calls finish in; a question on page 3 of 5 that keeps pages 2, 4 and 5; a failed
page that loses none of the others and is the only one read again on the worker's retry; the signature and header reads
in flight together. Synthetic pages, scripted model, fake database; no network."""
from __future__ import annotations

import asyncio
import json
from decimal import Decimal

from app.agent.fake import ScriptedTransport, fake_client
from app.librarian import Job
from app.librarian import process_pages as pp
from app.librarian.process_pages import process_pages
from app.llm import Completion
from app.spend import Charge
from tests.test_part_cut import HEADER, FakeDB, synth_page
import pytest

from tests.test_signature import LABELS, PagesCtx, sig


@pytest.fixture(autouse=True)
def _pages_read_at_low(monkeypatch):
    """These tests script one label answer per page; the minimal read and its fallback to low are tested in
    test_process_pages_guard.py."""
    import app.librarian.process_pages as pp
    monkeypatch.setattr(pp, "PAGE_EFFORT", "low")

SCORE = "11111111-1111-1111-1111-111111111111"


def labels(last: str = "Violin I", brief: str = "A test page. Nothing hard.") -> dict:
    """LABELS with the sixth staff's part renamed, and a brief that tells the pages apart."""
    return {**LABELS, "brief": brief, "systems": [{"index": 1, "parts": ["Flute", "Oboe", "Horn", "Piano", last], "staves_per_part": [1, 1, 1, 2, 1]}]}


class WaveCtx(PagesCtx):
    """Labels by call index (taken when the call starts, so a slow call keeps its page's answer); each call waits its delay,
    `fail_at` raises on that call; `order` makes the calls finish in that order of call indexes (each waits its turn); the
    number of calls in flight at once is kept."""
    def __init__(self, *a, delays: list[float] | None = None, fail_at: int | None = None, order: list[int] | None = None, **k):
        super().__init__(*a, **k)
        self.delays, self.fail_at, self.order = delays or [], fail_at, order
        self.n = self.in_flight = self.max_in_flight = 0
        self.prompts: list[str] = []
        self.finished: list[int] = []

    async def complete(self, user_text: str, **kw) -> Completion:
        k = self.n
        self.n += 1
        self.prompts.append(user_text)
        answer = self.labels[k]
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            await asyncio.sleep(self.delays[k] if k < len(self.delays) else 0)
            while self.order and len(self.finished) < self.order.index(k):
                await asyncio.sleep(0.002)
            if k == self.fail_at:
                self.finished.append(k)
                raise RuntimeError("scripted outage")
            c = Completion(json.dumps(answer), Charge("meta", "muse-spark-1.3", "spark", Decimal("0.008"), 1000, 200))
            self.charge(c.charge)
            self.finished.append(k)
            return c
        finally:
            self.in_flight -= 1


def world(n: int = 5, job_id: str = "job1", payload: dict | None = None, attempts: int = 1, db: FakeDB | None = None) -> tuple[Job, FakeDB, dict]:
    if db is None:
        db = FakeDB()
        db.rows["scores"] = [{"id": SCORE, "title": "Synth", "composer": None, "work": None}]
        db.rows["sources"] = [{"id": "src1", "score_id": SCORE, "kind": "images", "created_by": "u1",
                               "storage_paths": [f"{SCORE}/pages/{i}.png" for i in range(1, n + 1)], "page_order": list(range(1, n + 1)), "page_count": n}]
    job = Job(job_id, "process_pages", {"score_id": SCORE, "source_id": "src1", **(payload or {})}, SCORE, "u1", attempts, 3)
    return job, db, {f"{SCORE}/pages/{i}.png": synth_page() for i in range(1, n + 1)}


def state_of(db: FakeDB) -> dict:
    return db.rows["interpretations"][-1]["params"]["state"]


async def test_the_rest_are_read_at_once_and_assigned_in_page_order():
    """Page 1 names the sixth staff Clarinet. Page 2 (the slowest call) brings Violin I, a part the header lists; page 3 (the
    fastest) prints "Vl. I". In page order "Vl. I" is the Violin I that page 2 brought; assigned in finishing order it would
    have been a part of its own."""
    job, db, pages = world(5)
    script = [labels("Clarinet", "p1"), labels("Violin I", "p2"), labels("Vl. I", "p3"), labels("Violin I", "p4"), labels("Violin I", "p5")]
    ctx = WaveCtx(job, db, pages, labels=script, order=[0, 2, 4, 3, 1])
    c, _ = fake_client([sig(), HEADER])
    out = await process_pages(job, ctx, client=c, model="muse-spark-1.3")
    assert not out.get("question") and db.rows["scores"][0]["status"] == "ready" and db.rows["scores"][0]["bars"] == 20
    assert ctx.max_in_flight == 4 and ctx.finished == [0, 2, 4, 3, 1]          # pages 2-5 at once; they finish 3, 5, 4, 2
    state = state_of(db)
    assert [state["pages"][str(p)]["labels"]["brief"] for p in range(1, 6)] == ["p1", "p2", "p3", "p4", "p5"]
    assert state["known_parts"] == ["Flute", "Oboe", "Horn", "Piano", "Clarinet", "Violin I"]
    assert state["pages"]["3"]["parts"][0]["parts"][-1] == "Violin I" and not any(p.get("pending") for p in state["pages"].values())
    assert [r["name"] for r in db.rows["parts"]] == ["Flute", "Oboe", "Horn", "Piano", "Clarinet", "Violin I"]
    page_lines = [line for line in state["log"] if line.startswith("Page ") and "systems" in line]
    assert [line.split(":")[0] for line in page_lines] == ["Page 1", "Page 2", "Page 3", "Page 4", "Page 5"]
    # every page of the second wave is told the first page's parts, and only those
    assert "Parts already read" not in ctx.prompts[0]
    assert all("in score order: Flute; Oboe; Horn; Piano; Clarinet. When" in p for p in ctx.prompts[1:])
    assert out["cost_usd"] == float(sum(ch.cost_usd for ch in ctx.charges))


async def test_the_second_wave_keeps_to_its_bound(monkeypatch):
    monkeypatch.setattr(pp, "CONCURRENCY", 2)
    job, db, pages = world(6)
    ctx = WaveCtx(job, db, pages, labels=[LABELS] * 6, delays=[0] + [0.02] * 5)
    c, _ = fake_client([sig(), HEADER])
    await process_pages(job, ctx, client=c, model="muse-spark-1.3")
    assert ctx.max_in_flight == 2 and ctx.n == 6 and db.rows["scores"][0]["bars"] == 24


async def test_a_question_on_page_3_of_5_keeps_pages_2_4_and_5():
    job, db, pages = world(5)
    script = [labels(), labels(), labels("Viola", "p3"), labels(brief="p4"), labels(brief="p5")]
    ctx = WaveCtx(job, db, pages, labels=script, order=[0, 2, 3, 4, 1])
    c, _ = fake_client([sig(), HEADER])
    out = await process_pages(job, ctx, client=c, model="muse-spark-1.3")
    assert "Which parts are on page 3" in out["question"] and "Viola" in out["question"] and out["pages_read"] == 3
    interp = db.rows["interpretations"][0]
    assert interp["status"] == "needs_review" and ctx.n == 5
    state = interp["params"]["state"]
    assert sorted(state["pages"], key=int) == ["1", "2", "3", "4", "5"]
    assert state["pages"]["2"]["parts"] and not state["pages"]["2"].get("pending")          # assigned before the question
    assert state["pages"]["3"]["ambiguous"] and state["question"]["page"] == 3
    assert all(state["pages"][k]["pending"] and state["pages"][k]["parts"] is None for k in ("4", "5"))   # read, waiting on the answer
    assert state["known_parts"] == ["Flute", "Oboe", "Horn", "Piano", "Violin I"]

    # the answer: no label call at all, pages 4 and 5 assigned from what was read, in order after page 3
    job2, _, _ = world(5, "job2", {"answer": "Flute, Oboe, Horn, Piano, Viola"}, db=db)
    ctx2 = WaveCtx(job2, db, pages, labels=[])
    c2, t2 = fake_client([])
    out2 = await process_pages(job2, ctx2, client=c2, model="muse-spark-1.3")
    assert ctx2.n == 0 and len(t2.calls) == 0 and not out2.get("question")
    assert db.rows["scores"][0]["status"] == "ready" and db.rows["scores"][0]["bars"] == 20 and len(db.rows["interpretations"]) == 1
    state = state_of(db)
    assert [state["pages"]["5"]["labels"]["brief"], state["pages"]["4"]["labels"]["brief"]] == ["p5", "p4"]
    assert state["pages"]["4"]["parts"][0]["parts"][-1] == "Violin I" and state["known_parts"][-1] == "Viola"
    assert [r["name"] for r in db.rows["parts"]] == ["Flute", "Oboe", "Horn", "Piano", "Violin I", "Viola"]


async def test_a_failed_page_loses_none_of_the_others_and_the_retry_reads_only_it():
    job, db, pages = world(5)
    script = [labels(brief="p1"), labels(brief="p2"), labels(brief="p3"), labels(brief="p4"), labels(brief="p5")]
    ctx = WaveCtx(job, db, pages, labels=script, fail_at=2, order=[0, 2, 3, 1, 4])
    c, _ = fake_client([sig(), HEADER])
    try:
        await process_pages(job, ctx, client=c, model="muse-spark-1.3")
        raise AssertionError("the failed page should fail the attempt")
    except RuntimeError as e:
        assert "scripted outage" in str(e)
    interp = db.rows["interpretations"][0]
    state = interp["params"]["state"]
    assert interp["status"] == "running" and interp["params"]["job_id"] == "job1"
    assert sorted(state["pages"], key=int) == ["1", "2", "4", "5"] and ctx.n == 5
    assert not state["pages"]["2"].get("pending") and state["pages"]["4"]["pending"] and state["pages"]["5"]["pending"]
    paid = state["cost_usd"]

    # the worker's retry of the same job: this interpretation, one label call (page 3), no signature or header again
    retry, _, _ = world(5, "job1", attempts=2, db=db)
    ctx2 = WaveCtx(retry, db, pages, labels=[labels(brief="p3 again")])
    c2, t2 = fake_client([])
    out = await process_pages(retry, ctx2, client=c2, model="muse-spark-1.3")
    assert ctx2.n == 1 and len(t2.calls) == 0 and len(db.rows["interpretations"]) == 1 and not out.get("question")
    assert db.rows["scores"][0]["status"] == "ready" and db.rows["scores"][0]["bars"] == 20
    state = state_of(db)
    assert [state["pages"][str(p)]["labels"]["brief"] for p in range(1, 6)] == ["p1", "p2", "p3 again", "p4", "p5"]
    assert out["cost_usd"] == float(Decimal(str(paid)) + Decimal("0.008"))
    assert any(line.startswith("Attempt 2: 4 pages already read are kept") for line in state["log"])


async def test_a_retry_of_another_job_starts_a_new_reading():
    job, db, pages = world(2)
    ctx = WaveCtx(job, db, pages, labels=[LABELS, LABELS], fail_at=1)
    c, _ = fake_client([sig(), HEADER])
    try:
        await process_pages(job, ctx, client=c, model="muse-spark-1.3")
    except RuntimeError:
        pass
    other, _, _ = world(2, "job-other", attempts=2, db=db)
    ctx2 = WaveCtx(other, db, pages, labels=[LABELS, LABELS])
    c2, _ = fake_client([sig(), HEADER])
    await process_pages(other, ctx2, client=c2, model="muse-spark-1.3")
    assert len(db.rows["interpretations"]) == 2 and ctx2.n == 2 and db.rows["interpretations"][1]["version"] == 2


class SlowTransport(ScriptedTransport):
    """Answers like the scripted transport, after a short wait, keeping how many requests were in flight at once."""
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.in_flight = self.max_in_flight = 0

    async def handle_async_request(self, request):
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            res = await super().handle_async_request(request)
            await asyncio.sleep(0.05)
            return res
        finally:
            self.in_flight -= 1


async def test_the_signature_and_the_header_are_read_at_once():
    import httpx2 as httpx
    from anthropic import AsyncAnthropic
    job, db, pages = world(1)
    t = SlowTransport([sig(), HEADER])
    c = AsyncAnthropic(api_key="fake", base_url="http://fake", max_retries=0, http_client=httpx.AsyncClient(transport=t))
    ctx = PagesCtx(job, db, pages, labels=[LABELS])
    await process_pages(job, ctx, client=c, model="muse-spark-1.3")
    assert t.max_in_flight == 2 and len(t.calls) == 2
    summary = db.rows["interpretations"][0]["summary"]
    assert summary["key_sig"] == "F# minor" and summary["header"]["expected_staves"] == 6
    assert summary["log"][0].startswith("Page 1, first system: F# minor") and summary["log"][1].startswith("Page 1, score header: 6 staves")


def test_a_comma_joined_answer_keeps_a_part_whose_name_has_a_comma():
    """The iPad joins the chosen names with ", " (StaffQuestion.tsx); a name the question offered that holds a comma
    stays one part (E2E night, PC5 p4: "Timpani in Es, B" became "Timpani in Es" and "B")."""
    offered = ["Oboi I II", "Timpani in Es, B", "Violino I", "Flute I, II", "Viola"]
    said = "Oboi I II, Timpani in Es, B, Violino I"
    assert pp.parse_answer(said, offered) == ["Oboi I II", "Timpani in Es, B", "Violino I"]
    assert pp.parse_answer("Flute I, II, Viola", offered) == ["Flute I, II", "Viola"]
    assert pp.parse_answer(said) == ["Oboi I II", "Timpani in Es", "B", "Violino I"]          # nothing offered: commas split
    assert pp.parse_answer(["Timpani in Es, B", "Violino I"], offered) == ["Timpani in Es, B", "Violino I"]   # a list is exact
    assert pp.parse_answer("Piano, Violin 1", ["Piano"]) == ["Piano", "Violin I"]


async def test_the_resumed_page_reads_the_answer_against_the_offered_names():
    job, db, pages = world(5)
    script = [labels(), labels(), labels("Viola, Cello", "p3"), labels(brief="p4"), labels(brief="p5")]
    ctx = WaveCtx(job, db, pages, labels=script, order=[0, 2, 3, 4, 1])
    c, _ = fake_client([sig(), HEADER])
    out = await process_pages(job, ctx, client=c, model="muse-spark-1.3")
    assert "Which parts are on page 3" in out["question"]
    job2, _, _ = world(5, "job2", {"answer": "Flute, Oboe, Horn, Piano, Viola, Cello"}, db=db)
    out2 = await process_pages(job2, WaveCtx(job2, db, pages, labels=[]), client=fake_client([])[0], model="muse-spark-1.3")
    assert not out2.get("question")
    assert state_of(db)["pages"]["3"]["parts"][0]["parts"] == ["Flute", "Oboe", "Horn", "Piano", "Viola, Cello"]
