#!/usr/bin/env bash
#
# Build the offline Europe vector basemap (PMTiles) for the Geoguesser.
#
# Extracts a sub-pyramid from the hosted Protomaps planet build via HTTP range
# requests (does NOT download the whole planet). The result is a single
# static/data/basemap.pmtiles file served locally and read by the browser via
# range requests at runtime — it never needs to fit in RAM.
#
# Everything is configurable via environment variables:
#   MAXZOOM=10     detail cap. Higher = much bigger. Sizes for all-of-Europe:
#                  z10 ~1.4GB, z11 ~2.9GB, z12 ~6.5GB, z13 ~13GB
#   BBOX=...       area of interest "min_lon,min_lat,max_lon,max_lat"
#                  default is all of Europe.
#   BUILD_DATE     Protomaps daily build date (YYYYMMDD). Pick a recent one
#                  from https://build.protomaps.com (kept ~5 days).
#   MINZOOM=0      minimum zoom level.
#
# Example: rebuild Europe with more street detail
#   MAXZOOM=12 bash tools/build_basemap.sh
#
set -euo pipefail

MAXZOOM="${MAXZOOM:-10}"
MINZOOM="${MINZOOM:-0}"
BBOX="${BBOX:--25,34,45,72}"            # all of Europe
BUILD_DATE="${BUILD_DATE:-20260608}"
PMTILES_VERSION="${PMTILES_VERSION:-1.30.3}"

SOURCE="https://build.protomaps.com/${BUILD_DATE}.pmtiles"
OUT="static/data/basemap.pmtiles"

# --- resolve the pmtiles CLI (PATH, else tools/bin, else download) ----------
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
mkdir -p tools/bin static/data

if command -v pmtiles >/dev/null 2>&1; then
    PMTILES="pmtiles"
elif [ -x tools/bin/pmtiles ]; then
    PMTILES="tools/bin/pmtiles"
else
    echo ">> pmtiles CLI not found, downloading v${PMTILES_VERSION}..."
    case "$(uname -s)" in Darwin) OS=Darwin ;; Linux) OS=Linux ;; *) echo "unsupported OS"; exit 1 ;; esac
    case "$(uname -m)" in arm64|aarch64) ARCH=arm64 ;; x86_64|amd64) ARCH=x86_64 ;; *) echo "unsupported arch"; exit 1 ;; esac
    URL="https://github.com/protomaps/go-pmtiles/releases/download/v${PMTILES_VERSION}/go-pmtiles-${PMTILES_VERSION}_${OS}_${ARCH}.zip"
    curl -sL -o /tmp/go-pmtiles.zip "$URL"
    unzip -o /tmp/go-pmtiles.zip pmtiles -d tools/bin >/dev/null
    chmod +x tools/bin/pmtiles
    PMTILES="tools/bin/pmtiles"
fi

echo ">> building $OUT"
echo "   source=$SOURCE  bbox=$BBOX  zoom=$MINZOOM..$MAXZOOM"

"$PMTILES" extract "$SOURCE" "$OUT" \
    --bbox="$BBOX" \
    --minzoom="$MINZOOM" \
    --maxzoom="$MAXZOOM" \
    --download-threads=8

echo ">> done: $(du -h "$OUT" | cut -f1) at $OUT"
