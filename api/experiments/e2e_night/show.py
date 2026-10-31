"""Print a book's check, briefly: python -m experiments.e2e_night.show <slug> [keys...]"""
import json
import sys

from .common import load

s = load(sys.argv[1])
d = s.get("check") or {}
keys = sys.argv[2:] or ["title", "key", "meter", "measures", "bar_first", "bar_last", "parts", "landmarks", "label_memory", "bars_per_page",
                        "midi_part_tracks", "midi_tracks", "bars_json", "bar_map_missing_n", "bar_map_missing", "bar_map_extra_n", "bar_map_extra", "sources"]
for k in keys:
    print(k, json.dumps(d.get(k), ensure_ascii=False, default=str)[:600])
