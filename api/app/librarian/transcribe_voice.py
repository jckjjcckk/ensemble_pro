"""transcribe_voice (013): one push-to-talk take becomes proposed marks for the admin to confirm.

The route (`POST /scores/{id}/voice`) stores the WAV at `{score_id}/voice/{utterance_id}.wav` and runs this job at once.
Voice Transcribe (diarisation mode, the score's parts, players, letters and a trimmed glossary of musical terms as
keywords) gives the transcript; one Spark call with the eval's chosen prompt (v4e, `voice_prompt.py`: the facts list the
book's groups and its landmarks with bars, `scores.landmarks`) proposes marks; `checked_marks` drops any whose quote
is not verbatim, whose bars fall outside the score or whose audience is unknown. Each survivor is written as
`annotations` rows with `status = 'proposed'`, one row per audience, sharing `payload.mark_id`; players never see a
proposed row (`can_see_annotation`). A place named from a listed landmark comes back as bars; a mark the score
cannot place (a landmark it has no record of) is returned in `result.unplaced` for the admin to put on a bar by hand. Nothing here ever makes a mark live.

What was said stays the sender's (CK, 2026-10-30): the raw take is deleted as soon as it is transcribed (a sweep
removes any left by a failed job within the hour), and the transcript and each mark's quote live only on this job
row (`result.transcript`, `result.quotes`), which only its creator can read. An annotation carries its stand text
and ids, nothing of what else was said in the take. A retry after transcription reuses the saved transcript.

The job row has no `score_id` on purpose: a failed take must not mark the book failed (worker.run_one).
"""
from __future__ import annotations

import io
import json
import re
import time
import unicodedata
import uuid
import wave
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import httpx

from ..settings import settings
from ..spend import Charge
from . import Job, JobContext, ScoreFailure, handler, landmarks
from .voice_prompt import ScoreFacts, build_prompt, checked_marks, derive_groups, parse_answer

ASR_MODEL = "muse-voice-transcribe-1.0"
ASR_MODE = "DIARIZATION"          # the eval's choice: 22/26 lines fully right against 20/26 for PUSH_TO_TALK
ASR_USD_PER_HOUR = Decimal("0.18")
MAX_SECONDS = 150                  # the button stops at 120 s; a little slack for the header and rounding
AUDIO_MAX_AGE = timedelta(hours=1)   # a take is deleted once transcribed; this only catches failed jobs

Transcriber = Callable[[bytes, list[str]], Awaitable[dict]]

# Musical terms the recogniser mangles ("fermenta", "sforzato"), as ASR keywords (v4e eval, docs/features/013-v4e-eval.md:
# term-word errors 5 -> 3 of 34 in both runs, no WER cost). Trimmed: short or common words that pulled real words
# apart ("pizz" + "cut" made "pizzicato" into "pizz cut") or that the parts and letters already cover are left out:
# pizz, cut, piano, forte, mezzo, mute, bar, letter.
MUSIC_TERMS = ["pizzicato", "arco", "fermata", "ritardando", "ritard", "a tempo", "sforzando", "subito",
               "crescendo", "diminuendo", "staccato", "legato", "tenuto", "marcato", "accent", "sordino", "divisi",
               "tutti", "downbeat", "double bar", "coda", "segno", "key change", "vibrato", "harmonic", "up bow",
               "down bow", "breath mark", "repeat", "fortissimo", "pianissimo"]


# ---------- what the score knows ----------

def _first_name(s: str) -> str:
    return (s or "").strip().split(" ")[0]


def _fold(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s.casefold()) if not unicodedata.combining(c))


class Score:
    """The facts Spark is given and the lookups that turn its answer into rows."""

    def __init__(self, db, score_id: str, group: str | None):
        self.score = (db.table("scores").select("id,ensemble_id,owner_user_id,current_interpretation_id")
                      .eq("id", score_id).limit(1).execute().data or [None])[0]
        if not self.score:
            raise ScoreFailure("This book no longer exists")
        self.group = group or self.score.get("ensemble_id")
        rows = db.table("measures").select("id,number,part").eq("score_id", score_id).execute().data or []
        self.bar_ids = {r["number"]: r["id"] for r in rows if r.get("part") is None}
        if not self.bar_ids:
            raise ScoreFailure("This book has no bars to mark yet")
        parts = db.table("parts").select("name,position").eq("score_id", score_id).execute().data or []
        names = [p["name"] for p in sorted(parts, key=lambda p: p.get("position") or 0)]
        self.members: dict[str, str] = {}          # first name -> members.id
        if self.group:
            for m in db.table("members").select("id,display_name,part").eq("ensemble_id", self.group).execute().data or []:
                if m.get("display_name"):
                    self.members.setdefault(_first_name(m["display_name"]), m["id"])
                if not parts and m.get("part") and m["part"] not in names:
                    names.append(m["part"])       # a book with no parts read yet: the group's seats
        self.parts = names
        self.letters: dict[str, int] = {}          # rehearsal letter -> bar number
        interp = self.score.get("current_interpretation_id")
        if interp:
            number_of = {v: k for k, v in self.bar_ids.items()}
            for p in db.table("measure_placements").select("measure_id,rehearsal_mark").eq("interpretation_id", interp).execute().data or []:
                mark, n = (p.get("rehearsal_mark") or "").strip(), number_of.get(p.get("measure_id"))
                if mark and n is not None and (mark not in self.letters or n < self.letters[mark]):
                    self.letters[mark] = n
        bars = sorted(self.bar_ids)
        # The book's landmarks (013 v4e): a converted book's MusicXML ones replace what page reading found. A
        # digital book has no placements, so its rehearsal letters come from the MusicXML here.
        self.landmarks = [d for d in landmarks.for_facts(landmarks.load(db, score_id))
                          if bars[0] <= d["bar"] <= bars[-1]]
        for d in self.landmarks:
            if d["kind"] == "rehearsal" and d["label"] not in self.letters:
                self.letters[d["label"]] = d["bar"]
        self.facts = ScoreFacts(parts=self.parts, members=sorted(self.members), bar_first=bars[0], bar_last=bars[-1],
                                rehearsal_marks=sorted(self.letters, key=lambda k: self.letters[k]),
                                groups=derive_groups(self.parts), landmarks=self.landmarks)

    def keywords(self) -> list[str]:
        """Words the recogniser should prefer: parts and their plurals, seat nicknames, names, letters, and the
        trimmed glossary of musical terms (`MUSIC_TERMS`)."""
        out: list[str] = []
        for p in self.parts:
            base = re.sub(r"\s+(I{1,3}|IV|V|\d+)$", "", p).strip()
            out += [p, base, base.lower() + ("es" if base.lower().endswith(("s", "x")) else "s")]
        if any(re.search(r"\bI\b|\b1\b", p) for p in self.parts):
            out.append("firsts")
        if any(re.search(r"\bII\b|\b2\b", p) for p in self.parts):
            out.append("seconds")
        out += list(self.members) + ["bar", "pickup"] + [f"letter {c}" for c in self.letters] + MUSIC_TERMS
        return list(dict.fromkeys(w for w in out if w))

    def member_id(self, name: str) -> str | None:
        want = _fold(name)
        return next((mid for n, mid in self.members.items() if _fold(n) == want), None)


# ---------- a proposal to rows ----------

LETTER = re.compile(r"\b(?:letter|rehearsal)\s+([A-Z]{1,2})\b|\b(?:at|from|before|after|to)\s+([A-Z])\b")


def place(mark: dict, score: Score) -> tuple[int, int] | None:
    """(first bar, last bar) for a checked mark, or None when the score cannot place it."""
    first, last = score.facts.bar_first, score.facts.bar_last
    pos = mark.get("position")
    if pos in ("bar", "range"):
        a = mark["bar_from"]
        b = mark.get("bar_to")
        b = (last if pos == "range" else a) if b is None else b
        return (a, b) if a in score.bar_ids and b in score.bar_ids else None
    words = f"{mark.get('text', '')} {mark.get('quote', '')}"
    if pos == "mark":
        for m in LETTER.finditer(words):
            letter = m.group(1) or m.group(2)
            if letter in score.letters:
                n = score.letters[letter]
                if re.search(rf"\bbefore\s+(?:letter\s+)?{letter}\b", words) and n - 1 in score.bar_ids:
                    n -= 1
                return n, n
        return None                                  # a double bar, a key change, a coda: no record to place it by
    if pos == "global":
        w = words.lower()
        if re.search(r"\b(end|ending|last bar|final)\b", w):
            return last, last
        if re.search(r"\b(beginning|start|top|opening|first bar)\b", w):
            return first, first
        return first, last
    return None


def audiences(mark: dict, score: Score) -> list[dict]:
    """One dict of audience columns per row. The ensemble swallows any part named beside it."""
    raw = mark["audience"] if isinstance(mark["audience"], list) else [mark["audience"]]
    if "ensemble" in raw:
        return [{"audience": "ensemble", "audience_part": None, "audience_member_id": None}]
    out: list[dict] = []
    for a in dict.fromkeys(raw):
        if a.startswith("part:"):
            out.append({"audience": "part", "audience_part": a[5:], "audience_member_id": None})
        elif a.startswith("member:") and (mid := score.member_id(a[7:])):
            out.append({"audience": "member", "audience_part": None, "audience_member_id": mid})
    return out


def plain(reason: str) -> str:
    """`check_mark`'s reason in words the admin reads in the tray ("Left out: …")."""
    if m := re.match(r"audience 'part:(.+)'$", reason):
        return f"{m.group(1)} is not a part in this book"
    if m := re.match(r"audience 'member:(.+)'$", reason):
        return f"{m.group(1)} is not in this group"
    if m := re.match(r"bar_(?:from|to) (\S+) outside (\S+)$", reason):
        return f"bar {m.group(1)} is not in this book (bars {m.group(2).replace('-', '–')})"
    if reason.startswith("quote not verbatim"):
        return "a mark on words that were not said"
    return "a mark Muse could not read"


# ---------- Voice Transcribe ----------

def pcm_wav(data: bytes) -> tuple[bytes, float]:
    """The take as a plain 44-byte-header PCM WAV, and its length in seconds. Voice Transcribe takes mono 16-bit
    PCM at 16 or 24 kHz and refuses anything else (WAVE_FORMAT_EXTENSIBLE included), so check it here."""
    try:
        with wave.open(io.BytesIO(data)) as w:
            ch, width, rate, frames = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.readframes(w.getnframes())
    except (wave.Error, EOFError, RuntimeError, ValueError) as e:   # wave raises RuntimeError on a broken chunk size
        raise ScoreFailure("That recording could not be read") from e
    if ch != 1 or width != 2 or rate not in (16000, 24000):
        raise ScoreFailure("That recording is not 16 kHz mono speech")
    secs = len(frames) / 2 / rate
    if secs > MAX_SECONDS:
        raise ScoreFailure("That recording is longer than two minutes")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(frames)
    return buf.getvalue(), secs


async def meta_transcribe(wav: bytes, keywords: list[str]) -> dict:
    base = settings.meta_api_base_url.rstrip("/")
    req = {"model": ASR_MODEL, "audioEncoding": "WAV", "mode": ASR_MODE, "keywords": keywords}
    async with httpx.AsyncClient() as client:
        r = await client.post(f"{base}/asr/transcribe",
                              headers={"Authorization": f"Bearer {settings.meta_api_key}", "Accept": "application/json"},
                              files={"request": (None, json.dumps(req), "application/json"),
                                     "audio": ("take.wav", wav, "audio/wav")}, timeout=60)
    if r.status_code != 200:
        raise RuntimeError(f"Voice Transcribe HTTP {r.status_code}: {r.text[:300]}")
    return r.json()


# ---------- the handler ----------

def delete_audio(ctx: JobContext, path: str) -> None:
    try:
        ctx.db.storage.from_("scores").remove([path])
    except Exception:  # noqa: BLE001  (the sweep removes it within the hour)
        pass


def sweep_old_audio(ctx: JobContext, score_id: str) -> None:
    """Takes left behind by a failed job are deleted after an hour. Best effort."""
    try:
        bucket = ctx.db.storage.from_("scores")
        cutoff = datetime.now(timezone.utc) - AUDIO_MAX_AGE
        old = [f"{score_id}/voice/{o['name']}" for o in bucket.list(f"{score_id}/voice") or []
               if o.get("created_at") and datetime.fromisoformat(o["created_at"].replace("Z", "+00:00")) < cutoff]
        if old:
            bucket.remove(old)
    except Exception:  # noqa: BLE001  (a sweep that fails today runs again on the next take)
        pass


VOICE_EFFORT = "minimal"


@handler("transcribe_voice")
async def transcribe_voice(job: Job, ctx: JobContext, *, transcribe: Transcriber | None = None) -> dict[str, Any]:
    p = job.payload
    score_id, utterance = p["score_id"], p["utterance_id"]
    t0 = time.monotonic()
    score = Score(ctx.db, score_id, p.get("ensemble_id"))
    before = (ctx.db.table("jobs").select("result").eq("id", job.id).execute().data or [{}])[0].get("result") or {}
    if "transcript" in before:                       # a retry: the take was transcribed (and deleted) last time
        transcript, asr_cost = before["transcript"], Decimal("0")
    else:
        wav, secs = pcm_wav(ctx.storage_download(p["audio_path"]))
        heard = await (transcribe or meta_transcribe)(wav, score.keywords())
        ms = heard.get("audioDurationMs") or secs * 1000
        asr_cost = Decimal(str(ms)) / Decimal(3_600_000) * ASR_USD_PER_HOUR
        ctx.charge(Charge("meta", ASR_MODEL, "voice", asr_cost, units=round(ms / 1000, 2)))
        transcript = (heard.get("transcript") or " ".join(t.get("transcript", "") for t in heard.get("turns") or [])).strip()
        ctx.db.table("jobs").update({"result": {"utterance_id": utterance, "transcript": transcript}}).eq("id", job.id).execute()
        delete_audio(ctx, p["audio_path"])
    result: dict[str, Any] = {"utterance_id": utterance, "transcript": transcript, "proposed": 0, "rows": 0,
                              "unplaced": [], "refused": [], "quotes": {}}
    cost = asr_cost
    if transcript:
        system, user = build_prompt(transcript, score.facts)
        # Effort minimal on chat completions, streamed: the setting every voice eval ran at (013-text-eval,
        # 013-always-on) and half the time of Messages/low with the same marks (speed pass, benchmark 5.10).
        c = await ctx.complete(user, system=system, effort=VOICE_EFFORT, max_tokens=8192, provider="meta", stream=True)
        cost += c.charge.cost_usd
        try:
            answer = parse_answer(c.text)
        except ValueError:
            answer, result["refused"] = [], ["the model's answer was not JSON"]
        ok, refused = checked_marks(answer, transcript, score.facts)
        result["refused"] += [plain(r) for r in refused]
        rows: list[dict] = []
        for m in ok:
            bars, auds = place(m, score), audiences(m, score)
            if bars is None or not auds:
                result["unplaced"].append({k: m.get(k) for k in ("text", "kind", "position", "audience", "quote")})
                continue
            mark_id = str(uuid.uuid4())
            for a in auds:
                rows.append({
                    "score_id": score_id, "ensemble_id": p.get("ensemble_id"), "session_id": p.get("session_id"),
                    "kind": m["kind"], "body": m["text"].strip(), "status": "proposed", "author_id": job.created_by,
                    "measure_from": score.bar_ids[bars[0]], "measure_to": score.bar_ids[bars[1]], **a,
                    # Only this mark: never the take's transcript or quote, which may speak to other people.
                    "payload": {"source": "voice", "utterance_id": utterance, "mark_id": mark_id,
                                "position": m["position"], "bar": bars[0], "bar_to": bars[1]},
                })
            result["quotes"][mark_id] = m["quote"]
            result["proposed"] += 1
        if rows:
            ctx.db.table("annotations").insert(rows).execute()
        result["rows"] = len(rows)
    result["seconds"] = round(time.monotonic() - t0, 2)
    result["cost_usd"] = float(round(cost, 6))
    sweep_old_audio(ctx, score_id)
    return result
