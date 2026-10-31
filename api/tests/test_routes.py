"""The part-cut and answer routes against the fake database: auth through dependency overrides, no network."""
from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.auth import User, current_user
from app.main import app
from app.routes import jobs as jobs_routes, live_jobs, scores as scores_routes
from app.spend import require_budget
from tests.test_part_cut import FakeDB

SCORE = "11111111-1111-1111-1111-111111111111"
OWNER = User("u1", "owner@muse.test", "Owner", Decimal("5"), Decimal("0"))
OTHER = User("u2", "other@muse.test", "Other", Decimal("5"), Decimal("0"))


@pytest.fixture
def world(monkeypatch):
    db = FakeDB()
    db.rows["scores"] = [{"id": SCORE, "owner_user_id": "u1", "ensemble_id": None}]
    db.rows["sources"] = [{"id": "src1", "score_id": SCORE, "kind": "images"}]
    db.rows["members"] = []
    monkeypatch.setattr(scores_routes, "db", lambda: db)
    monkeypatch.setattr(jobs_routes, "db", lambda: db)
    client = TestClient(app)
    yield db, client
    app.dependency_overrides.clear()


def as_user(user: User) -> None:
    app.dependency_overrides[require_budget] = lambda: user
    app.dependency_overrides[current_user] = lambda: user


def test_parts_route_queues_a_part_cut_job(world):
    db, client = world
    as_user(OWNER)
    r = client.post(f"/scores/{SCORE}/parts", json={"instruments": ["Soprano", " Alto ", "Soprano"], "pages": [3, 1, 1]})
    assert r.status_code == 200, r.text
    job = r.json()
    assert job["kind"] == "part_cut" and job["score_id"] == SCORE and job["created_by"] == "u1" and job["id"]
    assert job["payload"] == {"score_id": SCORE, "instruments": ["Soprano", "Alto"], "parts_key": "alto|soprano", "pages": [1, 3]}
    assert db.rows["jobs"][-1]["id"] == job["id"]
    r = client.post(f"/scores/{SCORE}/parts", json={"instruments": ["Piano"]})
    assert r.status_code == 200 and r.json()["payload"] == {"score_id": SCORE, "instruments": ["Piano"], "parts_key": "piano"}     # no pages: every page


def test_parts_route_refuses_bad_input_and_strangers(world):
    db, client = world
    as_user(OWNER)
    assert client.post(f"/scores/{SCORE}/parts", json={"instruments": [" ", ""]}).status_code == 400
    assert client.post(f"/scores/{SCORE}/parts", json={"pages": [1]}).status_code == 422
    assert client.post("/scores/22222222-2222-2222-2222-222222222222/parts", json={"instruments": ["Alto"]}).status_code == 404
    db.rows["sources"] = []
    assert client.post(f"/scores/{SCORE}/parts", json={"instruments": ["Alto"]}).status_code == 400
    db.rows["sources"] = [{"id": "src1", "score_id": SCORE, "kind": "images"}]
    as_user(OTHER)
    assert client.post(f"/scores/{SCORE}/parts", json={"instruments": ["Alto"]}).status_code == 403
    assert db.rows.get("jobs", []) == []


def parked_job(db: FakeDB, job_id: str = "job1", status: str = "done", question: str | None = "Which staves on page 2, system 1 are Soprano + Tenor's?") -> dict:
    row = {"id": job_id, "kind": "part_cut", "status": status, "score_id": SCORE, "created_by": "u1",
           "payload": {"score_id": SCORE, "instruments": ["Soprano", "Tenor"], "pages": [1, 2]},
           "result": {"question": question, "question_payload": {"kind": "choose_staves", "page": 2, "system": 1, "interpretation_id": "interp9"}} if question else {}}
    db.rows.setdefault("jobs", []).append(row)
    return row


def test_answer_route_queues_the_resume_job(world):
    db, client = world
    parked_job(db)
    as_user(OWNER)
    r = client.post("/jobs/job1/answer", json={"blocks": [[13], [15]]})
    assert r.status_code == 200, r.text
    job = r.json()
    assert job["kind"] == "part_cut" and job["score_id"] == SCORE and job["created_by"] == "u1" and job["id"] != "job1"
    assert job["payload"] == {"score_id": SCORE, "instruments": ["Soprano", "Tenor"], "pages": [1, 2], "interpretation_id": "interp9",
                              "answer": {"blocks": [[13], [15]]}, "resume_from": "job1", "parts_key": "soprano|tenor"}
    assert client.post("/jobs/job1/answer", json={"staves": "absent"}).status_code == 409        # answered once
    parked_job(db, job_id="job2")                                                                 # the staves and absent forms pass as they are
    r = client.post("/jobs/job2/answer", json={"staves": "absent"})
    assert r.status_code == 200 and r.json()["payload"]["answer"] == {"staves": "absent"} and r.json()["payload"]["resume_from"] == "job2"
    parked_job(db, job_id="job3")
    r = client.post("/jobs/job3/answer", json={"staves": [13, 14]})
    assert r.status_code == 200 and r.json()["payload"]["answer"] == {"staves": [13, 14]}


def test_answer_route_refuses_when_not_parked_or_not_owner(world):
    db, client = world
    as_user(OWNER)
    assert client.post("/jobs/nope/answer", json={"staves": [1]}).status_code == 404
    parked_job(db, question=None)
    assert client.post("/jobs/job1/answer", json={"staves": [1]}).status_code == 409           # done without a question
    db.rows["jobs"] = []
    parked_job(db, status="queued")
    assert client.post("/jobs/job1/answer", json={"staves": [1]}).status_code == 409           # still running
    db.rows["jobs"] = []
    parked_job(db)
    assert client.post("/jobs/job1/answer", json={}).status_code == 400
    assert client.post("/jobs/job1/answer", json={"foo": 1}).status_code == 400
    as_user(OTHER)
    assert client.post("/jobs/job1/answer", json={"staves": [1]}).status_code == 403
    assert len(db.rows["jobs"]) == 1


class RpcDB(FakeDB):
    def __init__(self):
        super().__init__()
        self.calls: list[tuple] = []

    def rpc(self, name, params):
        self.calls.append((name, params))
        return type("Q", (), {"execute": lambda _self: type("R", (), {"data": None})})()


def test_details_route_saves_canonical_fields_and_confirms_the_signature(world):
    db, client = world
    as_user(OWNER)
    r = client.patch(f"/scores/{SCORE}", json={"title": " Ave verum corpus ", "composer": "William Byrd", "key_sig": "g minor",
                                              "meter": "cut", "tempo_bpm": 72, "tempo_text": "Andante", "cover_clef": "treble"})
    assert r.status_code == 200, r.text
    row = db.rows["scores"][0]
    assert (row["title"], row["key_sig"], row["meter"], row["tempo_bpm"], row["tempo_text"], row["cover_clef"], row["signature_confirmed"]) == \
        ("Ave verum corpus", "G minor", "2/2", 72, "Andante", "treble", True)
    r = client.patch(f"/scores/{SCORE}", json={"composer": ""})                      # only what is sent changes; empty clears
    assert r.status_code == 200 and row["composer"] is None and row["title"] == "Ave verum corpus"
    assert client.patch(f"/scores/{SCORE}", json={"key_sig": "H major"}).status_code == 400
    assert client.patch(f"/scores/{SCORE}", json={"meter": "5/3"}).status_code == 400
    assert client.patch(f"/scores/{SCORE}", json={"title": "  "}).status_code == 400
    assert client.patch(f"/scores/{SCORE}", json={"tempo_bpm": 1000}).status_code == 400
    assert client.patch(f"/scores/{SCORE}", json={"cover_clef": "tenor"}).status_code == 422
    as_user(OTHER)
    assert client.patch(f"/scores/{SCORE}", json={"title": "Mine now"}).status_code == 403


def test_details_route_renumbers_from_the_first_bar_on_a_page(monkeypatch):
    db = RpcDB()
    db.rows["scores"] = [{"id": SCORE, "owner_user_id": "u1", "ensemble_id": None, "current_interpretation_id": "i1"}]
    db.rows["sources"] = [{"id": "src1", "score_id": SCORE, "kind": "pdf"}]
    db.rows["measure_placements"] = [{"interpretation_id": "i1", "page": 2, "system": 1, "box": {}, "measures": {"number": n}} for n in (9, 10, 11)]
    monkeypatch.setattr(scores_routes, "db", lambda: db)
    client = TestClient(app)
    as_user(OWNER)
    try:
        r = client.patch(f"/scores/{SCORE}", json={"first_bar": 1, "first_bar_page": 2})
        assert r.status_code == 200, r.text
        assert r.json()["shifted_by"] == -8 and db.calls == [("shift_measures", {"s": SCORE, "delta": -8})]
        assert (db.rows["scores"][0]["first_bar"], db.rows["scores"][0]["first_bar_page"]) == (1, 2)
        assert client.patch(f"/scores/{SCORE}", json={"first_bar": 1, "first_bar_page": 5}).status_code == 400   # no bars there
        db.rows["sources"].append({"id": "src2", "score_id": SCORE, "kind": "musicxml"})
        assert client.patch(f"/scores/{SCORE}", json={"first_bar": 1, "first_bar_page": 2}).status_code == 409   # a Digital copy's numbers stay
        assert len(db.calls) == 1
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------- one live job per kind per book (007, CK 2026-10-31)

def test_a_second_split_of_the_same_parts_is_refused_with_the_live_job(world):
    """Queued, running or parked on an unanswered question, a split of the same parts (in any order or case) is the
    book's live split: 409 names it and nothing is inserted. Other parts may split meanwhile; a finished, failed or
    answered one does not block."""
    db, client = world
    as_user(OWNER)
    first = client.post(f"/scores/{SCORE}/parts", json={"instruments": ["Pianoforte"]}).json()
    for status in ("queued", "running"):
        first_row = next(r for r in db.rows["jobs"] if r["id"] == first["id"])
        first_row["status"] = status
        r = client.post(f"/scores/{SCORE}/parts", json={"instruments": [" pianoforte "]})
        assert r.status_code == 409, r.text
        assert r.json()["detail"] == {"message": "This split is already under way.", "job_id": first["id"], "kind": "part_cut", "status": status}
    assert len(db.rows["jobs"]) == 1
    two = client.post(f"/scores/{SCORE}/parts", json={"instruments": ["Viola", "Flauto"]})
    assert two.status_code == 200                                                                 # other parts are another split
    assert client.post(f"/scores/{SCORE}/parts", json={"instruments": ["flauto", "VIOLA"]}).status_code == 409   # same set, other order
    first_row = next(r for r in db.rows["jobs"] if r["id"] == first["id"])
    first_row.update(status="done", result={"question": "Which staves are the Pianoforte's on page 2, line 3?"})
    r = client.post(f"/scores/{SCORE}/parts", json={"instruments": ["Pianoforte"]})
    assert r.status_code == 409 and r.json()["detail"]["status"] == "needs_review"                # parked: still live
    ans = client.post(f"/jobs/{first['id']}/answer", json={"staves": [16, 17]})
    assert ans.status_code == 200
    assert client.post(f"/scores/{SCORE}/parts", json={"instruments": ["Pianoforte"]}).json()["detail"]["job_id"] == ans.json()["id"]
    next(r for r in db.rows["jobs"] if r["id"] == ans.json()["id"]).update(status="done", result={"systems_cut": 7})
    assert client.post(f"/scores/{SCORE}/parts", json={"instruments": ["Pianoforte"]}).status_code == 200   # finished: a new split may start


def test_answering_a_split_marks_its_interpretation_running(world):
    """The book stops showing the split's question the moment it is answered: the parked run's interpretation goes from
    needs_review to running in the same request (the resumed run used to rewrite it only when it ended)."""
    db, client = world
    parked_job(db)
    db.rows["interpretations"] = [{"id": "interp9", "score_id": SCORE, "status": "needs_review", "engine": "part-cut-agent"}]
    as_user(OWNER)
    assert client.post("/jobs/job1/answer", json={"staves": [13, 15]}).status_code == 200
    assert db.rows["interpretations"][0]["status"] == "running"


class RacingDB(FakeDB):
    """A second request that passed the check before the first one's row existed: the index refuses its insert."""
    def __init__(self, live: dict):
        super().__init__()
        self.live = live

    def table(self, name):
        q = super().table(name)
        if name == "jobs":
            ex = q.execute

            def execute():
                if q.op == "insert":
                    self.rows.setdefault("jobs", []).append(self.live)
                    raise Exception({"code": "23505", "message": 'duplicate key value violates unique constraint "jobs_one_live"'})
                return ex()
            q.execute = execute
        return q


def test_the_index_refusal_comes_back_as_the_same_409(monkeypatch):
    live = {"id": "live1", "kind": "part_cut", "status": "running", "score_id": SCORE, "created_at": "2026-10-31T00:00:00Z",
            "payload": {"score_id": SCORE, "instruments": ["Piano"], "parts_key": "piano"}, "result": {}}
    db = RacingDB(live)
    db.rows["scores"] = [{"id": SCORE, "owner_user_id": "u1", "ensemble_id": None}]
    db.rows["sources"] = [{"id": "src1", "score_id": SCORE, "kind": "images"}]
    for m in (scores_routes, jobs_routes):
        monkeypatch.setattr(m, "db", lambda: db)
    as_user(OWNER)
    try:
        r = TestClient(app).post(f"/scores/{SCORE}/parts", json={"instruments": ["Piano"]})
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 409 and r.json()["detail"]["job_id"] == "live1" and r.json()["detail"]["status"] == "running"
    assert live_jobs.parts_key(["Violino  I", "piano", "Piano"]) == "piano|violino i"
