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

    def fake_extract_region(pmtiles_bin, source, build_date, out_path, bbox, minzoom, maxzoom, log):
        extract_calls.append({"source": source, "build_date": build_date, "out_path": out_path})
        out_path.write_bytes(b"")

    monkeypatch.setattr(bb, "extract_region", fake_extract_region)

    def fake_run_pmtiles(pmtiles_bin, args, log):
        if args[0] == "merge":
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
        "merging",
        "done",
    ]
    extracting_events = [e for e in progress_events if e["stage"] == "extracting"]
    assert [e["region_name"] for e in extracting_events] == ["Welt", "Europa"]
    assert all(e["region_count"] == 2 for e in extracting_events)


def test_build_progress_lines_are_not_shown_as_plain_log_text(tmp_path, monkeypatch):
    """map_build.py strips ##PROGRESS## lines out of the human-facing log -
    this just confirms the prefix is exact/greppable so that works."""
    _out_path, lines, _extract_calls = _mocked_build(tmp_path, monkeypatch)

    assert any(line.startswith("##PROGRESS## {") for line in lines)


# --- friendly error on a stale/missing BUILD_DATE ------------------------


def test_extract_region_adds_hint_on_404_and_still_raises(monkeypatch):
    log_lines = []

    def fake_run(pmtiles_bin, args, log):
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

    def fake_run(pmtiles_bin, args, log):
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
