"""`omr_box.py --parallel`: each page its own Audiveris book, stitched into the whole-book layout that
`omr_book.load_run` reads. Audiveris and pdfseparate are stood in for; the stitching is the code under test."""
import json
import zipfile
from pathlib import Path

from app.librarian import omr_box


def book_xml(pages: list[tuple[int, bool, str | None]]) -> str:
    """One sheet with these Audiveris pages: (measures, movement-start, movement name)."""
    pgs = "".join(f'<page id="{i}" {"movement-start=\"true\" " if start else ""}delta-measure-id="{n}"/>' for i, (n, start, _) in enumerate(pages, 1))
    scores = "".join(f'<score id="{i}"><page sheet-number="1" sheet-page-id="{i}"/><logical-part name="{name}"/></score>'
                     for i, (_, start, name) in enumerate(pages, 1) if start and name)
    return f'<book><sheet number="1">{pgs}</sheet>{scores}</book>'


def test_pages_are_stitched_in_order_each_a_movement(tmp_path, monkeypatch):
    # page 1: one Audiveris page (the Aria starts); page 2: the Aria's end, then Var. 1 starts mid-page (two pages)
    layout = {1: [(28, True, "Aria")], 2: [(4, False, None), (16, True, "Var. 1.")]}
    calls = []

    def fake_run(cmd, **kw):
        assert cmd[0] == "pdfseparate"
        Path(cmd[-1]).write_bytes(b"%PDF one page")
        return None

    def fake_audiveris(pdf: Path, out: Path):
        page = int(out.name)
        calls.append(page)
        with zipfile.ZipFile(out / f"{pdf.stem}.omr", "w") as z:
            z.writestr("book.xml", book_xml(layout[page]))
            z.writestr("sheet#1/sheet#1.xml", f"<sheet page='{page}'/>")
            z.writestr("sheet#1/BINARY.png", b"png")
        k = len(layout[page])
        names = [f"{pdf.stem}.mxl"] if k == 1 else [f"{pdf.stem}.mvt{j}.mxl" for j in range(1, k + 1)]
        for j, n in enumerate(names, 1):
            (out / n).write_text(f"page {page} part {j}")
        (out / "audiveris.log").write_text("ok")
        return 0, 1.0

    monkeypatch.setattr(omr_box.subprocess, "run", fake_run)
    monkeypatch.setattr(omr_box, "run_audiveris", fake_audiveris)
    rc, secs, movements, tail = omr_box.parallel_pages(tmp_path / "book.pdf", 2, tmp_path, "book", [7, 8], workers=2)
    assert rc == 0 and sorted(calls) == [1, 2]
    assert [(m["sheet"], m["pdf_page"], m["page"], m["movement"], m["measures"]) for m in movements] == [
        (1, 7, 1, 1, 28), (2, 8, 1, 2, 4), (2, 8, 2, 3, 16)]
    assert [m["name"] for m in movements] == ["Aria", None, "Var. 1."]
    assert [(tmp_path / f"book.mvt{k}.mxl").read_text() for k in (1, 2, 3)] == ["page 1 part 1", "page 2 part 1", "page 2 part 2"]
    assert (tmp_path / "book" / "sheet#2" / "sheet#2.xml").read_text() == "<sheet page='2'/>"
    assert not list((tmp_path / "book").glob("sheet#*/BINARY.png")) and not (tmp_path / "pp").exists()
    # the stitched book.xml is what detected_movements and omr_book read: sheets 1 and 2 in order
    again = omr_box.detected_movements((tmp_path / "book" / "book.xml").read_bytes(), [7, 8])
    assert json.dumps(again) == json.dumps(movements)


def test_a_page_audiveris_fails_on_stops_the_run(tmp_path, monkeypatch):
    monkeypatch.setattr(omr_box.subprocess, "run", lambda cmd, **kw: Path(cmd[-1]).write_bytes(b"%PDF"))

    def fake_audiveris(pdf: Path, out: Path):
        (out / "audiveris.log").write_text("boom\nlast line")
        return (1, 2.0) if out.name == "2" else (0, 2.0)

    monkeypatch.setattr(omr_box, "run_audiveris", fake_audiveris)
    rc, _, movements, tail = omr_box.parallel_pages(tmp_path / "book.pdf", 2, tmp_path, "book", [1, 2], workers=2)
    assert rc != 0 and movements == [] and tail[-1] == "last line"   # page 1 left no .omr, page 2 exited 1
