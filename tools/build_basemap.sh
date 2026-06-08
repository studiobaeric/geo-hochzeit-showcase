#!/usr/bin/env bash
#
# Build the offline vector basemap (PMTiles) for the Geoguesser.
#
# Strategy: world overview at low zoom + Europe detail at high zoom, merged
# into a single static/data/basemap.pmtiles. World tiles let the player
# orient themselves globally; Europe tiles give street-level detail for guessing.
#
# Configurable via environment variables:
#   MAXZOOM=10          Europe detail cap. Sizes (Europe bbox only):
#                       z10 ~1.4GB, z11 ~2.9GB, z12 ~6.5GB, z13 ~13GB
#   WORLD_MAXZOOM=5     last zoom level served for the full world.
#                       z0-z5 world tiles are tiny (few MB total).
#   EUROPE_BBOX=...     area for high-zoom tiles (default: all of Europe).
#   BUILD_DATE          Protomaps daily build YYYYMMDD.
#                       Pick a recent one from https://build.protomaps.com
#
# Example: more street detail
#   MAXZOOM=12 bash tools/build_basemap.sh
#
set -euo pipefail

MAXZOOM="${MAXZOOM:-10}"
WORLD_MAXZOOM="${WORLD_MAXZOOM:-5}"
EUROPE_BBOX="${EUROPE_BBOX:--25,34,45,72}"   # all of Europe
WORLD_BBOX="-180,-90,180,90"
BUILD_DATE="${BUILD_DATE:-20260608}"
PMTILES_VERSION="${PMTILES_VERSION:-1.30.3}"

SOURCE="https://build.protomaps.com/${BUILD_DATE}.pmtiles"
OUT="static/data/basemap.pmtiles"
TMP_WORLD="/tmp/basemap_world_z0-${WORLD_MAXZOOM}.pmtiles"
TMP_EUROPE="/tmp/basemap_europe_z$((WORLD_MAXZOOM+1))-${MAXZOOM}.pmtiles"

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

echo ">> step 1/3: world overview  z0..${WORLD_MAXZOOM}  bbox=${WORLD_BBOX}"
"$PMTILES" extract "$SOURCE" "$TMP_WORLD" \
    --bbox="$WORLD_BBOX" \
    --minzoom=0 \
    --maxzoom="$WORLD_MAXZOOM" \
    --download-threads=8

echo ">> step 2/3: Europe detail   z$((WORLD_MAXZOOM+1))..${MAXZOOM}  bbox=${EUROPE_BBOX}"
"$PMTILES" extract "$SOURCE" "$TMP_EUROPE" \
    --bbox="$EUROPE_BBOX" \
    --minzoom="$((WORLD_MAXZOOM+1))" \
    --maxzoom="$MAXZOOM" \
    --download-threads=8

echo ">> step 3/3: merging into $OUT"
"$PMTILES" merge "$TMP_WORLD" "$TMP_EUROPE" "$OUT"

rm -f "$TMP_WORLD" "$TMP_EUROPE"
echo ">> done: $(du -h "$OUT" | cut -f1) at $OUT"
