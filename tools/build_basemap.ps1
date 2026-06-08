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
#   FORCE_REBUILD=$true ignore caches and rebuild everything from scratch
#
# Example: more street detail
#   $env:MAXZOOM=12; .\tools\build_basemap.ps1
#
$ErrorActionPreference = "Stop"

$MAXZOOM         = if ($env:MAXZOOM)         { [int]$env:MAXZOOM }         else { 10 }
$WORLD_MAXZOOM   = if ($env:WORLD_MAXZOOM)   { [int]$env:WORLD_MAXZOOM }   else { 5 }
$EUROPE_BBOX     = if ($env:EUROPE_BBOX)     { $env:EUROPE_BBOX }          else { "-25,32,45,72" }
$WORLD_BBOX      = "-180,-90,180,90"
$BUILD_DATE      = if ($env:BUILD_DATE)      { $env:BUILD_DATE }           else { "20260608" }
$FORCE_REBUILD   = if ($env:FORCE_REBUILD)   { [bool]::Parse($env:FORCE_REBUILD) } else { $false }
$PMTILES_VERSION = if ($env:PMTILES_VERSION) { $env:PMTILES_VERSION }      else { "1.30.3" }

$SOURCE = "https://build.protomaps.com/${BUILD_DATE}.pmtiles"
$OUT = "static/data/basemap.pmtiles"
$TMPDIR = $env:TEMP

# Persistent cache files
$WORLD_CACHE  = "$TMPDIR/basemap_world.pmtiles"
$WORLD_META   = "$TMPDIR/basemap_world.meta.json"
$EUROPE_CACHE = "$TMPDIR/basemap_europe.pmtiles"
$EUROPE_META  = "$TMPDIR/basemap_europe.meta.json"

# --- helpers ----------------------------------------------------------------

function Read-Meta($path) {
    if (Test-Path $path) { return Get-Content $path | ConvertFrom-Json }
    return $null
}

function Write-Meta($path, $meta) {
    $meta | ConvertTo-Json | Set-Content $path
}

function Bbox-Parts($bbox) {
    $parts = $bbox.Split(',')
    return @{
        min_lon = [double]$parts[0]
        min_lat = [double]$parts[1]
        max_lon = [double]$parts[2]
        max_lat = [double]$parts[3]
    }
}

function Extract-Europe($bbox, $outFile, $minzoom, $maxzoom) {
    Write-Host "    extracting bbox=$bbox  z${minzoom}..${maxzoom}"
    & $PMTILES extract $SOURCE $outFile `
        --bbox="$bbox" `
        --minzoom=$minzoom `
        --maxzoom=$maxzoom `
        --download-threads=8
    if (-not $?) { throw "pmtiles extract failed" }
}

function Invoke-Merge($sources, $outFile) {
    $args = $sources + @($outFile)
    & $PMTILES merge @args
    if (-not $?) { throw "pmtiles merge failed" }
}

# --- resolve pmtiles CLI ----------------------------------------------------

$ROOT = Split-Path -Parent $PSScriptRoot
Push-Location $ROOT

New-Item -ItemType Directory -Force -Path "tools/bin" | Out-Null
New-Item -ItemType Directory -Force -Path "static/data" | Out-Null

$PMTILES = $null

try {
    $PMTILES = (Get-Command pmtiles -ErrorAction Stop).Source
} catch {
    if (Test-Path "tools/bin/pmtiles.exe") {
        $PMTILES = "tools/bin/pmtiles.exe"
    } elseif (Test-Path "tools/bin/pmtiles") {
        $PMTILES = "tools/bin/pmtiles"
    }
}

if (-not $PMTILES) {
    Write-Host ">> pmtiles CLI not found, downloading v${PMTILES_VERSION}..."
    $OS = "Windows"
    $ProcessArch = $env:PROCESSOR_ARCHITECTURE
    $ARCH = switch ($ProcessArch) {
        { $_ -in "AMD64", "x86_64" } { "x86_64" }
        { $_ -eq "ARM64" } { "arm64" }
        default { throw "Unsupported architecture: $_" }
    }
    $URL = "https://github.com/protomaps/go-pmtiles/releases/download/v${PMTILES_VERSION}/go-pmtiles-${PMTILES_VERSION}_${OS}_${ARCH}.zip"
    $ZipPath = "$TMPDIR/go-pmtiles.zip"
    Invoke-WebRequest -Uri $URL -OutFile $ZipPath -ErrorAction Stop
    Expand-Archive -Path $ZipPath -DestinationPath "tools/bin" -Force
    Remove-Item $ZipPath
    $PMTILES = "tools/bin/pmtiles.exe"
}

# --- force rebuild ----------------------------------------------------------

if ($FORCE_REBUILD) {
    Write-Host ">> FORCE_REBUILD=true, removing caches"
    Remove-Item -Force -ErrorAction SilentlyContinue $WORLD_CACHE, $WORLD_META, $EUROPE_CACHE, $EUROPE_META
}

# --- step 1: world overview (z0..WORLD_MAXZOOM) ----------------------------

$worldMeta = Read-Meta $WORLD_META
$worldValid = $worldMeta -and `
    ($worldMeta.maxzoom -eq $WORLD_MAXZOOM) -and `
    ($worldMeta.build_date -eq $BUILD_DATE)

if ($worldValid) {
    Write-Host ">> step 1/3: world overview (cached)  z0..${WORLD_MAXZOOM}"
} else {
    Write-Host ">> step 1/3: world overview  z0..${WORLD_MAXZOOM}  bbox=${WORLD_BBOX}"
    & $PMTILES extract $SOURCE $WORLD_CACHE `
        --bbox="$WORLD_BBOX" `
        --minzoom=0 `
        --maxzoom=$WORLD_MAXZOOM `
        --download-threads=8
    if (-not $?) { throw "pmtiles extract failed" }
    Write-Meta $WORLD_META @{
        type       = 'world'
        minzoom    = 0
        maxzoom    = $WORLD_MAXZOOM
        build_date = $BUILD_DATE
    }
}

# --- step 2: Europe detail (z(WORLD_MAXZOOM+1)..MAXZOOM) --------------------

$EUROPE_MINZOOM = $WORLD_MAXZOOM + 1

$europeMeta = Read-Meta $EUROPE_META
$europeValid = $europeMeta -and `
    ($europeMeta.bbox       -eq $EUROPE_BBOX) -and `
    ($europeMeta.minzoom    -eq $EUROPE_MINZOOM) -and `
    ($europeMeta.maxzoom    -eq $MAXZOOM) -and `
    ($europeMeta.build_date -eq $BUILD_DATE)

$canIncremental = $europeMeta -and `
    (Test-Path $EUROPE_CACHE) -and `
    ($europeMeta.build_date -eq $BUILD_DATE) -and `
    ($europeMeta.minzoom    -eq $EUROPE_MINZOOM)

function Build-Europe-Deltas {
    $old = Bbox-Parts $europeMeta.bbox
    $new = Bbox-Parts $EUROPE_BBOX
    $deltaIdx = 0
    $deltaFiles = @()

    # South expansion: new.min_lat < old.min_lat
    if ($new.min_lat -lt $old.min_lat) {
        $file = "$TMPDIR/basemap_europe_delta_${deltaIdx}.pmtiles"
        Extract-Europe "$($new.min_lon),$($new.min_lat),$($new.max_lon),$($old.min_lat)" $file $EUROPE_MINZOOM $MAXZOOM
        $deltaFiles += $file
        $deltaIdx++
    }

    # North expansion: new.max_lat > old.max_lat
    if ($new.max_lat -gt $old.max_lat) {
        $file = "$TMPDIR/basemap_europe_delta_${deltaIdx}.pmtiles"
        Extract-Europe "$($new.min_lon),$($old.max_lat),$($new.max_lon),$($new.max_lat)" $file $EUROPE_MINZOOM $MAXZOOM
        $deltaFiles += $file
        $deltaIdx++
    }

    # West expansion: new.min_lon < old.min_lon
    if ($new.min_lon -lt $old.min_lon) {
        $file = "$TMPDIR/basemap_europe_delta_${deltaIdx}.pmtiles"
        Extract-Europe "$($new.min_lon),$($old.min_lat),$($old.min_lon),$($old.max_lat)" $file $EUROPE_MINZOOM $MAXZOOM
        $deltaFiles += $file
        $deltaIdx++
    }

    # East expansion: new.max_lon > old.max_lon
    if ($new.max_lon -gt $old.max_lon) {
        $file = "$TMPDIR/basemap_europe_delta_${deltaIdx}.pmtiles"
        Extract-Europe "$($old.max_lon),$($old.min_lat),$($new.max_lon),$($old.max_lat)" $file $EUROPE_MINZOOM $MAXZOOM
        $deltaFiles += $file
        $deltaIdx++
    }

    if ($deltaIdx -eq 0) {
        Write-Host "    (no geographic expansion needed)"
        return
    }

    # Merge old cache + all deltas → new cache
    $merged = "$TMPDIR/basemap_europe_merged.pmtiles"
    $mergeSources = @($EUROPE_CACHE) + $deltaFiles
    Write-Host "    merging $($mergeSources.Count) source(s) into Europe cache"
    Invoke-Merge $mergeSources $merged
    Move-Item -Force $merged $EUROPE_CACHE
    Remove-Item -Force -ErrorAction SilentlyContinue $deltaFiles
}

if ($europeValid) {
    Write-Host ">> step 2/3: Europe detail (cached)  z${EUROPE_MINZOOM}..${MAXZOOM}  bbox=${EUROPE_BBOX}"
} elseif ($FORCE_REBUILD -or (-not (Test-Path $EUROPE_CACHE))) {
    Write-Host ">> step 2/3: Europe detail (fresh)  z${EUROPE_MINZOOM}..${MAXZOOM}  bbox=${EUROPE_BBOX}"
    Extract-Europe $EUROPE_BBOX $EUROPE_CACHE $EUROPE_MINZOOM $MAXZOOM
} elseif ($canIncremental) {
    Write-Host ">> step 2/3: Europe detail (incremental)  z${EUROPE_MINZOOM}..${MAXZOOM}  bbox=${EUROPE_BBOX}"

    # Zoom increase: extract new zoom levels
    if ($europeMeta.maxzoom -lt $MAXZOOM) {
        $tmpfile = "$TMPDIR/basemap_europe_newzoom.pmtiles"
        Write-Host "    adding zoom levels $($europeMeta.maxzoom+1)..${MAXZOOM}"
        & $PMTILES extract $SOURCE $tmpfile `
            --bbox="$EUROPE_BBOX" `
            --minzoom=$($europeMeta.maxzoom+1) `
            --maxzoom=$MAXZOOM `
            --download-threads=8
        if (-not $?) { throw "pmtiles extract failed" }
        $merged = "$TMPDIR/basemap_europe_merged.pmtiles"
        Invoke-Merge @($EUROPE_CACHE, $tmpfile) $merged
        Move-Item -Force $merged $EUROPE_CACHE
        Remove-Item -Force $tmpfile
    }

    # Bbox expansion: extract geographic deltas
    if ($europeMeta.bbox -ne $EUROPE_BBOX) {
        Build-Europe-Deltas
    }
} else {
    Write-Host ">> step 2/3: Europe detail (fresh)  z${EUROPE_MINZOOM}..${MAXZOOM}  bbox=${EUROPE_BBOX}"
    Extract-Europe $EUROPE_BBOX $EUROPE_CACHE $EUROPE_MINZOOM $MAXZOOM
}

Write-Meta $EUROPE_META @{
    type       = 'europe'
    bbox       = $EUROPE_BBOX
    minzoom    = $EUROPE_MINZOOM
    maxzoom    = $MAXZOOM
    build_date = $BUILD_DATE
}

# --- step 3: merge world + Europe into final output -------------------------

Write-Host ">> step 3/3: merging into $OUT"
Invoke-Merge @($WORLD_CACHE, $EUROPE_CACHE) $OUT

$size = [math]::Round((Get-Item "$OUT").Length / 1MB, 2)
Write-Host ">> done: ${size} MB at $OUT"
Pop-Location