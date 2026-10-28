"""cut.py on synthetic pages: the page-edge shadow mask, the working scale and the lyric text-line rule."""
from __future__ import annotations

import numpy as np
from PIL import Image

from app.librarian import cut

PAPER, INK, SHADOW = 230, 20, 55


def draw_staff(page: np.ndarray, y_top: int, sp: int, x0: int, x1: int, thick: int = 2) -> dict:
    lines = [y_top + k * sp for k in range(5)]
    for y in lines:
        page[y: y + thick, x0: x1 + 1] = INK
    return {"y_top": lines[0], "y_bottom": lines[-1], "lines": lines, "spacing": float(sp), "x0": x0, "x1": x1}


def blank(w: int = 800, h: int = 1000) -> np.ndarray:
    return np.full((h, w), PAPER, dtype=np.uint8)


def png_bytes(page: np.ndarray) -> bytes:
    return cut.to_png(Image.fromarray(page))


# ---------------------------------------------------------------- page-edge shadows

def test_mask_page_edges_finds_book_shadows_and_leaves_staves_alone():
    page = blank()
    staves = [draw_staff(page, 200 + 110 * k, 7, 120, 700) for k in range(6)]
    # solid dark bands at the top, bottom and left edges with a blurred rim, as on the Beethoven 9 scan
    page[:60, :] = SHADOW
    page[-60:, :] = SHADOW
    page[:, :70] = SHADOW
    for k, v in enumerate((90, 120, 150, 180)):  # 4-px fade rows under the top band
        page[60 + k, :] = v
    # a printed rule near the right edge is thin: not a shadow
    page[:, 790:792] = INK
    mask, report = cut.mask_page_edges(page)
    assert report["top"]["shadow"] and report["bottom"]["shadow"] and report["left"]["shadow"]
    assert not report["right"]["shadow"]
    assert mask[:64, 400].all() and mask[-60:, 400].all() and mask[500, :70].all()
    assert not mask[500, 790]
    for s in staves:  # nothing of the staves is masked
        assert not mask[s["y_top"]: s["y_bottom"] + 1, s["x0"]: s["x1"]].any()
    gray, bw, info = cut.prepare_page(page)
    assert info["scale"] == 1
    assert not bw[:64, :].any() and not bw[:, :70].any()
    found = cut.find_staves(bw)
    assert len(found) == 6
    assert [s["y_top"] for s in found] == [s["y_top"] for s in staves]


def test_unmasked_shadow_rows_would_fake_a_staff_and_the_geometry_drops_it():
    page = blank()
    for k in range(4):
        draw_staff(page, 300 + 110 * k, 7, 120, 700)
    page[:50, :] = SHADOW
    # the band's blurred rim: a gradient back to paper over 25 rows, which the adaptive threshold turns into
    # dark rows at roughly the staff spacing (what fooled find_staves on the Beethoven 9 scan)
    for k in range(25):
        page[50 + k, :] = 70 + k * 6
    gray, bw, info = cut.prepare_page(page)
    assert info["edge_shadows"]["top"]["shadow"]
    assert info["edge_shadows"]["top"]["masked_px"] >= 70, "the rim is masked with the band"
    assert not bw[:70, :].any()
    assert len(cut.find_staves(bw)) == 4
    geom, _, _ = cut.page_geometry(png_bytes(page))
    assert len(geom["staves"]) == 4 and geom["prepare"]["edge_shadows"]["top"]["shadow"]


# ---------------------------------------------------------------- working scale

def test_working_scale_upscales_when_the_spacing_is_under_the_floor():
    small = blank(600, 700)
    for k in range(5):
        draw_staff(small, 100 + 70 * k, 4, 80, 520, thick=1)  # 4-px spacing: under SPACING_MIN
    scale, sp = cut.working_scale(cut.binarise(small))
    assert sp is not None and sp < cut.SPACING_MIN and scale == 2
    geom, bw, page = cut.page_geometry(png_bytes(small))
    assert geom["prepare"]["scale"] == 2 and geom["prepare"]["native_px"] == [600, 700]
    assert geom["image_px"] == [1200, 1400] and bw.shape == (1400, 1200) and page.size == (1200, 1400)
    assert len(geom["staves"]) == 5
    assert all(7.5 <= s["spacing"] <= 8.5 for s in geom["staves"])


def test_working_scale_leaves_the_tuned_spacing_alone():
    page = blank()
    for k in range(5):
        draw_staff(page, 100 + 110 * k, 7, 120, 700)
    scale, sp = cut.working_scale(cut.binarise(page))
    assert scale == 1 and sp == 7.0
    geom, _, _ = cut.page_geometry(png_bytes(page))
    assert geom["prepare"]["scale"] == 1 and geom["image_px"] == [800, 1000]


# ---------------------------------------------------------------- lyrics

def lyric_fixture(sp: int = 7, scratch: bool = False):
    """Two single staves 10 spaces apart; a text row 2 spaces under the upper staff (its lyrics) and a text row
    2 spaces above the lower staff (in the lower half of the gap). Returns (bw, page, geom, system, rows)."""
    page = blank(900, 400)
    upper = draw_staff(page, 100, sp, 100, 800)
    lower = draw_staff(page, upper["y_bottom"] + 10 * sp, sp, 100, 800)
    upper["index"], lower["index"] = 1, 2

    def text_row(y: int) -> list[tuple[int, int]]:
        xs = []
        for x in range(200, 760, 90):  # "words": 6-px tall blocks 24 px wide, a bar apart
            page[y: y + 6, x: x + 24] = INK
            page[y + 2: y + 4, x + 8: x + 16] = PAPER  # a hole, so the fill is text-like rather than solid
            xs.append((x, x + 23))
        return xs

    own_y = upper["y_bottom"] + 2 * sp
    neigh_y = lower["y_top"] - 2 * sp - 6
    own = text_row(own_y)
    neigh = text_row(neigh_y)
    if scratch:  # a 1-px scratch from under the second word down to the lower staff, as on B9 p175 "Brü"
        x0, x1 = own[1]
        for k in range(lower["y_top"] - (own_y + 6)):
            page[own_y + 6 + k, x0 + 10 - k // 3] = INK
    bw = cut.binarise(page)
    rgb = Image.fromarray(page).convert("RGB")
    geom = {"image_px": [900, 400], "staves": [upper, lower],
            "systems": [{"index": 1, "staff_indices": [1, 2], "box": {"x0": 100, "y0": 90, "x1": 800, "y1": lower["y_bottom"] + 10},
                         "barlines": [], "n_measures": 1}]}
    return bw, rgb, geom, geom["systems"][0], {"own": (own_y, own), "neigh": (neigh_y, neigh)}


def ink_at(crop: Image.Image, box: dict, y: int, x_ranges: list[tuple[int, int]]) -> list[bool]:
    arr = np.array(crop.convert("L"))
    out = []
    for x0, x1 in x_ranges:
        yy = y + 3 - box["y0"]
        out.append(bool(0 <= yy < arr.shape[0] and (arr[yy, x0 - box["x0"]: x1 + 1 - box["x0"]] < 128).any()))
    return out


def test_voice_keeps_its_own_text_line_whole_and_erases_the_lower_half_line():
    bw, page, geom, system, rows = lyric_fixture()
    crop, box, stats = cut.clean_crop(bw, page, geom, system, [1], voice=True)
    classes = {l["class"] for l in stats["lyric_lines"]}
    assert classes == {"lyric", "lyric-neighbour"}
    own_y, own = rows["own"]
    neigh_y, neigh = rows["neigh"]
    assert all(ink_at(crop, box, own_y, own)), "every word of the lyric line survives"
    assert not any(ink_at(crop, box, neigh_y, neigh)), "the line in the lower half of the gap is the staff below's"
    assert stats["kept"] >= len(own) and stats["erased"] >= len(neigh)


def test_without_the_voice_flag_the_old_rules_apply():
    bw, page, geom, system, rows = lyric_fixture()
    crop, box, stats = cut.clean_crop(bw, page, geom, system, [1], voice=False)
    assert stats["lyric_lines"] == [] and "lyric" not in stats["by_class"]


def test_vocal_neighbour_above_loses_its_lyrics_from_the_lower_cut():
    bw, page, geom, system, rows = lyric_fixture()
    crop, box, stats = cut.clean_crop(bw, page, geom, system, [2], voice=True, voice_above=True)
    own_y, own = rows["own"]  # the upper staff's lyric row: in the upper half of the gap above the target
    neigh_y, neigh = rows["neigh"]  # the row just above the target: not a lyric band, decided by the old rules
    assert any(l["class"] == "lyric-neighbour" for l in stats["lyric_lines"])
    assert not any(ink_at(crop, box, own_y, own)), "the staff above's lyrics are erased whole"
    assert all(ink_at(crop, box, neigh_y, neigh)), "text just above the target stays with it (nearest ink)"


def test_word_glued_to_the_staff_below_by_a_scratch_is_carved_out_and_kept():
    bw, page, geom, system, rows = lyric_fixture(scratch=True)
    own_y, own = rows["own"]
    crop, box, stats = cut.clean_crop(bw, page, geom, system, [1], voice=True)
    assert stats["lyric_pieces"], "the glued word comes back as a piece on the lyric line's rows"
    assert all(ink_at(crop, box, own_y, own)), "every word of the lyric line survives, the glued one included"
    # the scratch below the word is still erased: nothing dark under the word's columns below its row
    arr = np.array(crop.convert("L"))
    x0, x1 = own[1]
    below = arr[own_y + 8 - box["y0"]:, x0 - box["x0"]: x1 + 1 - box["x0"]]
    assert not (below < 128).any()


def test_text_lines_ignore_hairpins_and_lone_words():
    sp = 7.0
    comps = [{"label": 1, "x0": 10, "x1": 40, "y0": 50, "y1": 56, "area": 120, "cls": "gap"},
             {"label": 2, "x0": 80, "x1": 110, "y0": 49, "y1": 57, "area": 150, "cls": "gap"},
             {"label": 3, "x0": 60, "x1": 70, "y0": 56, "y1": 57, "area": 20, "cls": "gap"},   # hyphen between the words
             {"label": 4, "x0": 200, "x1": 400, "y0": 50, "y1": 57, "area": 90, "cls": "gap"},  # hairpin: fill ~0.06
             {"label": 5, "x0": 10, "x1": 40, "y0": 150, "y1": 156, "area": 120, "cls": "gap"}]  # a lone word
    lines = cut.text_lines(comps, sp)
    assert len(lines) == 1
    assert sorted(c["label"] for c in lines[0]) == [1, 2, 3]
