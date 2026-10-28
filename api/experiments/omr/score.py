"""One MusicXML for the page set, measures numbered with the global bar numbers of model.json.

Audiveris writes one file per movement (`<radix>.mvtK.mxl`), each numbered from 1. The k-th measure of
movement K is the stack with movement == K and movement_bar == k in the measure map, so every measure gets
its global number; a count mismatch between a movement file and the map stops the run (the map and the file
would then address different bars). Measures are moved, not copied, and each movement's spanners (slurs,
hairpins, ties across bars) are carried into the merged parts, so nothing the engine read is lost. Each
movement's clef, key and time signature are already on its first measure.

Usage: uv run python experiments/omr/score.py model.json out.musicxml mvt1.mxl mvt2.mxl ...
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from music21 import converter, stream

sys.path.insert(0, str(Path(__file__).parent))
from measure_map import by_movement  # noqa: E402


def merge(model: dict, movement_files: list[str]) -> tuple[stream.Score, list[str]]:
    groups = by_movement(model["measures"])
    if sorted(groups) != list(range(1, len(movement_files) + 1)):
        raise SystemExit(f"model has movements {sorted(groups)}, got {len(movement_files)} files")
    out = stream.Score()
    parts: list[stream.Part] | None = None
    notes = []
    for k, path in enumerate(movement_files, start=1):
        src = list(converter.parse(path).parts)
        if parts is None:
            parts = [stream.PartStaff(id=f"P1-Staff{i + 1}") for i in range(len(src))]
            for p, s in zip(parts, src):
                p.partName = s.partName or "Piano"
        if len(src) != len(parts):
            raise SystemExit(f"movement {k}: {len(src)} staves, movement 1 had {len(parts)}")
        bars = groups[k]
        for p, s in zip(parts, src):
            ms = list(s.getElementsByClass(stream.Measure))
            if len(ms) != len(bars):
                raise SystemExit(f"movement {k} ({path}): {len(ms)} measures in the file, {len(bars)} stacks in the map")
            for m, rec in zip(ms, bars):
                if str(m.number) != str(rec["movement_bar"]):
                    notes.append(f"movement {k}: file measure {m.number} at ordinal {rec['movement_bar']} -> bar {rec['number']}")
                m.number = rec["number"]
                p.append(m)
            for sp in s.spanners:
                p.insert(0, sp)
    for p in parts or []:
        out.insert(0, p)
    if parts and len(parts) == 2:
        from music21 import layout
        out.insert(0, layout.StaffGroup(parts, symbol="brace", barTogether=True, name="Piano"))
    return out, notes


def main() -> None:
    model = json.load(open(sys.argv[1]))
    sc, notes = merge(model, sys.argv[3:])
    sc.write("musicxml", fp=sys.argv[2], makeNotation=False)  # Audiveris bars can overflow; makeNotation would re-bar them
    n = len(model["measures"])
    print(f"wrote {sys.argv[2]}: {n} bars {model['measures'][0]['number']}..{model['measures'][-1]['number']}, "
          f"{len(sys.argv) - 3} movements")
    for line in notes:
        print("  " + line)


if __name__ == "__main__":
    main()
