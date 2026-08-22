#!/usr/bin/env python3
"""Build the offline vector basemap (PMTiles) for Kartenquiz.

One cross-platform script instead of separate bash/PowerShell copies -
the platform-specific parts (three earlier scripts: build_basemap_linux.sh,
build_basemap.sh, build_basemap.ps1) had drifted out of sync before (a
Windows/macOS release-asset naming mismatch shipped and broke on a real
Windows machine), and PowerShell/bash logic can't be unit tested the same
way Python can. Only the pmtiles CLI's own download URL differs by
platform now (see `pmtiles_asset_name`), and that's covered directly by
tests/test_build_basemap.py.

Strategy: an ordered list of regions, from least to most detailed, merged
into a single static/data/basemap.pmtiles. Each region only contributes
the zoom levels above the previous region's maxzoom, restricted to its own
bbox - e.g. a worldwide region at z0-5 for orientation, then a detailed
region at z6-13 for a specific area, then an even more detailed region at
z14 for one particular town. Any number of regions works, not just two.

Regions are read from a tab-separated file (name<TAB>bbox<TAB>maxzoom, one
per line, sorted ascending by maxzoom), passed via REGIONS_FILE. If unset,
a two-region default (worldwide overview + one detail area) is synthesized
from the legacy MAXZOOM/WORLD_MAXZOOM/EUROPE_BBOX env vars for backwards
compatible manual/CLI use.

Each region is cached independently (by index) under CACHE_DIR, keyed by
its bbox/zoom range/build date; unchanged regions are skipped on rerun.

Configurable via environment variables:
    REGIONS_FILE        Path to a TSV file: name<TAB>bbox<TAB>maxzoom per line.
    MAXZOOM=13           Legacy mode only: detail region's zoom cap.
    WORLD_MAXZOOM=5      Legacy mode only: last zoom level for the world overview.
    EUROPE_BBOX=...      Legacy mode only: bbox for the detail region.
    BUILD_DATE           Protomaps daily build YYYYMMDD. Leave unset/empty
                         to auto-resolve the newest build actually available
                         (see `resolve_latest_build_date`) - Protomaps only
                         keeps daily builds for a few days, so any fixed
                         date hardcoded here would eventually 404.
    FORCE_REBUILD=true   ignore caches and rebuild everything from scratch
    DRY_RUN=true         print the build plan without downloading/writing anything
    CACHE_DIR            where per-region caches are kept between runs (default: system temp dir)
    PMTILES_VERSION      go-pmtiles CLI release to use if not already installed

Example: more street detail in legacy mode
    MAXZOOM=12 python tools/build_basemap.py
"""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

SCRIPT_DIR = Path(__file__).resolve().parent

# Packaged binaries (see tools/build_release.py) run this module in-process
# from map_build.py (imported as `tools.build_basemap`) rather than as a
# standalone script - there, __file__ resolves inside PyInstaller's onefile
# temp extraction dir, not next to the actual executable. Mirror app.py's
# frozen-path handling so the basemap still lands beside the real static/
# folder instead of a directory that vanishes when the process exits.
if getattr(sys, "frozen", False):
    PROJECT_ROOT = Path(sys.executable).resolve().parent
else:
    PROJECT_ROOT = SCRIPT_DIR.parent

DEFAULT_PMTILES_VERSION = "1.30.3"
DEFAULT_MAXZOOM = 13
DEFAULT_WORLD_MAXZOOM = 5
DEFAULT_EUROPE_BBOX = "-25,32,45,72"  # all of Europe (covers all images down to Madeira 32.65°N)
WORLD_BBOX = "-180,-90,180,90"

OUT_RELATIVE = Path("static/data/basemap.pmtiles")
BUILD_SOURCE_URL_TEMPLATE = "https://build.protomaps.com/{build_date}.pmtiles"
BUILD_DATE_PROBE_WINDOW_DAYS = 21  # Protomaps documents ~5 days retention; wide safety margin

# Some CDNs/WAFs (build.protomaps.com and GitHub releases both went through
# a CDN) return 403 for Python's default "Python-urllib/x.y" User-Agent,
# treating it as bot/scraper traffic, even though the exact same request
# from a browser or the pmtiles CLI's own HTTP client succeeds. Every
# request this script makes itself (not the pmtiles binary, which has its
# own client) sends this instead - see `_request`.
USER_AGENT = "geo-hochzeit-build-basemap/1.0 (+https://github.com/n1c01/Geo_Hochzeit)"
BUILD_DATE_PLACEHOLDER = "<neuester verfuegbarer Stand>"  # DRY_RUN display only, never resolved over the network

LogFn = Callable[[str], None]


class BuildError(Exception):
    """Invalid input or an unrecoverable build failure."""


@dataclass(frozen=True)
class Region:
    name: str
    bbox: str
    maxzoom: int


@dataclass(frozen=True)
class RegionPlan:
    index: int
    region: Region
    minzoom: int


# --- region parsing / zoom-range assignment ---------------------------------


def parse_bbox(value: str) -> Tuple[float, float, float, float]:
    parts = value.split(",")
    if len(parts) != 4:
        raise BuildError(f"malformed bbox: '{value}'")
    try:
        min_lon, min_lat, max_lon, max_lat = (float(p) for p in parts)
    except ValueError as e:
        raise BuildError(f"malformed bbox: '{value}'") from e
    return min_lon, min_lat, max_lon, max_lat


def parse_regions_file(path: Path) -> List[Region]:
    if not path.is_file():
        raise BuildError(f"REGIONS_FILE not found: {path}")

    regions = []
    for line_no, raw_line in enumerate(path.read_text().splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        parts = raw_line.rstrip("\n").split("\t")
        if len(parts) != 3:
            raise BuildError(
                f"malformed region on line {line_no} (expected name<TAB>bbox<TAB>maxzoom): {raw_line!r}"
            )
        name, bbox, maxzoom_str = parts
        if not name.strip():
            raise BuildError(f"region on line {line_no} has an empty name")
        try:
            maxzoom = int(maxzoom_str)
        except ValueError as e:
            raise BuildError(f"region '{name}' has a non-integer maxzoom: '{maxzoom_str}'") from e
        parse_bbox(bbox)  # raises BuildError on malformed bbox
        regions.append(Region(name=name, bbox=bbox, maxzoom=maxzoom))

    if not regions:
        raise BuildError(f"no regions defined in {path}")
    return regions


def legacy_regions_from_env(env: Dict[str, str]) -> List[Region]:
    maxzoom = int(env.get("MAXZOOM", DEFAULT_MAXZOOM))
    world_maxzoom = int(env.get("WORLD_MAXZOOM", DEFAULT_WORLD_MAXZOOM))
    europe_bbox = env.get("EUROPE_BBOX", DEFAULT_EUROPE_BBOX)
    return [
        Region(name="Welt", bbox=WORLD_BBOX, maxzoom=world_maxzoom),
        Region(name="Europa", bbox=europe_bbox, maxzoom=maxzoom),
    ]


def assign_zoom_ranges(regions: Sequence[Region]) -> List[RegionPlan]:
    """Each region gets the zoom band above the previous region's maxzoom.

    Requires strictly increasing maxzoom values so bands never overlap or
    have negative height.
    """
    plans = []
    prev_maxzoom = -1
    for index, region in enumerate(regions):
        if region.maxzoom <= prev_maxzoom:
            raise BuildError(
                f"region '{region.name}' maxzoom ({region.maxzoom}) must be greater than "
                f"the previous region's maxzoom ({prev_maxzoom})"
            )
        plans.append(RegionPlan(index=index, region=region, minzoom=prev_maxzoom + 1))
        prev_maxzoom = region.maxzoom
    return plans


def _request(url: str, headers: Optional[Dict[str, str]] = None) -> urllib.request.Request:
    """A urllib Request with USER_AGENT set - see its definition for why."""
    all_headers = {"User-Agent": USER_AGENT}
    if headers:
        all_headers.update(headers)
    return urllib.request.Request(url, headers=all_headers)


# --- pmtiles CLI resolution --------------------------------------------------


def pmtiles_asset_name(version: str, system: str, machine: str) -> str:
    """The go-pmtiles release asset filename for this OS/arch.

    Upstream naming isn't consistent across platforms: Windows uses an
    underscore after "go-pmtiles", macOS uses a hyphen there, and Linux
    uses an underscore with a .tar.gz extension instead of .zip. Getting
    this wrong reached a real Windows user once already (a hyphen was used
    for Windows, copied from the older macOS-only script) - this is the
    single place that decides it now.
    """
    arch = {
        "AMD64": "x86_64",
        "x86_64": "x86_64",
        "ARM64": "arm64",
        "arm64": "arm64",
        "aarch64": "arm64",
    }.get(machine)
    if arch is None:
        raise BuildError(f"unsupported architecture: {machine}")

    if system == "Linux":
        return f"go-pmtiles_{version}_Linux_{arch}.tar.gz"
    if system == "Darwin":
        return f"go-pmtiles-{version}_Darwin_{arch}.zip"
    if system == "Windows":
        return f"go-pmtiles_{version}_Windows_{arch}.zip"
    raise BuildError(f"unsupported OS: {system}")


def pmtiles_download_url(version: str, system: str, machine: str) -> str:
    asset = pmtiles_asset_name(version, system, machine)
    return f"https://github.com/protomaps/go-pmtiles/releases/download/v{version}/{asset}"


def _extract_pmtiles_binary(archive_path: Path, dest_dir: Path) -> Path:
    """Pull just the `pmtiles`/`pmtiles.exe` binary out of a release archive."""
    wanted_names = ("pmtiles", "pmtiles.exe")

    if archive_path.suffixes[-2:] == [".tar", ".gz"] or archive_path.suffix == ".tgz":
        with tarfile.open(archive_path) as tar:
            member = next((m for m in tar.getmembers() if Path(m.name).name in wanted_names), None)
            if member is None:
                raise BuildError(f"no pmtiles binary found inside {archive_path.name}")
            out_name = Path(member.name).name
            out_path = dest_dir / out_name
            extracted = tar.extractfile(member)
            if extracted is None:
                raise BuildError(f"could not read {member.name} from {archive_path.name}")
            with extracted, open(out_path, "wb") as dst:
                shutil.copyfileobj(extracted, dst)
    else:
        with zipfile.ZipFile(archive_path) as zf:
            member = next((n for n in zf.namelist() if Path(n).name in wanted_names), None)
            if member is None:
                raise BuildError(f"no pmtiles binary found inside {archive_path.name}")
            out_name = Path(member).name
            out_path = dest_dir / out_name
            with zf.open(member) as src, open(out_path, "wb") as dst:
                shutil.copyfileobj(src, dst)

    return out_path


def resolve_pmtiles_cli(bin_dir: Path, version: str, log: LogFn) -> Path:
    found = shutil.which("pmtiles")
    if found:
        return Path(found)

    local_name = "pmtiles.exe" if platform.system() == "Windows" else "pmtiles"
    local_path = bin_dir / local_name
    if local_path.is_file():
        return local_path

    log(f">> pmtiles CLI not found, downloading v{version}...")
    url = pmtiles_download_url(version, platform.system(), platform.machine())
    log(f"    URL: {url}")

    bin_dir.mkdir(parents=True, exist_ok=True)
    archive_path = bin_dir / Path(url).name
    try:
        with urllib.request.urlopen(_request(url), timeout=60) as response, open(archive_path, "wb") as f:
            shutil.copyfileobj(response, f)
    except urllib.error.URLError as e:
        raise BuildError(f"download failed (check version/OS/arch): {url} ({e})") from e

    try:
        extracted_path = _extract_pmtiles_binary(archive_path, bin_dir)
    finally:
        archive_path.unlink(missing_ok=True)

    if extracted_path != local_path:
        extracted_path.replace(local_path)
    if platform.system() != "Windows":
        local_path.chmod(0o755)

    return local_path


# --- build-date resolution ------------------------------------------------


def build_source_url(build_date: str) -> str:
    return BUILD_SOURCE_URL_TEMPLATE.format(build_date=build_date)


def _source_exists(build_date: str, log: LogFn = lambda _line: None) -> bool:
    """Whether a Protomaps daily build actually exists for this date.

    Uses a ranged GET (`Range: bytes=0-0`) with USER_AGENT set, not a bare
    HEAD: pmtiles itself only ever reads these files via range requests,
    and some static-file/CDN backends don't support HEAD at all, or 403 a
    generic Python User-Agent as bot traffic - either one made every
    single candidate date look "missing" even though real builds existed,
    exhausting the whole probe window for no real reason. Both have
    happened for real, on different attempts, before this fix.

    Logs the outcome of every attempt (not just failures) so a repeat of
    that failure mode is diagnosable from the build log instead of just
    seeing a flat "nothing found" at the end.
    """
    url = build_source_url(build_date)
    request = _request(url, headers={"Range": "bytes=0-0"})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            ok = response.status in (200, 206)
            log(f"   {build_date}: HTTP {response.status}{'' if ok else ' (unexpected status)'}")
            return ok
    except urllib.error.HTTPError as e:
        ok = e.code in (200, 206)
        log(f"   {build_date}: HTTP {e.code}")
        return ok
    except urllib.error.URLError as e:
        log(f"   {build_date}: request failed ({e.reason})")
        return False


def resolve_latest_build_date(
    log: LogFn,
    probe: Optional[Callable[[str], bool]] = None,
    window_days: int = BUILD_DATE_PROBE_WINDOW_DAYS,
) -> str:
    """The most recent YYYYMMDD date that actually has a Protomaps daily
    build available, found by probing backwards from today.

    Protomaps keeps daily planet builds for only ~5 days, so no fixed date
    can be hardcoded reliably here - one shipped in source once already and
    404'd within weeks. Asking the server what's actually there instead
    means this never goes stale.
    """
    actual_probe = probe if probe is not None else (lambda candidate: _source_exists(candidate, log))
    today = datetime.now(timezone.utc).date()
    for offset in range(window_days):
        candidate = (today - timedelta(days=offset)).strftime("%Y%m%d")
        if actual_probe(candidate):
            return candidate
    raise BuildError(
        f"no Protomaps daily build found in the last {window_days} days - "
        "check https://maps.protomaps.com/builds/ manually and set BUILD_DATE"
    )


# --- per-region caching -------------------------------------------------


def _cache_path(cache_dir: Path, index: int) -> Path:
    return cache_dir / f"basemap_region_{index}.pmtiles"


def _meta_path(cache_dir: Path, index: int) -> Path:
    return cache_dir / f"basemap_region_{index}.meta.json"


def is_cache_valid(cache_dir: Path, index: int, *, bbox: str, minzoom: int, maxzoom: int, build_date: str) -> bool:
    if not _cache_path(cache_dir, index).is_file():
        return False
    meta_file = _meta_path(cache_dir, index)
    if not meta_file.is_file():
        return False
    try:
        meta = json.loads(meta_file.read_text())
    except (OSError, json.JSONDecodeError):
        return False
    return (
        meta.get("bbox") == bbox
        and meta.get("minzoom") == minzoom
        and meta.get("maxzoom") == maxzoom
        and meta.get("build_date") == build_date
    )


def write_cache_meta(cache_dir: Path, index: int, *, bbox: str, minzoom: int, maxzoom: int, build_date: str) -> None:
    _meta_path(cache_dir, index).write_text(
        json.dumps({"bbox": bbox, "minzoom": minzoom, "maxzoom": maxzoom, "build_date": build_date})
    )


def clear_region_caches(cache_dir: Path) -> None:
    for f in cache_dir.glob("basemap_region_*"):
        f.unlink(missing_ok=True)


def clear_stale_region_caches(cache_dir: Path, keep_count: int) -> None:
    """Remove cached regions left over from a previous run with more regions."""
    index = keep_count
    while _cache_path(cache_dir, index).exists() or _meta_path(cache_dir, index).exists():
        _cache_path(cache_dir, index).unlink(missing_ok=True)
        _meta_path(cache_dir, index).unlink(missing_ok=True)
        index += 1


# --- progress reporting --------------------------------------------------
#
# map_build.py (the Flask backend driving this script from the web UI)
# scans log lines for this prefix to update a structured "progress" field
# it exposes over the /api/map/build/status poll, without having to guess
# progress from free-form text. Lines with this prefix are stripped from
# the human-facing log by the backend; everything else is shown as-is.

PROGRESS_PREFIX = "##PROGRESS## "


def _emit_progress(log: LogFn, **fields) -> None:
    log(PROGRESS_PREFIX + json.dumps(fields))


# pmtiles (github.com/schollz/progressbar) renders "<label> NNN% |bar| (...)"
# per update. On a real terminal it overwrites one line via \r; piped
# (exactly how we invoke it - not a TTY) it instead prints each update as
# its own \n-terminated line, which is what makes this parseable at all.
# Confirmed against a real local `pmtiles extract`/`cluster` run - see
# tests/test_build_basemap.py for the exact captured line format.
_PMTILES_PROGRESS_RE = re.compile(r"(\d{1,3})%\s*\|")


def _parse_pmtiles_progress_percent(line: str) -> Optional[int]:
    match = _PMTILES_PROGRESS_RE.search(line)
    if not match:
        return None
    return min(100, max(0, int(match.group(1))))


# --- pmtiles CLI invocation -----------------------------------------------


class PmtilesError(BuildError):
    """A pmtiles CLI invocation failed; carries its captured output."""

    def __init__(self, message: str, output_lines: List[str]):
        super().__init__(message)
        self.output_lines = output_lines


def run_pmtiles(
    pmtiles_bin: Path,
    args: List[str],
    log: LogFn,
    on_progress: Optional[Callable[[int], None]] = None,
) -> List[str]:
    """Run a pmtiles subcommand, streaming its output line by line as it's
    produced (not buffered until the process exits - a long extract/merge
    needs to report progress *during* the download, not after it).

    Lines matching pmtiles' own progress-bar format are routed to
    `on_progress` (parsed to a percentage) instead of `log`, if given -
    that's what turns pmtiles' own "fetching chunks NN%" spam (updated
    many times per second) into a structured, throttleable progress signal
    instead of flooding the human-facing log with thousands of lines.
    """
    process = subprocess.Popen(
        [str(pmtiles_bin), *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    output_lines: List[str] = []
    assert process.stdout is not None
    for raw_line in process.stdout:
        line = raw_line.rstrip("\n")
        output_lines.append(line)
        percent = _parse_pmtiles_progress_percent(line) if on_progress else None
        if percent is not None:
            on_progress(percent)
        else:
            log(line)
    process.wait()
    if process.returncode != 0:
        raise PmtilesError(f"pmtiles {args[0]} failed with exit code {process.returncode}", output_lines)
    return output_lines


def extract_region(
    pmtiles_bin: Path,
    source: str,
    build_date: str,
    out_path: Path,
    bbox: str,
    minzoom: int,
    maxzoom: int,
    log: LogFn,
    on_progress: Optional[Callable[[int], None]] = None,
) -> None:
    try:
        run_pmtiles(
            pmtiles_bin,
            [
                "extract",
                source,
                str(out_path),
                f"--bbox={bbox}",
                f"--minzoom={minzoom}",
                f"--maxzoom={maxzoom}",
                "--download-threads=8",
            ],
            log,
            on_progress=on_progress,
        )
    except PmtilesError as e:
        if any("404" in line or "range reader" in line for line in e.output_lines):
            log(
                f">> Hinweis: Die Protomaps-Quelldatei fuer BUILD_DATE '{build_date}' wurde "
                "nicht gefunden (404). Protomaps haelt taegliche Builds nur ca. 5 Tage vor - "
                "entweder das Build-Datum-Feld in den Karten-Einstellungen leer lassen "
                "(automatisch neuester Stand) oder ein aktuelles Datum von "
                "https://maps.protomaps.com/builds/ eintragen."
            )
        raise


# --- orchestration -----------------------------------------------------


def build(env: Dict[str, str], log: LogFn = print) -> Path:
    """Run the full build (or, if DRY_RUN, print the plan). Returns the output path."""
    build_date = env.get("BUILD_DATE") or ""
    force_rebuild = env.get("FORCE_REBUILD", "false") == "true"
    dry_run = env.get("DRY_RUN", "false") == "true"
    cache_dir = Path(env["CACHE_DIR"]) if env.get("CACHE_DIR") else Path(tempfile.gettempdir())
    pmtiles_version = env.get("PMTILES_VERSION", DEFAULT_PMTILES_VERSION)
    regions_file = env.get("REGIONS_FILE")

    out_path = PROJECT_ROOT / OUT_RELATIVE

    if regions_file:
        regions = parse_regions_file(Path(regions_file))
    else:
        regions = legacy_regions_from_env(env)
    plans = assign_zoom_ranges(regions)

    pmtiles_bin: Optional[Path] = None
    if not dry_run:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        cache_dir.mkdir(parents=True, exist_ok=True)

        _emit_progress(log, stage="resolving_pmtiles_cli")
        pmtiles_bin = resolve_pmtiles_cli(PROJECT_ROOT / "tools" / "bin", pmtiles_version, log)

        if not build_date:
            _emit_progress(log, stage="resolving_build_date")
            log(">> BUILD_DATE not set, looking up the newest available Protomaps build...")
            build_date = resolve_latest_build_date(log)
            log(f"   using {build_date}")

        if force_rebuild:
            clear_region_caches(cache_dir)
    elif not build_date:
        build_date = BUILD_DATE_PLACEHOLDER  # display only - never resolved over the network in a dry run

    source = build_source_url(build_date)
    log(f">> Protomaps-Kartendaten vom {build_date}  ({source})")

    merge_sources = []
    for plan in plans:
        region = plan.region
        valid = is_cache_valid(
            cache_dir,
            plan.index,
            bbox=region.bbox,
            minzoom=plan.minzoom,
            maxzoom=region.maxzoom,
            build_date=build_date,
        )
        log(
            f">> region {plan.index + 1} '{region.name}'  z{plan.minzoom}..{region.maxzoom}  "
            f"bbox={region.bbox}  ({'cached' if valid else 'fresh'})"
        )

        region_cache = _cache_path(cache_dir, plan.index)
        if not valid and not dry_run:
            assert pmtiles_bin is not None
            _emit_progress(
                log,
                stage="extracting",
                region_index=plan.index,
                region_count=len(plans),
                region_name=region.name,
                percent=0,
            )

            def region_progress(percent, region=region, plan=plan):
                _emit_progress(
                    log,
                    stage="extracting",
                    region_index=plan.index,
                    region_count=len(plans),
                    region_name=region.name,
                    percent=percent,
                )

            extract_region(
                pmtiles_bin,
                source,
                build_date,
                region_cache,
                region.bbox,
                plan.minzoom,
                region.maxzoom,
                log,
                on_progress=region_progress,
            )
            write_cache_meta(
                cache_dir, plan.index, bbox=region.bbox, minzoom=plan.minzoom, maxzoom=region.maxzoom, build_date=build_date
            )
        merge_sources.append(region_cache)

    if not dry_run:
        clear_stale_region_caches(cache_dir, keep_count=len(plans))

    log(f">> merging {len(plans)} region(s) into {out_path}")
    if dry_run:
        log(f">> (dry run) would run: pmtiles merge {' '.join(str(s) for s in merge_sources)} {out_path}")
    else:
        _emit_progress(log, stage="merging", percent=0)
        assert pmtiles_bin is not None
        run_pmtiles(
            pmtiles_bin,
            ["merge", *[str(s) for s in merge_sources], str(out_path)],
            log,
            on_progress=lambda percent: _emit_progress(log, stage="merging", percent=percent),
        )
        size_mb = out_path.stat().st_size / (1024 * 1024)
        log(f">> done: {size_mb:.1f} MB at {out_path}")
        _emit_progress(log, stage="done")

    return out_path


def main(argv: Optional[List[str]] = None) -> int:
    try:
        build(dict(os.environ))
    except BuildError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
