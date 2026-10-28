"""OMR engines on the OMR box (ssh alias `omr`, feature 005). Engines are separate processes (AGPL): Folio's
code never imports them. Notes are the engines' job only; no model is asked about notes.

  audiveris   Audiveris 5.11 batch transcribe + export of one page PNG, Tesseract OCR (TESSDATA_PREFIX set);
              the MusicXML comes back and is scored per bar against the Open Goldberg ground truth.
  homr        stub (studied and rejected for now in 005; wire `run_homr` when it is wanted).
"""

from __future__ import annotations

import shlex
import subprocess
import time
from collections import Counter
from fractions import Fraction
from pathlib import Path
from typing import Any

HOST = "omr"
REMOTE = "omr/bench"  # relative to the box's home
AUDIVERIS = "~/.local/bin/audiveris"
TESSDATA = "$HOME/omr/tessdata"
BOX_PDFS = "~/muse/api/fixtures/pdf"
ENGINES = ("audiveris", "homr")


class EngineStub(NotImplementedError):
    pass


def _ssh(cmd: str, timeout: int) -> subprocess.CompletedProcess:
    return subprocess.run(["ssh", "-o", "BatchMode=yes", HOST, cmd], capture_output=True, text=True, timeout=timeout)


def run_audiveris(png: Path | None, key: str, out_dir: Path, timeout: int = 600, pdf: tuple[str, int] | None = None) -> dict[str, Any]:
    """Upload, transcribe, fetch every exported .mxl. Returns status ok/error, wall seconds on the box, files.
    `pdf` = (file name in the box's ~/muse/api/fixtures/pdf, page): Audiveris rasterises the PDF page itself
    (how 005 ran it) instead of reading our PNG."""
    rdir = f"{REMOTE}/{key}"
    t0 = time.perf_counter()
    _ssh(f"rm -rf {shlex.quote(rdir)} && mkdir -p {shlex.quote(rdir)}", 60).check_returncode()
    if pdf:
        src = f"-sheets {int(pdf[1])} -output out {BOX_PDFS}/{shlex.quote(pdf[0])}"
    else:
        subprocess.run(["scp", "-q", "-o", "BatchMode=yes", str(png), f"{HOST}:{rdir}/page.png"], check=True, timeout=120)
        src = "-output out page.png"
    r = _ssh(f"cd {shlex.quote(rdir)} && start=$(date +%s.%N) && TESSDATA_PREFIX={TESSDATA} {AUDIVERIS} -batch -transcribe -export "
             f"{src} > run.log 2>&1; rc=$?; end=$(date +%s.%N); echo rc=$rc secs=$(echo \"$end - $start\" | bc); "
             f"ls out/*.mxl 2>/dev/null; grep -E 'WARN|Exception' run.log | head -5", timeout)
    lines = r.stdout.splitlines()
    head = dict(kv.split("=", 1) for kv in (lines[0].split() if lines else []) if "=" in kv)
    mxls = [ln.strip() for ln in lines[1:] if ln.strip().endswith(".mxl")]
    warns = [ln for ln in lines[1:] if not ln.strip().endswith(".mxl")]
    out_dir.mkdir(parents=True, exist_ok=True)
    local = []
    for m in mxls:
        dst = out_dir / Path(m).name
        subprocess.run(["scp", "-q", "-o", "BatchMode=yes", f"{HOST}:{rdir}/{m}", str(dst)], check=True, timeout=120)
        local.append(str(dst))
    return {"status": "ok" if head.get("rc") == "0" and local else "error", "engine_s": float(head.get("secs") or 0),
            "wall_s": round(time.perf_counter() - t0, 1), "files": local, "warnings": warns[:5]}


def run_homr(png: Path | None, key: str, out_dir: Path, pdf: tuple[str, int] | None = None) -> dict[str, Any]:
    raise EngineStub("homr is a stub in the benchmark (005: studied and rejected for now)")


def run_engine(engine: str, png: Path | None, key: str, out_dir: Path, pdf: tuple[str, int] | None = None) -> dict[str, Any]:
    if engine == "audiveris":
        return run_audiveris(png, key, out_dir, pdf=pdf)
    if engine == "homr":
        return run_homr(png, key, out_dir, pdf=pdf)
    raise ValueError(f"unknown engine {engine}")


def mxl_bars(path: str) -> dict[int, dict[str, Counter]]:
    """bar -> {"pitch", "onset_pitch"} over every part (staves merged), skipping grace notes and tie continuations
    (005's compare.py)."""
    from music21 import chord, converter, note, stream

    sc = converter.parse(path)
    out: dict[int, dict[str, Counter]] = {}
    for part in sc.parts:
        for m in part.getElementsByClass(stream.Measure):
            b = out.setdefault(int(m.number), {"pitch": Counter(), "onset_pitch": Counter()})
            for v in (list(m.voices) or [m]):
                for el in v.notesAndRests:
                    if el.duration.isGrace:
                        continue
                    ns = el.notes if isinstance(el, chord.Chord) else ([el] if isinstance(el, note.Note) else [])
                    for n in ns:
                        if n.tie is not None and n.tie.type in ("stop", "continue"):
                            continue
                        b["pitch"][n.pitch.midi] += 1
                        b["onset_pitch"][(Fraction(el.offset), n.pitch.midi)] += 1
    return out
