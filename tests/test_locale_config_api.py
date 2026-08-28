"""Tests for the /api/locale-config endpoints (read + patch)."""

import pytest


def test_get_locale_config_has_default_shape(client):
    response = client.get("/api/locale-config")
    data = response.get_json()

    assert response.status_code == 200
    assert data == {"locale": "de"}


def test_patch_updates_locale(client):
    response = client.patch("/api/locale-config", json={"locale": "en"})
    data = response.get_json()

    assert response.status_code == 200
    assert data == {"locale": "en"}

    follow_up = client.get("/api/locale-config").get_json()
    assert follow_up["locale"] == "en"


def test_patch_ignores_unknown_fields(client):
    response = client.patch("/api/locale-config", json={"totally_made_up_field": "hi"})
    data = response.get_json()

    assert response.status_code == 200
    assert "totally_made_up_field" not in data


def test_patch_with_empty_body_does_not_error(client):
    response = client.patch("/api/locale-config", json={})

    assert response.status_code == 200


@pytest.mark.parametrize(
    "bad_payload",
    [
        {"locale": "fr"},
        {"locale": 123},
        {"locale": None},
        {"locale": ""},
    ],
)
def test_patch_rejects_invalid_field_values(client, bad_payload):
    response = client.patch("/api/locale-config", json=bad_payload)

    assert response.status_code == 400
    assert "error" in response.get_json()

    # Rejected updates must not partially apply.
    unchanged = client.get("/api/locale-config").get_json()
    assert unchanged == {"locale": "de"}


def test_patch_persists_to_disk(client):
    import json

    import game_state

    client.patch("/api/locale-config", json={"locale": "en"})

    with open(game_state.STATE_FILE) as f:
        on_disk = json.load(f)

    assert on_disk["locale_config"] == {"locale": "en"}


def test_reset_does_not_clear_locale_config(client):
    client.patch("/api/locale-config", json={"locale": "en"})

    client.post("/api/reset")

    data = client.get("/api/locale-config").get_json()
    assert data == {"locale": "en"}
