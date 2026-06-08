# Downloads the glyph fonts (Noto Sans Regular/Medium/Italic) needed by the
# "light" basemap style to render text labels offline.
#
# These are ~768 small .pbf files (~13 MB) and are NOT checked into git - run
# this once after cloning (and after every `npm install`-style setup):
#
#   .\tools\fetch_fonts.ps1
#
# Source: https://github.com/protomaps/basemaps-assets
#
$ErrorActionPreference = "Stop"

$ROOT = Split-Path -Parent $PSScriptRoot
Push-Location $ROOT

$TARBALL = "$env:TEMP/basemaps-assets.tar.gz"
$URL = "https://github.com/protomaps/basemaps-assets/archive/refs/heads/main.tar.gz"

Write-Host ">> downloading basemaps-assets..."
Invoke-WebRequest -Uri $URL -OutFile $TARBALL -ErrorAction Stop

Write-Host ">> extracting font stacks into static/fonts/"
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue "static/fonts"
New-Item -ItemType Directory -Force -Path "static/fonts" | Out-Null

# Extract using tar (available in Windows 10 1803+)
if (Get-Command tar -ErrorAction SilentlyContinue) {
    tar xzf "$TARBALL" -C "static" --strip-components=1 `
        "basemaps-assets-main/fonts/Noto Sans Regular" `
        "basemaps-assets-main/fonts/Noto Sans Medium" `
        "basemaps-assets-main/fonts/Noto Sans Italic"
} else {
    Write-Error "tar command not found. Please use one of:
  - Windows 10 1803+ (includes native tar support)
  - Git Bash (includes tar)
  - WSL2 with this script in bash
  - Install 7-Zip and use '7z x basemaps-assets.tar.gz' manually"
}

$fontCount = @(Get-ChildItem -Path "static/fonts" -Recurse).Count
$pbfCount = @(Get-ChildItem -Path "static/fonts" -Filter "*.pbf" -Recurse).Count

Write-Host ">> done: $fontCount font stacks, $pbfCount glyph ranges"
Remove-Item -Force -ErrorAction SilentlyContinue "$TARBALL"

Pop-Location
