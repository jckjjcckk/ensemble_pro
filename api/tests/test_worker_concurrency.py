"""The worker loop runs up to WORKER_CONCURRENCY jobs at once (speed pass 2026-10-30): claims go on while a slot is
free, a finished job frees its slot without waiting for the poll, and stop lets the jobs in hand finish."""
from __future__ import annotations

import asyncio

import pytest

from app import worker


class FakeRPC:
    def __init__(self, rows):
        self.rows = rows

    def execute(self):
        return type("R", (), {"data": self.rows.pop(0) if self.rows else None})


class FakeDB:
    def __init__(self, n: int):
        self.queue = [{"id": f"j{i}", "kind": "sleepy", "payload": {}, "attempts": 1, "max_attempts": 1} for i in range(n)]
        self.claims = 0

    def rpc(self, name, args):
        assert name == "claim_job"
        self.claims += 1
        return FakeRPC(self.queue)


@pytest.fixture
def world(monkeypatch):
    state = {"now": 0, "max": 0, "started": [], "finished": []}

    async def fake_run_one(row):
        state["now"] += 1
        state["max"] = max(state["max"], state["now"])
        state["started"].append(row["id"])
        await asyncio.sleep(0.05)
        state["now"] -= 1
        state["finished"].append(row["id"])

    monkeypatch.setattr(worker, "run_one", fake_run_one)
    monkeypatch.setattr(worker, "load_handlers", lambda: None)
    monkeypatch.setattr(worker, "requeue_stale", lambda: None)
    monkeypatch.setattr(worker, "POLL_S", 0.01)
    return state


async def run_until_idle(db, state, n_jobs, **kw):
    stop = asyncio.Event()
    task = asyncio.create_task(worker.loop(stop, **kw))
    for _ in range(400):
        await asyncio.sleep(0.01)
        if len(state["finished"]) == n_jobs:
            break
    stop.set()
    await asyncio.wait_for(task, 2)


async def test_two_jobs_run_at_once_by_default(world, monkeypatch):
    db = FakeDB(3)
    monkeypatch.setattr(worker, "db", lambda: db)
    assert worker.settings.worker_concurrency == 2
    await run_until_idle(db, world, 3)
    assert world["max"] == 2 and sorted(world["finished"]) == ["j0", "j1", "j2"]
    assert world["started"][:2] == ["j0", "j1"]                    # the second claim did not wait for the first job


async def test_concurrency_one_is_the_old_serial_loop(world, monkeypatch):
    db = FakeDB(3)
    monkeypatch.setattr(worker, "db", lambda: db)
    await run_until_idle(db, world, 3, concurrency=1)
    assert world["max"] == 1 and world["finished"] == ["j0", "j1", "j2"]


async def test_stop_lets_the_jobs_in_hand_finish(world, monkeypatch):
    db = FakeDB(2)
    monkeypatch.setattr(worker, "db", lambda: db)
    stop = asyncio.Event()
    task = asyncio.create_task(worker.loop(stop))
    await asyncio.sleep(0.02)
    stop.set()
    await asyncio.wait_for(task, 2)
    assert sorted(world["finished"]) == ["j0", "j1"]
