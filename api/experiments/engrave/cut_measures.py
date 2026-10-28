"""Cut a MusicXML (.musicxml or .mxl) to its first N measures per part, for side-by-side engraving.

Usage: python cut_measures.py in.(musicxml|mxl) out.musicxml N [--title "Aria"] [--strip-layout]

Plain ElementTree, no music21: notes, ornaments, words and spanners are left exactly as written.
--strip-layout removes <print> (system and page breaks, margins), measure widths, <credit>s and
<defaults> page layout, so each engraver lays the music out on its own.
"""
import sys
import zipfile
import xml.etree.ElementTree as ET


def read(path):
    if path.endswith(".mxl"):
        z = zipfile.ZipFile(path)
        name = next(n for n in z.namelist() if not n.startswith("META-INF") and n.endswith((".xml", ".musicxml")))
        return ET.fromstring(z.read(name))
    return ET.parse(path).getroot()


def main():
    args = sys.argv[1:]
    strip = "--strip-layout" in args
    title = None
    if "--title" in args:
        title = args[args.index("--title") + 1]
    src, dst, n = args[0], args[1], int(args[2])
    root = read(src)
    for part in root.findall("part"):
        for m in part.findall("measure")[n:]:
            part.remove(m)
        if strip:
            for m in part.findall("measure"):
                m.attrib.pop("width", None)
                for pr in m.findall("print"):
                    m.remove(pr)
    if strip:
        for c in root.findall("credit"):
            root.remove(c)
        d = root.find("defaults")
        if d is not None:
            for tag in ("page-layout", "system-layout", "staff-layout"):
                for e in d.findall(tag):
                    d.remove(e)
    if title is not None:
        for tag in ("work", "movement-number", "movement-title"):
            for e in root.findall(tag):
                root.remove(e)
        mt = ET.Element("movement-title")
        mt.text = title
        root.insert(0, mt)
    ET.ElementTree(root).write(dst, encoding="utf-8", xml_declaration=True)
    print(dst, "measures/part:", [len(p.findall("measure")) for p in root.findall("part")])


if __name__ == "__main__":
    main()
