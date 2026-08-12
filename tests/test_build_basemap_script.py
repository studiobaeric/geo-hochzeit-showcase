"""Tests for tools/build_basemap_linux.sh and tools/build_basemap.sh.

These scripts do real, multi-GB, network-heavy work (downloading map tiles)
so they can't be exercised end-to-end in CI. Instead every script supports
DRY_RUN=true, which runs the full region-parsing/zoom-assignment/caching
logic and prints the resulting build plan without touching the network, the
pmtiles CLI, or static/data/basemap.pmtiles - that's what's tested here.

Both scripts share the region-processing logic verbatim (they only differ
in how they download the pmtiles CLI itself, which DRY_RUN never reaches),
so every test below runs against both.
"""

import os
import subprocess
import textwrap

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = [
    os.path.join(PROJECT_ROOT, "tools", "build_basemap_linux.sh"),
    os.path.join(PROJECT_ROOT, "tools", "build_basemap.sh"),
]


def _run(script, env_overrides, timeout=15):
    env = os.environ.copy()
    env.update(env_overrides)
    env["DRY_RUN"] = "true"
    return subprocess.run(
        ["bash", script],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _write_regions(tmp_path, lines):
    path = tmp_path / "regions.tsv"
    path.write_text("\n".join(lines) + "\n")
    return str(path)


@pytest.fixture(params=SCRIPTS, ids=["linux", "macos"])
def script(request):
    return request.param


def test_scripts_exist_and_are_executable_bash(script):
    assert os.path.isfile(script)
    result = subprocess.run(["bash", "-n", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_legacy_mode_synthesizes_world_and_europe_regions(script, tmp_path):
    result = _run(script, {"CACHE_DIR": str(tmp_path)})

    assert result.returncode == 0, result.stderr
    assert "region 1 'Welt'  z0..5  bbox=-180,-90,180,90" in result.stdout
    assert "region 2 'Europa'  z6..13  bbox=-25,32,45,72" in result.stdout
    assert "merging 2 region(s)" in result.stdout


def test_legacy_mode_honors_custom_zoom_and_bbox(script, tmp_path):
    result = _run(
        script,
        {
            "CACHE_DIR": str(tmp_path),
            "MAXZOOM": "11",
            "WORLD_MAXZOOM": "3",
            "EUROPE_BBOX": "5.5,47,15.5,55",
        },
    )

    assert result.returncode == 0, result.stderr
    assert "region 1 'Welt'  z0..3  bbox=-180,-90,180,90" in result.stdout
    assert "region 2 'Europa'  z4..11  bbox=5.5,47,15.5,55" in result.stdout


def test_custom_regions_file_supports_more_than_two_regions(script, tmp_path):
    regions_file = _write_regions(
        tmp_path,
        [
            "Welt\t-180,-90,180,90\t5",
            "Europa\t-25,32,45,72\t11",
            "Madeira\t-17.5,32.5,-16.5,33\t14",
        ],
    )

    result = _run(script, {"CACHE_DIR": str(tmp_path), "REGIONS_FILE": regions_file})

    assert result.returncode == 0, result.stderr
    assert "region 1 'Welt'  z0..5  bbox=-180,-90,180,90" in result.stdout
    assert "region 2 'Europa'  z6..11  bbox=-25,32,45,72" in result.stdout
    assert "region 3 'Madeira'  z12..14  bbox=-17.5,32.5,-16.5,33" in result.stdout
    assert "merging 3 region(s)" in result.stdout


def test_single_region_is_accepted(script, tmp_path):
    regions_file = _write_regions(tmp_path, ["Solo\t5,47,15,55\t10"])

    result = _run(script, {"CACHE_DIR": str(tmp_path), "REGIONS_FILE": regions_file})

    assert result.returncode == 0, result.stderr
    assert "region 1 'Solo'  z0..10  bbox=5,47,15,55" in result.stdout


def test_matching_cache_is_reported_as_cached(script, tmp_path):
    (tmp_path / "basemap_region_0.pmtiles").write_bytes(b"")
    (tmp_path / "basemap_region_0.meta").write_text(
        textwrap.dedent(
            """\
            bbox=-180,-90,180,90
            minzoom=0
            maxzoom=5
            build_date=20260608
            """
        )
    )
    regions_file = _write_regions(tmp_path, ["Welt\t-180,-90,180,90\t5"])

    result = _run(
        script,
        {"CACHE_DIR": str(tmp_path), "REGIONS_FILE": regions_file, "BUILD_DATE": "20260608"},
    )

    assert result.returncode == 0, result.stderr
    assert "region 1 'Welt'  z0..5  bbox=-180,-90,180,90  (cached)" in result.stdout


def test_stale_cache_from_bbox_change_is_reported_as_fresh(script, tmp_path):
    (tmp_path / "basemap_region_0.pmtiles").write_bytes(b"")
    (tmp_path / "basemap_region_0.meta").write_text(
        "bbox=-180,-90,170,90\nminzoom=0\nmaxzoom=5\nbuild_date=20260608\n"
    )
    regions_file = _write_regions(tmp_path, ["Welt\t-180,-90,180,90\t5"])

    result = _run(
        script,
        {"CACHE_DIR": str(tmp_path), "REGIONS_FILE": regions_file, "BUILD_DATE": "20260608"},
    )

    assert result.returncode == 0, result.stderr
    assert "region 1 'Welt'  z0..5  bbox=-180,-90,180,90  (fresh)" in result.stdout


def test_missing_regions_file_is_an_error(script, tmp_path):
    result = _run(
        script, {"CACHE_DIR": str(tmp_path), "REGIONS_FILE": str(tmp_path / "nope.tsv")}
    )

    assert result.returncode != 0
    assert "REGIONS_FILE not found" in result.stderr


def test_empty_regions_file_is_an_error(script, tmp_path):
    regions_file = _write_regions(tmp_path, [])
    # _write_regions always appends a trailing newline; make it truly empty.
    with open(regions_file, "w"):
        pass

    result = _run(script, {"CACHE_DIR": str(tmp_path), "REGIONS_FILE": regions_file})

    assert result.returncode != 0
    assert "no regions defined" in result.stderr


def test_non_increasing_maxzoom_is_an_error(script, tmp_path):
    regions_file = _write_regions(
        tmp_path, ["A\t-10,-10,10,10\t10", "B\t-5,-5,5,5\t8"]
    )

    result = _run(script, {"CACHE_DIR": str(tmp_path), "REGIONS_FILE": regions_file})

    assert result.returncode != 0
    assert "must be greater than the previous region's maxzoom" in result.stderr


def test_non_integer_maxzoom_is_an_error(script, tmp_path):
    regions_file = _write_regions(tmp_path, ["A\t-10,-10,10,10\tnotanumber"])

    result = _run(script, {"CACHE_DIR": str(tmp_path), "REGIONS_FILE": regions_file})

    assert result.returncode != 0
    assert "non-integer maxzoom" in result.stderr


def test_malformed_bbox_is_an_error(script, tmp_path):
    regions_file = _write_regions(tmp_path, ["A\t1,2,3\t10"])

    result = _run(script, {"CACHE_DIR": str(tmp_path), "REGIONS_FILE": regions_file})

    assert result.returncode != 0
    assert "malformed bbox" in result.stderr


def test_dry_run_never_touches_the_real_output_file(script, tmp_path):
    out_path = os.path.join(PROJECT_ROOT, "static", "data", "basemap.pmtiles")
    existed_before = os.path.exists(out_path)
    mtime_before = os.path.getmtime(out_path) if existed_before else None

    result = _run(script, {"CACHE_DIR": str(tmp_path)})

    assert result.returncode == 0, result.stderr
    assert os.path.exists(out_path) == existed_before
    if existed_before:
        assert os.path.getmtime(out_path) == mtime_before
