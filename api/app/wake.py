"""The worker's wake: a newly queued job is claimed at once instead of at the next 2 s poll.

One Supabase Realtime channel (postgres_changes, INSERT on `public.jobs`, already in the `supabase_realtime`
publication) as the service role, so RLS lets every row through. Each INSERT of a `queued` row sets an asyncio.Event
that `worker.loop` waits on beside its poll timeout. The event carries no job: the loop still claims through
`claim_job()` (SKIP LOCKED), so two workers woken by one row never both get it, and a missed event costs only the
poll. A job inserted as `running` (a part split, a local run) does not wake anyone.

The connection is supervised here and never in the loop's way: a refused join, a dropped socket or a heartbeat
without a reply closes it and connects again with backoff (1 s doubling to 30 s), while the 2 s poll goes on. A
plain Phoenix v1 JSON client over `websockets` rather than the `realtime` package, whose reconnect gives up after five
tries inside a task nobody awaits.

Never logs the URL: the key rides in its query string, as supabase-js sends it.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Awaitable, Callable

log = logging.getLogger("folio.wake")

TOPIC = "realtime:folio-worker-wake"
HEARTBEAT_S = 25.0
REPLY_S = 10.0
BACKOFF_START_S = 1.0
BACKOFF_MAX_S = 30.0

Connect = Callable[[str], Awaitable[Any]]


def socket_url(supabase_url: str, key: str) -> str:
    base = supabase_url.rstrip("/")
    base = "wss://" + base[len("https://"):] if base.startswith("https://") else "ws://" + base.removeprefix("http://")
    return f"{base}/realtime/v1/websocket?apikey={key}&vsn=1.0.0"


def join_message(key: str) -> dict:
    return {
        "topic": TOPIC, "event": "phx_join", "ref": "1", "join_ref": "1",
        "payload": {
            "config": {"broadcast": {"ack": False, "self": False}, "presence": {"key": "", "enabled": False}, "private": False,
                       "postgres_changes": [{"event": "INSERT", "schema": "public", "table": "jobs"}]},
            "access_token": key,
        },
    }


def is_queued_insert(msg: dict) -> bool:
    if msg.get("event") != "postgres_changes":
        return False
    data = (msg.get("payload") or {}).get("data") or {}
    record = data.get("record") or {}
    return data.get("type", "INSERT") == "INSERT" and record.get("status", "queued") == "queued"


class Wake:
    """Holds the Event and the counters the benchmark reads (`events`, `connects`, `subscribed_at`)."""

    def __init__(self, supabase_url: str, key: str, connect: Connect | None = None):
        self.url = socket_url(supabase_url, key)
        self.key = key
        self.event = asyncio.Event()
        self.events = 0
        self.connects = 0
        self.subscribed_at: float | None = None
        self._connect = connect

    async def run(self, stop: asyncio.Event) -> None:
        backoff = BACKOFF_START_S
        while not stop.is_set():
            try:
                await self._session(stop)
                backoff = BACKOFF_START_S
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                if self.subscribed_at is not None:
                    backoff = BACKOFF_START_S        # it was listening: a fresh drop, not a run of refusals
                why = (type(e).__name__ + (f": {e}" if str(e) else "")).replace(self.key, "***") if self.key else type(e).__name__
                log.warning("wake: %s; the 2 s poll carries on, reconnecting in %.0f s", why[:300], backoff)
            self.subscribed_at = None
            if stop.is_set():
                break
            try:
                await asyncio.wait_for(stop.wait(), backoff)
            except asyncio.TimeoutError:
                pass
            backoff = min(backoff * 2, BACKOFF_MAX_S)

    async def _session(self, stop: asyncio.Event) -> None:
        connect = self._connect
        if connect is None:
            from websockets.asyncio.client import connect as ws_connect
            connect = lambda url: ws_connect(url, open_timeout=REPLY_S)  # noqa: E731
        async with connect(self.url) as ws:
            self.connects += 1
            await ws.send(json.dumps(join_message(self.key)))
            ref = 1
            pending: dict[str, float] = {}   # heartbeat ref -> when sent
            next_beat = time.monotonic() + HEARTBEAT_S
            stopping = asyncio.ensure_future(stop.wait())
            try:
                while not stop.is_set():
                    now = time.monotonic()
                    if any(now - t > REPLY_S for t in pending.values()):
                        raise ConnectionError("heartbeat unanswered")
                    if now >= next_beat:
                        ref += 1
                        pending[str(ref)] = now
                        await ws.send(json.dumps({"topic": "phoenix", "event": "heartbeat", "payload": {}, "ref": str(ref)}))
                        next_beat = now + HEARTBEAT_S
                    recv = asyncio.ensure_future(ws.recv())
                    done, _ = await asyncio.wait({recv, stopping}, timeout=min(next_beat - time.monotonic(), REPLY_S) + 0.05,
                                                 return_when=asyncio.FIRST_COMPLETED)
                    if recv not in done:
                        recv.cancel()
                        continue
                    self._handle(json.loads(recv.result()), pending)
            finally:
                stopping.cancel()

    def _handle(self, msg: dict, pending: dict[str, float]) -> None:
        ev, payload = msg.get("event"), msg.get("payload") or {}
        if msg.get("topic") == "phoenix" and ev == "phx_reply":
            pending.pop(str(msg.get("ref")), None)
            return
        if ev == "phx_reply" and msg.get("ref") == "1" and payload.get("status") != "ok":
            raise ConnectionError(f"join refused: {str(payload.get('response'))[:200]}")
        if ev == "system" and payload.get("extension") == "postgres_changes":
            if payload.get("status") != "ok":
                raise ConnectionError(f"postgres_changes: {str(payload.get('message'))[:200]}")
            self.subscribed_at = time.time()
            log.info("wake: listening for new jobs")
            self.event.set()          # anything inserted while we were away is claimed now, not at the next poll
            return
        if ev in ("phx_error", "phx_close"):
            raise ConnectionError(ev)
        if is_queued_insert(msg):
            self.events += 1
            self.event.set()
