"""One book through the real chain, step by step, as the iPad would ask for it. State per book in results/<slug>.json.

    PYTHONPATH=. uv run python -m experiments.e2e_night.book import <slug> <fixture> [--group]
    PYTHONPATH=. uv run python -m experiments.e2e_night.book wait <slug>            # reading / question / ready
    PYTHONPATH=. uv run python -m experiments.e2e_night.book answer <slug> <job_id> '<json body>'
    PYTHONPATH=. uv run python -m experiments.e2e_night.book cut <slug> "Violin I" ["Cello"]
    PYTHONPATH=. uv run python -m experiments.e2e_night.book waitjob <slug> <job_id>
    PYTHONPATH=. uv run python -m experiments.e2e_night.book convert <slug>
    PYTHONPATH=. uv run python -m experiments.e2e_night.book check <slug>
    PYTHONPATH=. uv run python -m experiments.e2e_night.book delete <slug>

Exit 3 means a question is waiting: the question and its payload are printed, and a page image is saved for a
musician's look. Every step appends {step, t0, seconds, ...} to the book's `steps`.
"""
from __future__ import annotations

import io
import json
import subprocess
import sys
import time
from pathlib import Path

from app.db import db

from .common import As, RESULTS, cost_of, group_id, guard, load, now, save, spent, sync_ledger, utcnow

SCRATCH = Path("/private/tmp/claude-501/-Users-ckjiang-Documents-muse/c322debc-0f64-428b-a5ee-2e7fbc0c306c/scratchpad")
POLL = 2.0


def state(slug: str) -> dict:
    s = load(slug)
    if not s:
        sys.exit(f"no book {slug}")
    return s


def step(s: dict, name: str, t0: float, **kw) -> dict:
    row = {"step": name, "at": now(), "seconds": round(time.time() - t0, 1), **kw}
    s.setdefault("steps", []).append(row)
    save(s["slug"], s)
    print(json.dumps(row, default=str))
    return row


def yoga_errors(since_utc: str) -> list[str]:
    """Error lines from the stable API's journal since a UTC time."""
    t = since_utc[:19].replace("T", " ")
    try:
        out = subprocess.run(["ssh", "-o", "ConnectTimeout=20", "yoga", f"journalctl -u folio-api-stable --since '{t} UTC' --no-pager -o cat"],
                             capture_output=True, text=True, timeout=60).stdout
    except Exception as e:  # noqa: BLE001
        return [f"(journal unreadable: {e})"]
    keep = [l for l in out.splitlines() if any(w in l for w in ("Traceback", "ERROR", "Error", "Exception", "failed", "WARNING"))]
    return keep[-40:]


def jobs_of(a: As, score_id: str) -> list[dict]:
    """The book's jobs as the iPad reads them (RLS), plus conversions, which keep the book in the payload only."""
    sel = "id,kind,status,progress,error,score_id,created_at,started_at,finished_at,payload,attempts,question:result->>question,question_payload:result->question_payload"
    own = a.rest("GET", f"jobs?select={sel}&score_id=eq.{score_id}&order=created_at").json()
    conv = a.rest("GET", f"jobs?select={sel}&kind=eq.omr_convert&payload->>score_id=eq.{score_id}&order=created_at").json()
    rows = {r["id"]: r for r in (own if isinstance(own, list) else []) + (conv if isinstance(conv, list) else [])}
    return sorted(rows.values(), key=lambda r: r["created_at"])


def open_question(jobs: list[dict]) -> dict | None:
    resumed = {(j.get("payload") or {}).get("resume_from") for j in jobs}
    for j in jobs:
        if j["status"] == "done" and j.get("question") and j["id"] not in resumed:
            return j
    return None


def save_page_image(a: As, s: dict, page: int, key: str | None = None) -> str | None:
    key = key or next((p for p in s.get("page_paths", []) if p.endswith(f"/{page:03d}.png") or p.endswith(f"-{page}.png") or p.endswith(f"/{page}.png")), None)
    if not key:
        files = a.list_storage(f"{s['score_id']}/pages")
        names = sorted(f["name"] for f in files if f.get("name"))
        s["page_paths"] = [f"{s['score_id']}/pages/{n}" for n in names]
        save(s["slug"], s)
        if 0 < page <= len(names):
            key = s["page_paths"][page - 1]
    if not key:
        return None
    r = a.download(key)
    if r.status_code != 200:
        return None
    out = SCRATCH / "pages" / s["slug"] / f"q-{Path(key).name}"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(r.content)
    return str(out)


def show_question(a: As, s: dict, j: dict) -> None:
    q = j.get("question_payload") or {}
    print("QUESTION", j["id"], j["kind"], "|", j["question"])
    slim = {k: v for k, v in q.items() if k not in ("staff_boxes",)}
    print(json.dumps(slim, default=str)[:3000])
    if q.get("staff_boxes"):
        print("staff_boxes", [(b.get("index"), [round(x) for x in (b.get("box") or b.get("bbox") or [])]) for b in q["staff_boxes"]])
    img = save_page_image(a, s, int(q.get("page") or 1), q.get("page_key") or q.get("image_key"))
    print("page image:", img)


# ---------------------------------------------------------------- steps

def cmd_import(slug: str, fixture: str, group: bool) -> None:
    guard()
    a = As()
    path = Path(fixture)
    data = path.read_bytes()
    pdf = path.suffix.lower() == ".pdf"
    eid = group_id() if group else None
    where = {"ensemble_id": eid, "owner_user_id": None if eid else a.uid}
    t0 = time.time()
    title = path.stem.replace("_", " ").strip() if pdf else ""
    r = a.rest("POST", "scores?select=id", json={**where, "title": title, "folder": "Imported", "status": "uploaded", "created_by": a.uid})
    assert r.status_code == 201, (r.status_code, r.text[:300])
    sid = r.json()[0]["id"]
    s = {"slug": slug, "fixture": str(path), "score_id": sid, "group": bool(eid), "started_utc": utcnow(), "steps": [], "questions": [], "jobs": {}}
    save(slug, s)
    if pdf:
        key = f"{sid}/source.pdf"
        up = a.upload(key, data, "application/pdf")
        assert up.status_code == 200, (up.status_code, up.text[:200])
        src = a.rest("POST", "sources?select=id", json={"score_id": sid, "kind": "pdf", "storage_paths": [key], "meta": {"filename": path.name}, "created_by": a.uid})
        assert src.status_code == 201, (src.status_code, src.text[:300])
        body = {"path": key, "filename": path.name, "kind": "pdf"}
    else:
        # data.tsx importMusicXml: the file goes to source.musicxml whatever its extension (an .mxl too)
        key = f"{sid}/source.musicxml"
        up = a.upload(key, data, "application/vnd.recordare.musicxml+xml")
        assert up.status_code == 200, (up.status_code, up.text[:200])
        body = {"path": key, "filename": path.name}
    up_s = round(time.time() - t0, 1)
    r = a.api("POST", f"/scores/{sid}/import", json=body)
    print("import", r.status_code, r.text[:300])
    assert r.status_code == 200, r.text
    s["import"] = r.json()
    step(s, "import-request", t0, upload_s=up_s, status=r.status_code)
    s["t_import"] = t0
    save(slug, s)
    cmd_wait(slug)


def cmd_wait(slug: str, timeout: float = 1800) -> None:
    """Wait for the reading: ready, failed, or a question."""
    a = As()
    s = state(slug)
    sid = s["score_id"]
    t0 = s.get("t_resume") or s.get("t_import") or time.time()
    last = None
    seen_jobs = set(s["jobs"])
    while time.time() - t0 < timeout:
        sc = a.rest("GET", f"scores?select=id,status,progress,failure_reason,title,composer,pages,key_sig,meter&id=eq.{sid}").json()
        if not sc:
            sys.exit("score gone")
        sc = sc[0]
        jobs = jobs_of(a, sid)
        for j in jobs:
            if j["id"] not in seen_jobs:
                seen_jobs.add(j["id"])
                s["jobs"][j["id"]] = {"kind": j["kind"], "created_at": j["created_at"]}
        state_now = (sc["status"], round(sc.get("progress") or 0, 2), tuple((j["kind"], j["status"]) for j in jobs))
        if state_now != last:
            print(now(), sc["status"], sc.get("progress"), [(j["kind"][:12], j["status"], j.get("attempts")) for j in jobs])
            last = state_now
        q = open_question(jobs)
        if q and q["id"] not in [x["job"] for x in s["questions"]]:
            s["questions"].append({"job": q["id"], "kind": q["kind"], "question": q["question"], "asked_at": now(),
                                   "page": (q.get("question_payload") or {}).get("page")})
            step(s, "question", t0, job=q["id"], kind=q["kind"])
            show_question(a, s, q)
            s["t_waiting_since"] = time.time()
            save(slug, s)
            sys.exit(3)
        if q:
            show_question(a, s, q)
            sys.exit(3)
        if sc["status"] in ("ready", "failed") and not any(j["status"] in ("queued", "running") for j in jobs if j["kind"] in ("import_pdf", "process_pages", "import_musicxml")):
            for j in jobs:
                s["jobs"].setdefault(j["id"], {})["status"] = j["status"]
            s["score"] = sc
            errs = yoga_errors(s["started_utc"])
            step(s, "reading", t0, status=sc["status"], failure=sc.get("failure_reason"), pages=sc.get("pages"), title=sc.get("title"),
                 key=sc.get("key_sig"), meter=sc.get("meter"), questions=len(s["questions"]),
                 cost=cost_of([j["id"] for j in jobs if j["kind"] in ("import_pdf", "process_pages", "import_musicxml")]),
                 job_errors=[j.get("error") for j in jobs if j.get("error")], yoga=errs[-8:])
            s.pop("t_resume", None)
            save(slug, s)
            return
        time.sleep(POLL)
    step(s, "reading-timeout", t0)


def cmd_answer(slug: str, job_id: str, body: str) -> None:
    a = As()
    s = state(slug)
    ans = json.loads(body)
    t0 = time.time()
    r = a.api("POST", f"/jobs/{job_id}/answer", json=ans)
    print("answer", r.status_code, r.text[:300])
    for q in s["questions"]:
        if q["job"] == job_id:
            q["answer"] = ans
            q["answered_at"] = now()
            q["status"] = r.status_code
            q["follow_up"] = r.json().get("id") if r.status_code == 200 else None
    human = time.time() - s.pop("t_waiting_since", time.time())
    s["human_wait_s"] = round(s.get("human_wait_s", 0) + human, 1)
    step(s, "answer", t0, job=job_id, status=r.status_code, human_wait_s=round(human, 1))
    if r.status_code == 200:
        follow = r.json()
        s["jobs"][follow["id"]] = {"kind": follow["kind"], "created_at": follow["created_at"]}
        save(slug, s)
        if follow["kind"] == "process_pages":
            s["t_resume"] = time.time()
            save(slug, s)
            cmd_wait(slug)
        else:
            cmd_waitjob(slug, follow["id"], label=s.get("cut_label", follow["kind"]))


def live_check(a: As, s: dict, path: str, body: dict, first: dict) -> dict:
    """A second request for the same work while the first is live: 409 naming the live job."""
    r = a.api("POST", path, json=body)
    detail = (r.json() if r.headers.get("content-type", "").startswith("application/json") else {}).get("detail")
    ok = r.status_code == 409 and isinstance(detail, dict) and detail.get("job_id") == first["id"]
    return {"status": r.status_code, "detail": detail, "names_live_job": ok}


def cmd_cut(slug: str, instruments: list[str]) -> None:
    guard()
    a = As()
    s = state(slug)
    sid = s["score_id"]
    t0 = time.time()
    body = {"instruments": instruments}
    r = a.api("POST", f"/scores/{sid}/parts", json=body)
    print("cut", r.status_code, r.text[:300])
    label = "cut:" + "+".join(instruments)
    if r.status_code != 200:
        step(s, label, t0, status=r.status_code, error=r.text[:300])
        return
    job = r.json()
    s["jobs"][job["id"]] = {"kind": job["kind"], "created_at": job["created_at"]}
    dup = live_check(a, s, f"/scores/{sid}/parts", body, job) if job["status"] in ("queued", "running") else {"skipped": job["status"]}
    step(s, label + ":request", t0, job=job["id"], kind=job["kind"], status=job["status"], duplicate=dup)
    s["cut_label"] = label
    save(slug, s)
    if job["status"] in ("queued", "running"):
        cmd_waitjob(slug, job["id"], label=label, t0=t0)
    else:
        step(s, label, t0, job=job["id"], final=job["status"], result_keys=sorted((job.get("result") or {}).keys()), error=job.get("error"))


def cmd_waitjob(slug: str, job_id: str, label: str | None = None, t0: float | None = None, timeout: float = 3600) -> None:
    a = As()
    s = state(slug)
    t0 = t0 or time.time()
    label = label or s["jobs"].get(job_id, {}).get("kind", "job")
    last = None
    while time.time() - t0 < timeout:
        j = a.rest("GET", f"jobs?select=id,kind,status,progress,error,attempts,started_at,finished_at,created_at,payload,result&id=eq.{job_id}").json()
        if not j:
            sys.exit("job gone")
        j = j[0]
        res = j.get("result") or {}
        cur = (j["status"], round(j.get("progress") or 0, 2), res.get("phase") if isinstance(res.get("phase"), str) else None)
        if cur != last:
            print(now(), j["kind"], *cur)
            last = cur
        if j["status"] == "done" and res.get("question"):
            q = {"id": j["id"], "kind": j["kind"], "question": res["question"], "question_payload": res.get("question_payload"), "status": "done", "payload": j["payload"]}
            if j["id"] not in [x["job"] for x in s["questions"]]:
                s["questions"].append({"job": j["id"], "kind": j["kind"], "question": res["question"], "asked_at": now(),
                                       "page": (res.get("question_payload") or {}).get("page"), "label": label})
                s["t_waiting_since"] = time.time()
                step(s, label + ":question", t0, job=j["id"])
            show_question(a, s, q)
            save(slug, s)
            sys.exit(3)
        if j["status"] in ("done", "failed"):
            chain = [k for k, v in s["jobs"].items() if v.get("kind") == j["kind"]]
            slim = {k: v for k, v in res.items() if k not in ("agent", "log", "items", "transcript_raw")}
            step(s, label, t0, job=job_id, final=j["status"], error=j.get("error"), attempts=j.get("attempts"),
                 started_at=j.get("started_at"), finished_at=j.get("finished_at"), cost=cost_of([job_id]), chain_cost=cost_of(chain),
                 result=json.loads(json.dumps(slim, default=str)[:4000]) if len(json.dumps(slim, default=str)) <= 4000 else {k: slim[k] for k in list(slim)[:25] if len(json.dumps(slim[k], default=str)) < 600},
                 yoga=yoga_errors(j.get("started_at") or s["started_utc"])[-8:])
            return
        time.sleep(POLL)
    step(s, (label or "job") + ":timeout", t0, job=job_id)


def cmd_convert(slug: str) -> None:
    guard()
    a = As()
    s = state(slug)
    sid = s["score_id"]
    t0 = time.time()
    r = a.api("POST", f"/scores/{sid}/convert", json={})
    print("convert", r.status_code, r.text[:300])
    if r.status_code != 200:
        step(s, "convert:request", t0, status=r.status_code, error=r.text[:300])
        return
    job = r.json()
    s["jobs"][job["id"]] = {"kind": job["kind"], "created_at": job["created_at"]}
    dup = live_check(a, s, f"/scores/{sid}/convert", {}, job)
    step(s, "convert:request", t0, job=job["id"], status=job["status"], duplicate=dup)
    cmd_waitjob(slug, job["id"], label="convert", t0=t0)


def cmd_check(slug: str) -> None:
    """Playback files, bar map, landmarks, label memory, measures, per-page bars, parts."""
    from music21 import midi as m21midi

    a = As()
    s = state(slug)
    sid = s["score_id"]
    t0 = time.time()
    sc = a.rest("GET", f"scores?select=id,title,composer,status,pages,key_sig,meter,landmarks,label_memory,playback,current_interpretation_id&id=eq.{sid}").json()[0]
    parts = a.rest("GET", f"parts?select=name,position,storage_path&score_id=eq.{sid}&order=position").json()
    measures = a.rest("GET", f"measures?select=number&score_id=eq.{sid}&order=number&limit=5000").json()
    numbers = [m["number"] for m in measures]
    out: dict = {"title": sc.get("title"), "composer": sc.get("composer"), "key": sc.get("key_sig"), "meter": sc.get("meter"), "pages": sc.get("pages"),
                 "parts": [p["name"] for p in parts], "measures": len(numbers), "bar_first": numbers[0] if numbers else None, "bar_last": numbers[-1] if numbers else None}
    lm = sc.get("landmarks")
    out["landmarks"] = {"n": len(lm) if isinstance(lm, list) else (len(lm.get("items", [])) if isinstance(lm, dict) else 0),
                        "sample": (lm if isinstance(lm, list) else (lm or {}).get("items", []))[:6] if lm else None,
                        "sources": sorted({x.get("source") for x in (lm if isinstance(lm, list) else (lm or {}).get("items", [])) if isinstance(x, dict)}) if lm else []}
    mem = sc.get("label_memory")
    out["label_memory"] = {"n": len((mem or {}).get("labels", mem or {})) if isinstance(mem, dict) else (len(mem) if isinstance(mem, list) else 0),
                           "raw": json.dumps(mem, default=str)[:600] if mem else None}
    # bars per page from the current interpretation
    interp = sc.get("current_interpretation_id")
    if interp:
        pl = a.rest("GET", f"measure_placements?select=page,system,measures(number)&interpretation_id=eq.{interp}&limit=10000").json()
        per: dict[int, list[int]] = {}
        for p in pl if isinstance(pl, list) else []:
            if p.get("measures"):
                per.setdefault(p["page"], []).append(p["measures"]["number"])
        out["bars_per_page"] = {str(k): {"n": len(v), "first": min(v), "last": max(v)} for k, v in sorted(per.items())}
    pb = sc.get("playback")
    out["playback_row"] = pb
    if pb:
        mid_key = pb.get("midi") or f"{sid}/playback/score.mid"
        bars_key = pb.get("bar_map") or f"{sid}/playback/bars.json"
        m = a.download(mid_key)
        b = a.download(bars_key)
        out["midi_status"], out["bars_status"] = m.status_code, b.status_code
        if m.status_code == 200:
            mf = m21midi.MidiFile()
            mf.readstr(m.content)
            names = []
            for tr in mf.tracks:
                nm = next((ev.data.decode("utf-8", "replace") if isinstance(ev.data, bytes) else str(ev.data) for ev in tr.events if ev.type == m21midi.MetaEvents.SEQUENCE_TRACK_NAME), None)
                notes = sum(1 for ev in tr.events if ev.type == m21midi.ChannelVoiceMessages.NOTE_ON and (ev.velocity or 0) > 0)
                names.append((nm, notes))
            out["midi_format"] = mf.format
            out["midi_tracks"] = names
            out["midi_part_tracks"] = sum(1 for _, n in names if n > 0)
        if b.status_code == 200:
            bj = b.json()
            bar_nums = [x["bar"] for x in bj.get("bars", [])]
            out["bars_json"] = {"parts": bj.get("parts"), "n": len(bar_nums), "first": bar_nums[0] if bar_nums else None,
                                "last": bar_nums[-1] if bar_nums else None, "tempos": bj.get("tempos", [])[:3], "meters": len(bj.get("meters", []))}
            missing = sorted(set(numbers) - set(bar_nums))
            extra = sorted(set(bar_nums) - set(numbers))
            out["bar_map_missing"] = missing[:30]
            out["bar_map_missing_n"] = len(missing)
            out["bar_map_extra_n"] = len(extra)
            out["bar_map_extra"] = extra[:30]
    srcs = a.rest("GET", f"sources?select=id,kind,storage_paths,meta&score_id=eq.{sid}").json()
    out["sources"] = [(x["kind"], (x.get("meta") or {}).get("transcribed_from") is not None, (x.get("meta") or {}).get("split_from") is not None or bool((x.get("meta") or {}).get("instruments"))) for x in srcs]
    s["check"] = out
    step(s, "check", t0, **{k: out[k] for k in ("measures", "parts", "pages") if k in out},
         landmarks=out["landmarks"]["n"], label_memory=out["label_memory"]["n"], midi_part_tracks=out.get("midi_part_tracks"),
         bar_map_missing=out.get("bar_map_missing_n"))
    print(json.dumps(out, indent=1, default=str)[:6000])


def cmd_delete(slug: str) -> None:
    a = As()
    s = state(slug)
    sid = s["score_id"]
    added = sync_ledger(a.uid, slug, s["started_utc"])
    t0 = time.time()
    r = a.rest("DELETE", f"scores?id=eq.{sid}", headers={"Prefer": "count=exact"})
    cnt = r.headers.get("content-range")
    left = {t: len(db().table(t).select("id").eq("score_id", sid).execute().data or []) for t in ("jobs", "sources", "parts", "measures", "annotations", "interpretations")}
    step(s, "delete", t0, status=r.status_code, content_range=cnt, children_left=left, ledger_added=round(added, 4))


def cmd_sync(slug: str) -> None:
    a = As()
    s = state(slug)
    added = sync_ledger(a.uid, slug, s["started_utc"])
    print(f"ledger +{added:.4f} -> {spent():.4f}")


if __name__ == "__main__":
    cmd, *args = sys.argv[1:]
    if cmd == "import":
        cmd_import(args[0], args[1], "--group" in args)
    elif cmd == "wait":
        cmd_wait(args[0])
    elif cmd == "answer":
        cmd_answer(args[0], args[1], args[2])
    elif cmd == "cut":
        cmd_cut(args[0], args[1:])
    elif cmd == "waitjob":
        cmd_waitjob(args[0], args[1])
    elif cmd == "convert":
        cmd_convert(args[0])
    elif cmd == "check":
        cmd_check(args[0])
    elif cmd == "delete":
        cmd_delete(args[0])
    elif cmd == "sync":
        cmd_sync(args[0])
    elif cmd != "names":
        sys.exit(__doc__)


def picker_names(slug: str) -> list[str]:
    """The names `PickerForm` offers (data.tsx headersOf): the latest reading's header, else its parts, else parts rows."""
    a = As()
    s = state(slug)
    rows = a.rest("GET", f"interpretations?select=created_at,header:params->state->header->instruments,summary_header:summary->header->instruments,summary_parts:summary->parts&score_id=eq.{s['score_id']}&order=created_at").json()
    out: list[str] = []
    for r in rows:
        for xs in (r.get("header"), r.get("summary_header"), r.get("summary_parts")):
            names = [str(x if isinstance(x, str) else (x or {}).get("name") or (x or {}).get("label") or "").strip().rstrip(".") for x in (xs or [])]
            names = [n for n in names if n]
            if names:
                out = names
                break
    return out


if __name__ == "__main__" and sys.argv[1] == "names":
    print(json.dumps(picker_names(sys.argv[2]), ensure_ascii=False))
