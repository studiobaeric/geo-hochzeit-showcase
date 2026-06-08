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
#   $env:MAXZOOM=12; .\tools\build_basemap.ps1
#
$ErrorActionPreference = "Stop"

$MAXZOOM = if ($env:MAXZOOM) { $env:MAXZOOM } else { "10" }
$WORLD_MAXZOOM = if ($env:WORLD_MAXZOOM) { $env:WORLD_MAXZOOM } else { "5" }
$EUROPE_BBOX = if ($env:EUROPE_BBOX) { $env:EUROPE_BBOX } else { "-25,34,45,72" }
$WORLD_BBOX = "-180,-90,180,90"
$BUILD_DATE = if ($env:BUILD_DATE) { $env:BUILD_DATE } else { "20260608" }
$PMTILES_VERSION = if ($env:PMTILES_VERSION) { $env:PMTILES_VERSION } else { "1.30.3" }

$SOURCE = "https://build.protomaps.com/${BUILD_DATE}.pmtiles"
$OUT = "static/data/basemap.pmtiles"
$TMP_WORLD = "$env:TEMP/basemap_world_z0-${WORLD_MAXZOOM}.pmtiles"
$TMP_EUROPE = "$env:TEMP/basemap_europe_z$($WORLD_MAXZOOM+1)-${MAXZOOM}.pmtiles"

# --- resolve the pmtiles CLI (PATH, else tools/bin, else download) ----------
$ROOT = Split-Path -Parent $PSScriptRoot
Push-Location $ROOT

New-Item -ItemType Directory -Force -Path "tools/bin" | Out-Null
New-Item -ItemType Directory -Force -Path "static/data" | Out-Null

$PMTILES = $null

# Check if pmtiles is in PATH
try {
    $PMTILES = (Get-Command pmtiles -ErrorAction Stop).Source
} catch {
    # Check if in tools/bin
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
    $ZipPath = "$env:TEMP/go-pmtiles.zip"

    Invoke-WebRequest -Uri $URL -OutFile $ZipPath -ErrorAction Stop
    Expand-Archive -Path $ZipPath -DestinationPath "tools/bin" -Force
    Remove-Item $ZipPath

    $PMTILES = "tools/bin/pmtiles.exe"
}

Write-Host ">> step 1/3: world overview  z0..${WORLD_MAXZOOM}  bbox=${WORLD_BBOX}"
& $PMTILES extract "$SOURCE" "$TMP_WORLD" `
    --bbox="$WORLD_BBOX" `
    --minzoom=0 `
    --maxzoom="$WORLD_MAXZOOM" `
    --download-threads=8

Write-Host ">> step 2/3: Europe detail   z$($WORLD_MAXZOOM+1)..${MAXZOOM}  bbox=${EUROPE_BBOX}"
& $PMTILES extract "$SOURCE" "$TMP_EUROPE" `
    --bbox="$EUROPE_BBOX" `
    --minzoom="$($WORLD_MAXZOOM+1)" `
    --maxzoom="$MAXZOOM" `
    --download-threads=8

Write-Host ">> step 3/3: merging into $OUT"
& $PMTILES merge "$TMP_WORLD" "$TMP_EUROPE" "$OUT"

Remove-Item -Force -ErrorAction SilentlyContinue "$TMP_WORLD"
Remove-Item -Force -ErrorAction SilentlyContinue "$TMP_EUROPE"

$size = (Get-Item "$OUT").Length / 1MB
Write-Host ">> done: $([math]::Round($size, 2)) MB at $OUT"

Pop-Location
