"""OMR plumbing (feature 005, api/experiments/omr): continuous bar ids over a book, x-to-bar text placement,
the grade gate, and merging per-movement exports onto the global numbers. Synthetic data, no network, no box."""

import pytest

from experiments.omr.audiveris_model import split_gate
from experiments.omr.measure_map import build_measures, parse_key, placements
from experiments.omr.text_place import bar_at, grid_to_page, place, staff_at


def stack(i, left, right, **kw):
    return {"id": i, "left": left, "right": right, **kw}


def system(sid, top, stacks):
    return {"id": sid, "top": top, "bottom": top + 200, "stacks": stacks}


# Two scan pages. Page 2 holds the end of movement 1 (Audiveris page 1) and the start of movement 2 (Audiveris
# page 2); Audiveris numbers stacks per Audiveris page, so both start at 1.
SHEETS = [
    {"sheet": 1, "width": 2000, "height": 3000, "pages": [{"page": 1, "systems": [
        system(2, 900, [stack(4, 100, 900), stack(5, 900, 1900)]),      # listed out of order on purpose
        system(1, 300, [stack(2, 600, 1200), stack(1, 100, 600, abnormal=True, expected="3/4", duration="1"),
                        stack(3, 1200, 1900)]),
    ]}]},
    {"sheet": 2, "width": 2000, "height": 3000, "pages": [
        {"page": 1, "systems": [system(1, 300, [stack(1, 100, 1000), stack(2, 1000, 1900)])]},
        {"page": 2, "systems": [system(2, 900, [stack(1, 300, 1100), stack(2, 1100, 1900)])]},
    ]},
]
MOVEMENTS = [{"sheet": 1, "page": 1, "movement": 1}, {"sheet": 2, "page": 1, "movement": 1},
             {"sheet": 2, "page": 2, "movement": 2}]


def test_numbers_run_continuously_over_pages_and_movements():
    ms = build_measures(SHEETS, MOVEMENTS)
    assert [m["number"] for m in ms] == list(range(1, 10))
    assert [m["key"] for m in ms] == ["1.1.1", "1.1.2", "1.1.3", "1.2.1", "1.2.2", "2.1.1", "2.1.2", "2.2.1", "2.2.2"]
    assert all(parse_key(m["key"]) == (m["page"], m["system"], m["bar"]) for m in ms)


def test_systems_and_bars_are_ordered_by_geometry_not_input_order():
    ms = build_measures(SHEETS, MOVEMENTS)
    first = ms[0]
    assert first["audiveris"] == {"sheet": 1, "page": 1, "system": 1, "stack": 1}
    assert first["px"] == [100, 300, 600, 500]
    assert first["box"] == {"x0": 0.05, "y0": 0.1, "x1": 0.3, "y1": 0.1667}


def test_movement_bars_restart_and_match_the_movement_export_ordinals():
    ms = build_measures(SHEETS, MOVEMENTS)
    assert [(m["movement"], m["movement_bar"]) for m in ms] == [(1, i) for i in range(1, 8)] + [(2, 1), (2, 2)]
    # the second Audiveris page of scan page 2 restarts its stack ids, the global number does not
    assert [(m["audiveris"]["page"], m["audiveris"]["stack"], m["number"]) for m in ms[5:]] == [
        (1, 1, 6), (1, 2, 7), (2, 1, 8), (2, 2, 9)]


def test_pickup_score_starts_at_zero_and_extra_fields_carry():
    ms = build_measures(SHEETS, MOVEMENTS, first_number=0)
    assert ms[0]["number"] == 0 and ms[-1]["number"] == 8
    assert ms[0]["abnormal"] is True and ms[0]["expected"] == "3/4"


def test_placements_have_the_004_shape():
    rows = placements(build_measures(SHEETS, MOVEMENTS))
    assert set(rows[0]) == {"key", "number", "page", "system", "box", "confidence", "flag", "rehearsal_mark"}
    assert rows[0]["confidence"] == "low" and "abnormal" in rows[0]["flag"]
    assert rows[1]["confidence"] == "high" and rows[1]["flag"] is None


# ---------------------------------------------------------------- text placement

SYS_MEASURES = [{"number": 10, "key": "1.2.1", "px": [200, 1000, 800, 1300]},
                {"number": 11, "key": "1.2.2", "px": [800, 1000, 1400, 1300]},
                {"number": 12, "key": "1.2.3", "px": [1400, 1000, 2000, 1300]}]
STAVES = [{"top": 1000, "bottom": 1080}, {"top": 1220, "bottom": 1300}]
CROP = {"origin": [100, 900], "size": [2000, 500]}  # grid x 0..1000 -> page x 100..2100, y -> 900..1400


def g(px_x, px_y):
    """Page pixels -> Spark's grid over CROP."""
    return (px_x - 100) / 2000 * 1000, (px_y - 900) / 500 * 1000


def test_grid_to_page():
    assert grid_to_page(0, 0, CROP) == (100, 900)
    assert grid_to_page(1000, 1000, CROP) == (2100, 1400)
    assert grid_to_page(*g(950, 1150), CROP) == pytest.approx((950, 1150))


def test_bar_at_contains_edges_and_gaps():
    assert bar_at(799, SYS_MEASURES)[0]["number"] == 10
    assert bar_at(800, SYS_MEASURES)[0]["number"] == 11  # [left, right)
    assert bar_at(150, SYS_MEASURES) == (SYS_MEASURES[0], "x-before-first")
    assert bar_at(2050, SYS_MEASURES) == (SYS_MEASURES[2], "x-after-last")
    gappy = [{"number": 1, "px": [0, 0, 100, 0]}, {"number": 2, "px": [140, 0, 300, 0]}]
    assert bar_at(130, gappy) == (gappy[1], "x-gap")


def test_staff_by_nearest_band_ties_go_up():
    assert staff_at(1030, STAVES) == (1, "above")      # inside the upper staff, above its middle
    assert staff_at(1100, STAVES) == (1, "below")      # just under the upper staff
    assert staff_at(1200, STAVES) == (2, "above")      # just over the lower staff
    assert staff_at(1150, STAVES) == (1, "below")      # dead centre between the staves: upper
    assert staff_at(1350, STAVES) == (2, "below")


def test_text_goes_where_its_x_is_not_where_the_label_says():
    x, y = g(1500, 1150)
    placed, dropped = place([{"text": "cresc.", "x": x, "y": y, "bar": 11}], SYS_MEASURES, STAVES, CROP)
    assert not dropped
    p = placed[0]
    assert (p["number"], p["key"], p["staff"], p["placement"], p["how"]) == (12, "1.2.3", 1, "below", "x")
    assert p["kind"] == "words" and p["spark_bar"] == 11 and p["label_agrees"] is False
    assert p["frac"] == pytest.approx(100 / 600, abs=1e-3)


def test_label_is_only_the_fallback_and_garbage_is_dropped():
    placed, dropped = place([{"text": "p", "bar": 10, "y": g(0, 1250)[1]}, {"text": "dim.", "x": "left"},
                             {"text": "", "x": 10, "y": 10}, {"text": "f", "x": 5000, "y": 10, "bar": 99}],
                            SYS_MEASURES, STAVES, CROP)
    assert [(p["text"], p["number"], p["how"], p["staff"], p["kind"]) for p in placed] == [("p", 10, "label", 2, "dynamic")]
    assert len(dropped) == 3


def test_snap_to_audiveris_glyph_pulls_a_drifted_point_back_into_its_bar():
    # Spark's point drifted 120 px past the barline at 1400; Audiveris has the word's ink at 1260-1340.
    glyphs = [{"tag": "word", "value": "erase.", "bounds": [1260, 1130, 80, 30]},
              {"tag": "word", "value": "3", "bounds": [1410, 1140, 15, 20]}]   # fingering digit: never a target
    x, y = g(1420, 1150)
    placed, _ = place([{"text": "cresc.", "x": x, "y": y, "bar": 11}], SYS_MEASURES, STAVES, CROP,
                      glyphs=glyphs, interline=20)
    assert (placed[0]["number"], placed[0]["how"], placed[0]["px"]) == (11, "glyph+x", [1300, 1145])
    assert placed[0]["spark_px"] == [1420, 1150]
    # nothing within 8 interlines: Spark's own x stands
    far, _ = place([{"text": "cresc.", "x": x, "y": y}], SYS_MEASURES, STAVES, CROP,
                   glyphs=[{"tag": "word", "value": "dolce", "bounds": [300, 1130, 80, 30]}], interline=20)
    assert (far[0]["number"], far[0]["how"]) == (12, "x")


def test_dynamic_takes_the_bar_of_the_first_note_at_or_after_its_ink():
    # An f whose ink straddles the barline at 1400 (centre 1395, bar 11) belongs to the first note of bar 12;
    # the last note of bar 11 sits left of the f's left edge.
    glyphs = [{"tag": "dynamics", "value": None, "bounds": [1370, 1130, 50, 40]}]
    heads = [{"x": 1355, "number": 11}, {"x": 1440, "number": 12}, {"x": 1500, "number": 12}]
    x, y = g(1390, 1160)
    placed, _ = place([{"text": "f", "x": x, "y": y, "bar": 12}], SYS_MEASURES, STAVES, CROP,
                      glyphs=glyphs, heads=heads, interline=20)
    assert (placed[0]["number"], placed[0]["how"], placed[0]["label_agrees"]) == (12, "glyph+head", True)
    # words do not anchor to notes: same ink as a word stays in bar 11
    words, _ = place([{"text": "dolce", "x": x, "y": y}], SYS_MEASURES, STAVES, CROP,
                     glyphs=glyphs, heads=heads, interline=20)
    assert (words[0]["number"], words[0]["how"]) == (11, "glyph+x")
    # no head within 3 interlines: the dynamic falls back to the bar holding its centre
    alone, _ = place([{"text": "p", "x": x, "y": y}], SYS_MEASURES, STAVES, CROP,
                     glyphs=glyphs, heads=[{"x": 1600, "number": 12}], interline=20)
    assert (alone[0]["number"], alone[0]["how"]) == (11, "glyph+x")


# ---------------------------------------------------------------- grade gate

def test_gate_knob_splits_asked_and_skipped():
    inters = [{"tag": "tuplet", "grade": 0.36}, {"tag": "tuplet", "grade": 0.75}, {"tag": "dynamics", "grade": 0.5},
              {"tag": "dynamics", "grade": 0.8}, {"tag": "word", "grade": 0.1}, {"tag": "rest", "grade": float("nan")}]
    asked, skipped = split_gate(inters, 0.6, {})
    assert [(i["tag"], i["grade"]) for i in asked] == [("tuplet", 0.36), ("dynamics", 0.5)]
    assert [(i["tag"], i["grade"]) for i in skipped] == [("tuplet", 0.75), ("dynamics", 0.8)]
    asked, skipped = split_gate(inters, 0.6, {"tuplet": 0.9})
    assert ("tuplet", 0.75) in [(i["tag"], i["grade"]) for i in asked]
    assert [(i["tag"], i["grade"]) for i in skipped] == [("dynamics", 0.8)]


# ---------------------------------------------------------------- per-movement exports onto global numbers

def test_movement_files_merge_onto_global_numbers(tmp_path):
    from music21 import meter, note, stream

    from experiments.omr.score import merge

    def movement(path, bars, ts):
        sc = stream.Score()
        for _ in range(2):
            p = stream.Part()
            for i in range(1, bars + 1):
                m = stream.Measure(number=i)
                if i == 1:
                    m.insert(0, meter.TimeSignature(ts))
                m.append(note.Note("C4", quarterLength=meter.TimeSignature(ts).barDuration.quarterLength))
                p.append(m)
            sc.insert(0, p)
        sc.write("musicxml", fp=str(path))
        return str(path)

    files = [movement(tmp_path / "mvt1.musicxml", 7, "3/4"), movement(tmp_path / "mvt2.musicxml", 2, "2/4")]
    model = {"measures": build_measures(SHEETS, MOVEMENTS)}
    merged, notes = merge(model, files)
    parts = list(merged.parts)
    assert len(parts) == 2 and not notes
    assert [m.number for m in parts[0].getElementsByClass(stream.Measure)] == list(range(1, 10))
    assert [(m.number, m.timeSignature.ratioString) for m in parts[1].getElementsByClass(stream.Measure)
            if m.timeSignature] == [(1, "3/4"), (8, "2/4")]
    with pytest.raises(SystemExit):
        merge(model, files[:1] + [movement(tmp_path / "short.musicxml", 1, "2/4")])
