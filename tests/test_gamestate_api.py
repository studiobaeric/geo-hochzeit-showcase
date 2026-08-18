"""Tests for the /api/gamestate endpoints (read + patch)."""

import pytest


def test_get_gamestate_has_default_shape(client):
    response = client.get("/api/gamestate")
    data = response.get_json()

    assert response.status_code == 200
    for field in ("state", "round", "player1_locked", "player2_locked"):
        assert field in data

    assert data["state"] == "waiting"
    assert data["round"] == 1
    assert data["player1_locked"] is False
    assert data["player2_locked"] is False


def test_patch_updates_known_fields(client):
    response = client.patch("/api/gamestate", json={"round": 3, "state": "playing"})
    data = response.get_json()

    assert response.status_code == 200
    assert data["round"] == 3
    assert data["state"] == "playing"

    # Change should be visible on a subsequent GET, not just the response.
    follow_up = client.get("/api/gamestate").get_json()
    assert follow_up["round"] == 3
    assert follow_up["state"] == "playing"


def test_patch_accepts_finished_state(client):
    response = client.patch("/api/gamestate", json={"state": "finished"})
    data = response.get_json()

    assert response.status_code == 200
    assert data["state"] == "finished"


def test_patch_locks_individual_players(client):
    client.patch("/api/gamestate", json={"player1_locked": True})
    data = client.get("/api/gamestate").get_json()

    assert data["player1_locked"] is True
    assert data["player2_locked"] is False


def test_patch_ignores_unknown_fields(client):
    response = client.patch("/api/gamestate", json={"totally_made_up_field": "hi"})
    data = response.get_json()

    assert response.status_code == 200
    assert "totally_made_up_field" not in data


def test_patch_with_empty_body_does_not_error(client):
    response = client.patch("/api/gamestate", json={})

    assert response.status_code == 200


@pytest.mark.parametrize(
    "bad_payload",
    [
        {"round": "three"},
        {"round": 0},
        {"round": -1},
        {"round": True},
        {"state": "not-a-real-state"},
        {"player1_locked": "yes"},
        {"player2_locked": 1},
    ],
)
def test_patch_rejects_invalid_field_values(client, bad_payload):
    response = client.patch("/api/gamestate", json=bad_payload)

    assert response.status_code == 400
    assert "error" in response.get_json()

    # Rejected updates must not partially apply.
    unchanged = client.get("/api/gamestate").get_json()
    assert unchanged["round"] == 1
    assert unchanged["state"] == "waiting"
