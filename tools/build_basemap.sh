#!/usr/bin/env bash
#
# Build the offline vector basemap (PMTiles) for the Geoguesser.
#
# Strategy: world overview at low zoom + Europe detail at high zoom, merged
# into a single static/data/basemap.pmtiles. World tiles let the player
# orient themselves globally; Europe tiles give street-level detail for guessing.
#
# Uses smart caching: intermediate files survive between runs so unchanged
# portions skip re-download. If the bbox expands, only the new sliver is
# downloaded and merged with the existing cache.
#
# Configurable via environment variables:
#   MAXZOOM=10          Europe detail cap. Sizes (Europe bbox only):
#                       z10 ~1.4GB, z11 ~2.9GB, z12 ~6.5GB, z13 ~13GB
#   WORLD_MAXZOOM=5     last zoom level served for the full world.
#                       z0-z5 world tiles are tiny (few MB total).
#   EUROPE_BBOX=...     area for high-zoom tiles (default: all of Europe).
#   BUILD_DATE          Protomaps daily build YYYYMMDD.
#                       Pick a recent one from https://build.protomaps.com
#   FORCE_REBUILD=true  ignore caches and rebuild everything from scratch
#
# Example: more street detail
#   MAXZOOM=12 bash tools/build_basemap.sh
#
set -euo pipefail

MAXZOOM="${MAXZOOM:-13}"
WORLD_MAXZOOM="${WORLD_MAXZOOM:-5}"
EUROPE_BBOX="${EUROPE_BBOX:--25,32,45,72}"   # all of Europe (covers all images down to Madeira 32.65°N)
WORLD_BBOX="-180,-90,180,90"
BUILD_DATE="${BUILD_DATE:-20260608}"
FORCE_REBUILD="${FORCE_REBUILD:-false}"
PMTILES_VERSION="${PMTILES_VERSION:-1.30.3}"

SOURCE="https://build.protomaps.com/${BUILD_DATE}.pmtiles"
OUT="static/data/basemap.pmtiles"

# Persistent cache files (survive between runs for smart incremental builds)
WORLD_CACHE="/tmp/basemap_world.pmtiles"
WORLD_META="/tmp/basemap_world.meta"
EUROPE_CACHE="/tmp/basemap_europe.pmtiles"
EUROPE_META="/tmp/basemap_europe.meta"

# --- helpers ----------------------------------------------------------------

read_meta() { grep "^${2}=" "$1" 2>/dev/null | cut -d= -f2-; }
write_meta() { echo "$2=$3" >> "$1"; }

write_meta_file() {
    local f="$1"; shift
    : > "$f"
    while [ $# -ge 2 ]; do
        echo "$1=$2" >> "$f"
        shift 2
    done
}

float_lt() { [ "$(echo "$1 < $2" | bc -l)" -eq 1 ]; }
float_gt() { [ "$(echo "$1 > $2" | bc -l)" -eq 1 ]; }

# --- resolve pmtiles CLI ----------------------------------------------------

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

# --- step 1: world overview (z0..WORLD_MAXZOOM) ----------------------------

cache_valid_world() {
    [ -f "$WORLD_CACHE" ] && [ -f "$WORLD_META" ] \
        && [ "$(read_meta "$WORLD_META" maxzoom)"  = "$WORLD_MAXZOOM" ] \
        && [ "$(read_meta "$WORLD_META" build_date)" = "$BUILD_DATE" ]
}

if [ "$FORCE_REBUILD" = "true" ]; then
    rm -f "$WORLD_CACHE" "$WORLD_META" "$EUROPE_CACHE" "$EUROPE_META"
fi

if cache_valid_world; then
    echo ">> step 1/3: world overview (cached)  z0..${WORLD_MAXZOOM}"
else
    echo ">> step 1/3: world overview  z0..${WORLD_MAXZOOM}  bbox=${WORLD_BBOX}"
    "$PMTILES" extract "$SOURCE" "$WORLD_CACHE" \
        --bbox="$WORLD_BBOX" \
        --minzoom=0 \
        --maxzoom="$WORLD_MAXZOOM" \
        --download-threads=8
    write_meta_file "$WORLD_META" \
        type       world \
        minzoom    0 \
        maxzoom    "$WORLD_MAXZOOM" \
        build_date "$BUILD_DATE"
fi

# --- step 2: Europe detail (z(WORLD_MAXZOOM+1)..MAXZOOM) --------------------

EUROPE_MINZOOM=$((WORLD_MAXZOOM+1))

cache_valid_europe() {
    [ -f "$EUROPE_CACHE" ] && [ -f "$EUROPE_META" ] \
        && [ "$(read_meta "$EUROPE_META" bbox)"       = "$EUROPE_BBOX" ] \
        && [ "$(read_meta "$EUROPE_META" minzoom)"    = "$EUROPE_MINZOOM" ] \
        && [ "$(read_meta "$EUROPE_META" maxzoom)"    = "$MAXZOOM" ] \
        && [ "$(read_meta "$EUROPE_META" build_date)"  = "$BUILD_DATE" ]
}

# Check if old cache can serve as a base for incremental update
can_incremental_europe() {
    [ -f "$EUROPE_CACHE" ] && [ -f "$EUROPE_META" ] \
        && [ "$(read_meta "$EUROPE_META" build_date)" = "$BUILD_DATE" ] \
        && [ "$(read_meta "$EUROPE_META" minzoom)"    = "$EUROPE_MINZOOM" ]
}

extract_europe() {
    local bbox="$1" out="$2"
    echo "    extracting bbox=$bbox  z${EUROPE_MINZOOM}..${MAXZOOM}"
    "$PMTILES" extract "$SOURCE" "$out" \
        --bbox="$bbox" \
        --minzoom="$EUROPE_MINZOOM" \
        --maxzoom="$MAXZOOM" \
        --download-threads=8
}

build_europe_deltas() {
    local OLD_BBOX OLD_MIN_LON OLD_MIN_LAT OLD_MAX_LON OLD_MAX_LAT
    local NEW_MIN_LON NEW_MIN_LAT NEW_MAX_LON NEW_MAX_LAT
    local delta_idx=0 tmpfile merged

    OLD_BBOX="$(read_meta "$EUROPE_META" bbox)"
    OLD_MIN_LON=$(echo "$OLD_BBOX" | cut -d, -f1)
    OLD_MIN_LAT=$(echo "$OLD_BBOX" | cut -d, -f2)
    OLD_MAX_LON=$(echo "$OLD_BBOX" | cut -d, -f3)
    OLD_MAX_LAT=$(echo "$OLD_BBOX" | cut -d, -f4)

    NEW_MIN_LON=$(echo "$EUROPE_BBOX" | cut -d, -f1)
    NEW_MIN_LAT=$(echo "$EUROPE_BBOX" | cut -d, -f2)
    NEW_MAX_LON=$(echo "$EUROPE_BBOX" | cut -d, -f3)
    NEW_MAX_LAT=$(echo "$EUROPE_BBOX" | cut -d, -f4)

    # South expansion: new_min_lat < old_min_lat
    if float_lt "$NEW_MIN_LAT" "$OLD_MIN_LAT"; then
        tmpfile="/tmp/basemap_europe_delta_${delta_idx}.pmtiles"
        extract_europe "${NEW_MIN_LON},${NEW_MIN_LAT},${NEW_MAX_LON},${OLD_MIN_LAT}" "$tmpfile"
        delta_idx=$((delta_idx+1))
    fi

    # North expansion: new_max_lat > old_max_lat
    if float_gt "$NEW_MAX_LAT" "$OLD_MAX_LAT"; then
        tmpfile="/tmp/basemap_europe_delta_${delta_idx}.pmtiles"
        extract_europe "${NEW_MIN_LON},${OLD_MAX_LAT},${NEW_MAX_LON},${NEW_MAX_LAT}" "$tmpfile"
        delta_idx=$((delta_idx+1))
    fi

    # West expansion: new_min_lon < old_min_lon
    if float_lt "$NEW_MIN_LON" "$OLD_MIN_LON"; then
        tmpfile="/tmp/basemap_europe_delta_${delta_idx}.pmtiles"
        extract_europe "${NEW_MIN_LON},${OLD_MIN_LAT},${OLD_MIN_LON},${OLD_MAX_LAT}" "$tmpfile"
        delta_idx=$((delta_idx+1))
    fi

    # East expansion: new_max_lon > old_max_lon
    if float_gt "$NEW_MAX_LON" "$OLD_MAX_LON"; then
        tmpfile="/tmp/basemap_europe_delta_${delta_idx}.pmtiles"
        extract_europe "${OLD_MAX_LON},${OLD_MIN_LAT},${NEW_MAX_LON},${OLD_MAX_LAT}" "$tmpfile"
        delta_idx=$((delta_idx+1))
    fi

    if [ "$delta_idx" -eq 0 ]; then
        echo "    (no geographic expansion needed)"
        return
    fi

    # Merge old cache + all deltas → new cache
    merged="/tmp/basemap_europe_merged.pmtiles"
    MERGE_ARGS=("$EUROPE_CACHE")
    for ((i=0; i<delta_idx; i++)); do
        MERGE_ARGS+=("/tmp/basemap_europe_delta_${i}.pmtiles")
    done
    MERGE_ARGS+=("$merged")

    echo "    merging $((${#MERGE_ARGS[@]}-1)) source(s) into Europe cache"
    "$PMTILES" merge "${MERGE_ARGS[@]}"

    mv "$merged" "$EUROPE_CACHE"

    for ((i=0; i<delta_idx; i++)); do
        rm -f "/tmp/basemap_europe_delta_${i}.pmtiles"
    done
}

if cache_valid_europe; then
    echo ">> step 2/3: Europe detail (cached)  z${EUROPE_MINZOOM}..${MAXZOOM}  bbox=${EUROPE_BBOX}"
elif [ "$FORCE_REBUILD" = "true" ] || [ ! -f "$EUROPE_CACHE" ]; then
    echo ">> step 2/3: Europe detail (fresh)  z${EUROPE_MINZOOM}..${MAXZOOM}  bbox=${EUROPE_BBOX}"
    extract_europe "$EUROPE_BBOX" "$EUROPE_CACHE"
elif can_incremental_europe; then
    OLD_MAXZOOM="$(read_meta "$EUROPE_META" maxzoom)"
    OLD_BBOX="$(read_meta "$EUROPE_META" bbox)"
    echo ">> step 2/3: Europe detail (incremental)  z${EUROPE_MINZOOM}..${MAXZOOM}  bbox=${EUROPE_BBOX}"

    # Check if zoom increased (extract new zoom levels)
    if [ "$OLD_MAXZOOM" -lt "$MAXZOOM" ] 2>/dev/null; then
        tmpfile="/tmp/basemap_europe_newzoom.pmtiles"
        echo "    adding zoom levels $((OLD_MAXZOOM+1))..${MAXZOOM}"
        "$PMTILES" extract "$SOURCE" "$tmpfile" \
            --bbox="$EUROPE_BBOX" \
            --minzoom="$((OLD_MAXZOOM+1))" \
            --maxzoom="$MAXZOOM" \
            --download-threads=8
        merged="/tmp/basemap_europe_merged.pmtiles"
        "$PMTILES" merge "$EUROPE_CACHE" "$tmpfile" "$merged"
        mv "$merged" "$EUROPE_CACHE"
        rm -f "$tmpfile"
    fi

    # Check if bbox expanded (extract geographic deltas)
    if [ "$OLD_BBOX" != "$EUROPE_BBOX" ]; then
        build_europe_deltas
    fi
else
    # Build date changed or minzoom mismatch → full re-extract
    echo ">> step 2/3: Europe detail (fresh)  z${EUROPE_MINZOOM}..${MAXZOOM}  bbox=${EUROPE_BBOX}"
    extract_europe "$EUROPE_BBOX" "$EUROPE_CACHE"
fi

write_meta_file "$EUROPE_META" \
    type       europe \
    bbox       "$EUROPE_BBOX" \
    minzoom    "$EUROPE_MINZOOM" \
    maxzoom    "$MAXZOOM" \
    build_date "$BUILD_DATE"

# --- step 3: merge world + Europe into final output -------------------------

echo ">> step 3/3: merging into $OUT"
"$PMTILES" merge "$WORLD_CACHE" "$EUROPE_CACHE" "$OUT"

echo ">> done: $(du -h "$OUT" | cut -f1) at $OUT"