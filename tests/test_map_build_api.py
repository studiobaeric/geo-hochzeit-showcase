"""Tests for the /api/map/build + /api/map/build/status endpoints.

The real build runner (map_build._default_runner) shells out to a
multi-GB, network-heavy script and must never run under pytest - the
`isolate_map_config` autouse fixture in conftest.py already points
`_build_runner` back at `_default_runner`, so every test here explicitly
swaps in a fast fake before triggering a build.
"""

import json
import threading
import time

import map_build


def _wait_until_not_running(client, timeout=2.0):
    deadline = time.time() + timeout
    status = None
    while time.time() < deadline:
        status = client.get("/api/map/build/status").get_json()
        if status["status"] != "running":
            return status
        time.sleep(0.01)
    raise AssertionError(f"build still running after {timeout}s: {status}")


def _fake_runner(exit_code=0, lines=("line 1", "line 2")):
    def runner(config, log_callback):
        for line in lines:
            log_callback(line)
        return exit_code

    return runner


def test_get_build_status_defaults_to_idle(client):
    response = client.get("/api/map/build/status")
    data = response.get_json()

    assert response.status_code == 200
    assert data == map_build._DEFAULT_BUILD_STATUS


def test_start_build_returns_running_immediately(client, monkeypatch):
    started = threading.Event()

    def slow_runner(config, log_callback):
        started.set()
        time.sleep(0.2)
        return 0

    monkeypatch.setattr(map_build, "_build_runner", slow_runner)

    response = client.post("/api/map/build")
    data = response.get_json()

    assert response.status_code == 202
    assert data["status"] == "running"
    assert data["started_at"] is not None
    assert started.wait(timeout=2)

    _wait_until_not_running(client)


def test_build_reports_success_and_log_tail(client, monkeypatch):
    monkeypatch.setattr(map_build, "_build_runner", _fake_runner(exit_code=0, lines=("a", "b")))

    client.post("/api/map/build")
    status = _wait_until_not_running(client)

    assert status["status"] == "success"
    assert status["exit_code"] == 0
    assert status["error"] is None
    assert status["log_tail"] == ["a", "b"]
    assert status["finished_at"] is not None
    assert status["finished_at"] >= status["started_at"]


def test_build_reports_error_on_nonzero_exit_code(client, monkeypatch):
    monkeypatch.setattr(map_build, "_build_runner", _fake_runner(exit_code=1))

    client.post("/api/map/build")
    status = _wait_until_not_running(client)

    assert status["status"] == "error"
    assert status["exit_code"] == 1
    assert "1" in status["error"]


def test_build_reports_error_when_runner_raises(client, monkeypatch):
    def broken_runner(config, log_callback):
        raise RuntimeError("boom")

    monkeypatch.setattr(map_build, "_build_runner", broken_runner)

    client.post("/api/map/build")
    status = _wait_until_not_running(client)

    assert status["status"] == "error"
    assert status["exit_code"] is None
    assert "boom" in status["error"]


def test_concurrent_build_request_is_rejected(client, monkeypatch):
    started = threading.Event()
    release = threading.Event()

    def blocking_runner(config, log_callback):
        started.set()
        release.wait(timeout=5)
        return 0

    monkeypatch.setattr(map_build, "_build_runner", blocking_runner)

    first = client.post("/api/map/build")
    assert first.status_code == 202
    assert started.wait(timeout=2)

    second = client.post("/api/map/build")
    assert second.status_code == 409
    assert "error" in second.get_json()

    release.set()
    _wait_until_not_running(client)


def test_build_uses_regions_from_settings(client, monkeypatch):
    client.patch(
        "/api/map/config",
        json={
            "regions": [
                {"name": "Welt", "bbox": "-180,-90,180,90", "maxzoom": 4},
                {"name": "Detail", "bbox": "5,47,15,55", "maxzoom": 12},
            ]
        },
    )

    captured = {}

    def capturing_runner(config, log_callback):
        captured.update(config)
        return 0

    monkeypatch.setattr(map_build, "_build_runner", capturing_runner)

    client.post("/api/map/build")
    _wait_until_not_running(client)

    assert [r["name"] for r in captured["regions"]] == ["Welt", "Detail"]
    assert captured["regions"][1]["maxzoom"] == 12
    assert captured["regions"][1]["bbox"] == "5,47,15,55"


def test_build_effective_bbox_covers_out_of_range_photo(client, monkeypatch, tmp_path):
    photos_file = tmp_path / "photos.json"
    photos_file.write_text(
        json.dumps([{"id": 1, "location": {"lat": 60.0, "lng": 100.0}}])
    )
    monkeypatch.setattr(map_build, "PHOTOS_FILE", str(photos_file))
    client.patch(
        "/api/map/config",
        json={
            "regions": [
                {"name": "Welt", "bbox": "-180,-90,180,90", "maxzoom": 5},
                {"name": "Detail", "bbox": "5,47,15,55", "maxzoom": 13},
            ]
        },
    )

    captured = {}

    def capturing_runner(config, log_callback):
        captured.update(config)
        return 0

    monkeypatch.setattr(map_build, "_build_runner", capturing_runner)

    client.post("/api/map/build")
    _wait_until_not_running(client)

    detail_region = captured["regions"][1]
    min_lon, min_lat, max_lon, max_lat = (
        float(v) for v in detail_region["effective_bbox"].split(",")
    )
    assert min_lon <= 100.0 and max_lon >= 100.0
    assert min_lat <= 60.0 and max_lat >= 60.0

    # The low-detail "Welt" region must stay untouched by the photo bbox.
    assert captured["regions"][0]["effective_bbox"] == captured["regions"][0]["bbox"]

    status = client.get("/api/map/build/status").get_json()
    assert status["config_used"]["regions"][1]["effective_bbox"] == detail_region["effective_bbox"]


# --- platform resolution + regions file -----------------------------------


def test_script_path_resolves_per_platform(monkeypatch):
    monkeypatch.setattr(map_build.os.path, "isfile", lambda path: True)

    monkeypatch.setattr(map_build.platform, "system", lambda: "Linux")
    assert map_build._script_path().endswith("build_basemap_linux.sh")

    monkeypatch.setattr(map_build.platform, "system", lambda: "Darwin")
    assert map_build._script_path().endswith("build_basemap.sh")

    monkeypatch.setattr(map_build.platform, "system", lambda: "Windows")
    assert map_build._script_path().endswith("build_basemap.ps1")

    monkeypatch.setattr(map_build.platform, "system", lambda: "Plan9")
    assert map_build._script_path() is None


def test_build_command_uses_powershell_on_windows(monkeypatch):
    monkeypatch.setattr(map_build.platform, "system", lambda: "Windows")
    command = map_build._build_command("C:\\repo\\tools\\build_basemap.ps1")

    assert command[0] == "powershell"
    assert command[-1] == "C:\\repo\\tools\\build_basemap.ps1"


def test_build_command_uses_bash_elsewhere(monkeypatch):
    monkeypatch.setattr(map_build.platform, "system", lambda: "Linux")
    assert map_build._build_command("/repo/tools/build_basemap_linux.sh") == [
        "bash",
        "/repo/tools/build_basemap_linux.sh",
    ]


def test_default_runner_returns_error_without_crashing_when_script_missing(monkeypatch):
    monkeypatch.setattr(map_build, "_script_path", lambda: None)
    lines = []

    exit_code = map_build._default_runner(
        {"regions": [{"name": "Welt", "bbox": "1,1,2,2", "effective_bbox": "1,1,2,2", "maxzoom": 5}], "build_date": "20260101"},
        lines.append,
    )

    assert exit_code == 1
    assert lines and "Kein Build-Skript" in lines[0]


def test_write_regions_file_produces_tsv_lines(tmp_path):
    regions = [
        {"name": "Welt", "effective_bbox": "-180,-90,180,90", "maxzoom": 5},
        {"name": "Has\tTab\nAnd Newline", "effective_bbox": "5,47,15,55", "maxzoom": 12},
    ]
    path = map_build._write_regions_file(regions)
    try:
        with open(path) as f:
            lines = f.read().splitlines()
        assert lines[0] == "Welt\t-180,-90,180,90\t5"
        assert lines[1] == "Has Tab And Newline\t5,47,15,55\t12"
    finally:
        import os

        os.remove(path)
