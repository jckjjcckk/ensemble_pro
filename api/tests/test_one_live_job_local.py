"""The `jobs_one_live` index (migration 20261031120000) against the LOCAL Supabase stack: one queued or running
`part_cut` per book and set of parts, one `omr_convert` per book (its book in `payload.score_id`), one `process_pages`.

Keys from `supabase status`, never `api/.env`, so this cannot touch the hosted project. Skipped when the stack is down
or the migration is not applied. Rows are inserted with the service role on a throwaway book and deleted after."""
from __future__ import annotations

import pytest

from tests.test_groups_local import STATUS

pytestmark = pytest.mark.skipif(STATUS is None, reason="local Supabase stack is not running (`supabase start`)")


@pytest.fixture
def svc():
    import httpx
    url, secret = STATUS["API_URL"], STATUS["SECRET_KEY"]
    c = httpx.Client(base_url=url, headers={"apikey": secret, "Authorization": f"Bearer {secret}", "Prefer": "return=representation"}, timeout=20)
    users = c.get("/auth/v1/admin/users", params={"per_page": 1}).json().get("users") or []
    if not users:
        pytest.skip("the local stack has no account to own a book")
    book = c.post("/rest/v1/scores", json={"title": "pytest one live job", "status": "ready", "created_by": users[0]["id"], "owner_user_id": users[0]["id"]})
    assert book.status_code == 201, book.text
    sid = book.json()[0]["id"]
    yield c, sid
    c.delete("/rest/v1/jobs", params={"payload->>score_id": f"eq.{sid}"})
    c.delete("/rest/v1/scores", params={"id": f"eq.{sid}"})
    c.close()


def test_the_index_holds_one_live_job_per_kind_per_book(svc):
    c, sid = svc
    def job(kind: str, status: str = "queued", key: str | None = None, on_row: bool = True):
        payload = {"score_id": sid, **({"parts_key": key} if key is not None else {})}
        return c.post("/rest/v1/jobs", json={"kind": kind, "status": status, "score_id": sid if on_row else None, "payload": payload})
    first = job("part_cut", key="pianoforte")
    assert first.status_code == 201, first.text
    if job("part_cut", key="pianoforte").status_code == 201:
        pytest.skip("migration 20261031120000 is not applied locally")
    again = job("part_cut", key="pianoforte")
    assert again.status_code == 409 and again.json()["code"] == "23505" and "jobs_one_live" in again.json()["message"]
    assert job("part_cut", key="flauto|viola").status_code == 201          # other parts: another split
    assert job("part_cut", status="done", key="pianoforte").status_code == 201   # finished rows are not live
    c.patch("/rest/v1/jobs", params={"id": f"eq.{first.json()[0]['id']}"}, json={"status": "running"})
    assert job("part_cut", key="pianoforte").status_code == 409            # running is live too
    assert job("omr_convert", on_row=False).status_code == 201
    assert job("omr_convert", on_row=False).status_code == 409             # the book only in the payload
    assert job("process_pages").status_code == 201
    assert job("process_pages").status_code == 409
    assert job("import_pdf").status_code == 201 and job("import_pdf").status_code == 201   # other kinds are not guarded
