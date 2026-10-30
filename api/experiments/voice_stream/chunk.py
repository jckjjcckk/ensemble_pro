"""Q4: client-side chunking on long.wav (eval lines, negatives, piano, known silences). No paid calls, except the
Meta ENDPOINTING run of the same file, which `realtime long` makes and this script only reads.

    uv run --with onnxruntime python -m experiments.voice_stream.chunk

Silero VAD v5 (onnx, from the silero-vad 5.1.2 wheel on PyPI; 512-sample frames at 16 kHz plus 64 samples of
context) against an energy gate (32 ms RMS, adaptive floor), both with the same hysteresis segmenter, at several
silence cut-offs. Meta's own turns are scored the same way.
"""

from __future__ import annotations

import json
import time

import numpy as np

from .common import LOCAL, RESULTS, SR, read_wav

FR = 512                           # 32 ms
FMS = FR / SR * 1000


def silero_probs(x: np.ndarray) -> tuple[np.ndarray, float]:
    import onnxruntime as ort
    opts = ort.SessionOptions()
    opts.intra_op_num_threads = 1
    s = ort.InferenceSession(str(LOCAL / "silero_vad.onnx"), opts, providers=["CPUExecutionProvider"])
    state = np.zeros((2, 1, 128), np.float32)
    ctx = np.zeros(64, np.float32)
    f = x.astype(np.float32) / 32768
    out = []
    t0 = time.perf_counter()
    for i in range(0, len(f) - FR + 1, FR):
        chunk = f[i:i + FR]
        inp = np.concatenate([ctx, chunk])[None, :]
        p, state = s.run(None, {"input": inp, "state": state, "sr": np.array(SR, np.int64)})
        ctx = chunk[-64:]
        out.append(float(p[0, 0]))
    per_frame_ms = (time.perf_counter() - t0) / len(out) * 1000
    return np.array(out), per_frame_ms


def energy_db(x: np.ndarray) -> np.ndarray:
    n = len(x) // FR
    f = x[: n * FR].astype(np.float64).reshape(n, FR)
    return 10 * np.log10((f ** 2).mean(axis=1) + 1e-9)


def energy_probs(x: np.ndarray, margin_db: float = 12.0) -> np.ndarray:
    """A pseudo-probability: 1 when the frame is `margin_db` over a slowly tracked noise floor."""
    db = energy_db(x)
    floor = np.empty_like(db)
    fl = np.percentile(db[: int(1000 / FMS)], 50)    # the first second
    for i, d in enumerate(db):
        fl = min(d, fl + 0.02) if d > fl else 0.9 * fl + 0.1 * d     # rises 0.6 dB/s, falls fast
        floor[i] = fl
    return (db > floor + margin_db).astype(float)


def segment(p: np.ndarray, *, on: float, off: float, min_silence_ms: float, min_speech_ms: float = 250,
            pad_ms: float = 100) -> list[dict]:
    """Hysteresis: start when p >= on, end after `min_silence_ms` of p < off. `decided` is when the end is known."""
    segs, start, last_speech = [], None, None
    for i, v in enumerate(p):
        t = i * FMS / 1000
        if start is None:
            if v >= on:
                start, last_speech = t, t
        else:
            if v >= off:
                last_speech = t
            elif (t - last_speech) * 1000 >= min_silence_ms:
                end = last_speech + FMS / 1000
                if (end - start) * 1000 >= min_speech_ms:
                    segs.append({"start": max(0, start - pad_ms / 1000), "end": end + pad_ms / 1000,
                                 "speech_end": end, "decided": t})
                start = None
    if start is not None:
        segs.append({"start": start, "end": len(p) * FMS / 1000, "speech_end": len(p) * FMS / 1000,
                     "decided": len(p) * FMS / 1000})
    return segs


def overlap(a, b) -> float:
    return max(0.0, min(a["end"], b["end"]) - max(a["start"], b["start"]))


def score(segs: list[dict], truth: list[dict]) -> dict:
    utt = [t for t in truth if t["utterance"]]
    music = [t for t in truth if not t["utterance"]]
    found = splits = merged = 0
    lat = []
    split_ids = []
    for u in utt:
        hits = [s for s in segs if overlap(s, u) > 0.1]
        if hits:
            found += 1
            if len(hits) > 1:
                splits += len(hits) - 1
                split_ids.append(u["id"])
            last = max(hits, key=lambda s: s["end"])
            lat.append(last["decided"] - u["end"])
    for s in segs:
        if sum(overlap(s, u) > 0.1 for u in utt) > 1:
            merged += 1
    on_music = [s for s in segs if any(overlap(s, m) > 0.1 for m in music)
                and not any(overlap(s, u) > 0.1 for u in utt)]
    music_s = sum(min(s["end"], m["end"]) - max(s["start"], m["start"]) for s in segs for m in music
                  if overlap(s, m) > 0)
    stray = [s for s in segs if not any(overlap(s, t) > 0.05 for t in truth)]
    return {"segments": len(segs), "utterances": len(utt), "found": found, "false_splits": splits,
            "split_ids": split_ids, "merged_segments": merged, "segments_on_music_only": len(on_music),
            "music_seconds_sent": round(music_s, 1), "stray_segments": len(stray),
            "end_decided_after_speech_end_median": round(float(np.median(lat)), 2) if lat else None,
            "end_decided_after_speech_end_p90": round(float(np.percentile(lat, 90)), 2) if lat else None,
            "seconds_sent": round(sum(s["end"] - s["start"] for s in segs), 1)}


def meta_turns(truth_seconds: float) -> list[dict] | None:
    p = RESULTS / "realtime_long.json"
    if not p.exists():
        return None
    ev = json.loads(p.read_text())["events"]
    starts = {e["turnId"]: e["audioProcessedMs"] / 1000 for e in ev if e.get("type") == "speechStart"}
    out = []
    for e in ev:
        if e.get("type") == "speechComplete":
            end = next((x["audioProcessedMs"] / 1000 for x in ev if x.get("type") == "speechEnd"
                        and x["turnId"] == e["turnId"]), e["audioProcessedMs"] / 1000)
            out.append({"start": starts.get(e["turnId"], end), "end": end, "speech_end": end, "decided": e["t"],
                        "text": e["transcript"]})
    return out


def main() -> None:
    x = read_wav(LOCAL / "long.wav")
    truth = json.loads((LOCAL / "long_truth.json").read_text())["segments"]
    ps, per_frame = silero_probs(x)
    pe = energy_probs(x)
    rows = []
    for ms in (300, 500, 700, 1000):
        rows.append({"chunker": "silero", "min_silence_ms": ms,
                     **score(segment(ps, on=0.5, off=0.35, min_silence_ms=ms), truth)})
        rows.append({"chunker": "energy", "min_silence_ms": ms,
                     **score(segment(pe, on=0.5, off=0.5, min_silence_ms=ms), truth)})
    mt = meta_turns(len(x) / SR)
    meta_texts = None
    if mt is not None:
        rows.append({"chunker": "meta ENDPOINTING", "min_silence_ms": None, **score(mt, truth)})
        meta_texts = [{"start": round(s["start"], 2), "end": round(s["end"], 2), "lag": round(s["decided"] - s["end"], 2),
                       "text": s["text"]} for s in mt]
    res = {"silero_ms_per_32ms_frame": round(per_frame, 3), "long_seconds": round(len(x) / SR, 1), "rows": rows,
           "meta_turns": meta_texts}
    (RESULTS / "chunking.json").write_text(json.dumps(res, indent=1, ensure_ascii=False))
    print(f"silero {per_frame:.3f} ms per 32 ms frame on this Mac (1 thread)")
    keys = ["chunker", "min_silence_ms", "segments", "found", "false_splits", "merged_segments",
            "segments_on_music_only", "music_seconds_sent", "end_decided_after_speech_end_median",
            "end_decided_after_speech_end_p90", "seconds_sent", "split_ids"]
    print(" | ".join(keys))
    for r in rows:
        print(" | ".join(str(r[k]) for k in keys))


if __name__ == "__main__":
    main()
