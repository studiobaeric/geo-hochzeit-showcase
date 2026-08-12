#!/usr/bin/env bash
#
# Build the offline vector basemap (PMTiles) for the Geoguesser.
#
# Strategy: an ordered list of regions, from least to most detailed, merged
# into a single static/data/basemap.pmtiles. Each region only contributes
# the zoom levels above the previous region's maxzoom, restricted to its own
# bbox - e.g. a worldwide region at z0-5 for orientation, then a detailed
# region at z6-13 for a specific area, then an even more detailed region at
# z14 for one particular town. Any number of regions works, not just two.
#
# Regions are read from a tab-separated file (name<TAB>bbox<TAB>maxzoom, one
# per line, sorted ascending by maxzoom), passed via REGIONS_FILE. If unset,
# a two-region default (worldwide overview + one detail area) is synthesized
# from the legacy MAXZOOM/WORLD_MAXZOOM/EUROPE_BBOX env vars for backwards
# compatible manual/CLI use.
#
# Each region is cached independently (by index) under CACHE_DIR, keyed by
# its bbox/zoom range/build date; unchanged regions are skipped on rerun.
#
# Configurable via environment variables:
#   REGIONS_FILE        Path to a TSV file: name<TAB>bbox<TAB>maxzoom per line.
#   MAXZOOM=13          Legacy mode only: detail region's zoom cap.
#   WORLD_MAXZOOM=5      Legacy mode only: last zoom level for the world overview.
#   EUROPE_BBOX=...      Legacy mode only: bbox for the detail region.
#   BUILD_DATE           Protomaps daily build YYYYMMDD.
#                        Pick a recent one from https://build.protomaps.com
#   FORCE_REBUILD=true   ignore caches and rebuild everything from scratch
#   DRY_RUN=true         print the build plan without downloading/writing anything
#   CACHE_DIR=/tmp        where per-region caches are kept between runs
#
# Example: more street detail in legacy mode
#   MAXZOOM=12 bash tools/build_basemap.sh
#
set -euo pipefail

BUILD_DATE="${BUILD_DATE:-20260608}"
FORCE_REBUILD="${FORCE_REBUILD:-false}"
DRY_RUN="${DRY_RUN:-false}"
CACHE_DIR="${CACHE_DIR:-/tmp}"
PMTILES_VERSION="${PMTILES_VERSION:-1.30.3}"
REGIONS_FILE="${REGIONS_FILE:-}"

SOURCE="https://build.protomaps.com/${BUILD_DATE}.pmtiles"
OUT="static/data/basemap.pmtiles"

# --- resolve regions ---------------------------------------------------------

CLEANUP_REGIONS_FILE=""
if [ -z "$REGIONS_FILE" ]; then
    MAXZOOM="${MAXZOOM:-13}"
    WORLD_MAXZOOM="${WORLD_MAXZOOM:-5}"
    EUROPE_BBOX="${EUROPE_BBOX:--25,32,45,72}"   # all of Europe (covers all images down to Madeira 32.65°N)
    REGIONS_FILE="$(mktemp)"
    CLEANUP_REGIONS_FILE=1
    printf 'Welt\t-180,-90,180,90\t%s\nEuropa\t%s\t%s\n' \
        "$WORLD_MAXZOOM" "$EUROPE_BBOX" "$MAXZOOM" > "$REGIONS_FILE"
fi

cleanup() {
    if [ -n "$CLEANUP_REGIONS_FILE" ]; then
        rm -f "$REGIONS_FILE"
    fi
}
trap cleanup EXIT

if [ ! -f "$REGIONS_FILE" ]; then
    echo "ERROR: REGIONS_FILE not found: $REGIONS_FILE" >&2
    exit 1
fi

# --- helpers ------------------------------------------------------------------

read_meta() { grep "^${2}=" "$1" 2>/dev/null | cut -d= -f2-; }

write_meta_file() {
    local f="$1"; shift
    : > "$f"
    while [ $# -ge 2 ]; do
        echo "$1=$2" >> "$f"
        shift 2
    done
}

is_int() { case "$1" in ''|*[!0-9-]*) return 1 ;; *) return 0 ;; esac; }

is_bbox() {
    # sanity check only (exact 4 comma-separated numbers); full validation
    # of ranges/ordering happens server-side before this file is written.
    local IFS=,; set -- $1
    [ "$#" -eq 4 ]
}

# --- resolve pmtiles CLI --------------------------------------------------

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
mkdir -p tools/bin static/data "$CACHE_DIR"

PMTILES=""
if [ "$DRY_RUN" != "true" ]; then
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
fi

if [ "$FORCE_REBUILD" = "true" ] && [ "$DRY_RUN" != "true" ]; then
    rm -f "${CACHE_DIR}"/basemap_region_*.pmtiles "${CACHE_DIR}"/basemap_region_*.meta
fi

# --- build each region, low detail to high detail --------------------------

MERGE_ARGS=()
region_index=0
prev_maxzoom=-1

while IFS=$'\t' read -r name bbox maxzoom || [ -n "${name:-}" ]; do
    [ -z "${name:-}" ] && continue

    if ! is_int "$maxzoom"; then
        echo "ERROR: region '$name' has a non-integer maxzoom: '$maxzoom'" >&2
        exit 1
    fi
    if ! is_bbox "$bbox"; then
        echo "ERROR: region '$name' has a malformed bbox: '$bbox'" >&2
        exit 1
    fi
    if [ "$maxzoom" -le "$prev_maxzoom" ]; then
        echo "ERROR: region '$name' maxzoom ($maxzoom) must be greater than the previous region's maxzoom ($prev_maxzoom)" >&2
        exit 1
    fi

    minzoom=$((prev_maxzoom + 1))
    cache="${CACHE_DIR}/basemap_region_${region_index}.pmtiles"
    meta="${CACHE_DIR}/basemap_region_${region_index}.meta"

    cache_valid() {
        [ -f "$cache" ] && [ -f "$meta" ] \
            && [ "$(read_meta "$meta" bbox)" = "$bbox" ] \
            && [ "$(read_meta "$meta" minzoom)" = "$minzoom" ] \
            && [ "$(read_meta "$meta" maxzoom)" = "$maxzoom" ] \
            && [ "$(read_meta "$meta" build_date)" = "$BUILD_DATE" ]
    }

    if cache_valid; then
        echo ">> region $((region_index+1)) '${name}'  z${minzoom}..${maxzoom}  bbox=${bbox}  (cached)"
    else
        echo ">> region $((region_index+1)) '${name}'  z${minzoom}..${maxzoom}  bbox=${bbox}  (fresh)"
        if [ "$DRY_RUN" != "true" ]; then
            "$PMTILES" extract "$SOURCE" "$cache" \
                --bbox="$bbox" \
                --minzoom="$minzoom" \
                --maxzoom="$maxzoom" \
                --download-threads=8
            write_meta_file "$meta" bbox "$bbox" minzoom "$minzoom" maxzoom "$maxzoom" build_date "$BUILD_DATE"
        fi
    fi

    MERGE_ARGS+=("$cache")
    prev_maxzoom="$maxzoom"
    region_index=$((region_index+1))
done < "$REGIONS_FILE"

if [ "$region_index" -eq 0 ]; then
    echo "ERROR: no regions defined in $REGIONS_FILE" >&2
    exit 1
fi

# Stale caches from an earlier run that had more regions than this one.
if [ "$DRY_RUN" != "true" ]; then
    i=$region_index
    while [ -f "${CACHE_DIR}/basemap_region_${i}.pmtiles" ] || [ -f "${CACHE_DIR}/basemap_region_${i}.meta" ]; do
        rm -f "${CACHE_DIR}/basemap_region_${i}.pmtiles" "${CACHE_DIR}/basemap_region_${i}.meta"
        i=$((i+1))
    done
fi

# --- merge all regions into the final output --------------------------------

echo ">> merging ${region_index} region(s) into $OUT"
if [ "$DRY_RUN" = "true" ]; then
    echo ">> (dry run) would run: pmtiles merge ${MERGE_ARGS[*]} $OUT"
else
    "$PMTILES" merge "${MERGE_ARGS[@]}" "$OUT"
    echo ">> done: $(du -h "$OUT" | cut -f1) at $OUT"
fi
