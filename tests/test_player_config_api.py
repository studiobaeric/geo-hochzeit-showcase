"""Tests for the /api/player-config endpoints (read + patch)."""

import pytest


def test_get_player_config_has_default_shape(client):
    response = client.get("/api/player-config")
    data = response.get_json()

    assert response.status_code == 200
    assert data == {
        "player1_name": "player1",
        "player2_name": "player2",
        "player1_photo": "",
        "player2_photo": "",
        "player1_photo_hq": "",
        "player2_photo_hq": "",
    }


def test_patch_updates_a_single_name(client):
    response = client.patch("/api/player-config", json={"player1_name": "Alice"})
    data = response.get_json()

    assert response.status_code == 200
    assert data["player1_name"] == "Alice"
    assert data["player2_name"] == "player2"

    # Change should be visible on a subsequent GET, not just the response.
    follow_up = client.get("/api/player-config").get_json()
    assert follow_up["player1_name"] == "Alice"


def test_patch_updates_both_names(client):
    response = client.patch(
        "/api/player-config", json={"player1_name": "Alice", "player2_name": "Bob"}
    )
    data = response.get_json()

    assert data == {
        "player1_name": "Alice",
        "player2_name": "Bob",
        "player1_photo": "",
        "player2_photo": "",
        "player1_photo_hq": "",
        "player2_photo_hq": "",
    }


def test_patch_trims_whitespace(client):
    response = client.patch("/api/player-config", json={"player1_name": "  Alice  "})
    data = response.get_json()

    assert data["player1_name"] == "Alice"


def test_patch_ignores_unknown_fields(client):
    response = client.patch("/api/player-config", json={"totally_made_up_field": "hi"})
    data = response.get_json()

    assert response.status_code == 200
    assert "totally_made_up_field" not in data


def test_patch_with_empty_body_does_not_error(client):
    response = client.patch("/api/player-config", json={})

    assert response.status_code == 200


@pytest.mark.parametrize(
    "bad_payload",
    [
        {"player1_name": ""},
        {"player1_name": "   "},
        {"player1_name": 123},
        {"player2_name": None},
        {"player1_name": "x" * 41},
    ],
)
def test_patch_rejects_invalid_field_values(client, bad_payload):
    response = client.patch("/api/player-config", json=bad_payload)

    assert response.status_code == 400
    assert "error" in response.get_json()

    # Rejected updates must not partially apply.
    unchanged = client.get("/api/player-config").get_json()
    assert unchanged == {
        "player1_name": "player1",
        "player2_name": "player2",
        "player1_photo": "",
        "player2_photo": "",
        "player1_photo_hq": "",
        "player2_photo_hq": "",
    }


def test_patch_persists_to_disk(client):
    import json

    import game_state

    client.patch("/api/player-config", json={"player1_name": "Alice"})

    with open(game_state.STATE_FILE) as f:
        on_disk = json.load(f)

    assert on_disk["player_config"]["player1_name"] == "Alice"


def test_reset_does_not_clear_player_names(client):
    client.patch("/api/player-config", json={"player1_name": "Alice"})

    client.post("/api/reset")

    data = client.get("/api/player-config").get_json()
    assert data["player1_name"] == "Alice"
