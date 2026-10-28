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
RECHECK_PIANO = text(json.dumps({"instrument": "Pno.", "confidence": "high", "why": "label"}))
RECHECK_VIOLIN = text(json.dumps({"instrument": "Violins", "confidence": "medium", "why": "two treble staves"}))


def synth_page(staves: int = 6, w: int = 1300, h: int = 1700) -> bytes:
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

    def execute(self):
        rows = self.db.rows.setdefault(self.table, [])
        self.db.ops.append((self.table, self.op, self.rows, dict(self.filters)))
        if self.op == "select":
            out = [r for r in rows if all(r.get(k) == v for k, v in self.filters.items())]
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


def world(n_pages: int, payload_extra: dict[str, Any] | None = None, db: FakeDB | None = None) -> tuple[Job, Ctx, FakeDB]:
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
    png = synth_page()
    ctx = Ctx(job, db, {f"{score}/pages/{i}.png": png for i in range(1, n_pages + 1)})
    return job, ctx, db


def commit(page: int, staves): return tool("commit_system", {"page": page, "system": 1, "staves": staves})


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


@pytest.mark.asyncio
async def test_refusal_then_correct_retry():
    script = [tool("read_header", {}), HEADER, tool("read_page", {"page": 1}), LABEL,
              commit(1, [4]),                       # count mismatch: refused before any model call
              commit(1, [3, 4]), RECHECK_VIOLIN,    # geometry passes, the recheck says violins: refused
              commit(1, [4, 5]), RECHECK_PIANO, tool("finish", {})]
    client, t = fake_client(script)
    job, ctx, db = world(1)
    out = await part_cut(job, ctx, client=client)
    assert out["systems_cut"] == 1
    results = [json.loads(c["content"]) for body in t.calls for c in (body["messages"][-1]["content"] if isinstance(body["messages"][-1]["content"], list) else []) if c.get("type") == "tool_result"]
    errors = [r["error"] for r in results if "error" in r]
    assert any("2 staves per system" in e for e in errors) and any("Violins" in e for e in errors)
    assert ctx.result["agent"]["refusals"] == {}                               # the counter reset on the good commit


@pytest.mark.asyncio
async def test_escalates_to_needs_review_then_resumes_with_answer():
    client, t = fake_client([tool("read_header", {}), HEADER, tool("read_page", {"page": 1}), LABEL, commit(1, [4]), commit(1, [4]), commit(1, [4])])
    job, ctx, db = world(1)
    out = await part_cut(job, ctx, client=client)
    q = out["question_payload"]
    assert q["kind"] == "choose_staves" and q["page"] == 1 and q["system"] == 1 and q["proposal"] == [4, 5] and q["last_attempt"] == [4]
    assert [b["index"] for b in q["staff_boxes"]] == [1, 2, 3, 4, 5, 6] and q["image_key"].endswith("/overlay-p001.png") and q["allowed"]["absent"] is True
    assert "Which staves on page 1" in out["question"] and out["agent"]["status"] == "needs_review"
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
    assert sc["pages"]["1"]["proposal"] == [{"system": 1, "staves": [4, 5], "status": "by-order"}]
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
