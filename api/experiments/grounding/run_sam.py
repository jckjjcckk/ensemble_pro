# /// script
# requires-python = ">=3.12"
# dependencies = ["httpx", "pillow", "numpy", "meta-sam-parser"]
# ///
"""SAM 3.1 through the Meta Model API: page and staff masks via text prompts.

Usage (from api/):  uv run experiments/grounding/run_sam.py [prompt ...]
Writes out/sam-<page>-<prompt>.json (raw response + parsed boxes) and
out/sam-<page>-<prompt>.png (boxes and masks drawn on the page).
"""

from __future__ import annotations

import re
import sys
import time

import numpy as np
from PIL import Image, ImageDraw

from common import OUT, PAGE_NAMES, PAGES, client, dump, image_data_url, output_text, responses

DEFAULT_PROMPTS = ["sheet of paper", "staff", "musical staff", "sheet music", "staff lines", "measure", "bar line"]

BOX_RE = re.compile(r"<\|box;x1=(\d+);y1=(\d+);x2=(\d+);y2=(\d+);w=(\d+);h=(\d+)(?:;c=([0-9.]+))?\|>")


def parse_boxes(text: str) -> list[dict]:
    boxes = []
    for m in BOX_RE.finditer(text):
        x1, y1, x2, y2, w, h = (int(v) for v in m.groups()[:6])
        c = float(m.group(7)) if m.group(7) else None
        boxes.append({"x1": x1, "y1": y1, "x2": x2, "y2": y2, "img_w": w, "img_h": h, "confidence": c})
    return boxes


def decode_masks(text: str) -> list[np.ndarray]:
    """Decode masks with meta-sam-parser; returns list of (H, W) uint8 arrays, or [] if unavailable."""
    try:
        from meta_sam_parser import CompletedOutcome, decode_mask_to_raster, image_segmentation_format
    except Exception as e:  # pragma: no cover
        print("meta_sam_parser unavailable:", e)
        return []
    parser = image_segmentation_format().create_parser()
    for _ in parser.push(text):
        pass
    finished = parser.finish(CompletedOutcome())
    masks = []
    for rec in getattr(finished.result, "records", []) or []:
        mask = getattr(rec, "mask", None)
        if mask is None:
            continue
        try:
            raster = decode_mask_to_raster(mask)
            arr = np.frombuffer(raster, dtype=np.uint8).reshape(mask.height, mask.width)
            masks.append(arr)
        except Exception as e:
            print("mask decode failed:", e)
    return masks


def draw(page_png, boxes, masks, out_png):
    im = Image.open(page_png).convert("RGB")
    overlay = Image.new("RGBA", im.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    colors = [(255, 0, 0), (0, 160, 0), (0, 0, 255), (200, 120, 0), (150, 0, 150), (0, 150, 150)]
    for i, b in enumerate(boxes):
        col = colors[i % len(colors)]
        if i < len(masks):
            m = masks[i]
            mi = Image.fromarray((m * 110).astype(np.uint8)).resize((b["x2"] - b["x1"] + 1, b["y2"] - b["y1"] + 1))
            tint = Image.new("RGBA", mi.size, col + (0,))
            tint.putalpha(mi)
            overlay.alpha_composite(tint, (b["x1"], b["y1"]))
        d.rectangle([b["x1"], b["y1"], b["x2"], b["y2"]], outline=col + (255,), width=3)
        d.text((b["x1"] + 4, b["y1"] + 4), str(i), fill=col + (255,))
    Image.alpha_composite(im.convert("RGBA"), overlay).convert("RGB").save(out_png)


def main(prompts: list[str]):
    c = client()
    summary = []
    for page in PAGE_NAMES:
        png = PAGES / f"{page}.png"
        data_url = image_data_url(png)
        for prompt in prompts:
            body = {
                "model": "sam-3.1",
                "metadata": {"include_confidence": "true"},
                "input": [{"type": "message", "role": "user", "content": [
                    {"type": "input_text", "text": prompt},
                    {"type": "input_image", "image_url": data_url},
                ]}],
            }
            resp, dt = responses(c, body)
            text = output_text(resp)
            boxes = parse_boxes(text)
            masks = decode_masks(text) if boxes else []
            slug = prompt.replace(" ", "_")
            dump(OUT / f"sam-{page}-{slug}.json", {"page": page, "prompt": prompt, "latency_s": round(dt, 2),
                                                   "usage": resp.get("usage"), "boxes": boxes, "raw_text_head": text[:400],
                                                   "mask_count": len(masks)})
            if boxes:
                draw(png, boxes, masks, OUT / f"sam-{page}-{slug}.png")
            row = {"page": page, "prompt": prompt, "n_boxes": len(boxes), "n_masks": len(masks), "latency_s": round(dt, 2),
                   "boxes": [(b["x1"], b["y1"], b["x2"], b["y2"], b["confidence"]) for b in boxes]}
            print(row)
            summary.append(row)
    dump(OUT / "sam-summary.json", summary)


if __name__ == "__main__":
    main(sys.argv[1:] or DEFAULT_PROMPTS)
