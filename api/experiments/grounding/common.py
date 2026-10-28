"""Shared helpers for the grounding experiment.

Plain scripts, run from `api/` with `uv run experiments/grounding/<script>.py`.
Each script declares its own dependencies with PEP 723 inline metadata, so the
main project's pyproject stays untouched.
"""

from __future__ import annotations

import base64
import json
import os
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
PAGES = HERE / "pages"
OUT = HERE / "out"
OUT.mkdir(exist_ok=True)

PAGE_NAMES = ["goldberg-bga-p01", "rach1-2pf-gutheil-p03"]

# Piano-cut experiment: which score. `--score <stem>` on the command line or PIANO_CUT_SCORE=<stem>; the
# default (Rach 1 Gutheil) keeps the original layout, out/piano-cut/; any other score writes to
# out/piano-cut/<stem>/ and reads fixtures/pdf/<stem>.pdf.
PIANO_CUT_DEFAULT = "rach1-fullscore-gutheil-1919"
PIANO_CUT_TITLES = {
    "rach1-fullscore-gutheil-1919": "Rachmaninoff, Piano Concerto No. 1, 1919 Gutheil edition",
    "rach2-fullscore-imslp03631": "Rachmaninoff, Piano Concerto No. 2",
    "beethoven-pc3-fullscore-imslp977417": "Beethoven, Piano Concerto No. 3",
    "beethoven-pc5-fullscore-imslp977419": "Beethoven, Piano Concerto No. 5",
}


def piano_cut_score() -> str:
    """Score stem from `--score X` (removed from sys.argv so the scripts' own parsers never see it) or the env."""
    import sys

    argv = sys.argv
    if "--score" in argv:
        i = argv.index("--score")
        os.environ["PIANO_CUT_SCORE"] = argv[i + 1]
        del argv[i : i + 2]
    return os.environ.get("PIANO_CUT_SCORE", PIANO_CUT_DEFAULT)


PIANO_CUT_SCORE = piano_cut_score()
PIANO_CUT_PDF = HERE.parent.parent / "fixtures" / "pdf" / f"{PIANO_CUT_SCORE}.pdf"
PIANO_CUT_OUT = OUT / "piano-cut" / ("" if PIANO_CUT_SCORE == PIANO_CUT_DEFAULT else PIANO_CUT_SCORE)
PIANO_CUT_TITLE = PIANO_CUT_TITLES.get(PIANO_CUT_SCORE, PIANO_CUT_SCORE)

# Which instrument to cut: `--instrument "Violin I"` on any script's command line (removed from sys.argv like
# --score) or PIANO_CUT_INSTRUMENT=. The score folder keeps what does not depend on the instrument (pages,
# geometry, overlays, header.json, spend.json); the default "Piano (solo)" keeps writing its labels, crops and
# results there too (the existing layout), any other instrument gets out/piano-cut/<stem>/<instrument-slug>/.
PIANO_CUT_DEFAULT_INSTRUMENT = "Piano (solo)"


def piano_cut_instrument() -> str:
    import sys

    argv = sys.argv
    if "--instrument" in argv:
        i = argv.index("--instrument")
        os.environ["PIANO_CUT_INSTRUMENT"] = argv[i + 1]
        del argv[i : i + 2]
    return os.environ.get("PIANO_CUT_INSTRUMENT", PIANO_CUT_DEFAULT_INSTRUMENT)


def instrument_slug(name: str) -> str:
    import re

    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


PIANO_CUT_INSTRUMENT = piano_cut_instrument()
PIANO_CUT_RUN = PIANO_CUT_OUT / ("" if PIANO_CUT_INSTRUMENT == PIANO_CUT_DEFAULT_INSTRUMENT else instrument_slug(PIANO_CUT_INSTRUMENT))

# Prices from dev.meta.ai pricing page (see README for the values and date).
PRICE = {
    "muse-spark-1.3": {"input_per_m": 1.25, "output_per_m": 4.25},  # dev.meta.ai pricing, 2026-10-27
    "sam-3.1": {"per_image": 0.0025},  # $2.50 / 1k images
}


def load_env() -> None:
    """Load api/.env into os.environ without overriding existing variables."""
    env = HERE.parent.parent / ".env"
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def client():
    import httpx

    load_env()
    base = os.environ.get("META_API_BASE_URL", "https://api.meta.ai/v1").rstrip("/")
    key = os.environ["META_API_KEY"]
    return httpx.Client(
        base_url=base,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        timeout=httpx.Timeout(600.0, connect=30.0),
    )


def image_data_url(path: Path) -> str:
    mime = "image/png" if path.suffix == ".png" else "image/jpeg"
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"


def image_size(path: Path) -> tuple[int, int]:
    from PIL import Image

    with Image.open(path) as im:
        return im.width, im.height


def responses(c, body: dict) -> tuple[dict, float]:
    """POST /responses, return (json, seconds)."""
    t0 = time.perf_counter()
    r = c.post("/responses", json=body)
    dt = time.perf_counter() - t0
    if r.status_code != 200:
        raise RuntimeError(f"{r.status_code}: {r.text[:2000]}")
    return r.json(), dt


def output_text(resp: dict) -> str:
    parts = []
    for o in resp.get("output", []):
        if o.get("type") == "message":
            for cpart in o.get("content", []):
                if cpart.get("type") == "output_text":
                    parts.append(cpart.get("text") or "")
    return "".join(parts)


def dump(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False))
