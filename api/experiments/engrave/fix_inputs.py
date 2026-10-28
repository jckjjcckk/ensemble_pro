"""The merge fix on the two engraving inputs: our Convert output (`A-input.musicxml`, as the merge wrote it) through the
app's `musicxml_fix` with Audiveris's first movement file as the page layout source, as `omr_convert` now writes it.

  F  fix_musicxml on the written bytes (the post-write pass itself)
  G  music21 parse + omr_convert.write_musicxml (a music21 re-write, then the pass), to show the pass survives a re-export

Usage: uv run python experiments/engrave/fix_inputs.py   (from api/)
"""
import sys
from pathlib import Path

from music21 import converter, metadata

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
from app.librarian.musicxml_fix import PageLayout, fix_musicxml  # noqa: E402
from app.librarian.omr_convert import write_musicxml  # noqa: E402

SETS = [
    (HERE / "goldberg/same-file", HERE / "goldberg/inputs/goldberg-bga.mxl", "Aria", "J. S. Bach"),
    (HERE / "chopin-op40-1", HERE / "chopin-op40-1/inputs/audiveris-p25.mxl", "Polonaise Op. 40 No. 1", "F. Chopin"),
]

for d, aud, title, composer in SETS:
    page = PageLayout.read(aud)
    raw = (d / "A-input.musicxml").read_bytes()
    (d / "F-input.musicxml").write_bytes(fix_musicxml(raw, page, title=title, composer=composer))
    sc = converter.parse(raw, format="musicxml")
    sc.metadata = metadata.Metadata()
    sc.metadata.title, sc.metadata.composer = title, composer
    (d / "G-input.musicxml").write_bytes(write_musicxml(sc, page))
    print(d.name, "F-input.musicxml G-input.musicxml")
