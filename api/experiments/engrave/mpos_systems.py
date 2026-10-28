"""Bars per system from MuseScore .mpos files (measure boxes; a system = one page + one y).

Usage: python mpos_systems.py a.mpos [b.mpos ...]
Prints the measure ordinal ranges of each system, page by page.
"""
import re
import sys

for f in sys.argv[1:]:
    els = re.findall(r'id="(\d+)" x="[^"]+" y="([^"]+)" sx="[^"]+" sy="[^"]+" page="(\d+)"', open(f).read())
    rows = {}
    for i, y, p in els:
        rows.setdefault((int(p), float(y)), []).append(int(i) + 1)
    pages = {}
    for (p, _), ids in sorted(rows.items()):
        pages.setdefault(p + 1, []).append(f"{min(ids)}-{max(ids)}")
    print(f.rsplit("/", 1)[-1], " | ".join(f"p{p}: " + " ".join(r) for p, r in pages.items()))
