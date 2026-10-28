"""The part-cut and answer routes against the fake database: auth through dependency overrides, no network."""
from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.auth import User
from app.main import app
from app.routes import jobs as jobs_routes, scores as scores_routes
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


def test_parts_route_queues_a_part_cut_job(world):
    db, client = world
    as_user(OWNER)
    r = client.post(f"/scores/{SCORE}/parts", json={"instruments": ["Soprano", " Alto ", "Soprano"], "pages": [3, 1, 1]})
    assert r.status_code == 200, r.text
    job = r.json()
    assert job["kind"] == "part_cut" and job["score_id"] == SCORE and job["created_by"] == "u1" and job["id"]
    assert job["payload"] == {"score_id": SCORE, "instruments": ["Soprano", "Alto"], "pages": [1, 3]}
    assert db.rows["jobs"][-1]["id"] == job["id"]
    r = client.post(f"/scores/{SCORE}/parts", json={"instruments": ["Piano"]})
    assert r.status_code == 200 and r.json()["payload"] == {"score_id": SCORE, "instruments": ["Piano"]}     # no pages: every page


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
                              "answer": {"blocks": [[13], [15]]}, "resume_from": "job1"}
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
