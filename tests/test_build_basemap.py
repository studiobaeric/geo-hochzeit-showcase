"""Tests for tools/build_basemap.py.

Unlike the bash/PowerShell scripts it replaced, this is plain Python, so
its logic (region parsing, zoom-range assignment, caching, the pmtiles
release-asset URL) is imported and unit tested directly - no more
DRY_RUN-and-grep-stdout black-box testing. A couple of true subprocess
tests at the bottom cover the `python tools/build_basemap.py` CLI entry
point itself, and a network test confirms the pinned PMTILES_VERSION's
release assets actually exist for all three platforms (this is exactly
the class of bug that broke Windows once already: a hyphen vs. underscore
mismatch in the asset name that nothing caught until a real user hit it).
"""

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "tools"))

import build_basemap as bb  # noqa: E402


# --- bbox / region parsing --------------------------------------------------


def test_parse_bbox_valid():
    assert bb.parse_bbox("-25,32,45,72") == (-25.0, 32.0, 45.0, 72.0)


@pytest.mark.parametrize("value", ["1,2,3", "1,2,3,4,5", "a,b,c,d", ""])
def test_parse_bbox_rejects_malformed_values(value):
    with pytest.raises(bb.BuildError):
        bb.parse_bbox(value)


def test_parse_regions_file(tmp_path):
    path = tmp_path / "regions.tsv"
    path.write_text("Welt\t-180,-90,180,90\t5\nEuropa\t-25,32,45,72\t13\n")

    regions = bb.parse_regions_file(path)

    assert regions == [
        bb.Region(name="Welt", bbox="-180,-90,180,90", maxzoom=5),
        bb.Region(name="Europa", bbox="-25,32,45,72", maxzoom=13),
    ]


def test_parse_regions_file_skips_blank_lines(tmp_path):
    path = tmp_path / "regions.tsv"
    path.write_text("Welt\t-180,-90,180,90\t5\n\n\nEuropa\t-25,32,45,72\t13\n")

    regions = bb.parse_regions_file(path)

    assert len(regions) == 2


def test_parse_regions_file_missing_raises(tmp_path):
    with pytest.raises(bb.BuildError, match="not found"):
        bb.parse_regions_file(tmp_path / "nope.tsv")


def test_parse_regions_file_empty_raises(tmp_path):
    path = tmp_path / "regions.tsv"
    path.write_text("")

    with pytest.raises(bb.BuildError, match="no regions defined"):
        bb.parse_regions_file(path)


def test_parse_regions_file_rejects_wrong_column_count(tmp_path):
    path = tmp_path / "regions.tsv"
    path.write_text("Welt\t-180,-90,180,90\n")

    with pytest.raises(bb.BuildError, match="malformed region"):
        bb.parse_regions_file(path)


def test_parse_regions_file_rejects_non_integer_maxzoom(tmp_path):
    path = tmp_path / "regions.tsv"
    path.write_text("Welt\t-180,-90,180,90\tnotanumber\n")

    with pytest.raises(bb.BuildError, match="non-integer maxzoom"):
        bb.parse_regions_file(path)


def test_parse_regions_file_rejects_malformed_bbox(tmp_path):
    path = tmp_path / "regions.tsv"
    path.write_text("Welt\t1,2,3\t5\n")

    with pytest.raises(bb.BuildError, match="malformed bbox"):
        bb.parse_regions_file(path)


def test_legacy_regions_from_env_defaults():
    regions = bb.legacy_regions_from_env({})

    assert regions == [
        bb.Region(name="Welt", bbox=bb.WORLD_BBOX, maxzoom=bb.DEFAULT_WORLD_MAXZOOM),
        bb.Region(name="Europa", bbox=bb.DEFAULT_EUROPE_BBOX, maxzoom=bb.DEFAULT_MAXZOOM),
    ]


def test_legacy_regions_from_env_honors_overrides():
    regions = bb.legacy_regions_from_env(
        {"MAXZOOM": "11", "WORLD_MAXZOOM": "3", "EUROPE_BBOX": "5.5,47,15.5,55"}
    )

    assert regions == [
        bb.Region(name="Welt", bbox=bb.WORLD_BBOX, maxzoom=3),
        bb.Region(name="Europa", bbox="5.5,47,15.5,55", maxzoom=11),
    ]


# --- zoom-range assignment --------------------------------------------------


def test_assign_zoom_ranges_single_region_starts_at_zero():
    plans = bb.assign_zoom_ranges([bb.Region(name="Solo", bbox="1,1,2,2", maxzoom=10)])

    assert len(plans) == 1
    assert plans[0].minzoom == 0
    assert plans[0].index == 0


def test_assign_zoom_ranges_stacks_bands():
    regions = [
        bb.Region(name="Welt", bbox=bb.WORLD_BBOX, maxzoom=5),
        bb.Region(name="Europa", bbox="-25,32,45,72", maxzoom=11),
        bb.Region(name="Madeira", bbox="-17.5,32.5,-16.5,33", maxzoom=14),
    ]

    plans = bb.assign_zoom_ranges(regions)

    assert [(p.index, p.minzoom, p.region.maxzoom) for p in plans] == [
        (0, 0, 5),
        (1, 6, 11),
        (2, 12, 14),
    ]


def test_assign_zoom_ranges_rejects_non_increasing_maxzoom():
    regions = [
        bb.Region(name="A", bbox="1,1,2,2", maxzoom=10),
        bb.Region(name="B", bbox="1,1,2,2", maxzoom=8),
    ]

    with pytest.raises(bb.BuildError, match="must be greater than"):
        bb.assign_zoom_ranges(regions)


def test_assign_zoom_ranges_rejects_equal_maxzoom():
    regions = [
        bb.Region(name="A", bbox="1,1,2,2", maxzoom=10),
        bb.Region(name="B", bbox="1,1,2,2", maxzoom=10),
    ]

    with pytest.raises(bb.BuildError, match="must be greater than"):
        bb.assign_zoom_ranges(regions)


# --- pmtiles release asset naming -------------------------------------------
#
# This is exactly the logic that shipped a bug once already: the Windows
# script used the macOS naming convention (a hyphen) instead of the
# underscore Windows release assets actually use.


@pytest.mark.parametrize(
    "system, machine, expected",
    [
        ("Linux", "x86_64", "go-pmtiles_1.30.3_Linux_x86_64.tar.gz"),
        ("Linux", "aarch64", "go-pmtiles_1.30.3_Linux_arm64.tar.gz"),
        ("Darwin", "x86_64", "go-pmtiles-1.30.3_Darwin_x86_64.zip"),
        ("Darwin", "arm64", "go-pmtiles-1.30.3_Darwin_arm64.zip"),
        ("Windows", "AMD64", "go-pmtiles_1.30.3_Windows_x86_64.zip"),
        ("Windows", "ARM64", "go-pmtiles_1.30.3_Windows_arm64.zip"),
    ],
)
def test_pmtiles_asset_name(system, machine, expected):
    assert bb.pmtiles_asset_name("1.30.3", system, machine) == expected


def test_pmtiles_asset_name_rejects_unsupported_os():
    with pytest.raises(bb.BuildError, match="unsupported OS"):
        bb.pmtiles_asset_name("1.30.3", "Plan9", "x86_64")


def test_pmtiles_asset_name_rejects_unsupported_arch():
    with pytest.raises(bb.BuildError, match="unsupported architecture"):
        bb.pmtiles_asset_name("1.30.3", "Linux", "riscv64")


def test_pmtiles_download_url():
    url = bb.pmtiles_download_url("1.30.3", "Windows", "AMD64")
    assert url == (
        "https://github.com/protomaps/go-pmtiles/releases/download/"
        "v1.30.3/go-pmtiles_1.30.3_Windows_x86_64.zip"
    )


@pytest.mark.parametrize("system, machine", [("Linux", "x86_64"), ("Darwin", "x86_64"), ("Windows", "AMD64")])
def test_pinned_pmtiles_release_asset_exists(system, machine):
    """Confirms the real release actually has the asset we'd request, for
    the PMTILES_VERSION pinned in this script. Skips without network access
    or on a transient server-side error (5xx) rather than failing the suite
    over connectivity/infrastructure hiccups - a 404 specifically (the
    asset genuinely doesn't exist) is still a hard failure."""
    url = bb.pmtiles_download_url(bb.DEFAULT_PMTILES_VERSION, system, machine)
    request = urllib.request.Request(url, method="HEAD")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            status = response.status
    except urllib.error.HTTPError as e:
        status = e.code
    except (urllib.error.URLError, TimeoutError) as e:
        pytest.skip(f"no network access to verify release asset ({e})")

    if status >= 500:
        pytest.skip(f"transient server error ({status}) verifying release asset: {url}")

    assert status == 200, f"pmtiles release asset not found: {url}"


# --- build-date resolution --------------------------------------------------
#
# BUILD_DATE used to default to a fixed string hardcoded in source, which
# 404'd for real once Protomaps' ~5-day retention window rolled past it.
# resolve_latest_build_date() asks the server instead of guessing, so
# these tests inject a fake probe rather than hitting the network - the
# real endpoint is covered separately, further down.


def test_build_source_url():
    assert bb.build_source_url("20260810") == "https://build.protomaps.com/20260810.pmtiles"


def test_resolve_latest_build_date_returns_first_available_date():
    today = datetime.now(timezone.utc).date()
    available = (today - timedelta(days=2)).strftime("%Y%m%d")

    def fake_probe(candidate):
        return candidate == available

    assert bb.resolve_latest_build_date(log=lambda _: None, probe=fake_probe) == available


def test_resolve_latest_build_date_prefers_more_recent_dates():
    today = datetime.now(timezone.utc).date()
    newer = today.strftime("%Y%m%d")
    older = (today - timedelta(days=3)).strftime("%Y%m%d")

    def fake_probe(candidate):
        return candidate in (newer, older)

    assert bb.resolve_latest_build_date(log=lambda _: None, probe=fake_probe) == newer


def test_resolve_latest_build_date_raises_when_nothing_found_in_window():
    with pytest.raises(bb.BuildError, match="no Protomaps daily build found"):
        bb.resolve_latest_build_date(log=lambda _: None, probe=lambda candidate: False, window_days=3)


def test_resolve_latest_build_date_stops_probing_once_found():
    today = datetime.now(timezone.utc).date()
    newest = today.strftime("%Y%m%d")
    probed = []

    def fake_probe(candidate):
        probed.append(candidate)
        return candidate == newest

    bb.resolve_latest_build_date(log=lambda _: None, probe=fake_probe)

    assert probed == [newest]


@pytest.mark.parametrize("status_code", [200, 206])
def test_source_exists_accepts_ok_and_partial_content(monkeypatch, status_code):
    class FakeResponse:
        status = status_code

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(bb.urllib.request, "urlopen", lambda *a, **k: FakeResponse())

    assert bb._source_exists("20260810") is True


def test_source_exists_false_on_404(monkeypatch):
    def raise_404(*args, **kwargs):
        raise urllib.error.HTTPError("url", 404, "not found", {}, None)

    monkeypatch.setattr(bb.urllib.request, "urlopen", raise_404)

    assert bb._source_exists("20260101") is False


def test_source_exists_false_on_connection_error(monkeypatch):
    def raise_url_error(*args, **kwargs):
        raise urllib.error.URLError("no network")

    monkeypatch.setattr(bb.urllib.request, "urlopen", raise_url_error)

    assert bb._source_exists("20260101") is False


def test_source_exists_uses_ranged_get_not_head(monkeypatch):
    """Regression test: HEAD isn't universally supported by static-file
    backends and using it here once made every candidate date look
    "missing" even though real builds existed - see resolve_latest_build_date's
    call site in build() for the reported failure. A ranged GET is what
    pmtiles itself uses to read these files, so it's guaranteed compatible."""
    captured = {}

    class FakeResponse:
        status = 206

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_urlopen(request, timeout=None):
        captured["method"] = request.get_method()
        captured["range_header"] = request.get_header("Range")
        return FakeResponse()

    monkeypatch.setattr(bb.urllib.request, "urlopen", fake_urlopen)

    assert bb._source_exists("20260810") is True
    assert captured["method"] == "GET"
    assert captured["range_header"] == "bytes=0-0"


def test_source_exists_sends_a_non_default_user_agent(monkeypatch):
    """Regression test: build.protomaps.com (and GitHub releases) 403
    Python's default "Python-urllib/x.y" User-Agent as bot traffic, even
    though the identical request from a browser or curl succeeds - this
    made every single candidate date look "missing" on a real run."""
    captured = {}

    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_urlopen(request, timeout=None):
        captured["user_agent"] = request.get_header("User-agent")  # urllib title-cases header keys
        return FakeResponse()

    monkeypatch.setattr(bb.urllib.request, "urlopen", fake_urlopen)

    bb._source_exists("20260810")

    assert captured["user_agent"] == bb.USER_AGENT
    assert "python-urllib" not in captured["user_agent"].lower()


def test_source_exists_false_on_403(monkeypatch):
    def raise_403(*args, **kwargs):
        raise urllib.error.HTTPError("url", 403, "forbidden", {}, None)

    monkeypatch.setattr(bb.urllib.request, "urlopen", raise_403)

    assert bb._source_exists("20260812") is False


def test_source_exists_logs_the_outcome_of_every_attempt(monkeypatch):
    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(bb.urllib.request, "urlopen", lambda *a, **k: FakeResponse())

    lines = []
    bb._source_exists("20260810", log=lines.append)

    assert any("20260810" in line and "200" in line for line in lines)


def test_resolve_latest_build_date_default_probe_uses_module_level_source_exists(monkeypatch):
    """Not passing `probe=` explicitly must still go through _source_exists
    (so monkeypatching it, e.g. in a test or a future caller, actually has
    an effect) rather than a stale reference captured at def-time."""
    calls = []

    def fake_source_exists(candidate, log=None):
        calls.append(candidate)
        return True

    monkeypatch.setattr(bb, "_source_exists", fake_source_exists)

    result = bb.resolve_latest_build_date(log=lambda _: None)

    today = datetime.now(timezone.utc).date().strftime("%Y%m%d")
    assert result == today
    assert calls == [today]


def test_resolve_latest_build_date_against_real_server():
    """Confirms the real endpoint responds as resolve_latest_build_date
    expects, without asserting an exact date (that changes daily). Skips
    without network access."""
    try:
        result = bb.resolve_latest_build_date(log=lambda _: None)
    except bb.BuildError as e:
        pytest.skip(f"no network access to verify build-date resolution ({e})")

    assert len(result) == 8 and result.isdigit()


# --- per-region cache metadata -----------------------------------------


def test_cache_round_trip(tmp_path):
    (tmp_path / "basemap_region_0.pmtiles").write_bytes(b"")
    bb.write_cache_meta(tmp_path, 0, bbox="1,1,2,2", minzoom=0, maxzoom=5, build_date="20260608")

    assert bb.is_cache_valid(tmp_path, 0, bbox="1,1,2,2", minzoom=0, maxzoom=5, build_date="20260608")
    assert not bb.is_cache_valid(tmp_path, 0, bbox="1,1,2,2", minzoom=0, maxzoom=6, build_date="20260608")
    assert not bb.is_cache_valid(tmp_path, 0, bbox="9,9,10,10", minzoom=0, maxzoom=5, build_date="20260608")


def test_cache_invalid_when_pmtiles_file_missing(tmp_path):
    bb.write_cache_meta(tmp_path, 0, bbox="1,1,2,2", minzoom=0, maxzoom=5, build_date="20260608")
    assert not bb.is_cache_valid(tmp_path, 0, bbox="1,1,2,2", minzoom=0, maxzoom=5, build_date="20260608")


def test_cache_invalid_when_meta_missing(tmp_path):
    (tmp_path / "basemap_region_0.pmtiles").write_bytes(b"")
    assert not bb.is_cache_valid(tmp_path, 0, bbox="1,1,2,2", minzoom=0, maxzoom=5, build_date="20260608")


def test_cache_invalid_when_meta_is_corrupt_json(tmp_path):
    (tmp_path / "basemap_region_0.pmtiles").write_bytes(b"")
    (tmp_path / "basemap_region_0.meta.json").write_text("not json")
    assert not bb.is_cache_valid(tmp_path, 0, bbox="1,1,2,2", minzoom=0, maxzoom=5, build_date="20260608")


def test_clear_stale_region_caches_removes_extra_indices(tmp_path):
    for i in range(4):
        (tmp_path / f"basemap_region_{i}.pmtiles").write_bytes(b"")
        (tmp_path / f"basemap_region_{i}.meta.json").write_text("{}")

    bb.clear_stale_region_caches(tmp_path, keep_count=2)

    remaining = sorted(p.name for p in tmp_path.iterdir())
    assert remaining == [
        "basemap_region_0.meta.json",
        "basemap_region_0.pmtiles",
        "basemap_region_1.meta.json",
        "basemap_region_1.pmtiles",
    ]


def test_clear_region_caches_removes_everything(tmp_path):
    for i in range(3):
        (tmp_path / f"basemap_region_{i}.pmtiles").write_bytes(b"")
        (tmp_path / f"basemap_region_{i}.meta.json").write_text("{}")

    bb.clear_region_caches(tmp_path)

    assert list(tmp_path.iterdir()) == []


# --- pmtiles progress-bar line parsing --------------------------------
#
# pmtiles (github.com/schollz/progressbar) renders "<label> NNN% |bar| (...)".
# These exact lines were captured from a real, local (non-network)
# `pmtiles cluster`/`extract` run piped through Python subprocess - not
# guessed - to make sure the regex matches the real format, not an assumed
# one (the assumption that progress was reported with '\r' and unparseable
# was wrong; piped/non-TTY output turned out to be one line per update).

REAL_CLUSTER_PROGRESS_LINE = "   0% |                                                | (0/1, 0 it/hr) [0s:0s]"
REAL_CLUSTER_PROGRESS_DONE_LINE = " 100% |" + ("█" * 49) + "| (1/1, 8004 it/s)"
REAL_EXTRACT_PROGRESS_LINE = "fetching chunks   0% |                                      | ( 0/69 B) [0s:0s]"
REAL_EXTRACT_PROGRESS_DONE_LINE = "fetching chunks 100% |" + ("█" * 29) + "| (69/69 B, 278 kB/s)"


@pytest.mark.parametrize(
    "line, expected",
    [
        (REAL_CLUSTER_PROGRESS_LINE, 0),
        (REAL_CLUSTER_PROGRESS_DONE_LINE, 100),
        (REAL_EXTRACT_PROGRESS_LINE, 0),
        (REAL_EXTRACT_PROGRESS_DONE_LINE, 100),
        ("2026/08/15 20:44:42 extract.go:373: fetching 0 dirs, 0 chunks, 0 requests", None),
        ("2026/08/15 20:44:42 extract.go:578: Completed in 693.893µs", None),
        ("", None),
        ("                                                                               ", None),
    ],
)
def test_parse_pmtiles_progress_percent(line, expected):
    assert bb._parse_pmtiles_progress_percent(line) == expected


def test_parse_pmtiles_progress_percent_clamps_out_of_range_values():
    assert bb._parse_pmtiles_progress_percent("999% |bar|") == 100


# --- run_pmtiles: live streaming + progress routing ----------------------


class _FakeProcess:
    """Stands in for subprocess.Popen: .stdout yields lines as an iterator
    (like a real pipe), matching how run_pmtiles consumes it."""

    def __init__(self, lines, returncode=0):
        self.stdout = iter(line + "\n" for line in lines)
        self.returncode = returncode

    def wait(self):
        pass


def test_run_pmtiles_uses_popen_not_blocking_run(monkeypatch):
    """Regression test: run_pmtiles used to call subprocess.run(capture_
    output=True), which blocks until the whole process exits before any
    output is available - meaning "live" progress would only ever appear
    after the download had already finished. Must use Popen + incremental
    reads instead."""
    monkeypatch.setattr(bb.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("run_pmtiles must not use subprocess.run (blocks until exit)")
    ))
    monkeypatch.setattr(bb.subprocess, "Popen", lambda *a, **k: _FakeProcess(["done"]))

    bb.run_pmtiles(Path("/fake/pmtiles"), ["merge"], log=lambda _: None)


def test_run_pmtiles_routes_progress_lines_to_on_progress_not_log(monkeypatch):
    lines = [
        "2026/08/15 20:44:42 extract.go:373: fetching 0 dirs, 0 chunks, 0 requests",
        REAL_EXTRACT_PROGRESS_LINE,
        REAL_EXTRACT_PROGRESS_DONE_LINE,
        "2026/08/15 20:44:42 extract.go:578: Completed in 693.893µs",
    ]
    monkeypatch.setattr(bb.subprocess, "Popen", lambda *a, **k: _FakeProcess(lines))

    logged = []
    progress = []
    bb.run_pmtiles(Path("/fake/pmtiles"), ["extract"], log=logged.append, on_progress=progress.append)

    assert progress == [0, 100]
    assert logged == [
        "2026/08/15 20:44:42 extract.go:373: fetching 0 dirs, 0 chunks, 0 requests",
        "2026/08/15 20:44:42 extract.go:578: Completed in 693.893µs",
    ]


def test_run_pmtiles_without_on_progress_logs_everything_raw(monkeypatch):
    """No on_progress given (e.g. the merge call site before this feature)
    must fall back to logging every line as before, progress bar noise
    included - only extract/merge call sites that opt in get filtering."""
    lines = [REAL_EXTRACT_PROGRESS_LINE, "some other line"]
    monkeypatch.setattr(bb.subprocess, "Popen", lambda *a, **k: _FakeProcess(lines))

    logged = []
    bb.run_pmtiles(Path("/fake/pmtiles"), ["extract"], log=logged.append)

    assert logged == lines


def test_run_pmtiles_raises_pmtiles_error_with_full_output_on_nonzero_exit(monkeypatch):
    lines = ["some output", "more output"]
    monkeypatch.setattr(bb.subprocess, "Popen", lambda *a, **k: _FakeProcess(lines, returncode=1))

    with pytest.raises(bb.PmtilesError) as exc_info:
        bb.run_pmtiles(Path("/fake/pmtiles"), ["extract"], log=lambda _: None)

    assert exc_info.value.output_lines == lines


# --- resolving/downloading the pmtiles CLI itself -----------------------


def test_resolve_pmtiles_cli_downloads_with_user_agent_and_extracts(tmp_path, monkeypatch):
    """End-to-end (but network-free) check of the download path that used
    to call urllib.request.urlretrieve - which can't send custom headers,
    so it always went out with Python's default User-Agent and got 403'd
    by build.protomaps.com/GitHub's CDN. Confirms the replacement
    (urlopen + streamed write) both sends USER_AGENT and produces a
    working binary."""
    import io
    import zipfile

    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as zf:
        zf.writestr("pmtiles", b"fake-pmtiles-binary")
    payload_bytes = payload.getvalue()

    monkeypatch.setattr(bb.shutil, "which", lambda name: None)
    monkeypatch.setattr(bb.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(bb.platform, "machine", lambda: "x86_64")

    captured = {}

    class FakeResponse(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_urlopen(request, timeout=None):
        captured["url"] = request.full_url
        captured["user_agent"] = request.get_header("User-agent")
        return FakeResponse(payload_bytes)

    monkeypatch.setattr(bb.urllib.request, "urlopen", fake_urlopen)

    bin_dir = tmp_path / "bin"
    result = bb.resolve_pmtiles_cli(bin_dir, "1.30.3", log=lambda _: None)

    assert captured["user_agent"] == bb.USER_AGENT
    assert "go-pmtiles-1.30.3_Darwin_x86_64.zip" in captured["url"]
    assert result == bin_dir / "pmtiles"
    assert result.read_bytes() == b"fake-pmtiles-binary"


def test_resolve_pmtiles_cli_raises_build_error_on_download_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(bb.shutil, "which", lambda name: None)

    def raise_url_error(*args, **kwargs):
        raise bb.urllib.error.URLError("connection refused")

    monkeypatch.setattr(bb.urllib.request, "urlopen", raise_url_error)

    with pytest.raises(bb.BuildError, match="download failed"):
        bb.resolve_pmtiles_cli(tmp_path / "bin", "1.30.3", log=lambda _: None)


# --- extracting the pmtiles binary from a release archive -------------


def test_extract_pmtiles_binary_from_tar_gz(tmp_path):
    import tarfile

    payload_dir = tmp_path / "payload"
    payload_dir.mkdir()
    (payload_dir / "pmtiles").write_bytes(b"fake-binary")
    (payload_dir / "README.md").write_text("hi")

    archive = tmp_path / "go-pmtiles_1.30.3_Linux_x86_64.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(payload_dir / "pmtiles", arcname="pmtiles")
        tar.add(payload_dir / "README.md", arcname="README.md")

    dest_dir = tmp_path / "dest"
    dest_dir.mkdir()
    out_path = bb._extract_pmtiles_binary(archive, dest_dir)

    assert out_path == dest_dir / "pmtiles"
    assert out_path.read_bytes() == b"fake-binary"


def test_extract_pmtiles_binary_from_zip_with_single_member(tmp_path):
    import zipfile

    archive = tmp_path / "go-pmtiles-1.30.3_Darwin_x86_64.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("pmtiles", b"fake-binary")

    dest_dir = tmp_path / "dest"
    dest_dir.mkdir()
    out_path = bb._extract_pmtiles_binary(archive, dest_dir)

    assert out_path == dest_dir / "pmtiles"
    assert out_path.read_bytes() == b"fake-binary"


def test_extract_pmtiles_binary_from_windows_zip_with_extras(tmp_path):
    import zipfile

    archive = tmp_path / "go-pmtiles_1.30.3_Windows_x86_64.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("LICENSE", "mit")
        zf.writestr("README.md", "hi")
        zf.writestr("pmtiles.exe", b"fake-binary")

    dest_dir = tmp_path / "dest"
    dest_dir.mkdir()
    out_path = bb._extract_pmtiles_binary(archive, dest_dir)

    assert out_path == dest_dir / "pmtiles.exe"
    assert out_path.read_bytes() == b"fake-binary"


def test_extract_pmtiles_binary_raises_when_binary_not_present(tmp_path):
    import zipfile

    archive = tmp_path / "empty.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("README.md", "hi")

    with pytest.raises(bb.BuildError, match="no pmtiles binary"):
        bb._extract_pmtiles_binary(archive, tmp_path / "dest")


# --- build() orchestration, DRY_RUN only (no network/subprocess) --------


def test_build_dry_run_legacy_mode_logs_two_regions(tmp_path):
    lines = []
    out_path = bb.build({"DRY_RUN": "true", "CACHE_DIR": str(tmp_path)}, log=lines.append)

    joined = "\n".join(lines)
    assert "region 1 'Welt'  z0..5  bbox=-180,-90,180,90  (fresh)" in joined
    assert "region 2 'Europa'  z6..13  bbox=-25,32,45,72  (fresh)" in joined
    assert "merging 2 region(s)" in joined
    assert out_path == bb.PROJECT_ROOT / bb.OUT_RELATIVE


def test_build_dry_run_uses_regions_file(tmp_path):
    regions_file = tmp_path / "regions.tsv"
    regions_file.write_text("Welt\t-180,-90,180,90\t5\nDetail\t5,47,15,55\t12\n")

    lines = []
    bb.build({"DRY_RUN": "true", "CACHE_DIR": str(tmp_path), "REGIONS_FILE": str(regions_file)}, log=lines.append)

    joined = "\n".join(lines)
    assert "region 1 'Welt'  z0..5" in joined
    assert "region 2 'Detail'  z6..12  bbox=5,47,15,55" in joined


def test_build_dry_run_detects_cached_region(tmp_path):
    (tmp_path / "basemap_region_0.pmtiles").write_bytes(b"")
    bb.write_cache_meta(tmp_path, 0, bbox=bb.WORLD_BBOX, minzoom=0, maxzoom=5, build_date="20260608")

    lines = []
    bb.build({"DRY_RUN": "true", "CACHE_DIR": str(tmp_path), "BUILD_DATE": "20260608"}, log=lines.append)

    assert any("(cached)" in line for line in lines if "'Welt'" in line)


def test_adding_a_new_highest_zoom_region_only_redownloads_the_new_one(tmp_path):
    """Answers a direct user question: does adding a Kartenausschnitt
    re-download everything, or only what's new? A newly added region is
    normally the most detailed one (the UI defaults a new region's zoom to
    "one more than the current maximum"), so it gets appended at the end
    of the zoom-ordered list - every earlier region's own bbox/zoom range
    is unchanged, so their cache stays valid and only the new region needs
    a fresh download."""
    build_date = "20260810"

    # Simulate a completed prior build with two cached regions...
    for index, (bbox, minzoom, maxzoom) in enumerate(
        [(bb.WORLD_BBOX, 0, 5), ("-25,32,45,72", 6, 13)]
    ):
        (tmp_path / f"basemap_region_{index}.pmtiles").write_bytes(b"")
        bb.write_cache_meta(tmp_path, index, bbox=bbox, minzoom=minzoom, maxzoom=maxzoom, build_date=build_date)

    # ...then add a third, more detailed region (as the UI's "+ add region" does).
    regions_file = tmp_path / "regions.tsv"
    regions_file.write_text(
        "Welt\t-180,-90,180,90\t5\nEuropa\t-25,32,45,72\t13\nMadeira\t-17.5,32.5,-16.5,33\t14\n"
    )

    lines = []
    bb.build(
        {
            "DRY_RUN": "true",
            "CACHE_DIR": str(tmp_path),
            "BUILD_DATE": build_date,
            "REGIONS_FILE": str(regions_file),
        },
        log=lines.append,
    )

    assert any("'Welt'" in line and "(cached)" in line for line in lines)
    assert any("'Europa'" in line and "(cached)" in line for line in lines)
    assert any("'Madeira'" in line and "(fresh)" in line for line in lines)


def test_inserting_a_region_in_the_middle_invalidates_later_regions_too(tmp_path):
    """The flip side of the above, so the caching behavior's actual limit
    is documented by a test rather than just asserted in prose: regions
    are merged in zoom-ascending order, and each one's zoom *band* is
    "previous region's maxzoom + 1" through its own maxzoom - so inserting
    a region *before* an existing one (by zoom, not by list position)
    shifts that later region's band even though its own bbox/maxzoom
    didn't change, correctly invalidating its cache too (the data at that
    zoom range genuinely changed)."""
    build_date = "20260810"
    (tmp_path / "basemap_region_0.pmtiles").write_bytes(b"")
    bb.write_cache_meta(tmp_path, 0, bbox=bb.WORLD_BBOX, minzoom=0, maxzoom=5, build_date=build_date)
    (tmp_path / "basemap_region_1.pmtiles").write_bytes(b"")
    bb.write_cache_meta(tmp_path, 1, bbox="-25,32,45,72", minzoom=6, maxzoom=13, build_date=build_date)

    # Insert a region between the two existing ones by zoom (8), not at the end.
    regions_file = tmp_path / "regions.tsv"
    regions_file.write_text("Welt\t-180,-90,180,90\t5\nZwischenstufe\t-10,30,40,60\t8\nEuropa\t-25,32,45,72\t13\n")

    lines = []
    bb.build(
        {
            "DRY_RUN": "true",
            "CACHE_DIR": str(tmp_path),
            "BUILD_DATE": build_date,
            "REGIONS_FILE": str(regions_file),
        },
        log=lines.append,
    )

    assert any("'Welt'" in line and "(cached)" in line for line in lines)
    assert any("'Zwischenstufe'" in line and "(fresh)" in line for line in lines)
    # Europa's bbox/maxzoom are unchanged, but its band is now z9..13
    # instead of z6..13 (Zwischenstufe took z6..8) - genuinely different
    # data, so re-fetching it is correct, not a caching bug.
    assert any("'Europa'" in line and "z9..13" in line and "(fresh)" in line for line in lines)


def test_build_dry_run_never_touches_the_real_output_file(tmp_path):
    out_path = bb.PROJECT_ROOT / bb.OUT_RELATIVE
    existed_before = out_path.exists()
    mtime_before = out_path.stat().st_mtime if existed_before else None

    bb.build({"DRY_RUN": "true", "CACHE_DIR": str(tmp_path)}, log=lambda _: None)

    assert out_path.exists() == existed_before
    if existed_before:
        assert out_path.stat().st_mtime == mtime_before


def test_build_dry_run_never_writes_cache_files(tmp_path):
    bb.build({"DRY_RUN": "true", "CACHE_DIR": str(tmp_path)}, log=lambda _: None)

    assert list(tmp_path.iterdir()) == []


def test_build_propagates_region_errors(tmp_path):
    regions_file = tmp_path / "regions.tsv"
    regions_file.write_text("A\t1,1,2,2\t10\nB\t1,1,2,2\t8\n")

    with pytest.raises(bb.BuildError, match="must be greater than"):
        bb.build({"DRY_RUN": "true", "CACHE_DIR": str(tmp_path), "REGIONS_FILE": str(regions_file)}, log=lambda _: None)


def test_build_dry_run_with_empty_build_date_never_touches_network(tmp_path, monkeypatch):
    """DRY_RUN must stay fully offline even when BUILD_DATE is left empty -
    it shows a placeholder instead of actually resolving "latest"."""

    def fail_if_called(*args, **kwargs):
        raise AssertionError("resolve_latest_build_date must not run a probe during DRY_RUN")

    monkeypatch.setattr(bb, "resolve_latest_build_date", fail_if_called)
    monkeypatch.setattr(bb, "_source_exists", fail_if_called)

    lines = []
    bb.build({"DRY_RUN": "true", "CACHE_DIR": str(tmp_path)}, log=lines.append)

    assert any(bb.BUILD_DATE_PLACEHOLDER in line for line in lines)


# --- build() orchestration with everything mocked out (no real network/subprocess, not DRY_RUN) --


def _mocked_build(tmp_path, monkeypatch, env=None, resolved_build_date="20260810"):
    """Runs the real (non-DRY_RUN) build() orchestration end-to-end, but
    with every network/subprocess touchpoint replaced by a fake, so the
    full control flow (build-date resolution, progress emission, region
    extraction, merging) is exercised without ever calling out to pmtiles
    or the network."""
    monkeypatch.setattr(bb, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(bb, "resolve_pmtiles_cli", lambda bin_dir, version, log: Path("/fake/pmtiles"))
    monkeypatch.setattr(bb, "resolve_latest_build_date", lambda log, **kwargs: resolved_build_date)

    extract_calls = []

    def fake_extract_region(pmtiles_bin, source, build_date, out_path, bbox, minzoom, maxzoom, log, on_progress=None):
        extract_calls.append({"source": source, "build_date": build_date, "out_path": out_path})
        if on_progress:
            on_progress(100)
        out_path.write_bytes(b"")

    monkeypatch.setattr(bb, "extract_region", fake_extract_region)

    def fake_run_pmtiles(pmtiles_bin, args, log, on_progress=None):
        if args[0] == "merge":
            if on_progress:
                on_progress(100)
            Path(args[-1]).write_bytes(b"fake-merged-basemap")
        return []

    monkeypatch.setattr(bb, "run_pmtiles", fake_run_pmtiles)

    lines = []
    out_path = bb.build({"CACHE_DIR": str(tmp_path / "cache"), **(env or {})}, log=lines.append)
    return out_path, lines, extract_calls


def test_build_resolves_empty_build_date_when_not_dry_run(tmp_path, monkeypatch):
    out_path, lines, extract_calls = _mocked_build(tmp_path, monkeypatch)

    assert extract_calls[0]["build_date"] == "20260810"
    assert extract_calls[0]["source"] == "https://build.protomaps.com/20260810.pmtiles"
    assert out_path.read_bytes() == b"fake-merged-basemap"
    assert any("looking up the newest available" in line for line in lines)


def test_build_does_not_resolve_when_build_date_explicitly_set(tmp_path, monkeypatch):
    _out_path, _lines, extract_calls = _mocked_build(tmp_path, monkeypatch, env={"BUILD_DATE": "20260101"})

    assert extract_calls[0]["build_date"] == "20260101"
    assert extract_calls[0]["source"] == "https://build.protomaps.com/20260101.pmtiles"


def test_build_emits_progress_lines_in_order(tmp_path, monkeypatch):
    # Each region/merge step emits an initial 0% event before the pmtiles
    # call, then whatever `on_progress` reports during the call itself -
    # the fake extract_region/run_pmtiles in _mocked_build report a single
    # 100% each, so every step shows up as an 0% -> 100% pair here. A real
    # run reports many more (once per pmtiles progress-bar line).
    _out_path, lines, _extract_calls = _mocked_build(tmp_path, monkeypatch)

    progress_events = [
        json.loads(line[len(bb.PROGRESS_PREFIX):])
        for line in lines
        if line.startswith(bb.PROGRESS_PREFIX)
    ]
    stages = [event["stage"] for event in progress_events]

    assert stages == [
        "resolving_pmtiles_cli",
        "resolving_build_date",
        "extracting",
        "extracting",
        "extracting",
        "extracting",
        "merging",
        "merging",
        "done",
    ]
    extracting_events = [e for e in progress_events if e["stage"] == "extracting"]
    assert [e["region_name"] for e in extracting_events] == ["Welt", "Welt", "Europa", "Europa"]
    assert [e["percent"] for e in extracting_events] == [0, 100, 0, 100]
    assert all(e["region_count"] == 2 for e in extracting_events)

    merging_events = [e for e in progress_events if e["stage"] == "merging"]
    assert [e["percent"] for e in merging_events] == [0, 100]


def test_build_progress_lines_are_not_shown_as_plain_log_text(tmp_path, monkeypatch):
    """map_build.py strips ##PROGRESS## lines out of the human-facing log -
    this just confirms the prefix is exact/greppable so that works."""
    _out_path, lines, _extract_calls = _mocked_build(tmp_path, monkeypatch)

    assert any(line.startswith("##PROGRESS## {") for line in lines)


# --- friendly error on a stale/missing BUILD_DATE ------------------------


def test_extract_region_adds_hint_on_404_and_still_raises(monkeypatch):
    log_lines = []

    def fake_run(pmtiles_bin, args, log, on_progress=None):
        raise bb.PmtilesError(
            "pmtiles extract failed with exit code 1",
            ["main.go:185: Failed to create range reader for 20260608.pmtiles, HTTP error: 404"],
        )

    monkeypatch.setattr(bb, "run_pmtiles", fake_run)

    with pytest.raises(bb.BuildError):
        bb.extract_region(
            Path("/fake/pmtiles"), "https://build.protomaps.com/20260608.pmtiles", "20260608",
            Path("/tmp/out.pmtiles"), "-1,-1,1,1", 0, 5, log_lines.append,
        )

    assert any("build.protomaps.com" in line for line in log_lines)
    assert any("20260608" in line for line in log_lines)


def test_extract_region_does_not_add_404_hint_for_unrelated_failures(monkeypatch):
    log_lines = []

    def fake_run(pmtiles_bin, args, log, on_progress=None):
        raise bb.PmtilesError("pmtiles extract failed with exit code 1", ["some unrelated error"])

    monkeypatch.setattr(bb, "run_pmtiles", fake_run)

    with pytest.raises(bb.BuildError):
        bb.extract_region(
            Path("/fake/pmtiles"), "https://build.protomaps.com/20260608.pmtiles", "20260608",
            Path("/tmp/out.pmtiles"), "-1,-1,1,1", 0, 5, log_lines.append,
        )

    assert not any("build.protomaps.com" in line for line in log_lines)


# --- CLI entry point (subprocess) ---------------------------------------


def _run_cli(env_overrides, timeout=15):
    env = os.environ.copy()
    env.update(env_overrides)
    env["DRY_RUN"] = "true"
    return subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "tools" / "build_basemap.py")],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def test_cli_dry_run_exits_zero_and_prints_plan(tmp_path):
    result = _run_cli({"CACHE_DIR": str(tmp_path)})

    assert result.returncode == 0, result.stderr
    assert "region 1 'Welt'" in result.stdout
    assert "region 2 'Europa'" in result.stdout


def test_cli_reports_errors_on_stderr_with_nonzero_exit(tmp_path):
    regions_file = tmp_path / "regions.tsv"
    regions_file.write_text("A\t1,1,2,2\t10\nB\t1,1,2,2\t8\n")

    result = _run_cli({"CACHE_DIR": str(tmp_path), "REGIONS_FILE": str(regions_file)})

    assert result.returncode == 1
    assert "must be greater than" in result.stderr
