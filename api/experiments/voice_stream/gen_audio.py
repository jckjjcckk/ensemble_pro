"""Negatives for the confidence gate and the long stream for the chunker (Q3, Q4). No paid calls.

    uv run python -m experiments.voice_stream.gen_audio

n01-n15: SYNTHETIC speech, macOS `say` (several voices) -> afconvert 16 kHz -> plain PCM WAV. Not CK's voice.
n16-n17: piano, 12 s each from the MuseScore render of the Open Goldberg (engrave experiment, a sampled piano).
n18: an instrument recording shipped with music21 (audioSearch/test_audio.wav), 12 s.
long.wav: eval lines and negatives joined with silences of known length over a low room-noise floor;
long_truth.json gives every segment's span and whether it is an utterance.
"""

from __future__ import annotations

import json
import struct
import subprocess
import tempfile
from pathlib import Path

import numpy as np

from .common import API, LOCAL, SR, WAVS, read_wav, speech_span, write_wav

NEG = [  # (id, voice, text, note)
    ("n01", "Daniel", "One, two, three, four.", "counting in"),
    ("n02", "Samantha", "And a one, and a two.", "counting in"),
    ("n03", "Karen", "Okay, let's take it from the top.", "start point, casual"),
    ("n04", "Moira", "Right, from the top then.", "start point, casual"),
    ("n05", "Fred", "Can somebody pass me the rosin?", "chat"),
    ("n06", "Daniel", "Has anyone seen my pencil? I had it a minute ago.", "chat"),
    ("n07", "Tessa", "That was lovely, well done everybody.", "praise"),
    ("n08", "Rishi", "Sorry, that's my phone, one second.", "chat"),
    ("n09", "Samantha", "Let's tune. Can I have an A, please?", "tuning request"),
    ("n10", "Karen", "Where were we? Bar forty?", "question with a bar number"),
    ("n11", "Daniel", "Ten minute break, back at quarter past.", "logistics with numbers"),
    ("n12", "Moira", "Okay, letter B, off we go.", "start point with a letter"),
    ("n13", "Fred", "I think the coffee machine is broken again.", "chat"),
    ("n14", "Tessa", "Again from bar twelve, please.", "start point with a bar number"),
    ("n15", "Rishi", "Three, four.", "counting in"),
]
GOLDBERG = API.parent / ".claude/worktrees/agent-a6373b95fb192e74a/api/experiments/engrave/goldberg/musescore-opengoldberg.mp3"
INSTRUMENT = API / ".venv/lib/python3.12/site-packages/music21/audioSearch/test_audio.wav"


def afconvert(src: Path, start: float = 0.0, dur: float | None = None) -> np.ndarray:
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td) / "a.wav"
        subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI16@16000", "-c", "1", str(src), str(tmp)], check=True)
        raw = tmp.read_bytes()
    i = 12
    while i + 8 <= len(raw):
        cid, size = raw[i:i + 4], struct.unpack("<I", raw[i + 4:i + 8])[0]
        if cid == b"data":
            x = np.frombuffer(raw[i + 8:i + 8 + size], dtype=np.int16).copy()
            break
        i += 8 + size + (size & 1)
    a = int(start * SR)
    return x[a:a + int(dur * SR)] if dur else x[a:]


def lead(x: np.ndarray, s: float = 0.4) -> np.ndarray:
    z = np.zeros(int(s * SR), np.int16)
    return np.concatenate([z, x, z])


def negatives() -> list[dict]:
    LOCAL.mkdir(exist_ok=True)
    meta = []
    with tempfile.TemporaryDirectory() as td:
        for uid, voice, text, note in NEG:
            aiff = Path(td) / f"{uid}.aiff"
            subprocess.run(["say", "-v", voice, "-o", str(aiff), text], check=True)
            write_wav(LOCAL / f"{uid}.wav", lead(afconvert(aiff)))
            meta.append({"id": uid, "kind": "synthetic speech", "voice": voice, "text": text, "note": note})
    write_wav(LOCAL / "n16.wav", afconvert(GOLDBERG, 5, 12))
    write_wav(LOCAL / "n17.wav", afconvert(GOLDBERG, 70, 12))
    meta += [{"id": "n16", "kind": "piano", "text": "", "note": "Goldberg Aria render, 0:05-0:17"},
             {"id": "n17", "kind": "piano", "text": "", "note": "Goldberg render, 1:10-1:22"}]
    write_wav(LOCAL / "n18.wav", afconvert(INSTRUMENT, 0, 12))
    meta.append({"id": "n18", "kind": "instrument", "text": "", "note": "music21 audioSearch test_audio.wav"})
    (LOCAL / "negatives.json").write_text(json.dumps(meta, indent=1))
    return meta


LONG = [  # (clip id, silence after it in s)
    ("n16", 0.8), ("v01", 1.2), ("v02", 2.0), ("n01", 0.6), ("n17", 1.5), ("v03c", 0.9), ("v05", 3.0),
    ("n05", 0.7), ("v07c", 1.0), ("v08", 0.5), ("v12", 2.5), ("n12", 0.8), ("n18", 1.2), ("v15", 1.0),
    ("v19", 5.0), ("v21", 0.7), ("n10", 1.5), ("v24", 0.6), ("v26", 2.0), ("n03", 1.0),
]


def long_stream() -> None:
    rng = np.random.default_rng(13)
    parts, truth, t = [np.zeros(int(1.0 * SR))], [], 1.0
    for uid, gap in LONG:
        p = WAVS / f"{uid}.wav"
        x = read_wav(p if p.exists() else LOCAL / f"{uid}.wav").astype(np.float64)
        if uid in ("n16", "n17", "n18"):
            on, end = 0.0, len(x) / SR
            utter = False
        else:
            on, end = speech_span(x)
            pad = 0.15
            a, b = max(0, int((on - pad) * SR)), min(len(x), int((end + pad) * SR))
            x = x[a:b]
            on, end = on - a / SR, end - a / SR
            utter = True
        truth.append({"id": uid, "start": round(t + on, 3), "end": round(t + end, 3), "utterance": utter,
                      "negative": uid.startswith("n")})
        parts += [x, np.zeros(int(gap * SR))]
        t += len(x) / SR + gap
    sig = np.concatenate(parts)
    noise = rng.normal(0, 25, len(sig))          # about -62 dBFS room noise under everything
    sig = np.clip(sig + noise, -32768, 32767)
    write_wav(LOCAL / "long.wav", sig)
    (LOCAL / "long_truth.json").write_text(json.dumps({"seconds": round(len(sig) / SR, 2), "segments": truth},
                                                      indent=1))
    print(f"long.wav {len(sig) / SR:.1f}s, {sum(s['utterance'] for s in truth)} utterances")


if __name__ == "__main__":
    for m in negatives():
        print(m["id"], m["kind"], m["text"])
    long_stream()
