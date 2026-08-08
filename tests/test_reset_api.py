"""Tests for POST /api/reset."""

import game_state

VALID_PAYLOAD = {
    "round_number": 2,
    "placed_by": "tobias",
    "coordinates": {"lat": 10.0, "lng": 20.0},
}


def test_reset_restores_default_gamestate(client):
    client.patch("/api/gamestate", json={"round": 5, "state": "playing", "jana_locked": True})

    response = client.post("/api/reset")
    data = response.get_json()

    assert response.status_code == 200
    assert data["state"] == "waiting"
    assert data["round"] == 1
    assert data["jana_locked"] is False
    assert data["tobias_locked"] is False


def test_reset_clears_previously_placed_points(client):
    client.post("/api/points", json=VALID_PAYLOAD)
    assert game_state._placed_points  # sanity check the point was actually stored

    client.post("/api/reset")

    assert game_state._placed_points == {}
