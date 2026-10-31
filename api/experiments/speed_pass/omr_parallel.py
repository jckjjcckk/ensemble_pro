"""Step 3 of the speed pass: Audiveris on the whole book vs on each page alone in parallel (`omr_box.py --parallel`),
no model call. Both runs go through the app's own `SshBox.transcribe`, `omr_book.load_run` and `omr_score.merge`, and
are compared bar by bar: measure count, the global bar numbering, the movement map, and the notes of every bar
(pitch or rest, duration, per staff), plus the time and key signatures the merged file carries.

    OMR_HOST=yoga uv run python -m experiments.speed_pass.omr_parallel fixtures/pdf/goldberg-bga-p1-5.pdf [--pages 1-5] [--workers 5]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import tempfile
import time
from pathlib import Path

from music21 import meter, key as m21key, note, chord, stream

from app.librarian import omr_convert as oc
from app.librarian.omr_book import load_run
from app.librarian.omr_score import merge, movement_files

from . import ledger

OUT = ledger.HERE / "results" / "omr_parallel"


def bars_of(sc: stream.Score) -> dict[int, list]:
    """Per bar, per staff: the sorted (onset in the bar, pitch or "rest", duration) of every note, so the order voices
    are written in does not count as a difference."""
    out: dict[int, list] = {}
    for si, p in enumerate(sc.parts):
        for m in p.getElementsByClass(stream.Measure):
            ev = []
            for n in m.recurse().notesAndRests:
                off = round(float(n.getOffsetInHierarchy(m)), 3)
                if isinstance(n, chord.Chord):
                    ev += [(off, x.nameWithOctave, float(n.quarterLength)) for x in n.pitches]
                elif isinstance(n, note.Note):
                    ev.append((off, n.nameWithOctave, float(n.quarterLength)))
                else:
                    ev.append((off, "rest", float(n.quarterLength)))
            out.setdefault(m.number, []).append(sorted(ev))
    return out


def sigs(sc: stream.Score) -> dict:
    p = sc.parts[0]
    ts = [(m.number, m.timeSignature.ratioString) for m in p.getElementsByClass(stream.Measure) if m.timeSignature]
    ks = [(m.number, m.keySignature.sharps) for m in p.getElementsByClass(stream.Measure) if m.keySignature]
    return {"time": ts, "key": ks}


async def one(pdf: bytes, pages: list[int] | None, workers: int, tag: str) -> dict:
    os.environ["OMR_PARALLEL_PAGES"] = str(workers)
    box = oc.SshBox(host=os.environ.get("OMR_HOST", "yoga"), root="omr/folio-speed")
    with tempfile.TemporaryDirectory() as tmp:
        t0 = time.perf_counter()
        run = await box.transcribe(f"par-{tag}-{workers}", pdf, pages, Path(tmp))
        wall = time.perf_counter() - t0
        doc = load_run(Path(tmp))
        sc, filled = merge(doc, movement_files(Path(tmp)))
        return {"wall_s": round(wall, 1), "audiveris_s": run.get("audiveris_s"), "box_s": run.get("box_s"), "parallel": run.get("parallel"),
                "movements": [(m["movement"], m["first_number"], m["last_number"], m["bars"]) for m in doc["movements"]],
                "measures": len(doc["measures"]), "numbers": [m["number"] for m in doc["measures"]],
                "per_page": {p["pdf_page"]: sum(1 for m in doc["measures"] if m["page"] == p["page"]) for p in doc["pages"]},
                "systems": len(doc["systems"]), "doubtful": len(doc["doubtful"]), "filled": sorted(filled), "bars": bars_of(sc), "sigs": sigs(sc),
                "texts": sum(1 for i in doc["inters"] if i["tag"] in ("word", "dynamics"))}


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--pages")
    ap.add_argument("--workers", type=int, default=5)
    a = ap.parse_args()
    pages = None
    if a.pages:
        lo, _, hi = a.pages.partition("-")
        pages = list(range(int(lo), int(hi or lo) + 1))
    pdf = Path(a.pdf).read_bytes()
    tag = Path(a.pdf).stem[:20].replace("_", "-")
    whole = await one(pdf, pages, 0, tag)
    par = await one(pdf, pages, a.workers, tag)
    same_bars = [n for n in whole["bars"] if whole["bars"][n] == par["bars"].get(n)]
    diff = [n for n in whole["bars"] if whole["bars"][n] != par["bars"].get(n)]
    report = {"pdf": a.pdf, "pages": pages, "workers": a.workers,
              "whole": {k: v for k, v in whole.items() if k not in ("bars", "numbers")},
              "parallel": {k: v for k, v in par.items() if k not in ("bars", "numbers")},
              "same_measure_count": whole["measures"] == par["measures"], "same_numbering": whole["numbers"] == par["numbers"],
              "bars_identical": len(same_bars), "bars_differ": diff, "of": len(whole["bars"]),
              "diff_detail": {n: {"whole": whole["bars"][n], "parallel": par["bars"].get(n)} for n in diff}}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{tag}.json").write_text(json.dumps(report, indent=1, default=str))
    print(json.dumps(report, indent=1, default=str))


if __name__ == "__main__":
    asyncio.run(main())
