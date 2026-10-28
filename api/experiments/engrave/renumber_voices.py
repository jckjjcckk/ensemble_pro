"""HAND PATCH / proposed merge fix: give every staff its own voice numbers, the MusicXML convention Audiveris
follows (staff 1 voices 1-4, staff 2 voices 5-8). music21's export (score.py's merge) renumbers voices per
measure across both staves (bar 16 of the Chopin page: voices 1, 2, 3 upper and 4 lower; bar 1: 1 upper, 2
lower), so one voice number means the treble in one bar and the bass in the next. MuseScore's importer maps
each voice number to one staff for the whole part, so the minority uses are imported as cross-staff chords or
dropped. Here each voice of each measure is renumbered by the staff that holds most of its notes in that
measure (ties: the lower staff number), in order of first appearance; notes keep their own <staff>, so a voice
that crosses staves stays one voice with a cross-staff note. Notes, durations, <backup>/<forward> untouched.

Usage: python3 -I renumber_voices.py in.musicxml out.musicxml
"""
import sys
import xml.etree.ElementTree as ET
from collections import Counter

tree = ET.parse(sys.argv[1])
changed = 0
for part in tree.getroot().findall("part"):
    for m in part.findall("measure"):
        notes = m.findall("note")
        per_voice = {}
        order = []
        for n in notes:
            v = n.findtext("voice")
            if v is None:
                continue
            if v not in per_voice:
                per_voice[v] = Counter()
                order.append(v)
            per_voice[v][int(n.findtext("staff") or 1)] += 1
        next_free = {}
        new = {}
        for v in order:
            staff = min(per_voice[v].items(), key=lambda kv: (-kv[1], kv[0]))[0]
            k = next_free.get(staff, 0)
            next_free[staff] = k + 1
            new[v] = str((staff - 1) * 4 + 1 + k)
        for n in notes:
            ve = n.find("voice")
            if ve is not None and ve.text != new[ve.text]:
                ve.text = new[ve.text]
                changed += 1
        for fw in m.findall("forward"):
            ve = fw.find("voice")
            if ve is not None and ve.text in new:
                ve.text = new[ve.text]
tree.write(sys.argv[2], encoding="utf-8", xml_declaration=True)
print(sys.argv[2], f"voice numbers changed on {changed} notes")
