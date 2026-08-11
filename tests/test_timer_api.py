"""Tests for the /api/timer/* endpoints (round countdown control)."""

import time

import pytest

import game_state


def _enable_countdown_mode(client, duration_seconds=60):
    client.patch(
        "/api/round-config", json={"mode": "countdown", "duration_seconds": duration_seconds}
    )


def test_get_timer_state_has_default_shape(client):
    response = client.get("/api/timer")
    data = response.get_json()

    assert response.status_code == 200
    assert data == {
        "running": False,
        "paused": False,
        "ends_at": None,
        "remaining_seconds": None,
    }


def test_start_requires_countdown_mode(client):
    response = client.post("/api/timer/start")

    assert response.status_code == 400
    assert "error" in response.get_json()
    assert game_state._timer_state["running"] is False


def test_start_sets_running_state(client):
    _enable_countdown_mode(client, duration_seconds=60)

    before = time.time()
    response = client.post("/api/timer/start")
    data = response.get_json()

    assert response.status_code == 200
    assert data["running"] is True
    assert data["paused"] is False
    assert data["remaining_seconds"] is None
    assert before + 60 <= data["ends_at"] <= time.time() + 60


def test_pause_requires_running_timer(client):
    _enable_countdown_mode(client)

    response = client.post("/api/timer/pause")

    assert response.status_code == 400
    assert "error" in response.get_json()


def test_pause_freezes_remaining_seconds(client, monkeypatch):
    _enable_countdown_mode(client, duration_seconds=60)

    monkeypatch.setattr(game_state.time, "time", lambda: 1000.0)
    client.post("/api/timer/start")

    monkeypatch.setattr(game_state.time, "time", lambda: 1010.0)
    response = client.post("/api/timer/pause")
    data = response.get_json()

    assert data["running"] is True
    assert data["paused"] is True
    assert data["ends_at"] is None
    assert data["remaining_seconds"] == pytest.approx(50.0)


def test_pause_twice_is_rejected(client):
    _enable_countdown_mode(client)
    client.post("/api/timer/start")
    client.post("/api/timer/pause")

    response = client.post("/api/timer/pause")

    assert response.status_code == 400


def test_resume_requires_paused_timer(client):
    _enable_countdown_mode(client)
    client.post("/api/timer/start")

    response = client.post("/api/timer/resume")

    assert response.status_code == 400


def test_resume_without_start_is_rejected(client):
    _enable_countdown_mode(client)

    response = client.post("/api/timer/resume")

    assert response.status_code == 400


def test_resume_recomputes_ends_at_from_remaining(client, monkeypatch):
    _enable_countdown_mode(client, duration_seconds=60)

    monkeypatch.setattr(game_state.time, "time", lambda: 1000.0)
    client.post("/api/timer/start")

    monkeypatch.setattr(game_state.time, "time", lambda: 1010.0)
    client.post("/api/timer/pause")

    monkeypatch.setattr(game_state.time, "time", lambda: 1030.0)
    response = client.post("/api/timer/resume")
    data = response.get_json()

    assert data["running"] is True
    assert data["paused"] is False
    assert data["remaining_seconds"] is None
    assert data["ends_at"] == pytest.approx(1030.0 + 50.0)


def test_extend_requires_running_timer(client):
    _enable_countdown_mode(client)

    response = client.post("/api/timer/extend", json={"seconds": 30})

    assert response.status_code == 400


@pytest.mark.parametrize(
    "bad_payload",
    [
        {"seconds": 0},
        {"seconds": -5},
        {"seconds": 601},
        {"seconds": "30"},
        {"seconds": True},
        {"seconds": 12.5},
        {},
    ],
)
def test_extend_rejects_invalid_seconds(client, bad_payload):
    _enable_countdown_mode(client)
    client.post("/api/timer/start")

    response = client.post("/api/timer/extend", json=bad_payload)

    assert response.status_code == 400
    assert "error" in response.get_json()


def test_extend_running_timer_adds_to_ends_at(client, monkeypatch):
    _enable_countdown_mode(client, duration_seconds=60)

    monkeypatch.setattr(game_state.time, "time", lambda: 1000.0)
    client.post("/api/timer/start")

    response = client.post("/api/timer/extend", json={"seconds": 30})
    data = response.get_json()

    assert data["running"] is True
    assert data["paused"] is False
    assert data["ends_at"] == pytest.approx(1000.0 + 60 + 30)


def test_extend_paused_timer_adds_to_remaining(client, monkeypatch):
    _enable_countdown_mode(client, duration_seconds=60)

    monkeypatch.setattr(game_state.time, "time", lambda: 1000.0)
    client.post("/api/timer/start")

    monkeypatch.setattr(game_state.time, "time", lambda: 1010.0)
    client.post("/api/timer/pause")

    response = client.post("/api/timer/extend", json={"seconds": 15})
    data = response.get_json()

    assert data["paused"] is True
    assert data["remaining_seconds"] == pytest.approx(50.0 + 15)


def test_stop_resets_to_default(client):
    _enable_countdown_mode(client)
    client.post("/api/timer/start")

    response = client.post("/api/timer/stop")
    data = response.get_json()

    assert data == {
        "running": False,
        "paused": False,
        "ends_at": None,
        "remaining_seconds": None,
    }


def test_advancing_round_resets_the_timer(client):
    _enable_countdown_mode(client)
    client.post("/api/timer/start")
    assert game_state._timer_state["running"] is True

    client.patch("/api/gamestate", json={"round": 2})

    data = client.get("/api/timer").get_json()
    assert data == {
        "running": False,
        "paused": False,
        "ends_at": None,
        "remaining_seconds": None,
    }


def test_patching_gamestate_without_changing_round_leaves_timer_alone(client):
    _enable_countdown_mode(client)
    client.post("/api/timer/start")

    client.patch("/api/gamestate", json={"state": "waiting"})

    assert game_state._timer_state["running"] is True


def test_reset_clears_running_timer(client):
    _enable_countdown_mode(client)
    client.post("/api/timer/start")

    client.post("/api/reset")

    data = client.get("/api/timer").get_json()
    assert data == {
        "running": False,
        "paused": False,
        "ends_at": None,
        "remaining_seconds": None,
    }


def test_timer_state_is_not_restored_as_running_after_restart(client):
    _enable_countdown_mode(client)
    client.post("/api/timer/start")
    assert game_state._timer_state["running"] is True

    # Simulate the process restarting: wipe the in-memory copy, then load
    # exactly what a fresh import of game_state would do.
    with game_state._lock:
        game_state._timer_state.clear()
        game_state._timer_state.update(dict(game_state._DEFAULT_TIMER_STATE))

    game_state.load_state_from_disk()

    assert game_state._timer_state == {
        "running": False,
        "paused": False,
        "ends_at": None,
        "remaining_seconds": None,
    }
