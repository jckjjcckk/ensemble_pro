"""Did MuseScore keep every note? Counts pitched notes per bar in a MusicXML input and <Note>s per measure in
the .mscx MuseScore wrote from it (musescore_render.sh out.mscx in.musicxml), and lists the bars that came up short.
same_notes.py proves two inputs are identical; only this shows what the engraver actually kept.

Usage: python3 -I musescore_kept.py in.musicxml out.mscx
"""
import re, sys
s=open(sys.argv[1]).read()
fileN={}
for mm in re.finditer(r'<measure [^>]*number="(\d+)".*?</measure>', s, re.S):
    notes=re.findall(r'<note\b.*?</note>', mm.group(0), re.S)
    fileN[int(mm.group(1))]=sum(1 for x in notes if '<rest' not in x)
m=open(sys.argv[2]).read()
ms={}
for sid,body in re.findall(r'<Staff id="(\d)">\n(.*?)\n      </Staff>', m, re.S):
    for k,meas in enumerate(re.findall(r'<Measure[^>]*>.*?</Measure>', body, re.S),1):
        ms[k]=ms.get(k,0)+meas.count('<Note>')
lost={k:(fileN[k],ms.get(k,0)) for k in fileN if fileN[k]!=ms.get(k,0)}
print(sys.argv[1].rsplit('/',1)[-1], 'notes in file', sum(fileN.values()), 'kept by MuseScore', sum(ms.values()), 'bars short (file, kept):', lost)
