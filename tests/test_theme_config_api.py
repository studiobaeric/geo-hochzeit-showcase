"""Tests for the /api/theme-config endpoints (read + patch)."""

import pytest


def test_get_theme_config_has_default_shape(client):
    response = client.get("/api/theme-config")
    data = response.get_json()

    assert response.status_code == 200
    assert data == {"mode": "dark"}


def test_patch_updates_mode(client):
    response = client.patch("/api/theme-config", json={"mode": "light"})
    data = response.get_json()

    assert response.status_code == 200
    assert data == {"mode": "light"}

    follow_up = client.get("/api/theme-config").get_json()
    assert follow_up["mode"] == "light"


def test_patch_ignores_unknown_fields(client):
    response = client.patch("/api/theme-config", json={"totally_made_up_field": "hi"})
    data = response.get_json()

    assert response.status_code == 200
    assert "totally_made_up_field" not in data


def test_patch_with_empty_body_does_not_error(client):
    response = client.patch("/api/theme-config", json={})

    assert response.status_code == 200


@pytest.mark.parametrize(
    "bad_payload",
    [
        {"mode": "auto"},
        {"mode": 123},
        {"mode": None},
        {"mode": ""},
    ],
)
def test_patch_rejects_invalid_field_values(client, bad_payload):
    response = client.patch("/api/theme-config", json=bad_payload)

    assert response.status_code == 400
    assert "error" in response.get_json()

    # Rejected updates must not partially apply.
    unchanged = client.get("/api/theme-config").get_json()
    assert unchanged == {"mode": "dark"}


def test_patch_persists_to_disk(client):
    import json

    import game_state

    client.patch("/api/theme-config", json={"mode": "light"})

    with open(game_state.STATE_FILE) as f:
        on_disk = json.load(f)

    assert on_disk["theme_config"] == {"mode": "light"}


def test_reset_does_not_clear_theme_config(client):
    client.patch("/api/theme-config", json={"mode": "light"})

    client.post("/api/reset")

    data = client.get("/api/theme-config").get_json()
    assert data == {"mode": "light"}
