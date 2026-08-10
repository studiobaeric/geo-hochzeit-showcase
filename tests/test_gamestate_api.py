"""Tests for the /api/gamestate endpoints (read + patch)."""

import pytest


def test_get_gamestate_has_default_shape(client):
    response = client.get("/api/gamestate")
    data = response.get_json()

    assert response.status_code == 200
    for field in ("state", "round", "jana_locked", "tobias_locked"):
        assert field in data

    assert data["state"] == "waiting"
    assert data["round"] == 1
    assert data["jana_locked"] is False
    assert data["tobias_locked"] is False


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


def test_patch_locks_individual_players(client):
    client.patch("/api/gamestate", json={"jana_locked": True})
    data = client.get("/api/gamestate").get_json()

    assert data["jana_locked"] is True
    assert data["tobias_locked"] is False


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
        {"jana_locked": "yes"},
        {"tobias_locked": 1},
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
