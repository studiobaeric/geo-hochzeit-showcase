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
#   REGIONS_FILE         Path to a TSV file: name<TAB>bbox<TAB>maxzoom per line.
#   MAXZOOM=13           Legacy mode only: detail region's zoom cap.
#   WORLD_MAXZOOM=5       Legacy mode only: last zoom level for the world overview.
#   EUROPE_BBOX=...       Legacy mode only: bbox for the detail region.
#   BUILD_DATE            Protomaps daily build YYYYMMDD.
#                         Pick a recent one from https://build.protomaps.com
#   FORCE_REBUILD=$true   ignore caches and rebuild everything from scratch
#   DRY_RUN=$true         print the build plan without downloading/writing anything
#   CACHE_DIR             where per-region caches are kept between runs (default: $env:TEMP)
#
# Example: more street detail in legacy mode
#   $env:MAXZOOM=12; .\tools\build_basemap.ps1
#
$ErrorActionPreference = "Stop"

$BUILD_DATE      = if ($env:BUILD_DATE)      { $env:BUILD_DATE }           else { "20260608" }
$FORCE_REBUILD   = if ($env:FORCE_REBUILD)   { [bool]::Parse($env:FORCE_REBUILD) } else { $false }
$DRY_RUN         = if ($env:DRY_RUN)         { [bool]::Parse($env:DRY_RUN) } else { $false }
$PMTILES_VERSION = if ($env:PMTILES_VERSION) { $env:PMTILES_VERSION }      else { "1.30.3" }
$CACHE_DIR       = if ($env:CACHE_DIR)       { $env:CACHE_DIR }            else { $env:TEMP }

$SOURCE = "https://build.protomaps.com/${BUILD_DATE}.pmtiles"
$OUT = "static/data/basemap.pmtiles"

# --- resolve regions ----------------------------------------------------------

$RegionsFilePath = $env:REGIONS_FILE
$CleanupRegionsFile = $false

if (-not $RegionsFilePath) {
    $MAXZOOM       = if ($env:MAXZOOM)       { [int]$env:MAXZOOM }       else { 13 }
    $WORLD_MAXZOOM = if ($env:WORLD_MAXZOOM) { [int]$env:WORLD_MAXZOOM } else { 5 }
    $EUROPE_BBOX   = if ($env:EUROPE_BBOX)   { $env:EUROPE_BBOX }        else { "-25,32,45,72" }

    $RegionsFilePath = [System.IO.Path]::GetTempFileName()
    $CleanupRegionsFile = $true
    @(
        "Welt`t-180,-90,180,90`t$WORLD_MAXZOOM"
        "Europa`t$EUROPE_BBOX`t$MAXZOOM"
    ) | Set-Content -Path $RegionsFilePath -Encoding utf8
}

if (-not (Test-Path $RegionsFilePath)) {
    Write-Error "REGIONS_FILE not found: $RegionsFilePath"
    exit 1
}

# --- helpers --------------------------------------------------------------

function Read-RegionMeta($path) {
    if (Test-Path $path) { return Get-Content $path | ConvertFrom-Json }
    return $null
}

function Write-RegionMeta($path, $meta) {
    $meta | ConvertTo-Json | Set-Content $path
}

function Test-IsInt($value) {
    return $value -match '^-?\d+$'
}

function Test-IsBbox($value) {
    return ($value.Split(',').Count -eq 4)
}

try {
    # --- resolve pmtiles CLI ------------------------------------------------

    $ROOT = Split-Path -Parent $PSScriptRoot
    Push-Location $ROOT

    New-Item -ItemType Directory -Force -Path "tools/bin" | Out-Null
    New-Item -ItemType Directory -Force -Path "static/data" | Out-Null
    New-Item -ItemType Directory -Force -Path "$CACHE_DIR" | Out-Null

    $PMTILES = $null

    if (-not $DRY_RUN) {
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
            $ZipPath = "$CACHE_DIR/go-pmtiles.zip"
            Invoke-WebRequest -Uri $URL -OutFile $ZipPath -ErrorAction Stop
            Expand-Archive -Path $ZipPath -DestinationPath "tools/bin" -Force
            Remove-Item $ZipPath
            $PMTILES = "tools/bin/pmtiles.exe"
        }
    }

    if ($FORCE_REBUILD -and -not $DRY_RUN) {
        Write-Host ">> FORCE_REBUILD=true, removing region caches"
        Remove-Item -Force -ErrorAction SilentlyContinue "$CACHE_DIR/basemap_region_*.pmtiles", "$CACHE_DIR/basemap_region_*.meta.json"
    }

    # --- build each region, low detail to high detail -----------------------

    $mergeSources = @()
    $regionIndex = 0
    $prevMaxzoom = -1

    $lines = Get-Content $RegionsFilePath | Where-Object { $_.Trim() -ne "" }
    foreach ($line in $lines) {
        $parts = $line -split "`t"
        if ($parts.Count -ne 3) {
            Write-Error "Malformed region line (expected name<TAB>bbox<TAB>maxzoom): $line"
            exit 1
        }
        $name, $bbox, $maxzoom = $parts

        if (-not (Test-IsInt $maxzoom)) {
            Write-Error "Region '$name' has a non-integer maxzoom: '$maxzoom'"
            exit 1
        }
        if (-not (Test-IsBbox $bbox)) {
            Write-Error "Region '$name' has a malformed bbox: '$bbox'"
            exit 1
        }
        $maxzoomInt = [int]$maxzoom
        if ($maxzoomInt -le $prevMaxzoom) {
            Write-Error "Region '$name' maxzoom ($maxzoomInt) must be greater than the previous region's maxzoom ($prevMaxzoom)"
            exit 1
        }
        $minzoom = $prevMaxzoom + 1

        $cache = "$CACHE_DIR/basemap_region_${regionIndex}.pmtiles"
        $meta = "$CACHE_DIR/basemap_region_${regionIndex}.meta.json"

        $existingMeta = Read-RegionMeta $meta
        $cacheValid = $existingMeta -and (Test-Path $cache) -and `
            ($existingMeta.bbox -eq $bbox) -and `
            ($existingMeta.minzoom -eq $minzoom) -and `
            ($existingMeta.maxzoom -eq $maxzoomInt) -and `
            ($existingMeta.build_date -eq $BUILD_DATE)

        if ($cacheValid) {
            Write-Host ">> region $($regionIndex+1) '$name'  z${minzoom}..${maxzoomInt}  bbox=${bbox}  (cached)"
        } else {
            Write-Host ">> region $($regionIndex+1) '$name'  z${minzoom}..${maxzoomInt}  bbox=${bbox}  (fresh)"
            if (-not $DRY_RUN) {
                & $PMTILES extract $SOURCE $cache `
                    --bbox="$bbox" `
                    --minzoom=$minzoom `
                    --maxzoom=$maxzoomInt `
                    --download-threads=8
                if (-not $?) { throw "pmtiles extract failed for region '$name'" }
                Write-RegionMeta $meta @{
                    bbox       = $bbox
                    minzoom    = $minzoom
                    maxzoom    = $maxzoomInt
                    build_date = $BUILD_DATE
                }
            }
        }

        $mergeSources += $cache
        $prevMaxzoom = $maxzoomInt
        $regionIndex++
    }

    if ($regionIndex -eq 0) {
        Write-Error "No regions defined in $RegionsFilePath"
        exit 1
    }

    # Stale caches from an earlier run that had more regions than this one.
    if (-not $DRY_RUN) {
        $i = $regionIndex
        while ((Test-Path "$CACHE_DIR/basemap_region_${i}.pmtiles") -or (Test-Path "$CACHE_DIR/basemap_region_${i}.meta.json")) {
            Remove-Item -Force -ErrorAction SilentlyContinue "$CACHE_DIR/basemap_region_${i}.pmtiles", "$CACHE_DIR/basemap_region_${i}.meta.json"
            $i++
        }
    }

    # --- merge all regions into the final output -----------------------------

    Write-Host ">> merging $regionIndex region(s) into $OUT"
    if ($DRY_RUN) {
        Write-Host ">> (dry run) would run: pmtiles merge $($mergeSources -join ' ') $OUT"
    } else {
        $mergeArgs = $mergeSources + @($OUT)
        & $PMTILES merge @mergeArgs
        if (-not $?) { throw "pmtiles merge failed" }
        $size = [math]::Round((Get-Item "$OUT").Length / 1MB, 2)
        Write-Host ">> done: ${size} MB at $OUT"
    }
} finally {
    if ($CleanupRegionsFile) {
        Remove-Item -Force -ErrorAction SilentlyContinue $RegionsFilePath
    }
    Pop-Location
}
