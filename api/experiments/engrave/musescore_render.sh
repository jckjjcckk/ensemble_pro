#!/usr/bin/env bash
# Engrave MusicXML with MuseScore Studio 4.7.5 headless on the OMR box.
# Usage (on the box): musescore_render.sh out.(pdf|png|svg|mpos|mp3|mscz) in.musicxml
# Prints "<seconds> <out>". MuseScore ignores QT_QPA_PLATFORM; it reads MU_QT_QPA_PLATFORM.
set -euo pipefail
MS="${MSCORE:-$HOME/omr/musescore/squashfs-root/AppRun}"
out="$1"; in="$2"
t0=$(date +%s.%N)
MU_QT_QPA_PLATFORM=offscreen QT_QPA_PLATFORM=offscreen "$MS" -o "$out" "$in" >"$out.log" 2>&1
t1=$(date +%s.%N)
printf '%.2f %s\n' "$(echo "$t1 - $t0" | bc)" "$out"
