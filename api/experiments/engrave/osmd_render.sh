#!/usr/bin/env bash
# Engrave a MusicXML with OSMD (the iPad renderer) in headless Google Chrome and print it to PDF.
# Usage: osmd_render.sh in.musicxml out.pdf [workdir]
# Prints "<osmd_ms> <pages> <wall_s> <out>". osmd_ms is OSMD load+render inside the page.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
in="$1"; out="$2"; work="${3:-${TMPDIR:-/tmp}/osmd-render}"
chrome="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
mkdir -p "$work"
html="$work/$(basename "$out" .pdf).html"
python3 -I "$here/osmd_page.py" "$in" "$html" >/dev/null
flags=(--headless --disable-gpu --allow-file-access-from-files --user-data-dir="$work/chrome" --virtual-time-budget=60000)
t0=$(python3 -c 'import time; print(time.time())')
body=$("$chrome" "${flags[@]}" --dump-dom "file://$html" 2>/dev/null | grep -o '<body[^>]*>' || true)
"$chrome" "${flags[@]}" --no-pdf-header-footer --print-to-pdf="$out" "file://$html" 2>/dev/null
t1=$(python3 -c 'import time; print(time.time())')
ms=$(echo "$body" | sed -n 's/.*data-done="\([0-9]*\)".*/\1/p')
pages=$(echo "$body" | sed -n 's/.*data-pages="\([0-9]*\)".*/\1/p')
err=$(echo "$body" | sed -n 's/.*data-error="\([^"]*\)".*/\1/p')
[ -n "$err" ] && echo "OSMD error: $err" >&2
python3 -c "print('${ms:-?} ${pages:-?} %.2f $out' % ($t1 - $t0))"
