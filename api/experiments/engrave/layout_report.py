"""Report the layout metadata a MusicXML (.musicxml or .mxl) carries.

Usage: python layout_report.py file [--max-measure N]

Prints: <defaults> scaling / page-layout / system-layout presence, <credit> words, and per part the
measures carrying <print new-system="yes"> or new-page="yes" (measure numbers as written), plus the
bar ranges of each system that follows. --max-measure limits the system listing to the first N measures.
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
    path = sys.argv[1]
    maxm = int(sys.argv[sys.argv.index("--max-measure") + 1]) if "--max-measure" in sys.argv else None
    root = read(path)
    d = root.find("defaults")
    print(f"== {path}")
    if d is None:
        print("defaults: none")
    else:
        sc = d.find("scaling")
        pl = d.find("page-layout")
        print("defaults: scaling", "yes" if sc is not None else "no",
              f"({sc.findtext('millimeters')} mm / {sc.findtext('tenths')} tenths)" if sc is not None else "",
              "| page-layout", "yes" if pl is not None else "no",
              f"({pl.findtext('page-width')} x {pl.findtext('page-height')})" if pl is not None else "",
              "| system-layout", "yes" if d.find("system-layout") is not None else "no",
              "| staff-layout", "yes" if d.find("staff-layout") is not None else "no")
    credits = root.findall("credit")
    print(f"credits: {len(credits)}")
    for c in credits:
        words = " / ".join((w.text or "").strip() for w in c.findall("credit-words"))
        print(f"  page {c.get('page', '1')}: {words[:90]}")
    for part in root.findall("part")[:1]:  # system breaks are the same in every part
        ms = part.findall("measure")
        sys_starts, page_starts, prints = [], [], 0
        for i, m in enumerate(ms):
            for pr in m.findall("print"):
                prints += 1
                if pr.get("new-page") == "yes":
                    page_starts.append(i)
                if pr.get("new-system") == "yes" or pr.get("new-page") == "yes":
                    sys_starts.append(i)
        num = lambda i: ms[i].get("number")
        print(f"part {part.get('id')}: {len(ms)} measures, {prints} <print>, "
              f"new-system {sum(1 for m in ms for p in m.findall('print') if p.get('new-system') == 'yes')}, "
              f"new-page {len(page_starts)}")
        print("  pages start at measure (ordinal:number):", [f"{i + 1}:{num(i)}" for i in page_starts])
        starts = sorted(set([0] + sys_starts))
        ranges = []
        for k, s in enumerate(starts):
            e = (starts[k + 1] if k + 1 < len(starts) else len(ms)) - 1
            if maxm is not None and s >= maxm:
                break
            ranges.append(f"{s + 1}-{e + 1}" + ("P" if s in page_starts else ""))
        print("  systems (ordinal ranges, P = new page):", " ".join(ranges))


if __name__ == "__main__":
    main()
