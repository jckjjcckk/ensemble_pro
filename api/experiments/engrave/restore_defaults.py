"""Preview of the merge fix: copy Audiveris's <defaults> (scaling, page layout, margins) into a MusicXML
and add a title and composer <credit>. Notes are untouched.

Usage: python restore_defaults.py in.musicxml audiveris.(mxl|musicxml) out.musicxml --title T --composer C
"""
import sys
import xml.etree.ElementTree as ET

from cut_measures import read

args = sys.argv[1:]
src, aud, dst = args[0], args[1], args[2]
title = args[args.index("--title") + 1]
composer = args[args.index("--composer") + 1]
root = read(src)
adef = read(aud).find("defaults")
for d in root.findall("defaults"):
    root.remove(d)
for c in root.findall("credit"):
    root.remove(c)
# MusicXML order: work?, movement-*, identification, defaults, credit*, part-list
idx = list(root).index(root.find("part-list"))
root.insert(idx, adef)
pl = adef.find("page-layout")
w = float(pl.findtext("page-width"))
h = float(pl.findtext("page-height"))
for i, (text, kind, x, y, just, size) in enumerate([
    (title, "title", w / 2, h - 100, "center", "22"),
    (composer, "composer", w - 100, h - 170, "right", "12"),
]):
    c = ET.Element("credit", page="1")
    ET.SubElement(c, "credit-type").text = kind
    cw = ET.SubElement(c, "credit-words", {"default-x": f"{x:g}", "default-y": f"{y:g}", "justify": just,
                                           "valign": "top", "font-size": size})
    cw.text = text
    root.insert(idx + 1 + i, c)
ident = root.find("identification")
if ident is not None:
    for cr in ident.findall("creator"):
        if cr.get("type") == "composer":
            cr.text = composer
ET.ElementTree(root).write(dst, encoding="utf-8", xml_declaration=True)
print(dst)
