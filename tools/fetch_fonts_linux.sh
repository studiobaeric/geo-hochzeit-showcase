#!/usr/bin/env bash
#
# Downloads the glyph fonts (Noto Sans Regular/Medium/Italic) needed by the
# "light" basemap style to render text labels offline.
#
# These are ~768 small .pbf files (~13 MB) and are NOT checked into git - run
# this once after cloning (and after every `npm install`-style setup):
#
#   bash tools/fetch_fonts.sh
#
# Source: https://github.com/protomaps/basemaps-assets
#
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
TARBALL="/tmp/basemaps-assets.tar.gz"
URL="https://github.com/protomaps/basemaps-assets/archive/refs/heads/main.tar.gz"
echo ">> downloading basemaps-assets..."
if ! curl -fsSL "$URL" -o "$TARBALL"; then
    echo "ERROR: download failed: $URL" >&2
    rm -f "$TARBALL"
    exit 1
fi
echo ">> extracting font stacks into static/fonts/"
rm -rf static/fonts
mkdir -p static/fonts
tar xzf "$TARBALL" -C static --strip-components=1 \
    "basemaps-assets-main/fonts/Noto Sans Regular" \
    "basemaps-assets-main/fonts/Noto Sans Medium" \
    "basemaps-assets-main/fonts/Noto Sans Italic"
rm -f "$TARBALL"
echo ">> done: $(ls static/fonts | wc -l | tr -d ' ') font stacks, $(find static/fonts -name '*.pbf' | wc -l | tr -d ' ') glyph ranges"
