"""Step 2: four variants x 2 runs of the page read on every prepared page, each book read in order as the app does
(parts read on earlier pages go into the next page's prompt; `process_pages.assign_parts` says whether the app would
park on a question). Results per chain in results/runs/<variant>-r<run>-<book>.json (an existing file is not re-run).

  A  today: Messages, effort low, full answer (the app's call)
  B  chat completions, reasoning_effort minimal, full answer
  C  Messages, effort low, trimmed answer (book-level fields only on the book's first page)
  D  chat completions, minimal, trimmed
  E  the app after the speed pass (2026-10-30): B, and a page `process_pages.page_doubts` questions read again as A

    cd api && uv run python -m experiments.pageread_speed.run [--runs 2] [--only A,B] [--books goldberg] [--conc 4]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import random

from app.librarian.labels import PageLabels, _int, canon_part, extract_json, page_landmarks
from app.librarian.process_pages import assign_parts, page_doubts

from . import prompt as P
from .common import BOOKS, RESULTS, call_chat, call_messages, spent

PREP = RESULTS / "prep"
RUNS = RESULTS / "runs"
VARIANTS = {"A": ("messages", "low", False), "B": ("chat", "minimal", False), "C": ("messages", "low", True), "D": ("chat", "minimal", True),
            "E": ("chat", "minimal", False)}


def parse(data: dict, n_boxes: int) -> PageLabels:
    """`labels.label_page`'s parsing, verbatim."""
    out = PageLabels(
        first_measure_number=_int(data.get("first_measure_number"), 1),
        is_pickup=bool(data.get("is_pickup")),
        confidence=str(data.get("confidence") or "low").lower(),
        systems=[{"index": _int(s.get("index"), i + 1), "parts": s.get("parts") or [], "staves_per_part": s.get("staves_per_part") or []}
                 for i, s in enumerate(data.get("systems") or []) if isinstance(s, dict)],
        rehearsal_marks={_int(m.get("provisional_measure"), -1): str(m.get("mark")) for m in (data.get("rehearsal_marks") or []) if isinstance(m, dict)},
        doubtful={_int(m.get("provisional_measure"), -1): str(m.get("reason") or "Spark doubts this bar") for m in (data.get("doubtful_measures") or []) if isinstance(m, dict)},
        title=str(data.get("title") or "").strip().rstrip("."),
        composer=str(data.get("composer") or "").strip().rstrip("."),
        key_signature=(str(data["key_signature"]).strip() or None) if data.get("key_signature") else None,
        time_signature=(str(data["time_signature"]).strip() or None) if data.get("time_signature") else None,
        parts_difficulty={canon_part(p.get("part", "")): max(1, min(5, _int(p.get("difficulty"), 3)))
                          for p in (data.get("parts_difficulty") or []) if isinstance(p, dict) and p.get("part")},
        brief=str(data.get("brief") or "").strip(),
        raw=data,
    )
    out.landmarks, out.landmarks_dropped = page_landmarks(data.get("landmarks"), n_boxes)
    return out


async def chain(variant: str, run: int, book: str) -> None:
    out_f = RUNS / f"{variant}-r{run}-{book}.json"
    if out_f.exists():
        return
    api, effort, trim = VARIANTS[variant]
    kind, _, seeded, _, pages = BOOKS[book]
    hf = PREP / f"{book}-header.json"
    header = json.loads(hf.read_text()) if hf.exists() else None
    known = list(seeded)
    first_page = not seeded
    recs = []
    for pid, _ in pages:
        png = (PREP / f"{pid}.png").read_bytes()
        geo = json.loads((PREP / f"{pid}-geo.json").read_text())
        from app.librarian.labels import annotated_png
        img = annotated_png(png, geo)
        trimmed = trim and not first_page
        prompt = P.build(geo, known, trimmed=trimmed)
        call = call_chat if api == "chat" else call_messages
        tag = f"{variant}-r{run}"
        attempts, labels, err = [], None, None
        for _ in range(2):          # the app's worker retries a malformed answer; here one retry, both charged
            c = await call(prompt, img, effort=effort, tag=tag, uid=pid)
            attempts.append({k: c[k] for k in c if k != "text"} | {"text": c["text"]})
            try:
                labels = parse(extract_json(c["text"]), len(geo["measures"]))
                break
            except Exception as e:  # noqa: BLE001
                err = f"{type(e).__name__}: {e}"
        fallback = None
        if variant == "E" and labels and (why := page_doubts(labels, geo["systems"], known, header)):
            fallback, labels = why, None
            for _ in range(2):
                c = await call_messages(prompt, img, effort="low", tag=f"{tag}-fallback", uid=pid)
                attempts.append({k: c[k] for k in c if k != "text"} | {"text": c["text"], "fallback": True})
                try:
                    labels = parse(extract_json(c["text"]), len(geo["measures"]))
                    break
                except Exception as e:  # noqa: BLE001
                    err = f"{type(e).__name__}: {e}"
        rec = {"page": pid, "kind": kind, "variant": variant, "run": run, "trimmed": trimmed, "first_page": first_page, "fallback": fallback,
               "known_in": list(known), "attempts": attempts, "parse_error": None if labels else err,
               "seconds": sum(a["seconds"] for a in attempts), "usd": sum(a["usd"] for a in attempts),
               "output_tokens": sum(a["output_tokens"] for a in attempts), "input_tokens": sum(a["input_tokens"] for a in attempts),
               "reasoning_tokens": attempts[-1].get("reasoning_tokens"), "n_boxes": len(geo["measures"])}
        if labels:
            parts, why = assign_parts(geo["systems"], labels, known, 1 if first_page else 2, header)
            rec.update(labels=labels.as_dict(), assigned=parts, question=why)
            on_page = list(dict.fromkeys(n for p in parts for n in p["parts"])) if parts else \
                list(dict.fromkeys(canon_part(n) for s in labels.systems for n in (s.get("parts") or [])))
            for n in on_page:            # the app would park on a question; here the read goes on with Spark's names
                if n not in known:
                    known.append(n)
        recs.append(rec)
        first_page = False
        print(f"{variant}-r{run} {pid}: {rec['seconds']:.1f}s out {rec['output_tokens']} ${rec['usd']:.4f}"
              + (f" PARSE {err}" if not labels else "") + (f" Q: {rec.get('question')}" if rec.get("question") else ""), flush=True)
    RUNS.mkdir(parents=True, exist_ok=True)
    out_f.write_text(json.dumps(recs, ensure_ascii=False, indent=1))


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=2)
    ap.add_argument("--only", default="A,B,C,D")
    ap.add_argument("--books", default=",".join(BOOKS))
    ap.add_argument("--conc", type=int, default=4)
    a = ap.parse_args()
    jobs = [(v, r, b) for r in range(1, a.runs + 1) for v in a.only.split(",") for b in a.books.split(",")]
    random.Random(7).shuffle(jobs)      # variants interleaved, so server load falls on all of them alike
    sem = asyncio.Semaphore(a.conc)

    async def go(j):
        async with sem:
            try:
                await chain(*j)
            except SystemExit as e:
                print("STOP", e)
            except Exception as e:  # noqa: BLE001
                print("ERROR", j, type(e).__name__, e)
    await asyncio.gather(*(go(j) for j in jobs))
    print(f"ledger total ${spent():.4f}")


if __name__ == "__main__":
    asyncio.run(main())
