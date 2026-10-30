"""Q1: Muse Voice Transcribe realtime (wss://api.meta.ai/v1/asr/realtime), measured against the batch endpoint.

    uv run python -m experiments.voice_stream.realtime probe v02
    uv run python -m experiments.voice_stream.realtime clips            # every eval clip + negatives, ENDPOINTING
    uv run python -m experiments.voice_stream.realtime modes            # 5 lines: PTT / ENDPOINTING / DIARIZATION realtime + batch
    uv run python -m experiments.voice_stream.realtime long             # the long stream for Q4, ENDPOINTING

Audio is sent as 80 ms binary frames of 16 kHz PCM (PCM_16KHZ) at real-time pace, with 0.3 s of silence before
(a live microphone is already open) and silence after (Meta: "send PCM silence during silence on live sources").
Times are wall clock from the first audio frame; the clip's speech end is placed on that clock by its sample index.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time

import httpx
import numpy as np
import websockets

from app.settings import settings

from ..voice.textnorm import wer
from .common import (KEYWORDS, LOCAL, RESULTS, SR, WAVS, asr_usd, base_id, guard, labels, log_spend, read_wav,
                     speech_span, wav_bytes)

WS_URL = "wss://api.meta.ai/v1/asr/realtime"
ASR_URL = "https://api.meta.ai/v1/asr/transcribe"
MODEL = "muse-voice-transcribe-1.0"
FRAME = SR * 80 // 1000          # samples per 80 ms frame
FIVE = ["v02", "v08", "v11", "v15", "v21"]


async def stream(x: np.ndarray, mode: str, *, pre: float = 0.3, post: float = 2.5, end_stream: bool = True,
                 keywords: list[str] | None = KEYWORDS, tag: str = "", uid: str = "") -> dict:
    """Stream one signal; return every server event with its wall time (s from the first frame)."""
    sig = np.concatenate([np.zeros(int(pre * SR), np.int16), x, np.zeros(int(post * SR), np.int16)])
    guard(asr_usd(len(sig) / SR) + 0.001)
    hs = {"authorization": {"accessToken": f"Bearer {settings.meta_api_key}"}, "audioEncoding": "PCM_16KHZ",
          "model": MODEL, "mode": mode, "partialMode": "CUMULATIVE", "emitAudioProgress": False}
    if keywords:
        hs["keywords"] = keywords
    events: list[dict] = []
    t_conn = time.monotonic()
    async with websockets.connect(WS_URL, max_size=2**22) as ws:
        await ws.send(json.dumps(hs))
        ack = json.loads(await ws.recv())
        t_ack = time.monotonic() - t_conn
        t0 = time.monotonic()

        async def sender():
            for k, i in enumerate(range(0, len(sig), FRAME)):
                due = t0 + k * FRAME / SR
                d = due - time.monotonic()
                if d > 0:
                    await asyncio.sleep(d)
                await ws.send(sig[i:i + FRAME].tobytes())
            if end_stream:
                events.append({"type": "_endStream_sent", "t": time.monotonic() - t0})
                await ws.send(json.dumps({"type": "endStream"}))

        async def receiver():
            try:
                async for m in ws:
                    if isinstance(m, bytes):
                        continue
                    ev = json.loads(m)
                    ev["t"] = time.monotonic() - t0
                    events.append(ev)
            except websockets.ConnectionClosed:
                pass

        rx = asyncio.create_task(receiver())
        await sender()
        try:
            await asyncio.wait_for(rx, timeout=30)
        except asyncio.TimeoutError:
            events.append({"type": "_timeout", "t": time.monotonic() - t0})
        close = ws.close_code
    secs = len(sig) / SR
    usd = asr_usd(secs)
    log_spend(kind=f"asr_rt:{mode}{tag}", id=uid, usd=round(usd, 6), secs=round(secs, 2))
    return {"events": events, "ack": ack, "handshake_s": round(t_ack, 3), "close": close, "pre": pre,
            "audio_s": secs, "usd": usd}


def summarise(res: dict, x: np.ndarray, mode: str) -> dict:
    """Latency figures for one clip: the clip's own speech onset/end on the stream clock."""
    on, end = speech_span(x)
    on, end = on + res["pre"], end + res["pre"]
    ev = res["events"]
    partials = [e for e in ev if e.get("type") == "transcript" and not e.get("final")]
    finals = [e for e in ev if e.get("type") == "transcript" and e.get("final")]
    completes = [e for e in ev if e.get("type") == "speechComplete"]
    ends = [e for e in ev if e.get("type") == "speechEnd"]
    starts = [e for e in ev if e.get("type") == "speechStart"]
    out = {"speech_on": round(on, 2), "speech_end": round(end, 2),
           "first_partial_after_onset": round(partials[0]["t"] - on, 2) if partials else None,
           "n_partials": len(partials), "turns": len(completes) or len(finals)}
    if mode == "PUSH_TO_TALK":
        sent = next((e["t"] for e in ev if e["type"] == "_endStream_sent"), None)
        out["final_after_speech_end"] = round(finals[-1]["t"] - end, 2) if finals else None
        out["final_after_endStream"] = round(finals[-1]["t"] - sent, 2) if finals and sent else None
        out["transcript"] = (finals[-1]["transcript"] if finals else "").strip()
    else:
        # On a real-time-paced stream the wall clock and the audio clock agree (t0 = sample 0), so a turn's lag is
        # its event's wall time minus the turn end the server reports (speechEnd.audioProcessedMs).
        out["speechEnd_after_speech_end"] = round(ends[-1]["t"] - end, 2) if ends else None
        out["complete_after_speech_end"] = round(completes[-1]["t"] - end, 2) if completes else None
        out["complete_lag_per_turn"] = [round(c["t"] - c["audioProcessedMs"] / 1000, 2) for c in completes]
        out["first_partial_after_speechStart"] = None
        if starts and partials:
            out["first_partial_after_speechStart"] = round(partials[0]["t"] - starts[0]["audioProcessedMs"] / 1000, 2)
        out["transcript"] = " ".join(e["transcript"].strip() for e in completes).strip()
        if ends:
            pre_end = [e for e in partials if e["t"] <= ends[-1]["t"]]
            out["partial_at_speechEnd"] = pre_end[-1]["transcript"].strip() if pre_end else ""
        out["turn_spans"] = [[round(s["audioProcessedMs"] / 1000 - res["pre"], 2) for s in (a, b)]
                             for a, b in zip(starts, ends)]
        out["turn_texts"] = [c["transcript"].strip() for c in completes]
    return out


async def batch(x: np.ndarray, mode: str, uid: str, accept: str = "application/json") -> dict:
    guard(asr_usd(len(x) / SR) + 0.001)
    req = {"model": MODEL, "audioEncoding": "WAV", "mode": mode, "keywords": KEYWORDS}
    t0 = time.monotonic()
    async with httpx.AsyncClient() as c:
        r = await c.post(ASR_URL, headers={"Authorization": f"Bearer {settings.meta_api_key}", "Accept": accept},
                         files={"request": (None, json.dumps(req), "application/json"),
                                "audio": ("take.wav", wav_bytes(x), "audio/wav")}, timeout=120)
    took = time.monotonic() - t0
    r.raise_for_status()
    usd = asr_usd(len(x) / SR)
    log_spend(kind=f"asr_batch:{mode}", id=uid, usd=round(usd, 6), secs=round(took, 2))
    body = r.json() if accept == "application/json" else {"raw": r.text}
    return {"seconds": took, **body}


def clip(uid: str) -> np.ndarray:
    p = WAVS / f"{uid}.wav"
    return read_wav(p if p.exists() else LOCAL / f"{uid}.wav")


async def cmd_probe(uid: str, mode: str) -> None:
    x = clip(uid)
    res = await stream(x, mode, uid=uid)
    for e in res["events"]:
        print(json.dumps(e, ensure_ascii=False)[:200])
    print(res["ack"], res["handshake_s"], res["close"])
    print(json.dumps(summarise(res, x, mode), ensure_ascii=False, indent=1))


def all_clip_ids() -> list[str]:
    ids = sorted(p.stem for p in WAVS.glob("v*.wav"))
    ids += sorted(p.stem for p in LOCAL.glob("n*.wav"))
    return ids


async def cmd_clips(mode: str, ids: list[str] | None) -> None:
    ids = ids or all_clip_ids()
    sem = asyncio.Semaphore(6)
    lab = labels()

    async def one(uid):
        async with sem:
            x = clip(uid)
            res = await stream(x, mode, uid=uid)
            s = summarise(res, x, mode)
            if uid.startswith("v"):
                s["wer"] = list(wer(lab[base_id(uid)]["text"], s["transcript"]))
            print(uid, json.dumps({k: v for k, v in s.items() if k != "turn_spans"}, ensure_ascii=False)[:300])
            return uid, {**s, "events": res["events"], "handshake_s": res["handshake_s"], "close": res["close"]}

    rows = dict(await asyncio.gather(*(one(u) for u in ids)))
    dst = RESULTS / f"realtime_{mode.lower()}.json"
    old = json.loads(dst.read_text()) if dst.exists() else {}
    old.update(rows)
    dst.write_text(json.dumps(old, ensure_ascii=False, indent=1))


async def cmd_modes() -> None:
    """The five lines: batch DIARIZATION (today's pipeline) and the three realtime modes, timed."""
    lab = labels()
    out = {}
    for uid in FIVE:
        x = clip(uid)
        row = {}
        for rep in range(2):
            b = await batch(x, "DIARIZATION", uid)
            row.setdefault("batch_DIARIZATION", []).append({"seconds": round(b["seconds"], 2),
                                                             "transcript": b["transcript"].strip()})
        b = await batch(x, "PUSH_TO_TALK", uid)
        row["batch_PUSH_TO_TALK"] = [{"seconds": round(b["seconds"], 2), "transcript": b["transcript"].strip()}]
        for mode in ("PUSH_TO_TALK", "ENDPOINTING", "DIARIZATION"):
            res = await stream(x, mode, uid=uid, post=2.5 if mode != "PUSH_TO_TALK" else 0.3)
            row[f"rt_{mode}"] = summarise(res, x, mode)
        for k, v in row.items():
            tr = v[0]["transcript"] if isinstance(v, list) else v["transcript"]
            e, n = wer(lab[base_id(uid)]["text"], tr)
            (v[0] if isinstance(v, list) else v)["wer"] = [e, n]
        out[uid] = row
        print(uid, json.dumps(row, ensure_ascii=False)[:800])
    (RESULTS / "modes_five.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))


async def cmd_long() -> None:
    x = read_wav(LOCAL / "long.wav")
    res = await stream(x, "ENDPOINTING", pre=0.0, post=2.5, uid="long")
    (RESULTS / "realtime_long.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))
    print(sum(1 for e in res["events"] if e.get("type") == "speechComplete"), "turns")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd")
    ap.add_argument("ids", nargs="*")
    ap.add_argument("--mode", default="ENDPOINTING")
    a = ap.parse_args()
    if a.cmd == "probe":
        asyncio.run(cmd_probe(a.ids[0], a.mode))
    elif a.cmd == "clips":
        asyncio.run(cmd_clips(a.mode, a.ids))
    elif a.cmd == "modes":
        asyncio.run(cmd_modes())
    elif a.cmd == "long":
        asyncio.run(cmd_long())


if __name__ == "__main__":
    main()
