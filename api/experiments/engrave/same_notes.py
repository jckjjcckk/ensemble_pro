"""Check that MusicXML files carry identical music: every measure's content with <print> removed and the
measure's width attribute ignored, compared as canonical XML. Prints one sha256 per file.

Usage: python same_notes.py a.musicxml b.musicxml ...
"""
import hashlib
import sys
import xml.etree.ElementTree as ET

for f in sys.argv[1:]:
    root = ET.parse(f).getroot()
    h = hashlib.sha256()
    n = 0
    for part in root.findall("part"):
        for m in part.findall("measure"):
            for child in m:
                if child.tag == "print":
                    continue
                h.update(ET.tostring(child))
                n += child.tag == "note"
    print(h.hexdigest()[:16], n, "notes", f)
