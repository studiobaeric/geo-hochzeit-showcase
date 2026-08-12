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
    rather than failing the suite over connectivity."""
    url = bb.pmtiles_download_url(bb.DEFAULT_PMTILES_VERSION, system, machine)
    request = urllib.request.Request(url, method="HEAD")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            status = response.status
    except urllib.error.HTTPError as e:
        status = e.code
    except (urllib.error.URLError, TimeoutError) as e:
        pytest.skip(f"no network access to verify release asset ({e})")

    assert status == 200, f"pmtiles release asset not found: {url}"


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
    bb.write_cache_meta(tmp_path, 0, bbox=bb.WORLD_BBOX, minzoom=0, maxzoom=5, build_date=bb.DEFAULT_BUILD_DATE)

    lines = []
    bb.build({"DRY_RUN": "true", "CACHE_DIR": str(tmp_path)}, log=lines.append)

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
