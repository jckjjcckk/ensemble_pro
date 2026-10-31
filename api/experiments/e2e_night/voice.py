"""A voice note on a book, as the iPad sends it (`sendVoice`), watched as `useVoice` watches it, then the first card
accepted and the others dismissed through `commit_marks`, exactly as `VoiceNotes.tsx` + `ink.ts` do. Real Meta calls
(Voice Transcribe + one Spark call), run in-process on the dev API.

    PYTHONPATH=. uv run python -m experiments.e2e_night.voice <slug> v03 [v12 ...]

For each line: the take's seconds (POST to job done), its cost, the proposals with their bars, audience and kind
against `fixtures/voice/script.csv`, then the accept/dismiss and who can read the accepted mark (the two players).
"""
from __future__ import annotations

import csv
import json
import sys
import time

from .book import POLL, state, step
from .common import API_DIR, As, cost_of, guard

WAVS = API_DIR / "fixtures" / "voice" / "audio" / "wav"
SCRIPT = {r["id"]: r for r in csv.DictReader((API_DIR / "fixtures" / "voice" / "script.csv").open())}
SEL = "id,kind,body,status,audience,audience_part,audience_member_id,ensemble_id,payload,author_id,measure_from:measures!annotations_measure_from_fkey(number),measure_to:measures!annotations_measure_to_fkey(number)"


def bars(r: dict) -> tuple[int | None, int | None]:
    f, t = r.get("measure_from"), r.get("measure_to")
    return (f or {}).get("number") if isinstance(f, dict) else None, (t or {}).get("number") if isinstance(t, dict) else None


def run_line(a: As, s: dict, line: str, layer: str | None) -> dict:
    guard(0.02)
    sid = s["score_id"]
    wav = (WAVS / f"{line}.wav").read_bytes()
    t0 = time.time()
    q = f"?ensemble_id={layer}" if layer else ""
    r = a.api("POST", f"/scores/{sid}/voice{q}", content=wav, headers={"Content-Type": "audio/wav"})
    if r.status_code != 202:
        return {"line": line, "status": r.status_code, "error": r.text[:300]}
    start = r.json()
    post_s = round(time.time() - t0, 2)
    job = None
    while time.time() - t0 < 300:
        rows = a.rest("GET", f"jobs?select=id,status,result,error,attempts&id=eq.{start['job_id']}").json()
        job = rows[0] if rows else None
        if job and job["status"] in ("done", "failed"):
            break
        time.sleep(POLL / 4)
    took = round(time.time() - t0, 2)
    res = (job or {}).get("result") or {}
    props = a.rest("GET", f"annotations?select={SEL}&score_id=eq.{sid}&status=eq.proposed&payload->>utterance_id=eq.{start['utterance_id']}").json()
    if not isinstance(props, list):
        props = []
    cards: dict[str, list[dict]] = {}
    for p in props:
        cards.setdefault(str((p.get("payload") or {}).get("mark_id") or p["id"]), []).append(p)
    exp = SCRIPT.get(line.rstrip("c"), {}) if line not in SCRIPT else SCRIPT[line]
    out = {"line": line, "said": exp.get("text"), "expect": {k: exp.get(k) for k in ("bar_from", "bar_to", "audience", "kind", "expect")},
           "status": job and job["status"], "error": job and job.get("error"), "post_s": post_s, "seconds": took,
           "handler_s": res.get("seconds"), "cost": cost_of([start["job_id"]]), "transcript": res.get("transcript"),
           "proposed": res.get("proposed"), "unplaced": res.get("unplaced"), "refused": res.get("refused"),
           "cards": [{"kind": rs[0]["kind"], "body": rs[0]["body"], "bars": bars(rs[0]), "payload_bars": ((rs[0].get("payload") or {}).get("bar"), (rs[0].get("payload") or {}).get("bar_to")),
                      "who": [(x["audience"], x.get("audience_part") or x.get("audience_member_id")) for x in rs], "layer": rs[0].get("ensemble_id"),
                      "confidence": (rs[0].get("payload") or {}).get("confidence"), "ids": [x["id"] for x in rs]} for rs in cards.values()]}
    return out


def accept_and_dismiss(a: As, s: dict, out: dict, layer: str | None, accept: bool = True) -> None:
    """The first card accepted unedited (acceptWrites: every row of the mark goes live with its bars), the rest dismissed;
    with `accept` False every card is dismissed."""
    sid = s["score_id"]
    if not out.get("cards"):
        return
    if not accept:
        for c in out["cards"]:
            d = a.rpc("commit_marks", {"p_score": sid, "p_layer": layer, "p_remove": c["ids"], "p_update": [], "p_insert": []})
            out.setdefault("dismiss", []).append({"status": d.status_code, "n": len(c["ids"]), "err": None if d.status_code in (200, 204) else d.text[:200]})
        left = a.rest("GET", f"annotations?select=id&id=in.({','.join(i for c in out['cards'] for i in c['ids'])})").json()
        out["dismissed_left"] = len(left) if isinstance(left, list) else left
        return
    first, rest = out["cards"][0], out["cards"][1:]
    f, t = first["bars"]
    r = a.rpc("commit_marks", {"p_score": sid, "p_layer": layer, "p_remove": [],
                               "p_update": [{"id": i, "bar_from": f, "bar_to": t, "status": "live"} for i in first["ids"]], "p_insert": []})
    out["accept"] = {"status": r.status_code, "rows": [(x["status"], x.get("audience"), x.get("audience_part"), (x.get("payload") or {}).get("bar")) for x in r.json()] if r.status_code == 200 else r.text[:300]}
    for c in rest:
        d = a.rpc("commit_marks", {"p_score": sid, "p_layer": layer, "p_remove": c["ids"], "p_update": [], "p_insert": []})
        out.setdefault("dismiss", []).append({"status": d.status_code, "n": len(c["ids"]), "err": None if d.status_code in (200, 204) else d.text[:200]})
    if not rest and out["cards"]:
        out["dismiss"] = "nothing else proposed"
    # who reads the accepted mark: the players, through RLS
    if s.get("group"):
        for email in ("test1@muse.test", "test2@muse.test"):
            p = As(email)
            seen = p.rest("GET", f"annotations?select=id,status,audience,audience_part&id=in.({','.join(first['ids'])})").json()
            out.setdefault("players_see", {})[email] = [(x["status"], x["audience"], x.get("audience_part")) for x in seen] if isinstance(seen, list) else seen
        left = a.rest("GET", f"annotations?select=id&status=eq.proposed&id=in.({','.join(i for c in rest for i in c['ids']) or '00000000-0000-0000-0000-000000000000'})").json()
        out["dismissed_left"] = len(left) if isinstance(left, list) else left


def main(slug: str, lines: list[str]) -> None:
    a = As()
    s = state(slug)
    # Stand.tsx: a group's own book has one layer (null), and so has a personal book read in no group; the take goes
    # without ensemble_id and the accept with p_layer null.
    layer = None
    for k, line in enumerate(lines):
        t0 = time.time()
        out = run_line(a, s, line, layer)
        accept_and_dismiss(a, s, out, layer, accept=k == 0)
        s.setdefault("voice", []).append(out)
        step(s, f"voice:{line}", t0, **{k: out.get(k) for k in ("status", "seconds", "handler_s", "cost", "proposed")},
             cards=[(c["kind"], c["body"], c["bars"], c["who"]) for c in out.get("cards", [])], unplaced=len(out.get("unplaced") or []))
        print(json.dumps(out, indent=1, default=str)[:3000])


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2:])
