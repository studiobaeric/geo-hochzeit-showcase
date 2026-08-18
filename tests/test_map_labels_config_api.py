"""Tests for the /api/map-labels-config endpoints (read + patch)."""

import pytest


def test_get_map_labels_config_has_default_shape(client):
    response = client.get("/api/map-labels-config")
    data = response.get_json()

    assert response.status_code == 200
    assert data == {"hide_city_labels": False}


def test_patch_updates_hide_city_labels(client):
    response = client.patch("/api/map-labels-config", json={"hide_city_labels": True})
    data = response.get_json()

    assert response.status_code == 200
    assert data == {"hide_city_labels": True}

    follow_up = client.get("/api/map-labels-config").get_json()
    assert follow_up["hide_city_labels"] is True


def test_patch_ignores_unknown_fields(client):
    response = client.patch("/api/map-labels-config", json={"totally_made_up_field": "hi"})
    data = response.get_json()

    assert response.status_code == 200
    assert "totally_made_up_field" not in data


def test_patch_with_empty_body_does_not_error(client):
    response = client.patch("/api/map-labels-config", json={})

    assert response.status_code == 200


@pytest.mark.parametrize(
    "bad_payload",
    [
        {"hide_city_labels": "yes"},
        {"hide_city_labels": 1},
        {"hide_city_labels": None},
    ],
)
def test_patch_rejects_invalid_field_values(client, bad_payload):
    response = client.patch("/api/map-labels-config", json=bad_payload)

    assert response.status_code == 400
    assert "error" in response.get_json()

    # Rejected updates must not partially apply.
    unchanged = client.get("/api/map-labels-config").get_json()
    assert unchanged == {"hide_city_labels": False}


def test_patch_persists_to_disk(client):
    import json

    import game_state

    client.patch("/api/map-labels-config", json={"hide_city_labels": True})

    with open(game_state.STATE_FILE) as f:
        on_disk = json.load(f)

    assert on_disk["map_labels_config"] == {"hide_city_labels": True}


def test_reset_does_not_clear_map_labels_config(client):
    client.patch("/api/map-labels-config", json={"hide_city_labels": True})

    client.post("/api/reset")

    data = client.get("/api/map-labels-config").get_json()
    assert data == {"hide_city_labels": True}
