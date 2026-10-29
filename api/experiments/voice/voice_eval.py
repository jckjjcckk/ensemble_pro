"""Voice eval (013): Muse Voice Transcribe, then one Spark call per utterance, scored against script.csv.

    uv run python -m experiments.voice.voice_eval transcribe
    uv run python -m experiments.voice.voice_eval run --prompt v1
    uv run python -m experiments.voice.voice_eval summary

Audio: `FOLIO_VOICE_DIR` (default api/fixtures/voice/audio), `vNN.m4a` the 30 script lines, `vNNc.m4a` retakes of
lines 1-10 (self-corrections, blurred wording; same labels). WAVs are cached in `<audio>/wav/` as plain PCM
(afconvert writes WAVE_FORMAT_EXTENSIBLE with an FLLR chunk, which the endpoint refuses). Raw transcripts and
replies go to `out/` (ignored); per-version scores to `results/` and every paid call to `spend.jsonl`
(committed). Only Meta is called: the env loader copies the META_* keys and forces LLM_PROVIDER=meta.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import datetime as dt
import json
import os
import struct
import subprocess
import sys
import time
import wave
from pathlib import Path

HERE = Path(__file__).resolve().parent
API = HERE.parent.parent

import httpx  # noqa: E402

from app import llm  # noqa: E402
from app.librarian.voice_prompt import ScoreFacts, checked_marks, parse_answer  # noqa: E402
from app.settings import settings  # noqa: E402

from . import prompts  # noqa: E402
from .textnorm import annotation_key, wer  # noqa: E402

assert settings.llm_provider == "meta", "voice eval calls Meta only"

AUDIO = Path(os.environ.get("FOLIO_VOICE_DIR", API / "fixtures" / "voice" / "audio"))
SCRIPT = API / "fixtures" / "voice" / "script.csv"
OUT = HERE / "out"
# Voice Transcribe mode: DIARIZATION (turns + speaker) or PUSH_TO_TALK (one transcript). Each has its own cache.
ASR_MODE = os.environ.get("VOICE_ASR_MODE", "DIARIZATION")
TRANS_DIR = OUT / ("transcripts" if ASR_MODE == "DIARIZATION" else f"transcripts_{ASR_MODE.lower()}")
RESULTS = HERE / "results"
LEDGER = HERE / "spend.jsonl"
BUDGET_USD = 20.0  # raised from $5 by CK, 2026-10-29
ASR_USD_PER_HOUR = 0.18
ASR_URL = "https://api.meta.ai/v1/asr/transcribe"

FACTS = ScoreFacts(parts=["Violin I", "Violin II", "Viola", "Cello", "Soprano", "Alto", "Tenor", "Bass"],
                   members=["Lin", "Inès"])
KEYWORDS = FACTS.parts + ["Violin", "violins", "violas", "cellos", "sopranos", "altos", "tenors", "basses",
                          "Lin", "Inès", "bar", "pickup"] + [f"letter {c}" for c in FACTS.rehearsal_marks]
# CSV audience "member" names one person; the script says who.
MEMBER_OF = {"v11": "Lin", "v22": "Inès"}


# ---------- ledger ----------

def spent() -> float:
    if not LEDGER.exists():
        return 0.0
    return sum(json.loads(line)["usd"] for line in LEDGER.read_text().splitlines() if line.strip())


def log_spend(**row) -> None:
    row = {"ts": dt.datetime.now().isoformat(timespec="seconds"), **row}
    with LEDGER.open("a") as f:
        f.write(json.dumps(row) + "\n")


def guard(next_usd: float) -> None:
    if spent() + next_usd > BUDGET_USD:
        sys.exit(f"STOP: spend {spent():.4f} + {next_usd:.4f} would pass the ${BUDGET_USD} budget")


# ---------- labels ----------

def labels() -> dict[str, dict]:
    with SCRIPT.open() as f:
        return {r["id"]: r for r in csv.DictReader(f)}


def base_id(uid: str) -> str:
    return uid[:-1] if uid.endswith("c") else uid


# ---------- audio + transcription ----------

def to_wav(m4a: Path) -> Path:
    wdir = AUDIO / "wav"
    wdir.mkdir(exist_ok=True)
    dst = wdir / (m4a.stem + ".wav")
    if dst.exists() and dst.stat().st_mtime >= m4a.stat().st_mtime:
        return dst
    tmp = wdir / (m4a.stem + ".afc.wav")
    subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI16@16000", "-c", "1", str(m4a), str(tmp)], check=True)
    raw = tmp.read_bytes()
    i, pcm = 12, None
    while i + 8 <= len(raw):
        cid, size = raw[i:i + 4], struct.unpack("<I", raw[i + 4:i + 8])[0]
        if cid == b"data":
            pcm = raw[i + 8:i + 8 + size]
            break
        i += 8 + size + (size & 1)
    if pcm is None:
        raise RuntimeError(f"{m4a.name}: no data chunk")
    with wave.open(str(dst), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(pcm)
    tmp.unlink()
    return dst


async def transcribe_one(client: httpx.AsyncClient, sem: asyncio.Semaphore, m4a: Path) -> None:
    dst = TRANS_DIR / f"{m4a.stem}.json"
    if dst.exists():
        return
    wav = to_wav(m4a)
    with wave.open(str(wav)) as w:
        secs = w.getnframes() / w.getframerate()
    usd = secs / 3600 * ASR_USD_PER_HOUR
    guard(usd)
    req = {"model": "muse-voice-transcribe-1.0", "audioEncoding": "WAV", "mode": ASR_MODE,
           "keywords": KEYWORDS}
    async with sem:
        t0 = time.monotonic()
        r = await client.post(ASR_URL, headers={"Authorization": f"Bearer {settings.meta_api_key}",
                                                "Accept": "application/json"},
                              files={"request": (None, json.dumps(req), "application/json"),
                                     "audio": (wav.name, wav.read_bytes(), "audio/wav")}, timeout=120)
        took = time.monotonic() - t0
    if r.status_code != 200:
        raise RuntimeError(f"{m4a.name}: HTTP {r.status_code} {r.text[:300]}")
    body = r.json()
    usd = body.get("audioDurationMs", secs * 1000) / 3_600_000 * ASR_USD_PER_HOUR
    log_spend(kind=f"asr:{ASR_MODE}", id=m4a.stem, usd=round(usd, 6), secs=round(took, 2))
    dst.write_text(json.dumps({**body, "_seconds": took, "_usd": usd}, ensure_ascii=False, indent=1))
    print(f"{m4a.stem}: {took:.1f}s {body['transcript']!r}")


async def cmd_transcribe() -> None:
    TRANS_DIR.mkdir(parents=True, exist_ok=True)
    files = sorted(AUDIO.glob("v*.m4a"))
    sem = asyncio.Semaphore(4)
    async with httpx.AsyncClient() as client:
        await asyncio.gather(*(transcribe_one(client, sem, f) for f in files))
    write_transcripts_md()


def load_transcripts() -> dict[str, dict]:
    return {p.stem: json.loads(p.read_text()) for p in sorted(TRANS_DIR.glob("v*.json"))}


def write_transcripts_md() -> None:
    lab = labels()
    rows = ["| id | WER | script | transcript |", "|---|---|---|---|"]
    for uid, t in load_transcripts().items():
        e, n = wer(lab[base_id(uid)]["text"], t["transcript"])
        rows.append(f"| {uid} | {e}/{n} | {lab[base_id(uid)]['text']} | {t['transcript']} |")
    RESULTS.mkdir(exist_ok=True)
    tot = [wer(lab[base_id(u)]["text"], t["transcript"]) for u, t in load_transcripts().items()]
    rows.append(f"| all | {sum(e for e, _ in tot)}/{sum(n for _, n in tot)} | | |")
    name = "transcripts.md" if ASR_MODE == "DIARIZATION" else f"transcripts_{ASR_MODE.lower()}.md"
    (RESULTS / name).write_text(f"# Transcripts (Muse Voice Transcribe, {ASR_MODE}, keywords)\n\n"
                                            + "\n".join(rows) + "\n")


# ---------- Spark ----------

async def spark(system: str, user: str, *, tag: str, uid: str) -> tuple[str, float, float, int, int]:
    guard(0.03)
    t0 = time.monotonic()
    for attempt in range(3):
        try:
            c = await llm.complete(user, system=system, effort="low", max_tokens=8192)
            break
        except Exception as e:  # noqa: BLE001 - transient API errors: retry twice
            if attempt == 2:
                raise
            print(f"  {uid} {tag}: retry after {type(e).__name__}: {e}")
            await asyncio.sleep(3 * (attempt + 1))
    took = time.monotonic() - t0
    usd = float(c.charge.cost_usd)
    log_spend(kind=tag, id=uid, usd=round(usd, 6), secs=round(took, 2),
              input_tokens=c.charge.input_tokens, output_tokens=c.charge.output_tokens)
    return c.text, usd, took, c.charge.input_tokens, c.charge.output_tokens


def few_shot_pool() -> list[dict]:
    """Every CSV line as a worked example (text as the transcript, labels as the answer)."""
    out = []
    for uid, r in labels().items():
        if r["expect"] == "none":
            ans: object = {"none": True}
        else:
            ans = expected_marks(uid, r)
        out.append({"id": uid, "transcript": r["text"], "answer": ans})
    return out


def expected_marks(uid: str, r: dict) -> object:
    """The CSV row written in the answer schema (for few-shot examples)."""
    if uid == "v21":  # the one two-mark line, written out by hand
        q = r["text"]
        return [{"position": "bar", "bar_from": 64, "bar_to": 64, "audience": ["part:Alto", "part:Tenor"],
                 "kind": "breath", "text": "Breath at 64", "quote": q},
                {"position": "bar", "bar_from": 65, "bar_to": 65, "audience": ["ensemble"], "kind": "dynamic",
                 "text": "sfz at 65", "quote": q}]
    aud = [a if a != "member" else f"member:{MEMBER_OF[uid]}" for a in r["audience"].split(";")]
    bf = int(r["bar_from"]) if r["bar_from"] else None
    bt = int(r["bar_to"]) if r["bar_to"] else None
    return {"position": r["position"], "bar_from": bf, "bar_to": bt, "audience": aud,
            "kind": r["kind"], "text": r["expect"],
            "quote": r["text"]}


def run_tag(version: str) -> str:
    """Cache and results name: the prompt version, suffixed by the ASR mode when it is not the default."""
    return version if ASR_MODE == "DIARIZATION" else f"{version}_{ASR_MODE.lower()}"


def alt_transcript(uid: str) -> str | None:
    """The other mode's transcript of the same file, for prompts that read both recognisers."""
    other = OUT / ("transcripts_push_to_talk" if ASR_MODE == "DIARIZATION" else "transcripts") / f"{uid}.json"
    return json.loads(other.read_text())["transcript"] if other.exists() else None


async def propose(version: str, uid: str, transcript: str) -> dict:
    dst = OUT / "runs" / run_tag(version) / f"{uid}.json"
    if dst.exists():
        return json.loads(dst.read_text())
    build = getattr(prompts, version)
    if version in prompts.TWO_TRANSCRIPTS:
        system, user = build(transcript, FACTS, {uid, base_id(uid)}, few_shot_pool(), alt=alt_transcript(uid))
    else:
        system, user = build(transcript, FACTS, {uid, base_id(uid)}, few_shot_pool())
    text, usd, took, tin, tout = await spark(system, user, tag=f"propose:{version}", uid=uid)
    rec = {"id": uid, "version": version, "reply": text, "usd": usd, "seconds": took, "input_tokens": tin,
           "output_tokens": tout, "prompt_user": user}
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(rec, ensure_ascii=False, indent=1))
    return rec


JUDGE_SYSTEM = "You check rehearsal marks for a music librarian. Answer with JSON only."


def _show(m: dict) -> str:
    """A proposed mark as the stand would label it: text, then bars (when it has any) and who it is for."""
    aud = m["audience"] if isinstance(m["audience"], list) else [m["audience"]]
    who = ", ".join("everyone" if a == "ensemble" else a.split(":", 1)[1] for a in aud)
    bf, bt = m.get("bar_from"), m.get("bar_to")
    where = "" if bf is None else (f"bar {bf}, " if bt in (None, bf) else f"bars {bf}-{bt}, ")
    return f"{m['text']} ({where}for {who})"


# Judge v2 (2026-10-29): v1 printed "bars None-None" for letter and global marks and refused identical texts.
JUDGE_VERSION = "judge2"


async def judge(version: str, uid: str, expect: str, marks: list[dict]) -> dict:
    dst = OUT / "runs" / run_tag(version) / f"{uid}.{JUDGE_VERSION}.json"
    if dst.exists():
        return json.loads(dst.read_text())
    shown = "; ".join(_show(m) for m in marks)
    user = (f"Expected mark on the stand: \"{expect}\"\nProposed mark: \"{shown}\"\n\n"
            "Would a musician reading the proposed mark on their part accept it as saying the same thing as the "
            "expected one (same place, same instruction; wording may differ)? Answer {\"accept\": true} or "
            "{\"accept\": false}.")
    text, usd, took, _, _ = await spark(JUDGE_SYSTEM, user, tag=f"judge:{version}", uid=uid)
    try:
        acc = bool(parse_answer(text).get("accept"))
    except Exception:  # noqa: BLE001
        acc = False
    rec = {"accept": acc, "reply": text, "usd": usd, "shown": shown}
    dst.write_text(json.dumps(rec, ensure_ascii=False, indent=1))
    return rec


# ---------- scoring ----------

def _aud_set(marks: list[dict]) -> set[str]:
    s: set[str] = set()
    for m in marks:
        a = m["audience"]
        s |= set(a if isinstance(a, list) else [a])
    return s


def score_line(uid: str, r: dict, marks: list[dict]) -> dict:
    negative = r["expect"] == "none"
    if negative:
        return {"negative": True, "ok": not marks}
    if not marks:
        return {"negative": False, "produced": False, "position": False, "bar_from": False, "bar_to": False,
                "audience": False, "kind": False, "expect_exact": False, "all_fields": False}
    want_bf = int(r["bar_from"]) if r["bar_from"] else None
    want_bt = int(r["bar_to"]) if r["bar_to"] else None
    bfs = [m.get("bar_from") for m in marks if m.get("bar_from") is not None]
    bts = []
    for m in marks:
        bt = m.get("bar_to")
        if bt is None and m.get("position") == "bar":
            bt = m.get("bar_from")
        if bt is not None:
            bts.append(bt)
    got_bf = min(bfs) if bfs else None
    got_bt = max(bts) if bts else None
    if want_bt is None and r["position"] == "range" and got_bt == FACTS.bar_last:
        got_bt = None  # "to the end": null or the last bar
    want_aud = {a if a != "member" else f"member:{MEMBER_OF[uid]}" for a in r["audience"].split(";")}
    pos = {m.get("position") for m in marks} == {r["position"]}
    kind = {m.get("kind") for m in marks} == set(r["kind"].split(";"))
    out = {
        "negative": False, "produced": True, "position": pos, "bar_from": got_bf == want_bf,
        "bar_to": got_bt == want_bt, "audience": _aud_set(marks) == want_aud, "kind": kind,
        "expect_exact": annotation_key("; ".join(m["text"] for m in marks)) == annotation_key(r["expect"]),
    }
    out["all_fields"] = all(out[k] for k in ("position", "bar_from", "bar_to", "audience", "kind"))
    return out


FIELDS = ["position", "bar_from", "bar_to", "audience", "kind", "expect_exact", "expect_judge", "all_fields"]


def aggregate(rows: list[dict]) -> dict:
    pos = [r for r in rows if not r["score"]["negative"]]
    neg = [r for r in rows if r["score"]["negative"]]
    e = sum(r["wer"][0] for r in rows)
    n = sum(r["wer"][1] for r in rows)
    agg = {"lines": len(rows), "positives": len(pos), "negatives": len(neg), "wer": round(e / n, 4) if n else None,
           "wer_counts": [e, n], "produced": sum(r["score"]["produced"] for r in pos),
           "refused": sum(len(r["refused"]) for r in rows),
           "negatives_ok": sum(r["score"]["ok"] for r in neg),
           "usd_per_line": round(sum(r["usd_line"] for r in rows) / len(rows), 5),
           "seconds_per_line": round(sum(r["seconds_line"] for r in rows) / len(rows), 2),
           "asr_seconds_per_line": round(sum(r["asr_seconds"] for r in rows) / len(rows), 2),
           "spark_seconds_per_line": round(sum(r["spark_seconds"] for r in rows) / len(rows), 2),
           "judge_usd": round(sum(r["judge_usd"] for r in rows), 5)}
    for f in FIELDS:
        agg[f] = sum(bool(r["score"].get(f)) for r in pos)
    return agg


async def cmd_run(version: str) -> None:
    lab = labels()
    trans = load_transcripts()
    if not trans:
        sys.exit("no transcripts: run `transcribe` first")
    sem = asyncio.Semaphore(6)

    async def one(uid: str) -> dict:
        t = trans[uid]
        r = lab[base_id(uid)]
        async with sem:
            rec = await propose(version, uid, t["transcript"])
        try:
            ans = parse_answer(rec["reply"])
            heard = t["transcript"]
            if version in prompts.TWO_TRANSCRIPTS:  # a quote may come from either recogniser
                heard = f"{heard}\n{alt_transcript(uid) or ''}"
            marks, refused = checked_marks(ans, heard, FACTS)
        except Exception as e:  # noqa: BLE001
            ans, marks, refused = None, [], [f"unparseable: {e}"]
        sc = score_line(base_id(uid), r, marks)
        jud = {"accept": False, "usd": 0.0}
        if not sc["negative"] and marks:
            async with sem:
                jud = await judge(version, uid, r["expect"], marks)
            sc["expect_judge"] = jud["accept"]
        elif not sc["negative"]:
            sc["expect_judge"] = False
        return {"id": uid, "transcript": t["transcript"], "wer": list(wer(r["text"], t["transcript"])),
                "answer": ans, "marks": marks, "refused": refused, "score": sc,
                "asr_seconds": round(t["_seconds"], 2), "spark_seconds": round(rec["seconds"], 2),
                "seconds_line": round(t["_seconds"] + rec["seconds"], 2),
                "usd_line": round(t["_usd"] + rec["usd"], 6), "judge_usd": round(jud.get("usd", 0.0), 6),
                "judge_shown": jud.get("shown")}

    rows = await asyncio.gather(*(one(u) for u in sorted(trans)))
    base = [r for r in rows if not r["id"].endswith("c")]
    retake = [r for r in rows if r["id"].endswith("c")]
    # the base lines the retakes repeat, for a like-for-like comparison
    base10 = [r for r in base if r["id"] in {base_id(x["id"]) for x in retake}]
    res = {"version": run_tag(version), "base": aggregate(base), "base_1_10": aggregate(base10) if base10 else None,
           "retakes": aggregate(retake) if retake else None, "rows": rows}
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / f"{run_tag(version)}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))
    print(json.dumps({k: res[k] for k in ("base", "base_1_10", "retakes")}, indent=1))
    for r in rows:
        s = r["score"]
        if s["negative"]:
            flag = "ok" if s["ok"] else "FALSE POSITIVE"
        else:
            flag = " ".join(f for f in FIELDS if not s.get(f)) or "all ok"
        print(f"{r['id']:5} {flag:60} {json.dumps(r['marks'], ensure_ascii=False)[:160]} {r['refused']}")
    cmd_summary()
    print(f"spend so far ${spent():.4f}")


def cmd_summary() -> None:
    rows = ["| version | set | lines | WER | produced | position | bar_from | bar_to | audience | kind | "
            "expect exact | expect judge | all 5 fields | negatives ok | refused | $/line | s/line |",
            "|" + "---|" * 17]
    for p in sorted(RESULTS.glob("v*.json")):
        res = json.loads(p.read_text())
        for key in ("base", "base_1_10", "retakes"):
            a = res.get(key)
            if not a:
                continue
            pp = a["positives"]
            rows.append(f"| {res['version']} | {key} | {a['lines']} | {a['wer']:.3f} | {a['produced']}/{pp} | "
                        + " | ".join(f"{a[f]}/{pp}" for f in FIELDS[:-2])
                        + f" | {a['expect_judge']}/{pp} | {a['all_fields']}/{pp} | {a['negatives_ok']}/{a['negatives']}"
                        f" | {a['refused']} | {a['usd_per_line']:.4f} | {a['seconds_per_line']:.1f} |")
    (RESULTS / "summary.md").write_text("# Voice eval summary\n\n" + "\n".join(rows)
                                        + f"\n\nTotal Meta spend (spend.jsonl): ${spent():.4f}\n")
    print("\n".join(rows))


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("transcribe")
    r = sub.add_parser("run")
    r.add_argument("--prompt", required=True)
    sub.add_parser("summary")
    a = ap.parse_args()
    if a.cmd == "transcribe":
        asyncio.run(cmd_transcribe())
    elif a.cmd == "run":
        asyncio.run(cmd_run(a.prompt))
    else:
        cmd_summary()


if __name__ == "__main__":
    main()
