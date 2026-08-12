"""Tests for the /api/round-config endpoints (read + patch)."""

import pytest


def test_get_round_config_has_default_shape(client):
    response = client.get("/api/round-config")
    data = response.get_json()

    assert response.status_code == 200
    assert data == {"mode": "manual", "duration_seconds": 60}


def test_patch_updates_mode(client):
    response = client.patch("/api/round-config", json={"mode": "countdown"})
    data = response.get_json()

    assert response.status_code == 200
    assert data == {"mode": "countdown", "duration_seconds": 60}

    follow_up = client.get("/api/round-config").get_json()
    assert follow_up["mode"] == "countdown"


def test_patch_updates_duration(client):
    response = client.patch("/api/round-config", json={"duration_seconds": 90})
    data = response.get_json()

    assert data == {"mode": "manual", "duration_seconds": 90}


def test_patch_updates_both_fields(client):
    response = client.patch(
        "/api/round-config", json={"mode": "countdown", "duration_seconds": 120}
    )
    data = response.get_json()

    assert data == {"mode": "countdown", "duration_seconds": 120}


def test_patch_ignores_unknown_fields(client):
    response = client.patch("/api/round-config", json={"totally_made_up_field": "hi"})
    data = response.get_json()

    assert response.status_code == 200
    assert "totally_made_up_field" not in data


def test_patch_with_empty_body_does_not_error(client):
    response = client.patch("/api/round-config", json={})

    assert response.status_code == 200


@pytest.mark.parametrize(
    "bad_payload",
    [
        {"mode": "auto"},
        {"mode": 123},
        {"mode": None},
        {"duration_seconds": 0},
        {"duration_seconds": 4},
        {"duration_seconds": 3601},
        {"duration_seconds": "60"},
        {"duration_seconds": True},
        {"duration_seconds": 12.5},
    ],
)
def test_patch_rejects_invalid_field_values(client, bad_payload):
    response = client.patch("/api/round-config", json=bad_payload)

    assert response.status_code == 400
    assert "error" in response.get_json()

    # Rejected updates must not partially apply.
    unchanged = client.get("/api/round-config").get_json()
    assert unchanged == {"mode": "manual", "duration_seconds": 60}


def test_patch_persists_to_disk(client):
    import json

    import game_state

    client.patch("/api/round-config", json={"mode": "countdown", "duration_seconds": 45})

    with open(game_state.STATE_FILE) as f:
        on_disk = json.load(f)

    assert on_disk["round_config"] == {"mode": "countdown", "duration_seconds": 45}


def test_reset_does_not_clear_round_config(client):
    client.patch("/api/round-config", json={"mode": "countdown", "duration_seconds": 45})

    client.post("/api/reset")

    data = client.get("/api/round-config").get_json()
    assert data == {"mode": "countdown", "duration_seconds": 45}
