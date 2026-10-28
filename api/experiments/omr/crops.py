"""Crops from the 300 dpi scan using Audiveris's own pixel bounds (model.json from audiveris_model.py).

  system_crop(page, system)  one system, every bar boxed and labelled with its GLOBAL number (the labelling
                             trick from the grounding experiment), plus the crop frame text_place needs
  symbol_crop(inter)         a context window around one doubtful symbol, boxed in red
"""

from __future__ import annotations

import io

from PIL import Image, ImageDraw, ImageFont


def _font(size: int):
    for cand in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/System/Library/Fonts/Helvetica.ttc"):
        try:
            return ImageFont.truetype(cand, size)
        except OSError:
            continue
    return ImageFont.load_default()


def png_bytes(im: Image.Image) -> bytes:
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


class Cropper:
    def __init__(self, model: dict, page: int, scan: Image.Image):
        self.model = model
        self.page_no = page
        self.page = scan.convert("RGB")
        self.il = next(p["interline"] for p in model["pages"] if p["page"] == page)
        self.measures = [m for m in model["measures"] if m["page"] == page]
        self.systems = {s["system"]: s for s in model["systems"] if s["page"] == page}

    def system_crop(self, system: int, pad_y: float = 4.0, number: bool = True) -> tuple[Image.Image, dict]:
        s = self.systems[system]
        py = int(pad_y * self.il)
        x0, x1 = max(0, s["left"] - 2 * self.il), min(self.page.width, s["right"] + self.il)
        y0, y1 = max(0, int(s["top"]) - py), min(self.page.height, int(s["bottom"]) + py)
        im = self.page.crop((x0, y0, x1, y1))
        d = ImageDraw.Draw(im)
        font = _font(int(1.6 * self.il))
        for m in self.measures:
            if m["system"] != system or not number:
                continue
            l, t, r, b = m["px"]
            bx = (l - x0, int(t) - y0 - 3, r - x0, int(b) - y0 + 3)
            d.rectangle(bx, outline=(0, 90, 220), width=2)
            label = str(m["number"])
            tw = d.textlength(label, font=font)
            lx, ly = bx[0] + 4, bx[1] - int(1.8 * self.il)
            d.rectangle((lx - 3, ly - 2, lx + tw + 3, ly + int(1.7 * self.il)), fill=(255, 230, 0))
            d.text((lx, ly), label, fill=(0, 0, 0), font=font)
        return im, {"origin": [x0, y0], "size": [x1 - x0, y1 - y0]}

    def symbol_crop(self, inter: dict, ctx: float = 6.0) -> Image.Image:
        x, y, w, h = inter["bounds"]
        c = int(ctx * self.il)
        x0, y0 = max(0, x - c), max(0, y - c)
        x1, y1 = min(self.page.width, x + w + c), min(self.page.height, y + h + c)
        im = self.page.crop((x0, y0, x1, y1))
        ImageDraw.Draw(im).rectangle((x - x0 - 3, y - y0 - 3, x + w - x0 + 3, y + h - y0 + 3), outline=(220, 0, 0), width=3)
        return im
