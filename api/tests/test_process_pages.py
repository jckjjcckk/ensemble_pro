"""Page reading (feature 004) on the part cut's geometry: `cut.page_measures`, the header-driven staff recovery inside
`process_pages`, the systemic line of an indented system, the spacing-scaled barline tolerance, and the part
assignment that tells a cut-away system from a page with parts the book does not have. Synthetic pages, scripted
model, fake database; no network."""
from __future__ import annotations

import pytest

from app.agent.fake import fake_client, text
from app.librarian import Job, cut
from app.librarian.labels import PageLabels, match_part, parts_context
from app.librarian.process_pages import assign_parts, process_pages
from app.llm import Completion
from tests.test_cut import INK, blank, draw_staff, png_bytes, system_page
from tests.test_part_cut import HEADER, FakeDB, synth_page
from tests.test_signature import LABELS, PagesCtx, sig


@pytest.fixture(autouse=True)
def _pages_read_at_low(monkeypatch):
    """These tests script one label answer per page; the minimal read and its fallback to low are tested in
    test_process_pages_guard.py."""
    import app.librarian.process_pages as pp
    monkeypatch.setattr(pp, "PAGE_EFFORT", "low")

SCORE = "11111111-1111-1111-1111-111111111111"


# ---------------------------------------------------------------- the page record

def test_page_measures_gives_fraction_boxes_numbered_left_to_right():
    rec = cut.page_measures(synth_page())
    assert rec["image_px"] == [1300, 1700] and rec["staves"] == 6
    assert [(s["index"], s["staves"]) for s in rec["systems"]] == [(1, 6)]
    ms = rec["measures"]
    assert [m["provisional"] for m in ms] == [1, 2, 3, 4] and {m["system"] for m in ms} == {1}
    assert all(m["confidence"] == "high" and m["flag"] is None for m in ms)
    xs = [(m["box"]["x0"], m["box"]["x1"]) for m in ms]
    assert all(0 <= a < b <= 1 for a, b in xs) and [a for a, _ in xs] == sorted(a for a, _ in xs)
    assert abs(xs[0][0] - 120 / 1300) < 0.005 and abs(xs[-1][1] - 1200 / 1300) < 0.005      # system start to the final barline
    assert all(b["cover"] == 1.0 for b in rec["systems"][0]["barlines"])


def test_page_measures_flags_an_open_end_and_a_narrow_bar():
    page = blank(1300, 700)
    staves = [draw_staff(page, y, 8, 120, 1200) for y in (150, 260)]
    top, bot = staves[0]["y_top"], staves[-1]["y_bottom"] + 1
    for bx in (118, 500, 540):                    # no closing barline at 1200; between 500 and 540 under 4 spaces of white
        page[top: bot, bx: bx + 3] = INK
    rec = cut.page_measures(png_bytes(page))
    flags = [(m["confidence"], m["flag"]) for m in rec["measures"]]
    assert len(flags) == 3
    assert flags[1][0] == "low" and "narrow" in flags[1][1]
    assert flags[2] == ("medium", "no closing barline; bar runs to the end of the staves")


def test_an_indented_first_system_is_one_system_not_single_staves():
    """Goldberg p1-2 and the two-piano p3 open with an indented system (a title or "Var. 1." in the margin): its
    systemic line stands right of the page's median staff start and must still join its staves."""
    page = blank(1300, 1100)
    sp, systems = 10, []
    for k, (x0, y) in enumerate([(300, 150), (120, 450), (120, 750)]):
        a = draw_staff(page, y, sp, x0, 1200)
        b = draw_staff(page, y + 4 * sp + 80, sp, x0, 1200)
        page[a["y_top"]: b["y_bottom"] + 2, x0 - 4: x0 - 1] = INK           # the systemic line
        for bx in (x0 + 400, 1198):
            page[a["y_top"]: b["y_bottom"] + 2, bx: bx + 3] = INK
        systems.append((a, b))
    geom, _, _ = cut.page_geometry(png_bytes(page))
    assert [len(s["staff_indices"]) for s in geom["systems"]] == [2, 2, 2]
    assert geom["grouping"] == "systemic-line"


def test_barline_tolerance_scales_with_the_staff_spacing():
    assert [cut.barline_tol(sp) for sp in (6.25, 7.25, 9.75, 11.0, 15.5)] == [4, 4, 4, 4, 6]


def test_a_drifting_barline_on_a_large_scan_is_found_at_the_scaled_tolerance():
    """Spacing 16 px (Beethoven 9 rendered at 3150 px): a barline that drifts 20 px down the system loses its gap
    votes at 4 px and keeps them at the scaled 6 px."""
    sp, x0, x1 = 16, 100, 1500
    page = blank(1600, 900)
    staves = [draw_staff(page, 120 + k * (4 * sp + 96), sp, x0, x1) for k in range(4)]
    top, bot = staves[0]["y_top"], staves[-1]["y_bottom"] + 1
    for bx in (x0 - 2, x1 - 2):
        page[top: bot, bx: bx + 3] = INK
    for y in range(top, bot):                      # the drifting barline at 800 -> 820
        x = 800 + round(20 * (y - top) / (bot - top))
        page[y, x: x + 3] = INK
    geom, bw, _ = cut.page_geometry(png_bytes(page))
    ss = geom["staves"]
    assert len(ss) == 4 and [len(s["staff_indices"]) for s in geom["systems"]] == [4]
    assert [len(cut.find_system_barlines(bw, ss, x0, x1, tol=t)) for t in (4, 5)] == [2, 2]     # the systemic line and the end
    assert len(geom["systems"][0]["barlines"]) == 3 and geom["systems"][0]["n_measures"] == 2


# ---------------------------------------------------------------- the parts

def labels_for(*systems: list[str], spp: list[list[int]] | None = None) -> PageLabels:
    return PageLabels(systems=[{"index": i + 1, "parts": p, "staves_per_part": (spp[i] if spp else [])} for i, p in enumerate(systems)])


def geo_systems(*staves: int) -> list[dict]:
    return [{"index": i + 1, "staves": n} for i, n in enumerate(staves)]


TWO_PIANO_HEADER = {"instruments": [{"label": "Piano I.", "staves": 2}, {"label": "Piano II.", "staves": 2}], "expected_staves": 4}


def test_a_cut_away_system_with_known_parts_is_not_a_question():
    """Two-piano page: piano II rests in the first two systems and is not printed there."""
    parts, why = assign_parts(geo_systems(2, 2, 4), labels_for(["Piano I"], ["Piano I"], ["Piano I", "Piano II"]), ["Piano I", "Piano II"], 4,
                              TWO_PIANO_HEADER)
    assert why is None and [p["parts"] for p in parts] == [["Piano I"], ["Piano I"], ["Piano I", "Piano II"]]
    assert [p["staves_per_part"] for p in parts] == [[2], [2], [2, 2]]


def test_later_pages_keep_the_names_already_in_use():
    parts, why = assign_parts(geo_systems(3), labels_for(["Fl.", "Vl. I", "Vc."]), ["Flutes I. II", "Violins I", "Violins II", "Cellos"], 2)
    assert why is None and parts[0]["parts"] == ["Flutes I. II", "Violins I", "Cellos"]


def test_a_part_the_header_lists_is_accepted_when_it_first_appears():
    header = {"instruments": [{"label": "Flauti I. II.", "staves": 1}, {"label": "Arpa", "staves": 2}, {"label": "Violini I.", "staves": 1}]}
    parts, why = assign_parts(geo_systems(3), labels_for(["Flute", "Harp"], spp=[[1, 2]]), ["Flute", "Violin I"], 5, header)
    assert why is None and parts[0]["parts"] == ["Flute", "Harp"]


@pytest.mark.parametrize("known, systems, staves, header, words", [
    (["Piano"], [["Piano I", "Piano II"]], [4], {"instruments": [{"label": "Piano", "staves": 2}]}, "Piano I, Piano II"),   # a second piano is new
    (["Piano I", "Piano II"], [["Organ"]], [6], TWO_PIANO_HEADER, "Organ"),
    (["Violins I", "Violins II"], [["Violins", "Violins"]], [2], None, "Violins"),                                        # two names, one part
])
def test_parts_the_book_does_not_have_are_a_question(known, systems, staves, header, words):
    parts, why = assign_parts(geo_systems(*staves), labels_for(*systems), known, 3, header)
    assert parts == [] and words in why and "earlier pages did not have" in why


def test_staves_that_do_not_add_up_are_still_a_question():
    parts, why = assign_parts(geo_systems(4, 2), labels_for(["Piano I", "Piano II"], ["Piano I", "Piano II"], spp=[[2, 2], [2, 2]]),
                              ["Piano I", "Piano II"], 4, TWO_PIANO_HEADER)
    assert parts == [] and "system 2" in why and "2 staves" in why


def test_match_part():
    assert match_part("Piano I", ["Piano"]) is None
    assert match_part("Piano", ["Piano I", "Piano II"]) is None
    assert match_part("Fl.", ["Flutes I. II", "Oboes I. II"]) == "Flutes I. II"
    assert match_part("Flute I", ["Flauti I. II."]) == "Flauti I. II."
    assert match_part("Horns III. IV. in F", ["Horns I. II. in F", "Horns III. IV. in F"]) == "Horns III. IV. in F"
    assert match_part("Viola", ["Violins I", "Viole"]) == "Viole"
    assert match_part("Piano I", ["Piano I.", "Piano II."]) == "Piano I."
    assert match_part("Double Bass", ["Cellos", "Double Basses"]) == "Double Basses"     # the synonym table reads "basses" as the voice
    assert match_part("Flutes I. II", ["Flutes I, II"]) == "Flutes I, II"


def test_parts_context_names_the_parts_already_read():
    assert "Piano I; Piano II" in parts_context(["Piano I", "Piano II"]) and "is a new part" in parts_context(["Piano"])
    assert parts_context([]) == ""


# ---------------------------------------------------------------- process_pages with the header

class PromptCtx(PagesCtx):
    """PagesCtx that keeps the label prompts."""
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.prompts: list[str] = []

    async def complete(self, user_text: str, **kw) -> Completion:
        self.prompts.append(user_text)
        return await super().complete(user_text, **kw)


def bowed_world(n: int = 2) -> tuple[Job, FakeDB, dict]:
    page, _ = system_page(bowed={4})          # six staves, the fourth bowed: the page-wide profile finds five
    db = FakeDB()
    db.rows["scores"] = [{"id": SCORE, "title": "Synth", "composer": None, "work": None}]
    db.rows["sources"] = [{"id": "src1", "score_id": SCORE, "kind": "images", "created_by": "u1",
                           "storage_paths": [f"{SCORE}/pages/{i}.png" for i in range(1, n + 1)], "page_order": list(range(1, n + 1)), "page_count": n}]
    job = Job("job1", "process_pages", {"score_id": SCORE, "source_id": "src1"}, SCORE, "u1", 1, 3)
    return job, db, {f"{SCORE}/pages/{i}.png": png_bytes(page) for i in range(1, n + 1)}


async def test_the_header_count_recovers_the_staff_and_the_page_reads_itself():
    job, db, pages = bowed_world(2)
    ctx = PromptCtx(job, db, pages, labels=[LABELS, LABELS])
    c, t = fake_client([sig(), HEADER])
    out = await process_pages(job, ctx, client=c, model="muse-spark-1.3")
    assert not out.get("question") and db.rows["scores"][0]["status"] == "ready" and len(t.calls) == 2
    state = db.rows["interpretations"][0]["params"]["state"]
    assert state["header"]["expected_staves"] == 6 and f"{SCORE}/header/p001-overlay.png" in ctx.uploads
    for key in ("1", "2"):
        geo = state["pages"][key]["geometry"]
        assert geo["staves_before_recovery"] == [5] and [s["staves"] for s in geo["systems"]] == [6] and geo["systems"][0]["recovered"] == 1
    log = db.rows["interpretations"][0]["summary"]["log"]
    assert log[1].startswith("Page 1, score header: 6 staves per full system") and "1 staves recovered" in log[2]
    assert [r["name"] for r in db.rows["parts"]] == ["Flute", "Oboe", "Horn", "Piano", "Violin I"]
    # the header's names become the book's label memory, as the parts this reading named (008, 006 memory rule)
    mem = db.rows["scores"][0]["label_memory"]["entries"]
    assert mem["piano"]["part"] == "Piano" and mem["piano"]["source"] == "model" and mem["piano"]["origin"] == "header" and len(mem) == 5
    # Spark is told the parts already read from page 2 on (never the header's names: a keyboard header reads "Aria." as the instrument)
    assert "Parts already read" not in ctx.prompts[0] and "Parts already read on earlier pages of this book: Flute; Oboe" in ctx.prompts[1].replace(", in score order", "")
    assert sum(1 for ch in ctx.charges if ch.cost_usd > 0) == 4 and out["cost_usd"] == pytest.approx(float(sum(ch.cost_usd for ch in ctx.charges)))


async def test_without_a_header_the_missed_staff_is_a_question():
    job, db, pages = bowed_world(1)
    ctx = PagesCtx(job, db, pages, labels=[LABELS])
    c, _ = fake_client([sig(), text("I cannot read the labels."), text("Still no labels.")])
    out = await process_pages(job, ctx, client=c, model="muse-spark-1.3")
    state = db.rows["interpretations"][0]["params"]["state"]
    assert state["header"]["expected_staves"] is None and "no JSON" in state["header"]["error"]
    assert "staves are not recovered" in state["log"][1]
    assert out.get("question") and "with staves [1, 1, 1, 2, 1], but it has 5 staves" in out["question"]
    assert out["question_payload"]["remembered"] == []                # nothing remembered for a five-staff system yet


async def test_a_page_with_no_music_before_the_first_system_costs_no_header_call():
    import io

    from PIL import Image
    buf = io.BytesIO()
    Image.new("L", (1275, 1650), 255).save(buf, format="PNG")
    db = FakeDB()
    db.rows["scores"] = [{"id": SCORE, "title": "Synth", "composer": None, "work": None}]
    db.rows["sources"] = [{"id": "src1", "score_id": SCORE, "kind": "images", "created_by": "u1",
                           "storage_paths": [f"{SCORE}/pages/1.png", f"{SCORE}/pages/2.png"], "page_order": [1, 2], "page_count": 2}]
    job = Job("job1", "process_pages", {"score_id": SCORE, "source_id": "src1"}, SCORE, "u1", 1, 3)
    ctx = PagesCtx(job, db, {f"{SCORE}/pages/1.png": buf.getvalue(), f"{SCORE}/pages/2.png": synth_page()}, labels=[LABELS])
    c, t = fake_client([sig(), HEADER])
    await process_pages(job, ctx, client=c, model="muse-spark-1.3")
    summary = db.rows["interpretations"][0]["summary"]
    assert len(t.calls) == 2 and summary["header"]["page"] == 2 and summary["signature"]["page"] == 2
    assert db.rows["scores"][0]["status"] == "ready" and db.rows["scores"][0]["bars"] == 4


# ---------------------------------------------------------------- 013 v4e: printed landmarks at the bars geometry gives them

def test_page_landmarks_keep_only_a_known_kind_pointed_at_a_box_on_the_page():
    from app.librarian.labels import page_landmarks
    kept, dropped = page_landmarks([
        {"kind": "tempo", "text": "Allegro moderato", "provisional_measure": 1},
        {"kind": "double bar", "text": "double bar", "provisional_measure": 4},
        {"kind": "tempo", "text": "Allegro moderato", "provisional_measure": 1},          # the same twice: once
        {"kind": "tempo", "text": "meno mosso", "provisional_measure": None},              # no box: dropped
        {"kind": "section", "text": "Var. 2", "provisional_measure": 9},                   # not on this page
        {"kind": "dynamic", "text": "ff", "provisional_measure": 2},                       # not a landmark
        {"kind": "tempo", "text": "", "provisional_measure": 2}, "nonsense"], n_boxes=6)
    assert kept == [{"kind": "tempo", "text": "Allegro moderato", "provisional": 1},
                    {"kind": "double_bar", "text": "double bar", "provisional": 4}]
    assert [d["why"] for d in dropped] == ["no box", "box 9 not on the page", "kind dynamic", "no text"]


def test_the_label_prompt_asks_for_a_box_never_a_bar_number():
    from app.librarian.labels import PROMPT
    p = PROMPT.format(n=6, systems_desc="1 has 2 staves", parts_context="")
    assert "8. landmarks:" in p and "Do not count bars or give bar numbers; only point at a box." in p
    assert "never infer a start repeat from an end repeat" in p
    assert "If you cannot tell which box it belongs to, give null." in p and '"provisional_measure": 12' in p


async def test_landmarks_get_their_bars_from_the_count_and_ambiguous_ones_are_left_out():
    """Two one-bar pages: page 2's box 1 is bar 2 by the count, whatever Spark would have said; a double bar closing
    the book's last bar has no bar after it; a landmark with no box is logged and left out."""
    job, db, pages = bowed_world(2)
    first = {**LABELS, "landmarks": [{"kind": "tempo", "text": "Allegro", "provisional_measure": 1},
                                     {"kind": "tempo", "text": "rit.", "provisional_measure": None}]}
    second = {**LABELS, "landmarks": [{"kind": "tempo", "text": "Adagio", "provisional_measure": 1},
                                      {"kind": "repeat", "text": "end repeat", "provisional_measure": 1},
                                      {"kind": "section", "text": "Trio", "provisional_measure": 2}]}
    ctx = PromptCtx(job, db, pages, labels=[first, second])
    c, _ = fake_client([sig(), HEADER])
    await process_pages(job, ctx, client=c, model="muse-spark-1.3")
    state = db.rows["interpretations"][0]["params"]["state"]
    assert [len(state["pages"][k]["geometry"]["measures"]) for k in ("1", "2")] == [1, 1] and "8. landmarks:" in ctx.prompts[0]
    assert db.rows["scores"][0]["landmarks"] == [
        {"kind": "tempo", "label": "Allegro", "bar": 1, "bar_after": None, "source": "page"},
        {"kind": "tempo", "label": "Adagio", "bar": 2, "bar_after": None, "source": "page"},
        {"kind": "repeat", "label": "end repeat", "bar": 2, "bar_after": None, "source": "page"}]
    log = db.rows["interpretations"][0]["summary"]["log"]
    assert "Page 1: landmark 'rit.' left out (no box)" in log and "Page 2: landmark 'Trio' left out (box 2 not on the page)" in log
    assert "3 landmarks read" in " ".join(log) and db.rows["interpretations"][0]["summary"]["landmarks"] == 3


# ---------------------------------------------------------------- the book's memory before a question (follow-up, 2026-10-31)

def test_a_page_with_no_labels_takes_the_layout_of_an_earlier_page_of_the_same_staff_count():
    from app.librarian.label_memory import LabelMemory
    m = LabelMemory()
    m.learn_layout(3, [], "Violin", [1], "model", "page", page=1)
    m.learn_layout(3, [], "Piano", [2, 3], "model", "page", page=1)
    parts, why = assign_parts(geo_systems(3, 3), labels_for([], []), ["Violin", "Piano"], 4, None, m)
    assert why is None and [p["parts"] for p in parts] == [["Violin", "Piano"]] * 2 and parts[0]["staves_per_part"] == [1, 2]
    assert parts[0]["remembered"][0]["how"] == "layout" and parts[0]["remembered"][0]["page"] == 1
    # without the memory, or for a staff count it has not seen, the page still asks
    assert assign_parts(geo_systems(3), labels_for([]), ["Violin", "Piano"], 4, None)[1].startswith("Spark named no parts")
    assert assign_parts(geo_systems(4), labels_for([]), ["Violin", "Piano"], 4, None, m)[1].startswith("Spark named no parts")
    # staves that do not add up take the layout when it names the same parts
    parts, why = assign_parts(geo_systems(3), labels_for(["Violin", "Piano"], spp=[[2, 2]]), ["Violin", "Piano"], 4, None, m)
    assert why is None and parts[0]["staves_per_part"] == [1, 2]
    # a disputed layout settles nothing
    m.learn_layout(3, [], "Piano", [1, 2], "model", "page", page=2)
    assert assign_parts(geo_systems(3), labels_for([]), ["Violin", "Piano"], 4, None, m)[1].startswith("Spark named no parts")


def test_a_name_the_parts_do_not_match_is_what_the_memory_says_its_label_is():
    """PC5 p. 4 (E2E night): a label the synonyms do not know was a question on the page read although the admin had
    already said what it is; once an answer (or a read) has tied the label to a part, it is that part."""
    from app.librarian.label_memory import LabelMemory
    known = ["Violino I", "Viola", "Violoncello e Contrabasso"]
    assert "earlier pages did not have" in assign_parts(geo_systems(3), labels_for(["Viol. I", "Vla.", "Xq."]), known, 4)[1]
    m = LabelMemory()
    m.learn("Xq.", "Violoncello e Contrabasso", "human", "answer", page=4)
    parts, why = assign_parts(geo_systems(3), labels_for(["Viol. I", "Vla.", "Xq."]), known, 5, None, m)
    assert why is None and parts[0]["parts"] == known and parts[0]["remembered"][0] == {
        "how": "label", "label": "Xq", "part": "Violoncello e Contrabasso", "page": 4, "source": "human"}


def test_an_answer_is_remembered_only_where_its_staves_are_known():
    from app.librarian.label_memory import LabelMemory
    from app.librarian.process_pages import answer_staves, learn_page
    assert answer_staves(3, ["Violin", "Piano"], (["Vl.", "Pfte."], [1, 2])) == ([1, 2], True)          # Spark's own counts
    assert answer_staves(3, ["Violin", "Viola", "Cello"]) == ([1, 1, 1], True)                         # one staff each
    hdr = {"instruments": [{"label": "Violin", "staves": 1}, {"label": "Piano", "staves": 2}]}
    assert answer_staves(3, ["Violin", "Piano"], ([], []), hdr) == ([1, 2], True)                     # the header's counts
    assert answer_staves(10, ["A", "B", "C"]) == ([4, 3, 3], False)                                    # an even split is a guess
    lay = LabelMemory()
    lay.learn_layout(3, [], "Piano", [1, 2], "human", "answer", page=2)
    lay.learn_layout(3, [], "Violin", [3], "human", "answer", page=2)
    assert answer_staves(3, ["Piano", "Violin"], mem=lay) == ([2, 1], True)                            # "As on page 2"
    m = LabelMemory()
    systems = geo_systems(3, 10)
    parts = [{"index": 1, "parts": ["Violin", "Piano"], "staves_per_part": [1, 2]}, {"index": 2, "parts": ["A", "B", "C"], "staves_per_part": [4, 3, 3]}]
    said = learn_page(m, 4, systems, parts, labels_for(["Vl.", "Pfte."], ["A", "B", "C"]), "human", "job2", sure=[True, False])
    assert m.full_layout(3)["source"] == "human" and m.full_layout(10) is None
    assert m.resolve("Vl.")["part"] == "Violin" and m.resolve("Vl.")["source"] == "human" and len(said) == 4


async def test_a_page_with_no_labels_is_read_with_the_first_pages_layout_not_asked():
    """End to end: page 2's label call names no parts (no margin labels); page 1's layout for six staves applies, the
    book is ready, and the layouts are kept on the score row for the next reading or split."""
    job, db, pages = bowed_world(2)
    bare = {**LABELS, "systems": [{"index": 1, "parts": [], "staves_per_part": []}]}
    ctx = PromptCtx(job, db, pages, labels=[LABELS, bare])
    c, _ = fake_client([sig(), HEADER])
    out = await process_pages(job, ctx, client=c, model="muse-spark-1.3")
    assert not out.get("question") and db.rows["scores"][0]["status"] == "ready"
    log = db.rows["interpretations"][0]["summary"]["log"]
    assert any("Page 2 system 1: Flute, Oboe, Horn, Piano, Violin I as on page 1" in l for l in log)
    lay = db.rows["scores"][0]["label_memory"]["layouts"]["6"]["parts"]
    assert lay["Piano"]["positions"] == [4, 5] and lay["Piano"]["source"] == "model" and lay["Piano"]["page"] == 1
