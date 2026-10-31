"""The worker's wake (app/wake.py): a queued row inserted over Realtime is claimed at once, not at the next poll; the
poll stays the fallback; a busy worker does not spin on a wake it cannot use; the listener reconnects on its own.
Offline: a fake database and a fake socket, nothing reaches Supabase."""
from __future__ import annotations

import asyncio
import json
import time

import pytest

from app import wake as wake_mod
from app import worker
from app.wake import Wake, is_queued_insert, socket_url


class FakeDB:
    def __init__(self):
        self.queue: list[dict] = []
        self.claims = 0

    def rpc(self, name, args):
        assert name == "claim_job"
        self.claims += 1
        row = self.queue.pop(0) if self.queue else None
        return type("Q", (), {"execute": lambda _s: type("R", (), {"data": row})})()


def job(i: int) -> dict:
    return {"id": f"j{i}", "kind": "sleepy", "payload": {}, "attempts": 1, "max_attempts": 1}


@pytest.fixture
def world(monkeypatch):
    state = {"started": {}, "hold": asyncio.Event()}

    async def fake_run_one(row):
        state["started"][row["id"]] = time.monotonic()
        await state["hold"].wait()

    db = FakeDB()
    monkeypatch.setattr(worker, "run_one", fake_run_one)
    monkeypatch.setattr(worker, "load_handlers", lambda: None)
    monkeypatch.setattr(worker, "requeue_stale", lambda: None)
    monkeypatch.setattr(worker, "db", lambda: db)
    monkeypatch.setattr(worker, "POLL_S", 5.0)          # long enough that only the wake can explain a quick claim
    state["db"] = db
    return state


async def test_a_wake_claims_at_once_instead_of_at_the_next_poll(world):
    stop, wake = asyncio.Event(), asyncio.Event()
    task = asyncio.create_task(worker.loop(stop, wake=wake))
    await asyncio.sleep(0.05)                          # the first claim found nothing; the loop now waits 5 s
    world["db"].queue.append(job(0))
    t0 = time.monotonic()
    wake.set()
    for _ in range(100):
        await asyncio.sleep(0.01)
        if "j0" in world["started"]:
            break
    assert world["started"]["j0"] - t0 < 0.2
    world["hold"].set()
    stop.set()
    await asyncio.wait_for(task, 2)


async def test_without_a_wake_the_poll_still_claims(world, monkeypatch):
    monkeypatch.setattr(worker, "POLL_S", 0.05)
    stop = asyncio.Event()
    task = asyncio.create_task(worker.loop(stop, wake=asyncio.Event()))
    await asyncio.sleep(0.02)
    world["db"].queue.append(job(0))
    for _ in range(100):
        await asyncio.sleep(0.01)
        if "j0" in world["started"]:
            break
    assert "j0" in world["started"]
    world["hold"].set()
    stop.set()
    await asyncio.wait_for(task, 2)


async def test_a_busy_worker_keeps_the_wake_for_its_next_free_slot(world):
    stop, wake = asyncio.Event(), asyncio.Event()
    world["db"].queue += [job(0), job(1)]
    task = asyncio.create_task(worker.loop(stop, concurrency=2, wake=wake))
    await asyncio.sleep(0.05)
    assert set(world["started"]) == {"j0", "j1"}
    claims = world["db"].claims
    world["db"].queue.append(job(2))
    wake.set()
    await asyncio.sleep(0.2)
    assert world["db"].claims == claims and "j2" not in world["started"]     # no spin, no third job: the slots are full
    world["hold"].set()                                                     # both finish; the kept wake claims j2 at once
    for _ in range(100):
        await asyncio.sleep(0.01)
        if "j2" in world["started"]:
            break
    assert "j2" in world["started"]
    stop.set()
    await asyncio.wait_for(task, 2)


# ---------------------------------------------------------------- the listener

class FakeSocket:
    def __init__(self, script: list):
        self.inbox: asyncio.Queue = asyncio.Queue()
        for m in script:
            self.inbox.put_nowait(m)
        self.sent: list[dict] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def send(self, text):
        self.sent.append(json.loads(text))

    async def recv(self):
        m = await self.inbox.get()
        if isinstance(m, Exception):
            raise m
        return json.dumps(m)


JOINED = [
    {"topic": wake_mod.TOPIC, "event": "phx_reply", "ref": "1", "payload": {"status": "ok", "response": {"postgres_changes": [{"id": 1}]}}},
    {"topic": wake_mod.TOPIC, "event": "system", "payload": {"extension": "postgres_changes", "status": "ok", "message": "Subscribed to PostgreSQL"}},
]


def change(status: str) -> dict:
    return {"topic": wake_mod.TOPIC, "event": "postgres_changes",
            "payload": {"data": {"type": "INSERT", "table": "jobs", "record": {"id": "x", "status": status}}}}


def test_the_socket_url_and_the_filter():
    assert socket_url("https://abc.supabase.co/", "k") == "wss://abc.supabase.co/realtime/v1/websocket?apikey=k&vsn=1.0.0"
    assert socket_url("http://127.0.0.1:54321", "k").startswith("ws://127.0.0.1:54321/realtime/v1/websocket")
    assert is_queued_insert(change("queued")) and not is_queued_insert(change("running"))
    assert not is_queued_insert({"event": "presence_state", "payload": {}})


async def test_the_listener_wakes_on_a_queued_insert_only_and_reconnects(monkeypatch):
    monkeypatch.setattr(wake_mod, "BACKOFF_START_S", 0.01)
    monkeypatch.setattr(wake_mod, "BACKOFF_MAX_S", 0.01)
    first = FakeSocket([*JOINED, change("running"), change("queued"), ConnectionError("dropped")])
    second = FakeSocket([*JOINED])
    sockets = [first, second]
    w = Wake("https://abc.supabase.co", "k", connect=lambda url: sockets.pop(0) if sockets else FakeSocket([]))
    stop = asyncio.Event()
    task = asyncio.create_task(w.run(stop))
    for _ in range(200):
        await asyncio.sleep(0.01)
        if w.connects == 2 and w.subscribed_at:
            break
    assert w.events == 1                               # the running row woke no one
    assert w.connects == 2 and w.event.is_set()        # back after the drop, and the rejoin wakes the loop once
    join = first.sent[0]
    assert join["event"] == "phx_join" and join["payload"]["config"]["postgres_changes"] == [{"event": "INSERT", "schema": "public", "table": "jobs"}]
    stop.set()
    await asyncio.wait_for(task, 2)


async def test_an_unanswered_heartbeat_drops_the_socket(monkeypatch):
    monkeypatch.setattr(wake_mod, "HEARTBEAT_S", 0.02)
    monkeypatch.setattr(wake_mod, "REPLY_S", 0.05)
    sock = FakeSocket([*JOINED])
    w = Wake("https://abc.supabase.co", "k", connect=lambda url: sock)
    with pytest.raises(ConnectionError, match="heartbeat"):
        await asyncio.wait_for(w._session(asyncio.Event()), 2)
    assert any(m["event"] == "heartbeat" for m in sock.sent)


async def test_a_refused_join_is_an_error_not_a_silent_socket():
    sock = FakeSocket([{"topic": wake_mod.TOPIC, "event": "phx_reply", "ref": "1", "payload": {"status": "error", "response": {"reason": "nope"}}}])
    w = Wake("https://abc.supabase.co", "k", connect=lambda url: sock)
    with pytest.raises(ConnectionError, match="join refused"):
        await asyncio.wait_for(w._session(asyncio.Event()), 2)



def test_the_api_starts_the_listener_beside_the_loop_and_not_with_worker_0(monkeypatch):
    from fastapi.testclient import TestClient

    from app import main, settings as settings_mod
    seen: dict = {}

    async def fake_loop(stop, concurrency=None, wake=None):
        seen["wake"] = wake
        await stop.wait()

    async def fake_run(self, stop):
        seen["listener"] = self
        await stop.wait()

    monkeypatch.setattr(worker, "loop", fake_loop)
    monkeypatch.setattr(Wake, "run", fake_run)
    monkeypatch.setattr(settings_mod.settings, "supabase_url", "https://abc.supabase.co")
    monkeypatch.setattr(settings_mod.settings, "supabase_secret_key", "k")
    monkeypatch.setenv("WORKER", "1")
    with TestClient(main.app):
        pass
    assert isinstance(seen["wake"], asyncio.Event) and seen["listener"].event is seen["wake"]

    seen.clear()
    monkeypatch.setattr(settings_mod.settings, "worker_wake", False)
    with TestClient(main.app):
        pass
    assert seen == {"wake": None}

    seen.clear()
    monkeypatch.setenv("WORKER", "0")
    with TestClient(main.app):
        pass
    assert seen == {}
