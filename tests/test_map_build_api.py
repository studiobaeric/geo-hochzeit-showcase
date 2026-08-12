"""Tests for the /api/map/build + /api/map/build/status endpoints.

The real build runner (map_build._default_runner) shells out to a
multi-GB, network-heavy bash script and must never run under pytest - the
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


def test_build_uses_config_from_settings(client, monkeypatch):
    client.patch("/api/map/config", json={"maxzoom": 8, "world_maxzoom": 2, "bbox": "5,47,15,55"})

    captured = {}

    def capturing_runner(config, log_callback):
        captured.update(config)
        return 0

    monkeypatch.setattr(map_build, "_build_runner", capturing_runner)

    client.post("/api/map/build")
    _wait_until_not_running(client)

    assert captured["maxzoom"] == 8
    assert captured["world_maxzoom"] == 2
    assert captured["bbox"] == "5,47,15,55"


def test_build_effective_bbox_covers_out_of_range_photo(client, monkeypatch, tmp_path):
    photos_file = tmp_path / "photos.json"
    photos_file.write_text(
        json.dumps([{"id": 1, "location": {"lat": 60.0, "lng": 100.0}}])
    )
    monkeypatch.setattr(map_build, "PHOTOS_FILE", str(photos_file))
    client.patch("/api/map/config", json={"bbox": "5,47,15,55"})

    captured = {}

    def capturing_runner(config, log_callback):
        captured.update(config)
        return 0

    monkeypatch.setattr(map_build, "_build_runner", capturing_runner)

    client.post("/api/map/build")
    _wait_until_not_running(client)

    min_lon, min_lat, max_lon, max_lat = (
        float(v) for v in captured["effective_bbox"].split(",")
    )
    assert min_lon <= 100.0 and max_lon >= 100.0
    assert min_lat <= 60.0 and max_lat >= 60.0

    status = client.get("/api/map/build/status").get_json()
    assert status["config_used"]["effective_bbox"] == captured["effective_bbox"]


def test_default_runner_returns_error_without_crashing_when_script_missing(monkeypatch):
    monkeypatch.setattr(map_build, "_script_path", lambda: None)
    lines = []

    exit_code = map_build._default_runner(
        {"maxzoom": 10, "world_maxzoom": 5, "bbox": "1,1,2,2", "effective_bbox": "1,1,2,2", "build_date": "20260101"},
        lines.append,
    )

    assert exit_code == 1
    assert lines and "Kein Build-Skript" in lines[0]
