"""Probe: can Muse Spark read the Aria's tempo heading and fingering digits? (Task 2 of the engrave study,
2026-10-28; at most 3 calls, logged in spend.json next to this file.)

The pipeline's B prompt (spark_layers.REREAD_PROMPT) forbids both ("Do NOT include fingering digits ... tempo
headings"), and its crop (pad 4 interlines) cuts the tempo line off. This asks for them on the same kind of crop,
padded 8 interlines on system 1 so the heading is in frame.

Usage: uv run python experiments/engrave/goldberg/text-layer/spark_probe.py RUN_DIR page system [pad]
RUN_DIR is the p1-5 run (model.json, scan/page300-01.png).
"""
import json
import sys
from pathlib import Path

from PIL import Image

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parents[2] / "omr"))
import spark  # noqa: E402
from crops import Cropper, png_bytes  # noqa: E402

SYSTEM = "You are a music engraver reading a scanned page of printed piano music. Answer with strict JSON only, no prose."
PROMPT = """This is one system (treble + bass staff) of a scanned page of printed piano music, 300 dpi{above}. Blue boxes with yellow numbers mark the measures {first}..{last}; the yellow labels and blue boxes are not part of the music.

1. "heading": any tempo or character heading and any metronome mark printed above the first staff (for example "Allegro con brio", "Andante espressivo. (quarter = 72.)"), exactly as printed, one item per heading line, with "x0" = the left edge of its ink and "y" = its vertical centre on a 0-1000 grid over this image ((0,0) top-left, (1000,1000) bottom-right), and "bar" = the yellow number of the first measure it stands over. Empty list if there is none. Do not include the piece title or the composer.
2. "fingering": every fingering numeral (small bold digits 1-5 printed beside noteheads). Digits stacked or printed together for one note (e.g. "54" = finger substitution, or "2" above "1" for a two-note chord) are ONE item with all its digits in printed order, top to bottom or left to right. For each give "digits", "bar" (yellow number), "staff" ("upper" or "lower"), "note_index" = which notehead of that staff in that measure it belongs to, counting noteheads left to right (1-based; a chord counts once; a small grace note counts as its own notehead), "grace" (true if it belongs to a small grace note), and "x", "y" = centre of the digits on the 0-1000 grid.

Return only JSON: {{"heading": [{{"text": "...", "x0": 50, "y": 40, "bar": {first}}}], "fingering": [{{"digits": "3", "bar": {first}, "staff": "upper", "note_index": 1, "grace": false, "x": 120, "y": 100}}]}}"""


def main():
    run, page, system = Path(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3])
    pad = float(sys.argv[4]) if len(sys.argv) > 4 else 4.0
    spark.configure(HERE / "spend.json", 0.10)
    model = json.load(open(run / "model.json"))
    pdf_page = next(p["pdf_page"] for p in model["pages"] if p["page"] == page)
    cr = Cropper(model, page, Image.open(run / "scan" / f"page300-{pdf_page:02d}.png"))
    im, frame = cr.system_crop(system, pad_y=pad)
    nums = [m["number"] for m in model["measures"] if m["page"] == page and m["system"] == system]
    above = ", with the text printed above it" if pad > 4 else ""
    name = f"probe-p{page}-sys{system}"
    im.save(HERE / f"{name}.png")
    ans, usages, raw = spark.ask_json(PROMPT.format(first=nums[0], last=nums[-1], above=above), system=SYSTEM,
                                      image_png=png_bytes(im), tag=name)
    out = {"page": page, "system": system, "pad_interlines": pad, "crop": frame, "numbers": nums,
           "answer": ans, "usages": usages, "raw": raw}
    (HERE / f"{name}.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(ans, indent=1))
    print(usages)


if __name__ == "__main__":
    main()
