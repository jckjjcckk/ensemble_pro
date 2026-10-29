#!/usr/bin/env bash
# Engrave a v2 Convert output with MuseScore on the OMR box and prove every note is kept.
# Usage: experiments/engrave/v2_render.sh NAME final.musicxml OUT_DIR
#   -> OUT_DIR/NAME.pdf, NAME.mpos, NAME.mscx, NAME.kept.txt, NAME.systems.txt
set -euo pipefail
name="$1"; in="$2"; out="$3"
mkdir -p "$out"
ssh omr "mkdir -p ~/omr/musescore/v2"
scp -q "$in" "omr:omr/musescore/v2/$name.musicxml"
scp -q "$(dirname "$0")/musescore_kept.py" "omr:omr/musescore/v2/musescore_kept.py"
ssh omr "cd ~/omr/musescore/v2 && for ext in pdf mpos mscx; do ~/omr/musescore/scripts/musescore_render.sh $name.\$ext $name.musicxml; done \
  && python3 -I musescore_kept.py $name.musicxml $name.mscx" | tee "$out/$name.kept.txt"
for ext in pdf mpos mscx; do scp -q "omr:omr/musescore/v2/$name.$ext" "$out/$name.$ext"; done
python3 -I "$(dirname "$0")/mpos_systems.py" "$out/$name.mpos" | tee "$out/$name.systems.txt"
