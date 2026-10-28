"""HAND PATCH, not pipeline output: the Aria's text layer fixed by hand in D-input.musicxml, to show in MuseScore
what the three proposed pipeline fixes would look like. Notes are untouched (same_notes.py hash unchanged).

  1. tempo   the metronome mark that score.py/apply_edits left in bar 2 is removed; bar 1 gets one direction,
             placement above, staff 1, at offset 0: <words font-weight="bold">Andante espressivo.</words> and
             <metronome parentheses="yes"> quarter = 72, with <sound tempo="72"/> (one direction, two
             direction-types: MuseScore imports it as a single tempo text at the head of the piece)
  2. italics every expression <words> (cresc., dim., poco, a, dolce) gets font-style="italic"
  3. phrase  "cresc." and "poco" in bar 27, which Spark returned as two items and apply_edits wrote as two
             directions on two staves, become one "cresc. poco" (as printed in the scan)

Usage: python3 hand_patch_text.py D-input.musicxml E-input.musicxml
"""
import sys
import xml.etree.ElementTree as ET

src, dst = sys.argv[1], sys.argv[2]
tree = ET.parse(src)
root = tree.getroot()
part = root.find("part")
ms = {m.get("number"): m for m in part.findall("measure")}

# 1. tempo at the head of the piece
for d in list(ms["2"].findall("direction")):
    if d.find("direction-type/metronome") is not None:
        ms["2"].remove(d)
d = ET.Element("direction", placement="above")
dt = ET.SubElement(d, "direction-type")
w = ET.SubElement(dt, "words", {"font-weight": "bold", "font-size": "12"})
w.text = "Andante espressivo. "
dt2 = ET.SubElement(d, "direction-type")
mm = ET.SubElement(dt2, "metronome", parentheses="yes")
ET.SubElement(mm, "beat-unit").text = "quarter"
ET.SubElement(mm, "per-minute").text = "72"
ET.SubElement(d, "staff").text = "1"
ET.SubElement(d, "sound", tempo="72")
m1 = ms["1"]
kids = list(m1)
idx = max(i for i, c in enumerate(kids) if c.tag in ("print", "attributes")) + 1
m1.insert(idx, d)

# 3. "cresc. poco" in bar 27 as one direction
m27 = ms["27"]
dirs = m27.findall("direction")
cresc = next(x for x in dirs if x.findtext("direction-type/words") == "cresc.")
poco = next(x for x in dirs if x.findtext("direction-type/words") == "poco")
cresc.find("direction-type/words").text = "cresc. poco"
m27.remove(poco)

# 2. italics on expression words
n = 0
for w in root.iter("words"):
    if w.text and w.text.strip().rstrip(".").lower() in {"cresc", "cresc. poco", "dim", "poco", "a", "dolce", "espressivo"}:
        w.set("font-style", "italic")
        n += 1
mt = root.find("movement-title")
if mt is not None:
    mt.text = "Aria"
tree.write(dst, encoding="utf-8", xml_declaration=True)
print(dst, f"italic words: {n}")
