"""part_cut against the scripted model and a fake database: no network, no Supabase.

Pages are drawn with PIL: six staves per system, a systemic line, four barlines, a brace on staves 4-5 (the
"Piano"). The scripted transport answers every request in order, so a test's script interleaves the loop's
tool calls with the text replies the in-tool calls consume (header, labels, recheck)."""
from __future__ import annotations

import io
import json
import uuid
from typing import Any

import pytest
from PIL import Image, ImageDraw

from app.agent.fake import fake_client, text, tool, truncated
from app.librarian import Job, JobContext
from app.librarian.header import match_instrument, same_instrument
from app.librarian.part_cut import part_cut

HEADER = text(json.dumps({"instruments": [{"name": "Flute", "staves": 1}, {"name": "Oboe", "staves": 1}, {"name": "Horn", "staves": 1},
                                          {"name": "Piano", "staves": 2}, {"name": "Violin I", "staves": 1}], "key": "C major", "time": "4/4"}))
LABEL = text(json.dumps({"systems": [{"index": 1, "wanted_staves": [4, 5], "status": "playing"}], "confidence": "high"}))
LABEL_ABSENT = text(json.dumps({"systems": [{"index": 1, "wanted_staves": [], "status": "absent"}], "confidence": "high"}))
RECHECK_PIANO = text(json.dumps({"matches": True, "staves_seen": 2, "clefs_seen": ["treble", "bass"], "label_seen": "Pno.", "why": "braced pair, label"}))
RECHECK_VIOLIN = text(json.dumps({"matches": False, "staves_seen": 1, "clefs_seen": ["treble"], "label_seen": "Vl.", "why": "a violin staff, not the horn"}))


def synth_page(staves: int = 6, w: int = 1300, h: int = 1700, vocal_gap: bool = False) -> bytes:
    """Six staves, a systemic line, four barlines, a brace on staves 4-5 (the "Piano"). `vocal_gap` leaves the
    barlines out of the gap between staves 1 and 2, as a choir's lyric gap does."""
    im = Image.new("L", (w, h), 255)
    d = ImageDraw.Draw(im)
    sp, x0, x1, y = 8, 120, 1200, 150
    tops = []
    for _ in range(staves):
        tops.append(y)
        for l in range(5):
            d.line([(x0, y + l * sp), (x1, y + l * sp)], fill=0, width=2)
        for nx in range(x0 + 60, x1 - 40, 90):
            d.ellipse([nx, y + sp, nx + 8, y + sp + 7], fill=0)
            d.line([(nx + 8, y + sp + 3), (nx + 8, y - 2 * sp)], fill=0, width=2)
        y += 4 * sp + 60
    top, bot = tops[0], tops[-1] + 4 * sp
    for bx in (x0, x0 + 300, x0 + 600, x0 + 900, x1):
        d.line([(bx, top), (bx, bot)], fill=0, width=3)
        if vocal_gap and bx != x0:
            d.line([(bx, tops[0] + 4 * sp + 2), (bx, tops[1] - 2)], fill=255, width=5)
    d.line([(x0 - 14, tops[3]), (x0 - 14, tops[4] + 4 * sp)], fill=0, width=4)   # brace on staves 4-5
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


class Query:
    def __init__(self, db: "FakeDB", table: str):
        self.db, self.table, self.op, self.rows, self.filters, self._single = db, table, "select", None, {}, False

    def select(self, *a, **k): self.op = "select"; return self
    def insert(self, rows): self.op, self.rows = "insert", rows; return self
    def upsert(self, rows, **k): self.op, self.rows = "upsert", rows; return self
    def update(self, row): self.op, self.rows = "update", row; return self
    def eq(self, k, v): self.filters[k] = v; return self
    def in_(self, k, v): return self
    def is_(self, k, v): return self
    def order(self, *a, **k): return self
    def limit(self, n): return self
    def single(self): self._single = True; return self

    @staticmethod
    def get(row: dict, key: str):
        """A column, or a JSON field as PostgREST spells it (`payload->>resume_from`)."""
        if "->>" in key:
            col, field = key.split("->>", 1)
            return (row.get(col) or {}).get(field)
        return row.get(key)

    def execute(self):
        rows = self.db.rows.setdefault(self.table, [])
        self.db.ops.append((self.table, self.op, self.rows, dict(self.filters)))
        if self.op == "select":
            out = [r for r in rows if all(self.get(r, k) == v for k, v in self.filters.items())]
            return type("R", (), {"data": (out[0] if out else None) if self._single else out})
        if self.op in ("insert", "upsert"):
            new = [dict(r, id=r.get("id") or str(uuid.uuid4())) for r in (self.rows if isinstance(self.rows, list) else [self.rows])]
            rows.extend(new)
            return type("R", (), {"data": new})
        out = [r for r in rows if all(r.get(k) == v for k, v in self.filters.items())]
        for r in out:
            r.update(self.rows)
        return type("R", (), {"data": out})


class FakeDB:
    def __init__(self):
        self.rows: dict[str, list[dict]] = {}
        self.ops: list[tuple] = []

    def table(self, name: str) -> Query:
        return Query(self, name)


class Ctx(JobContext):
    def __init__(self, job: Job, db: FakeDB, pages: dict[str, bytes]):
        super().__init__(job)
        self._db, self.pages, self.uploads, self.charges = db, pages, {}, []

    @property
    def db(self): return self._db
    def charge(self, c): self.charges.append(c); return {}
    def storage_download(self, path): return self.pages[path]
    def storage_upload(self, path, data, content_type): self.uploads[path] = data


def world(n_pages: int, payload_extra: dict[str, Any] | None = None, db: FakeDB | None = None, page: bytes | None = None) -> tuple[Job, Ctx, FakeDB]:
    db = db or FakeDB()
    score = "11111111-1111-1111-1111-111111111111"
    if not db.rows.get("sources"):
        db.rows["sources"] = [{"id": "src1", "score_id": score, "kind": "images", "created_by": "u1",
                               "storage_paths": [f"{score}/pages/{i}.png" for i in range(1, n_pages + 1)], "page_order": list(range(1, n_pages + 1)), "page_count": n_pages}]
        db.rows["scores"] = [{"id": score, "current_interpretation_id": "intake1"}]
        db.rows["interpretations"] = [{"id": "intake1", "score_id": score, "version": 1}]
        db.rows["measure_placements"] = [{"interpretation_id": "intake1", "measure_id": f"m{i}", "page": 1, "system": 1, "box": {}, "confidence": "high", "flag": None, "rehearsal_mark": None} for i in range(3)]
    job = Job(str(uuid.uuid4()), "part_cut", {"score_id": score, "instrument": "Piano", **(payload_extra or {})}, score, "u1", 1, 3)
    db.rows.setdefault("jobs", []).append({"id": job.id, "result": {}})
    png = page or synth_page()
    ctx = Ctx(job, db, {f"{score}/pages/{i}.png": png for i in range(1, n_pages + 1)})
    return job, ctx, db


def commit(page: int, staves): return tool("commit_system", {"page": page, "system": 1, "staves": staves})


@pytest.fixture(autouse=True)
def _pages_in_call_order(monkeypatch):
    """The scripted fake answers in call order, so these tests read each page when the agent asks for it; the read-ahead
    is tested with a fake that answers by prompt (`test_part_cut_speed.py`)."""
    import app.librarian.part_cut as pc
    monkeypatch.setattr(pc, "PREREAD_PAGES", False)


@pytest.mark.asyncio
async def test_happy_path_three_pages():
    script = [tool("read_header", {}), HEADER]
    for n in (1, 2, 3):
        script += [tool("read_page", {"page": n}), LABEL, commit(n, [4, 5]), RECHECK_PIANO]
    script += [tool("finish", {})]
    client, t = fake_client(script)
    job, ctx, db = world(3)
    out = await part_cut(job, ctx, client=client)
    assert out["systems_cut"] == 3 and out["absent"] == 0 and out["questions"] == 0
    keys = sorted(k for k in ctx.uploads if "/p0" in k)
    assert keys == [f"{job.score_id}/parts/piano/p00{n}-s1.png" for n in (1, 2, 3)]
    derived = [r for r in db.rows["sources"] if r["kind"] == "part_images"][0]
    assert derived["storage_paths"] == keys and derived["meta"]["instrument"] == "Piano" and derived["page_count"] == 3
    interp = [r for r in db.rows["interpretations"] if r.get("engine") == "part-cut-agent"][0]
    assert interp["status"] == "done" and interp["summary"]["systems_cut"] == 3 and interp["summary"]["pages"] == 3 and interp["summary"]["log"]
    copied = [r for r in db.rows["measure_placements"] if r["interpretation_id"] == interp["id"]]
    assert sorted(r["measure_id"] for r in copied) == ["m0", "m1", "m2"]      # stable ids reused, nothing deleted
    assert len(db.rows["measure_placements"]) == 6
    assert len(t.calls) == 2 + 3 * 4 + 1 and len(ctx.charges) == len(t.calls)   # every call charged
    assert ctx.result["agent"]["status"] == "done"
    # the row the iPad watches said where the cut stood on every turn: page 3 of 3 and three systems at the end
    assert ctx.result["phase"] == {"page": 3, "pages": 3, "systems_cut": 3}
    progress = [op[2]["progress"] for op in db.ops if op[0] == "jobs" and op[1] == "update" and "progress" in op[2]]
    assert progress == sorted(progress) and progress[0] == 0 and 0.95 in progress and progress[-1] == 1.0


@pytest.mark.asyncio
async def test_refusal_then_correct_retry():
    script = [tool("read_header", {}), HEADER, tool("read_page", {"page": 1}), LABEL,
              commit(1, [4]),                       # count mismatch: refused before any model call
              commit(1, [3, 4]),                    # one staff off the labels' [4, 5]: refused before any model call
              commit(1, [4, 5]), RECHECK_PIANO, tool("finish", {})]
    client, t = fake_client(script)
    job, ctx, db = world(1)
    out = await part_cut(job, ctx, client=client)
    assert out["systems_cut"] == 1
    results = [json.loads(c["content"]) for body in t.calls for c in (body["messages"][-1]["content"] if isinstance(body["messages"][-1]["content"], list) else []) if c.get("type") == "tool_result"]
    errors = [r["error"] for r in results if "error" in r]
    assert any("2 staves per system" in e for e in errors)
    assert any("the labels put Piano on [4, 5] in system 1; the block [3, 4] adds staff [3]" in e for e in errors)
    assert len(t.calls) == 9                                                  # the two refusals cost no model call
    assert ctx.result["agent"]["refusals"] == {}                               # the counter reset on the good commit


@pytest.mark.asyncio
async def test_staves_given_as_json_text_are_accepted():
    # Claude serialised the array argument as its JSON text ("[4, 5]", "[[4, 5]]") on the first hosted split (2026-10-29).
    script = [tool("read_header", {}), HEADER, tool("read_page", {"page": 1}), LABEL,
              commit(1, "[4, 5]"), RECHECK_PIANO, tool("finish", {})]
    client, t = fake_client(script)
    job, ctx, db = world(1)
    out = await part_cut(job, ctx, client=client)
    assert out["systems_cut"] == 1 and out["questions"] == 0 and ctx.result["agent"]["refusals"] == {}
    script = [tool("read_header", {}), HEADER, tool("read_page", {"page": 1}), LABEL,
              tool("commit_system", {"page": 1, "system": 1, "blocks": "[[4, 5]]"}), RECHECK_PIANO, tool("finish", {})]
    client, t = fake_client(script)
    job, ctx, db = world(1)
    out = await part_cut(job, ctx, client=client)
    assert out["systems_cut"] == 1 and out["questions"] == 0


@pytest.mark.asyncio
async def test_escalates_to_needs_review_then_resumes_with_answer():
    client, t = fake_client([tool("read_header", {}), HEADER, tool("read_page", {"page": 1}), LABEL, commit(1, [4]), commit(1, [4]), commit(1, [4])])
    job, ctx, db = world(1)
    out = await part_cut(job, ctx, client=client)
    q = out["question_payload"]
    assert q["kind"] == "choose_staves" and q["page"] == 1 and q["system"] == 1 and q["proposal"] == [4, 5] and q["last_attempt"] == [4]
    assert [b["index"] for b in q["staff_boxes"]] == [1, 2, 3, 4, 5, 6] and q["image_key"].endswith("/overlay-p001.png") and q["allowed"]["absent"] is True
    assert out["question"] == "Which staves are the Piano's on page 1, line 1?" and out["agent"]["status"] == "needs_review"
    assert out["question_payload"]["page_key"].endswith("/pages/1.png") and out["question_payload"]["image_px"]
    interp = [r for r in db.rows["interpretations"] if r.get("engine") == "part-cut-agent"][0]
    assert interp["status"] == "needs_review" and interp["summary"]["questions_asked"] == 1
    # the admin answers; a follow-up job of the same kind carries the answer and resume_from
    db.rows["jobs"][-1]["result"] = out
    client2, t2 = fake_client([tool("finish", {})])
    job2, ctx2, _ = world(1, {"answer": {"staves": [4, 5]}, "resume_from": job.id}, db=db)
    out2 = await part_cut(job2, ctx2, client=client2)
    assert out2["systems_cut"] == 1 and out2["questions"] == 1
    assert f"{job.score_id}/parts/piano/p001-s1.png" in ctx2.uploads           # applied as a successful commit, no recheck call
    assert t2.calls[0]["messages"][-1]["role"] == "user" and "admin decided page 1 system 1: [4, 5]" in t2.calls[0]["messages"][-1]["content"]
    assert len(t2.calls) == 1
    assert [r for r in db.rows["interpretations"] if r.get("engine") == "part-cut-agent"] == [interp] and interp["status"] == "done"


@pytest.mark.asyncio
async def test_absent_page_and_finish_refuses_uncommitted():
    client, t = fake_client([tool("read_header", {}), HEADER, tool("read_page", {"page": 1}), LABEL_ABSENT, commit(1, "absent"),
                             tool("finish", {}),                                   # page 2 unread: refused
                             tool("read_page", {"page": 2}), LABEL, commit(2, [4, 5]), RECHECK_PIANO, tool("finish", {})])
    job, ctx, db = world(2)
    out = await part_cut(job, ctx, client=client)
    assert out["systems_cut"] == 1 and out["absent"] == 1
    fb = json.loads(t.calls[6]["messages"][-1]["content"][0]["content"])
    assert "uncommitted: page 2 not read" in fb["error"]
    derived = [r for r in db.rows["sources"] if r["kind"] == "part_images"][0]
    assert derived["storage_paths"] == [f"{job.score_id}/parts/piano/p002-s1.png"]
    assert [s["staves"] for s in derived["meta"]["systems"]] == ["absent", [4, 5]]


OVERLAY_HEADER = {"instruments": [
    {"label": "Flauti I. II.", "abbreviations": ["Fl."], "boxes": [1], "staves": 2, "clefs": ["treble"], "family": "woodwind"},  # a pair on one staff
    {"label": "Oboi", "abbreviations": ["Ob."], "boxes": [2], "staves": 1, "clefs": ["treble"], "family": "woodwind"},
    {"label": "Corni in F", "abbreviations": ["Cor."], "boxes": [3], "staves": 1, "clefs": ["treble"], "family": "brass"},
    {"label": "Pianoforte", "abbreviations": ["Pfte."], "boxes": [4, 5], "staves": 2, "clefs": ["treble", "bass"], "family": "keyboard"},
    {"label": "Violini I.", "abbreviations": ["Vl. I"], "boxes": [6], "staves": 1, "clefs": ["treble"], "family": "strings"}],
    "staff_total": 7, "key": "F# minor", "time": "4/4", "tempo": "Vivace"}


@pytest.mark.asyncio
async def test_header_from_overlay_drives_the_proposal():
    """The header is read from page 1's numbered overlay with an 8k budget, retried once when cut off, reconciled
    against the boxes (the flute pair is 1 staff), and the page's proposal follows from it by score order when the
    label call gives nothing usable."""
    script = [tool("read_header", {}), truncated(text('{"instruments": [{"label": "Flauti')), text(json.dumps(OVERLAY_HEADER)),
              tool("read_page", {"page": 1}), text('{"confidence": "high"}'), text("still no JSON"),   # JSON without systems counts as a miss
              commit(1, [4, 5]), RECHECK_PIANO, tool("finish", {})]
    client, t = fake_client(script)
    job, ctx, db = world(1, {"instrument": "Piano (solo)"})
    out = await part_cut(job, ctx, client=client)
    assert out["systems_cut"] == 1 and out["questions"] == 0
    for call in t.calls[1:3]:
        assert call["max_tokens"] >= 8000 and call["output_config"]["effort"] == "low"
        img = call["messages"][0]["content"][0]["source"]["data"]
        assert img == ctx.png_b64(ctx.uploads[f"{job.score_id}/parts/piano-solo/overlay-p001.png"])     # the numbered overlay
        assert "yellow box numbers" in call["messages"][0]["content"][1]["text"]
        assert "strict JSON" in call["system"] and "tool" not in call["system"]          # not the agent's system prompt
    sc = ctx.result["agent"]["scratch"]
    h = sc["header"]
    assert [(i["name"], i["staves"]) for i in h["instruments"]] == [("Flauti I. II.", 1), ("Oboi", 1), ("Corni in F", 1), ("Pianoforte", 2), ("Violini I.", 1)]
    assert h["expected_staves"] == 6 and h["validation"]["match"] and h["key"] == "F# minor" and len(h["retries"]) == 1
    assert sc["log"][0].startswith("Header: Flauti I. II. (1), Oboi (1), Corni in F (1), Pianoforte (2), Violini I. (1); 6 staves")
    label_prompt = t.calls[4]["messages"][0]["content"][1]["text"]
    assert "by order the wanted instrument is staff [4, 5]" in label_prompt and "(2 staves per system" in label_prompt
    assert sc["pages"]["1"]["proposal"] == [{"system": 1, "staves": [4, 5], "blocks": [[4, 5]], "per_instrument": {"Piano (solo)": [4, 5]}, "status": "by-order"}]
    assert "no 'systems' list" in sc["pages"]["1"]["summary"]["notes"] and sc["cost_usd"] > 0
    assert len(t.calls) == 1 + 2 + 1 + 2 + 1 + 1 + 1 and len(ctx.charges) == len(t.calls)


@pytest.mark.parametrize("wanted,label", [
    ("Piano", "Pianoforte"), ("Piano (solo)", "Pianoforte"), ("Pno.", "Pianoforte"),
    ("Violin I", "Violini I."), ("Vn. I", "Violini I."), ("Violini I", "Violini I."), ("Violin II", "Violini II."), ("Violin", "Violini I."),
    ("Flute 1", "Flauti I. II."), ("Flute", "Flauti I. II."), ("Cello", "Violoncelli"), ("Contrabass", "Contrabassi"), ("Double Bass", "Contrabassi"),
    ("Horn", "Corni in F"), ("Trumpet", "Trombe in B"), ("Trombone", "Tromboni"), ("Timpani", "Timpani"), ("Viola", "Viole"),
    ("Soprano", "Soprano"), ("Alto", "Alto"), ("Bass", "Basso")])
def test_matcher_names_abbreviations_synonyms_numerals(wanted, label):
    inst = [{"label": x, "abbreviations": a, "family": f} for x, a, f in [
        ("Flauti I. II.", ["Fl."], "woodwind"), ("Corni in F", ["Cor."], "brass"), ("Trombe in B", ["Tr."], "brass"), ("Tromboni", ["Trbni."], "brass"),
        ("Timpani", ["Timp."], "percussion"), ("Pianoforte", ["Pfte."], "keyboard"), ("Soprano", ["S."], "voice"), ("Alto", ["A."], "voice"),
        ("Basso", ["B."], "voice"), ("Violini I.", ["Vl. I"], "strings"), ("Violini II.", ["Vl. II"], "strings"), ("Viole", ["Vle."], "strings"),
        ("Violoncelli", ["Vc."], "strings"), ("Contrabassi", ["Cb."], "strings")]]
    m = match_instrument(inst, wanted)
    assert m is not None and m["label"] == label


def test_same_instrument_for_the_recheck():
    assert same_instrument("Pno.", "Piano (solo)") and same_instrument("Violins", "Violin I") and same_instrument("Vl. I", "Violini I")
    assert same_instrument("Flauti I. II.", "Flute 1") and same_instrument("Klavier", "Piano")
    assert not same_instrument("Violini II", "Violin I") and not same_instrument("Viola", "Violin I") and not same_instrument("Violoncello", "Contrabass")
    assert not same_instrument("Corno inglese", "Horn") and not same_instrument("Oboe", "Piano")


@pytest.mark.asyncio
async def test_absent_refused_when_the_labels_propose_staves():
    client, t = fake_client([tool("read_header", {}), HEADER, tool("read_page", {"page": 1}), LABEL, commit(1, "absent"),
                             commit(1, [4, 5]), RECHECK_PIANO, tool("finish", {})])
    job, ctx, db = world(1)
    out = await part_cut(job, ctx, client=client)
    assert out["systems_cut"] == 1 and out["absent"] == 0
    fb = json.loads(t.calls[5]["messages"][-1]["content"][0]["content"])
    assert "proposed staves [4, 5]" in fb["error"]


# ---------------------------------------------------------------- several instruments at once (the multi-part contract)

def multi_label(**staves_by_instrument):
    return text(json.dumps({"systems": [{"index": 1, "wanted": [{"instrument": k, "staves": v, "status": "playing" if v else "absent"} for k, v in staves_by_instrument.items()]}],
                            "confidence": "high"}))


def recheck(name: str, matches: bool = True, clefs: list[str] | None = None):
    """The closed recheck's answer: yes (with the margin label seen) unless `matches` is False; `clefs` is what Spark saw."""
    return text(json.dumps({"matches": matches, "staves_seen": 1, "clefs_seen": clefs or [], "label_seen": name, "why": "label" if matches else f"the margin says {name}"}))


@pytest.mark.asyncio
async def test_two_blocks_are_cut_separately_and_stacked():
    """Flute (staff 1) and Horn (staff 3) skip the oboe: each run is its own block, rechecked on its own, and the
    strip is the two blocks stacked with a gap. A recheck that names the wrong instrument for one block refuses the
    whole commit."""
    from app.librarian.cut import cut_system, page_geometry
    script = [tool("read_header", {}), HEADER, tool("read_page", {"page": 1}), multi_label(Flute=[1], Horn=[3]),
              tool("commit_system", {"page": 1, "system": 1, "blocks": [[1], [3]]}), recheck("Fl."), RECHECK_VIOLIN,   # block 2 is not a horn: refused
              tool("commit_system", {"page": 1, "system": 1, "staves": [1, 3]}), recheck("Flauti"), recheck("Cor."),   # same cut given as staves
              tool("finish", {})]
    client, t = fake_client(script)
    job, ctx, db = world(1, {"instruments": ["Flute", "Horn"]})
    del job.payload["instrument"]
    out = await part_cut(job, ctx, client=client)
    assert out["systems_cut"] == 1 and out["questions"] == 0
    key = f"{job.score_id}/parts/flute+horn/p001-s1.png"
    assert key in ctx.uploads
    fb = json.loads(t.calls[7]["messages"][-1]["content"][0]["content"])
    assert "block of staves [3] alone against the header" in fb["error"] and "the Horn" in fb["error"] and "does not match" in fb["error"] and "'Vl.'" in fb["error"]
    # the strip is block [1] over block [3] with a gap of 1.5 staff spaces (12 px at spacing 8)
    geom, bw, im = page_geometry(synth_page())
    crop1, _, _ = cut_system(bw, im, geom, geom["systems"][0], [1])
    crop3, _, _ = cut_system(bw, im, geom, geom["systems"][0], [3])
    strip = Image.open(io.BytesIO(ctx.uploads[key]))
    assert strip.size == (max(crop1.width, crop3.width), crop1.height + 12 + crop3.height)
    assert strip.crop((0, crop1.height, strip.width, crop1.height + 12)).convert("L").getextrema() == (255, 255)   # the gap is white
    imgs = [c["messages"][0]["content"][0]["source"]["data"] for c in t.calls[8:10]]                               # one recheck per block
    assert imgs[0] != imgs[1]
    derived = [r for r in db.rows["sources"] if r["kind"] == "part_images"][0]
    assert derived["meta"]["instruments"] == ["Flute", "Horn"] and derived["meta"]["instrument"] == "Flute + Horn" and derived["meta"]["slug"] == "flute+horn"
    assert derived["meta"]["systems"] == [{"page": 1, "system": 1, "staves": [1, 3], "blocks": [[1], [3]], "key": key, "bars": derived["meta"]["systems"][0]["bars"]}]
    sc = ctx.result["agent"]["scratch"]
    assert sc["pages"]["1"]["proposal"] == [{"system": 1, "staves": [1, 3], "blocks": [[1], [3]], "per_instrument": {"Flute": [1], "Horn": [3]}, "status": "playing"}]
    assert sc["commits"]["1:1"]["blocks"] == [[1], [3]] and len(sc["commits"]["1:1"]["verify"]) == 2 and len(sc["commits"]["1:1"]["boxes"]) == 2
    assert any("2 blocks stacked" in line for line in sc["log"])
    assert [r["name"] for r in db.rows["parts"]] == ["Flute + Horn"]
    label_prompt = t.calls[3]["messages"][0]["content"][1]["text"]
    assert 'Instruments wanted: "Flute" (1 staves per system according to the header), "Horn" (1 staves' in label_prompt
    assert label_prompt.count("Score header (read from the first page)") == 1 and '"Flute" is printed as' in label_prompt and '"Horn" is printed as' in label_prompt


@pytest.mark.asyncio
async def test_adjacent_instruments_are_one_block():
    """Flute and Oboe sit on staves 1 and 2: one block, one clean pass, one recheck (which may name either)."""
    script = [tool("read_header", {}), HEADER, tool("read_page", {"page": 1}), multi_label(Flute=[1], Oboe=[2]),
              commit(1, [1, 2]), recheck("Oboi"), tool("finish", {})]
    client, t = fake_client(script)
    job, ctx, db = world(1, {"instruments": ["Flute", "Oboe"]})
    out = await part_cut(job, ctx, client=client)
    assert out["systems_cut"] == 1
    assert len(t.calls) == 7 and len(ctx.charges) == 7                                  # one recheck for the one block
    key = f"{job.score_id}/parts/flute+oboe/p001-s1.png"
    assert key in ctx.uploads
    derived = [r for r in db.rows["sources"] if r["kind"] == "part_images"][0]
    assert derived["meta"]["systems"][0]["blocks"] == [[1, 2]] and derived["meta"]["systems"][0]["staves"] == [1, 2]
    sc = ctx.result["agent"]["scratch"]
    assert sc["commits"]["1:1"]["blocks"] == [[1, 2]] and len(sc["commits"]["1:1"]["verify"]) == 1
    assert any("(one block)" in line for line in sc["log"])
    header_result = json.loads(t.calls[2]["messages"][-1]["content"][0]["content"])
    assert header_result["staves_total"] == 2 and header_result["staves_per_system"] == {"Flute": 1, "Oboe": 1}
    # a commit that names only one of the two instruments' staves is refused with the per-instrument counts
    client2, t2 = fake_client([tool("read_header", {}), HEADER, tool("read_page", {"page": 1}), multi_label(Flute=[1], Oboe=[2]),
                               commit(1, [1]), commit(1, [1, 2]), recheck("Fl."), tool("finish", {})])
    job2, ctx2, _ = world(1, {"instruments": ["Flute", "Oboe"]})
    await part_cut(job2, ctx2, client=client2)
    fb = json.loads(t2.calls[5]["messages"][-1]["content"][0]["content"])
    assert "Flute + Oboe has 2 staves per system according to the header (Flute 1, Oboe 1); you named 1" in fb["error"]


@pytest.mark.asyncio
async def test_recheck_is_per_block_and_blocks_must_agree_with_the_labels():
    """The recheck is asked per block against that block's own header entry (checking the export as a whole was tried
    and shipped alto + tenor on Beethoven 9 S+T run 2), and a block one staff off the labels is refused before any model call."""
    script = [tool("read_header", {}), HEADER, tool("read_page", {"page": 1}), multi_label(Flute=[1], Horn=[3]),
              tool("commit_system", {"page": 1, "system": 1, "blocks": [[2, 3]]}),      # staff 2 is nobody's by the labels: no model call
              commit(1, [1, 3]), recheck("Cor.", matches=False),                        # the flute block does not look like the flute: refused
              commit(1, [1, 3]), recheck("Fl."), recheck("Horn"), tool("finish", {})]
    client, t = fake_client(script)
    job, ctx, db = world(1, {"instruments": ["Flute", "Horn"]})
    out = await part_cut(job, ctx, client=client)
    assert out["systems_cut"] == 1 and out["questions"] == 0
    fb = json.loads(t.calls[5]["messages"][-1]["content"][0]["content"])
    assert "the labels put Horn on [3] in system 1; the block [2, 3] adds staff [2] that the labels give to no wanted instrument" in fb["error"]
    fb = json.loads(t.calls[7]["messages"][-1]["content"][0]["content"])
    assert "block of staves [1] alone against the header (According to the score header and the page's staff labels this block is the Flute: 1 staff" in fb["error"] and "the margin says Cor." in fb["error"]
    assert len(t.calls) == 11


@pytest.mark.asyncio
async def test_vocal_pair_passes_barlines_per_staff():
    """A choir's barlines stop at each staff: the whole-span check fails on the pair, every staff passes alone, and
    the commit goes through with the fallback recorded."""
    from app.librarian.cut import cut_system, page_geometry
    page = synth_page(vocal_gap=True)
    geom, bw, im = page_geometry(page)
    _, _, checks = cut_system(bw, im, geom, geom["systems"][0], [1, 2])
    assert not checks["pass"] and not checks["barlines_present"]["pass"] and checks["staves_in_crop"]["pass"]   # the plain verify refuses the pair
    script = [tool("read_header", {}), HEADER, tool("read_page", {"page": 1}), multi_label(Flute=[1], Oboe=[2]),
              commit(1, [1, 2]), recheck("Flauti"), tool("finish", {})]
    client, t = fake_client(script)
    job, ctx, db = world(1, {"instruments": ["Flute", "Oboe"]}, page=page)
    out = await part_cut(job, ctx, client=client)
    assert out["systems_cut"] == 1 and out["questions"] == 0
    v = ctx.result["agent"]["scratch"]["commits"]["1:1"]["verify"][0]
    assert v["barlines_present"]["pass"] and v["barlines_present"]["per_staff"] is True and v["pass"]


@pytest.mark.asyncio
async def test_absent_for_every_chosen_instrument():
    script = [tool("read_header", {}), HEADER, tool("read_page", {"page": 1}), multi_label(Soprano=[], Alto=[]),
              tool("commit_system", {"page": 1, "system": 1, "blocks": "absent"}), tool("finish", {})]
    client, t = fake_client(script)
    job, ctx, db = world(1, {"instruments": ["Soprano", "Alto"]})
    out = await part_cut(job, ctx, client=client)
    assert out["systems_cut"] == 0 and out["absent"] == 1
    sc = ctx.result["agent"]["scratch"]
    assert sc["pages"]["1"]["proposal"] == [{"system": 1, "staves": [], "blocks": [], "per_instrument": {"Soprano": [], "Alto": []}, "status": "absent"}]
    assert sc["commits"]["1:1"] == {"staves": "absent", "blocks": [], "key": None, "verify": None}
    derived = [r for r in db.rows["sources"] if r["kind"] == "part_images"][0]
    assert derived["storage_paths"] == [] and derived["meta"]["systems"] == [{"page": 1, "system": 1, "staves": "absent", "blocks": [], "key": None, "bars": None}]


@pytest.mark.asyncio
async def test_question_and_answer_carry_blocks():
    """Three refused commits park the run; the question names the instruments and the proposal's blocks; the admin's
    `{"blocks": [[1], [3]]}` is applied as a commit without a recheck."""
    client, t = fake_client([tool("read_header", {}), HEADER, tool("read_page", {"page": 1}), multi_label(Flute=[1], Horn=[3]),
                             commit(1, [1]), commit(1, [1, 2, 3]), tool("commit_system", {"page": 1, "system": 1, "blocks": [[1], [9]]})])   # all refused before any model call
    job, ctx, db = world(1, {"instruments": ["Flute", "Horn"]})
    out = await part_cut(job, ctx, client=client)
    q = out["question_payload"]
    assert q["kind"] == "choose_staves" and q["instruments"] == ["Flute", "Horn"] and q["instrument"] == "Flute + Horn"
    assert q["proposal"] == [1, 3] and q["blocks"] == [{"staves": [1], "instruments": ["Flute"]}, {"staves": [3], "instruments": ["Horn"]}]
    assert q["last_attempt"] == [[1], [9]] and q["staves_per_instrument"] == {"Flute": 1, "Horn": 1} and q["allowed"]["blocks"]
    assert "staves [9] are not in system 1" in q["feedback"]
    assert out["question"] == "Which staves are the Flute + Horn's on page 1, line 1?"
    db.rows["jobs"][-1]["result"] = out
    client2, t2 = fake_client([tool("finish", {})])
    job2, ctx2, _ = world(1, {"instruments": ["Flute", "Horn"], "answer": {"blocks": [[1], [3]]}, "resume_from": job.id}, db=db)
    out2 = await part_cut(job2, ctx2, client=client2)
    assert out2["systems_cut"] == 1 and out2["questions"] == 1 and len(t2.calls) == 1
    assert f"{job.score_id}/parts/flute+horn/p001-s1.png" in ctx2.uploads
    assert "admin decided page 1 system 1: [1, 3]" in t2.calls[0]["messages"][-1]["content"]
    assert ctx2.result["agent"]["scratch"]["commits"]["1:1"]["blocks"] == [[1], [3]]


@pytest.mark.asyncio
async def test_admin_answer_is_final_even_against_the_header_count():
    """The geometry may have missed a staff: the admin's `{"staves": [2]}` for a two-instrument export is applied
    without the count, verify or recheck refusals (011: answers are the admin's words)."""
    client, t = fake_client([tool("read_header", {}), HEADER, tool("read_page", {"page": 1}), multi_label(Flute=[1], Horn=[3]),
                             commit(1, [1]), commit(1, [1, 2, 3]), commit(1, [9])])
    job, ctx, db = world(1, {"instruments": ["Flute", "Horn"]})
    out = await part_cut(job, ctx, client=client)
    assert out["agent"]["status"] == "needs_review"
    db.rows["jobs"][-1]["result"] = out
    client2, t2 = fake_client([tool("finish", {})])
    job2, ctx2, _ = world(1, {"instruments": ["Flute", "Horn"], "answer": {"staves": [2]}, "resume_from": job.id}, db=db)
    out2 = await part_cut(job2, ctx2, client=client2)
    assert out2["systems_cut"] == 1 and len(t2.calls) == 1
    assert ctx2.result["agent"]["scratch"]["commits"]["1:1"]["staves"] == [2] and f"{job.score_id}/parts/flute+horn/p001-s1.png" in ctx2.uploads


HEADER_CHOIR = text(json.dumps({"instruments": [
    {"label": "Flauti", "staves": 1, "clefs": ["treble"], "family": "woodwind"}, {"label": "Oboi", "staves": 1, "clefs": ["treble"], "family": "woodwind"},
    {"label": "CORO Soprano", "staves": 1, "clefs": ["soprano"], "family": "voice"}, {"label": "CORO Alto", "staves": 1, "clefs": ["alto"], "family": "voice"},
    {"label": "CORO Tenore", "staves": 1, "clefs": ["tenor"], "family": "voice"}, {"label": "Violini I", "staves": 1, "clefs": ["treble"], "family": "strings"}]}))


@pytest.mark.asyncio
@pytest.mark.parametrize("wanted,block,flags,above_text", [
    (["Alto"], [4], (True, True), "voice staves of the chorus"),       # under the soprano: both flags, the lyric rule on both sides
    (["Soprano"], [3], (True, False), "voice staves of the chorus"),   # under the oboe
    (["Flute"], [1], (False, False), None),                            # an orchestral staff: the old rules, no chorus text
])
async def test_voice_flags_reach_cut_system_and_the_recheck_gets_the_header_clefs(monkeypatch, wanted, block, flags, above_text):
    """The header's families decide `voice` / `voice_above` for the clean pass (the staff above by score order when
    the system is full), the commit records them, and the closed recheck prompt states the header's part and clef for
    the block and, for voices, that these are chorus staves in C clefs."""
    import app.librarian.part_cut as pc
    seen: list[dict] = []
    real = pc.cut_system

    def spy(bw, page, geom, system, staves, **kw):
        seen.append({"staves": staves, **kw})
        return real(bw, page, geom, system, staves, **kw)
    monkeypatch.setattr(pc, "cut_system", spy)
    script = [tool("read_header", {}), HEADER_CHOIR, tool("read_page", {"page": 1}), multi_label(**{wanted[0]: block}),
              commit(1, block), recheck(wanted[0]), tool("finish", {})]
    client, t = fake_client(script)
    job, ctx, db = world(1, {"instruments": wanted})
    out = await part_cut(job, ctx, client=client)
    assert out["systems_cut"] == 1
    assert seen == [{"staves": block, "voice": flags[0], "voice_above": flags[1]}]
    sc = ctx.result["agent"]["scratch"]
    assert sc["commits"]["1:1"]["voices"][0]["voice"] is flags[0] and sc["commits"]["1:1"]["voices"][0]["voice_above"] is flags[1]
    assert sc["pages"]["1"]["geometry"]["expected_staves"] == 6 and sc["pages"]["1"]["geometry"]["staves_before_recovery"] == [6]   # page 1 re-read with the header
    prompt = t.calls[5]["messages"][0]["content"][1]["text"]
    expect = {"Alto": "the CORO Alto: 1 staff in the alto clef", "Soprano": "the CORO Soprano: 1 staff in the soprano clef", "Flute": "the Flauti: 1 staff in the treble clef"}[wanted[0]]
    assert f"this block is {expect}." in prompt and "Does this crop look like that: 1 staff in the" in prompt and '"matches": true|false' in prompt
    if above_text:
        assert above_text in prompt and "soprano clef, C on the bottom line" in prompt
    else:
        assert "chorus" not in prompt
    rc = sc["commits"]["1:1"]["rechecks"][0]
    assert rc["verdict"] == "yes" and rc["matches"] is True and rc["label_seen"] == wanted[0]


def test_header_position_helpers():
    from app.librarian.header import at_position, is_voice, previous_entry
    h = {"instruments": [{"label": "Flauti", "staves": 1, "family": "woodwind", "position": 1}, {"label": "Pianoforte", "staves": 2, "family": "keyboard", "position": 2},
                         {"label": "CORO Soprano", "staves": 1, "family": "voice", "position": 3}, {"label": "Bassi", "staves": 1, "family": "strings", "position": 4}]}
    full = {"staff_indices": [1, 2, 3, 4, 5]}
    assert at_position(h, full, 1)["label"] == "Flauti" and at_position(h, full, 3)["label"] == "Pianoforte" and at_position(h, full, 4)["label"] == "CORO Soprano"
    assert at_position(h, {"staff_indices": [1, 2, 3]}, 2) is None and at_position(h, full, 9) is None       # short system, unknown staff
    assert previous_entry(h, "Soprano")["label"] == "Pianoforte" and previous_entry(h, "Flute") is None and previous_entry(h, "Timpani") is None
    assert is_voice(h["instruments"][2]) and not is_voice(h["instruments"][3], "Bass") and is_voice(None, "Bass") and not is_voice(None, "Viola")


def test_instruments_payload_forms():
    from app.librarian.part_cut import instruments_of, parse_answer, runs
    assert instruments_of({"instrument": "Piano"}) == ["Piano"]
    assert instruments_of({"instruments": ["Soprano", " Alto ", "Soprano", ""]}) == ["Soprano", "Alto"]
    assert instruments_of({"instruments": "Tenor"}) == ["Tenor"] and instruments_of({}) == []
    assert runs([12, 11, 14, 15, 17]) == [[11, 12], [14, 15], [17]] and runs([]) == []
    assert parse_answer({"staves": [11, 12]}) == [11, 12] and parse_answer({"blocks": [[13], [11]]}) == [11, 13]
    assert parse_answer({"staves": "absent"}) == "absent" and parse_answer("absent") == "absent" and parse_answer({"blocks": "absent"}) == "absent"
    assert parse_answer("11, 12") == [11, 12] and parse_answer('{"blocks": [[3], [1]]}') == [1, 3] and parse_answer({"staves": []}) == "absent"


@pytest.mark.asyncio
async def test_closed_recheck_yes_no_and_clef_paths():
    """The recheck is a closed question against the header: yes commits; no refuses (the run asks the admin after three);
    yes with a clef that contradicts the header refuses too (a bass clef where the header has the flute's treble); for a
    voice any C clef or the treble passes (Spark confuses the C clefs: Beethoven 9 soprano read as alto), a bass clef not."""
    import app.librarian.part_cut as pc
    # Flute, header clef treble: no -> refused; yes with a bass clef seen -> refused; yes with "G clef" (another spelling) -> accepted
    script = [tool("read_header", {}), HEADER_CHOIR, tool("read_page", {"page": 1}), multi_label(Flute=[1]),
              commit(1, [1]), recheck("Fl.", matches=False, clefs=["treble"]),
              commit(1, [1]), recheck("Fl.", clefs=["bass"]),
              commit(1, [1]), recheck("", clefs=["G clef"]), tool("finish", {})]
    client, t = fake_client(script)
    job, ctx, db = world(1, {"instruments": ["Flute"]})
    out = await part_cut(job, ctx, client=client)
    assert out["systems_cut"] == 1 and out["questions"] == 0
    fb = json.loads(t.calls[6]["messages"][-1]["content"][0]["content"])
    assert "the model says it does not match" in fb["error"] and "the margin says Fl." in fb["error"]
    fb = json.loads(t.calls[8]["messages"][-1]["content"][0]["content"])
    assert "sees the bass clef where the header expects treble" in fb["error"]
    rc = ctx.result["agent"]["scratch"]["commits"]["1:1"]["rechecks"]
    assert [r["verdict"] for r in rc] == ["yes"] and rc[0]["clefs_seen"] == ["G clef"]
    # Soprano, header clef soprano: seen "alto" passes (lenient C clefs for voices); seen "bass" contradicts
    script = [tool("read_header", {}), HEADER_CHOIR, tool("read_page", {"page": 1}), multi_label(Soprano=[3]),
              commit(1, [3]), recheck("S.", clefs=["bass"]),
              commit(1, [3]), recheck("", clefs=["alto"]), tool("finish", {})]
    client, t = fake_client(script)
    job, ctx, db = world(1, {"instruments": ["Soprano"]})
    out = await part_cut(job, ctx, client=client)
    assert out["systems_cut"] == 1
    fb = json.loads(t.calls[6]["messages"][-1]["content"][0]["content"])
    assert "sees the bass clef where the header expects soprano" in fb["error"]
    assert ctx.result["agent"]["scratch"]["commits"]["1:1"]["rechecks"][0]["clefs_seen"] == ["alto"]
    # three noes in a row park the run with the choose_staves question
    script = [tool("read_header", {}), HEADER_CHOIR, tool("read_page", {"page": 1}), multi_label(Soprano=[3])]
    for _ in range(3):
        script += [commit(1, [3]), recheck("A.", matches=False)]
    client, t = fake_client(script)
    job, ctx, db = world(1, {"instruments": ["Soprano"]})
    out = await part_cut(job, ctx, client=client)
    assert out["agent"]["status"] == "needs_review" and out["question_payload"]["kind"] == "choose_staves" and out["question_payload"]["last_attempt"] == [3]
    assert "the margin says A." in out["question_payload"]["feedback"]
    assert pc.clefs_fit(["tenor"], ["soprano"], True) and not pc.clefs_fit(["treble"], ["bass"], True) and pc.clefs_fit(["C3"], ["treble"], True)
    assert pc.clefs_fit(["C clef"], ["alto"], False) and not pc.clefs_fit(["C clef"], ["treble"], False) and pc.clefs_fit(["odd"], ["treble"], False)


@pytest.mark.asyncio
async def test_recheck_claim_takes_the_voice_clef_from_a_one_entry_chorus():
    """Beethoven 9's live header lists the choir as one entry "CORO." of four staves with clefs S A T B: the soprano's
    claim still names the soprano clef (by the clef named after the voice, else by S A T B order)."""
    header = text(json.dumps({"instruments": [{"label": "Flauti", "staves": 1, "clefs": ["treble"], "family": "woodwind"},
                                              {"label": "CORO.", "staves": 4, "clefs": ["soprano", "alto", "tenor", "bass"], "family": "voice"},
                                              {"label": "Violoncelli", "staves": 1, "clefs": ["bass"], "family": "strings"}]}))
    script = [tool("read_header", {}), header, tool("read_page", {"page": 1}), multi_label(Tenor=[4]),
              commit(1, [4]), recheck("", clefs=["tenor"]), tool("finish", {})]
    client, t = fake_client(script)
    job, ctx, db = world(1, {"instruments": ["Tenor"]})
    out = await part_cut(job, ctx, client=client)
    assert out["systems_cut"] == 1
    prompt = t.calls[5]["messages"][0]["content"][1]["text"]
    assert "this block is the Tenor: 1 staff in the tenor clef." in prompt and "voice staves of the chorus" in prompt


# ---------------------------------------------------------------- the book's label memory (006 agentic memory rule)

KLAV_HEADER = text(json.dumps({"instruments": [{"label": "Flöten", "staves": 1}, {"label": "Oboen", "staves": 1}, {"label": "Hörner", "staves": 1},
                                               {"label": "Klavier", "staves": 2}, {"label": "Violine I", "staves": 1}], "key": "C major", "time": "4/4"}))


def label_margin(margins: list[tuple[str, list[int]]], wanted: list[int] | None = None):
    """The label reply with the printed margin labels Spark read on system 1."""
    return text(json.dumps({"systems": [{"index": 1, "wanted_staves": [4, 5] if wanted is None else wanted, "status": "playing",
                                         "margin_labels": [{"text": t, "staves": s} for t, s in margins]}], "confidence": "high"}))


def doubt(label: str):
    """The recheck of PC3 p. 2 and 3 (2026-10-30): the label is read right, the crop is doubted for neighbour ink."""
    return text(json.dumps({"matches": False, "staves_seen": 3, "clefs_seen": ["treble", "bass"], "label_seen": label,
                            "why": f"{label} brace shows treble and bass but notes from the staff above intrude at the top edge"}))


@pytest.mark.asyncio
async def test_the_header_seeds_the_memory_and_a_known_label_outweighs_the_crops_doubts():
    """The book's first page reads "Klavier"; page 2 prints "Klav.". The label the memory knows (from the header) sits on
    exactly the staves the page's proposal gives the piano, so both blocks are settled with no recheck call (speed pass
    2026-10-30: before, both rechecks doubted the crop for neighbour ink and the label outweighed them), no question."""
    script = [tool("read_header", {}), KLAV_HEADER,
              tool("read_page", {"page": 1}), label_margin([("Flöten", [1]), ("Klavier", [4, 5])]), commit(1, [4, 5]),
              tool("read_page", {"page": 2}), label_margin([("Fl.", [1]), ("Klav.", [4, 5])]), commit(2, [4, 5]),
              tool("finish", {})]
    client, t = fake_client(script)
    job, ctx, db = world(2)
    out = await part_cut(job, ctx, client=client)
    assert out["systems_cut"] == 2 and out["questions"] == 0 and ctx.result["agent"]["refusals"] == {}
    assert len(t.calls) == len(script)                                              # no recheck call at all
    sc = ctx.result["agent"]["scratch"]
    assert [sc["commits"][k]["rechecks"][0]["verdict"] for k in ("1:1", "2:1")] == ["remembered", "remembered"]
    assert [sc["commits"][k]["rechecks"][0]["source"] for k in ("1:1", "2:1")] == ["model", "model"]
    assert sc["pages"]["2"]["proposal"][0]["remembered"]["Piano"] == {"staves": [4, 5], "label": "Klav.", "source": "model", "origin": "header",
                                                                      "page": 1, "agreed": True}
    page2_prompt = t.calls[6]["messages"][0]["content"][1]["text"]
    assert 'Known labels in this book: "Klavier" is Piano (read from the first page)' in page2_prompt
    mem = db.rows["scores"][0]["label_memory"]["entries"]
    assert mem["klavier"]["part"] == "Piano" and mem["klavier"]["source"] == "model"
    interp = [r for r in db.rows["interpretations"] if r.get("engine") == "part-cut-agent"][0]
    assert interp["summary"]["settled_by_memory"] == 2


@pytest.mark.asyncio
async def test_a_human_answer_is_remembered_for_the_later_pages():
    """Page 1's margin is bare to the label read, so the doubting recheck parks the run; the admin answers [4, 5]. The
    label the recheck saw on that block ("Klavier") is remembered as the admin's; page 2 prints "Klav.", which
    resolves to it, so page 2 is committed with no recheck and no second question: one question for the book."""
    script = [tool("read_header", {}), KLAV_HEADER, tool("read_page", {"page": 1}), label_margin([]),
              commit(1, [4, 5]), doubt("Klavier"), commit(1, [4, 5]), doubt("Klavier"), commit(1, [4, 5]), doubt("Klavier")]
    client, t = fake_client(script)
    job, ctx, db = world(2)
    out = await part_cut(job, ctx, client=client)
    assert out["question_payload"]["kind"] == "choose_staves" and out["question_payload"]["page"] == 1
    assert {"label": "Klavier", "part": "Piano", "source": "model", "origin": "header", "page": 1} in out["question_payload"]["known_labels"]
    db.rows["jobs"][-1]["result"] = out
    client2, t2 = fake_client([tool("read_page", {"page": 2}), label_margin([("Klav.", [4, 5])]), commit(2, [4, 5]), tool("finish", {})])
    job2, ctx2, _ = world(2, {"answer": {"staves": [4, 5]}, "resume_from": job.id}, db=db)
    out2 = await part_cut(job2, ctx2, client=client2)
    assert out2["systems_cut"] == 2 and out2["questions"] == 1                     # at most one question for the two pages
    assert len(t2.calls) == 4                                                       # page 2: no recheck call at all
    assert "Remembered for the later pages: 'Klavier' is Piano" in t2.calls[0]["messages"][-1]["content"]
    sc = ctx2.result["agent"]["scratch"]
    assert sc["commits"]["2:1"]["rechecks"] == [{"block": [4, 5], "verdict": "remembered", "source": "human", "labels": ["Klav."], "pages": [1]}]
    mem = db.rows["scores"][0]["label_memory"]["entries"]
    assert mem["klavier"]["source"] == "human" and mem["klavier"]["origin"] == "answer" and mem["klavier"]["page"] == 1 and mem["klavier"]["job_id"] == job2.id
    assert 'Known labels in this book: "Klavier" is Piano (confirmed by the user on page 1)' in t2.calls[1]["messages"][0]["content"][1]["text"]


@pytest.mark.asyncio
async def test_a_new_label_still_asks():
    """A label the memory does not know ("Org." for the wanted Piano) settles nothing: three doubting rechecks park
    the run with the question as before, and nothing is learned from the model."""
    script = [tool("read_header", {}), KLAV_HEADER, tool("read_page", {"page": 1}), label_margin([("Org.", [4, 5])]),
              commit(1, [4, 5]), doubt("Org."), commit(1, [4, 5]), doubt("Org."), commit(1, [4, 5]), doubt("Org.")]
    client, t = fake_client(script)
    job, ctx, db = world(1)
    out = await part_cut(job, ctx, client=client)
    assert out["question_payload"]["kind"] == "choose_staves" and "remembered" not in ctx.result["agent"]["scratch"]["pages"]["1"]["proposal"][0]
    assert "org" not in db.rows["scores"][0]["label_memory"]["entries"]


@pytest.mark.asyncio
async def test_a_human_memory_settles_only_where_the_page_agrees():
    """The admin confirmed "Klav." earlier (in the row); on this page the label read puts "Klav." on [3, 4] while the
    wanted-staves read says [4, 5]: the two reads disagree, nothing is settled, and the recheck runs as usual."""
    script = [tool("read_header", {}), KLAV_HEADER, tool("read_page", {"page": 1}), label_margin([("Klav.", [3, 4])]),
              commit(1, [4, 5]), RECHECK_PIANO, tool("finish", {})]
    client, t = fake_client(script)
    job, ctx, db = world(1)
    db.rows["scores"][0]["label_memory"] = {"entries": {"klav": {"label": "Klav.", "part": "Piano", "source": "human", "origin": "answer", "page": 7}}}
    out = await part_cut(job, ctx, client=client)
    assert out["systems_cut"] == 1 and len(t.calls) == 7
    prop = ctx.result["agent"]["scratch"]["pages"]["1"]["proposal"][0]
    assert "remembered" not in prop and prop["label_conflicts"] == [{"instrument": "Piano", "label": "Klav.", "label_staves": [3, 4], "proposed": [4, 5]}]
    assert ctx.result["agent"]["scratch"]["commits"]["1:1"]["rechecks"][0]["verdict"] == "yes"


@pytest.mark.asyncio
async def test_the_cut_reuses_the_books_header():
    """The book's first reading (process_pages, 004) already holds the header: read_header makes no model call."""
    book = {"page": 1, "expected_staves": 6, "instruments": [
        {"position": 1, "name": "Flute", "label": "Flute", "abbreviations": ["Fl."], "boxes": [1], "staves": 1, "clefs": ["treble"], "family": "woodwind"},
        {"position": 2, "name": "Oboe", "label": "Oboe", "abbreviations": [], "boxes": [2], "staves": 1, "clefs": ["treble"], "family": "woodwind"},
        {"position": 3, "name": "Horn", "label": "Horn", "abbreviations": [], "boxes": [3], "staves": 1, "clefs": ["treble"], "family": "brass"},
        {"position": 4, "name": "Klavier", "label": "Klavier", "abbreviations": ["Klav."], "boxes": [4, 5], "staves": 2, "clefs": ["treble", "bass"], "family": "keyboard"},
        {"position": 5, "name": "Violine I", "label": "Violine I", "abbreviations": [], "boxes": [6], "staves": 1, "clefs": ["treble"], "family": "strings"}]}
    script = [tool("read_header", {}), tool("read_page", {"page": 1}), LABEL, commit(1, [4, 5]), RECHECK_PIANO, tool("finish", {})]
    client, t = fake_client(script)
    job, ctx, db = world(1)
    db.rows["interpretations"][0]["params"] = {"state": {"header": book}}
    db.rows["parts"] = [{"score_id": job.score_id, "name": n} for n in ("Flute", "Oboe", "Horn", "Piano", "Violin I")]
    out = await part_cut(job, ctx, client=client)
    assert out["systems_cut"] == 1 and len(t.calls) == 6
    sc = ctx.result["agent"]["scratch"]
    assert sc["header"]["from_book"] and sc["log"][0].startswith("Header from the book's first reading (page 1)")
    mem = db.rows["scores"][0]["label_memory"]["entries"]
    assert mem["klav"]["part"] == "Piano" and mem["violine i"]["part"] == "Violin I"


HEADER_PC5 = text(json.dumps({"instruments": [{"name": "Flauti", "staves": 1, "clefs": ["treble"]}, {"name": "Oboi", "staves": 1, "clefs": ["treble"]},
                                              {"name": "Fagotti", "staves": 1, "clefs": ["bass"]}, {"name": "Pianoforte", "staves": 2, "clefs": ["treble", "bass"]},
                                              {"name": "Violino I", "staves": 1, "clefs": ["treble"]}], "key": "E-flat major", "time": "4/4"}))


@pytest.mark.asyncio
async def test_brace_rule_a_keyboard_pair_is_the_keyboard_whatever_its_clefs():
    """PC5 page 2 (the pianist, 2026-10-30): the header says the Pianoforte is treble and bass, the page's third system
    prints "Pfte." over two treble staves, and the recheck said no three times on the clefs, which parked the run.
    The brace rule: the recheck is told a braced keyboard pair is the keyboard whatever its clefs, claims no clefs for it,
    and its no is overruled when the label it read is a keyboard's on as many staves as the part has. 0 questions."""
    import app.librarian.part_cut as pc
    no_on_clefs = text(json.dumps({"matches": False, "staves_seen": 2, "clefs_seen": ["treble", "treble"], "label_seen": "Pfte.",
                                   "why": "both visible staves have treble clefs with brace labeled Pfte., no bass clef present"}))
    script = [tool("read_header", {}), HEADER_PC5, tool("read_page", {"page": 1}), LABEL, commit(1, [4, 5]), no_on_clefs, tool("finish", {})]
    client, t = fake_client(script)
    job, ctx, db = world(1, {"instruments": ["Pianoforte"]})
    out = await part_cut(job, ctx, client=client)
    assert out["systems_cut"] == 1 and out["questions"] == 0 and out["agent"]["status"] == "done"
    rc = ctx.result["agent"]["scratch"]["commits"]["1:1"]["rechecks"]
    assert [r["verdict"] for r in rc] == ["brace"]
    prompt = t.calls[5]["messages"][0]["content"][1]["text"] if isinstance(t.calls[5]["messages"][0]["content"], list) and len(t.calls[5]["messages"][0]["content"]) > 1 else json.dumps(t.calls[5])
    assert "whatever clefs the staves show" in prompt and "joined by a brace" in prompt and "treble and bass clef" not in prompt
    # a seen clef never refuses a keyboard pair, a matching yes with two treble clefs passes as it is
    assert pc.keyboard_brace({"label_seen": "Klav.", "staves_seen": 2}, 2) and pc.keyboard_brace({"label_seen": "Celesta", "staves_seen": "2"}, 2)
    assert not pc.keyboard_brace({"label_seen": "Vl. I", "staves_seen": 2}, 2) and not pc.keyboard_brace({"label_seen": "Pfte.", "staves_seen": 3}, 2)
    assert not pc.keyboard_brace({"label_seen": "", "staves_seen": 2}, 2)
    assert pc.is_keyboard("Pfte.") and pc.is_keyboard("Organo") and pc.is_keyboard("Harfe") and not pc.is_keyboard("Violoncello")


def test_strip_bars_number_the_strips_and_name_the_tacet_pages():
    """PC5 p1-4 as the pianist saw it: the piano plays on pages 1-3 and rests through page 4. Each strip carries its
    running bar numbers from the book's placements (not "2 bars") and where each bar sits across the strip; page 4,
    where nothing of the part was cut, is a tacet row with the bars printed there."""
    import app.librarian.part_cut as pc
    def bar(n, page, system, x0, x1): return {"number": n, "page": page, "system": system, "box": {"x0": x0, "y0": 0.1, "x1": x1, "y1": 0.9}}
    placements = [bar(1, 1, 1, 0.25, 0.4), bar(2, 1, 1, 0.4, 0.9),
                  bar(3, 2, 1, 0.2, 0.9), bar(4, 2, 2, 0.2, 0.5), bar(5, 2, 2, 0.5, 0.9),
                  bar(6, 3, 1, 0.2, 0.9), *[bar(n, 4, 1, 0.2 + (n - 7) * 0.1, 0.3 + (n - 7) * 0.1) for n in range(7, 12)],
                  {"number": 12, "page": 4, "system": None, "box": {"x0": 0, "y0": 0, "x1": 0, "y1": 0}}]
    systems = [{"page": 1, "system": 1, "key": "p1", "bars": 2}, {"page": 2, "system": 1, "key": "p2a", "bars": 1},
               {"page": 2, "system": 2, "key": "p2b", "bars": 2}, {"page": 3, "system": 1, "key": None, "bars": 1},
               {"page": 3, "system": 2, "key": "p3", "bars": 0}, {"page": 4, "system": 1, "key": None, "bars": 5}]
    crops = {"1:1": (0.0, 0.95), "2:2": (0.0, 1.0)}
    out, tacet = pc.strip_bars(systems, placements, [1, 2, 3, 4], crops)
    assert [(s.get("bar_from"), s.get("bar_to")) for s in out] == [(1, 2), (3, 3), (4, 5), (None, None), (None, None), (None, None)]
    assert out[0]["bars_at"] == [[1, 0.2632, 0.4211], [2, 0.4211, 0.9474]]          # fractions of the strip, the crop's own width
    assert out[2]["bars_at"] == [[4, 0.2, 0.5], [5, 0.5, 0.9]]
    assert tacet == [{"page": 4, "bar_from": 7, "bar_to": 12}]                         # page 4: the part rests, bars 7-12
    _, none = pc.strip_bars(systems[:3], [], [1, 2, 5], {})
    assert none == [{"page": 5, "bar_from": None, "bar_to": None}]                    # a page with no bars placed still says so


@pytest.mark.asyncio
async def test_the_split_source_carries_bar_numbers_and_tacet_pages():
    """End to end on the scripted run: page 1 holds the piano, page 2 does not; the derived source's meta numbers the
    strip from the placements the run copied and names page 2 as tacet."""
    script = [tool("read_header", {}), HEADER, tool("read_page", {"page": 1}), LABEL, commit(1, [4, 5]), RECHECK_PIANO,
              tool("read_page", {"page": 2}), LABEL_ABSENT, commit(2, "absent"), tool("finish", {})]
    client, t = fake_client(script)
    job, ctx, db = world(2)
    db.rows["measure_placements"] = [{"interpretation_id": "intake1", "measure_id": f"m{i}", "page": 1 if i < 4 else 2, "system": 1,
                                      "box": {"x0": 0.1 + 0.2 * (i % 4), "y0": 0.1, "x1": 0.3 + 0.2 * (i % 4), "y1": 0.4}, "measures": {"number": i + 1},
                                      "confidence": "high", "flag": None, "rehearsal_mark": None} for i in range(6)]
    out = await part_cut(job, ctx, client=client)
    assert out["systems_cut"] == 1
    meta = [r for r in db.rows["sources"] if r["kind"] == "part_images"][0]["meta"]
    s1 = next(s for s in meta["systems"] if s["key"])
    assert (s1["bar_from"], s1["bar_to"]) == (1, 4) and [b[0] for b in s1["bars_at"]] == [1, 2, 3, 4]
    assert all(0 <= b[1] < b[2] <= 1 for b in s1["bars_at"])
    assert meta["tacet"] == [{"page": 2, "bar_from": 5, "bar_to": 6}] and meta["pages"] == [1, 2]
