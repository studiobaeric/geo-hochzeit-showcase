"""Tests for POST /api/reset."""

import game_state

VALID_PAYLOAD = {
    "round_number": 2,
    "placed_by": "player2",
    "coordinates": {"lat": 10.0, "lng": 20.0},
}


def test_reset_restores_default_gamestate(client):
    client.patch("/api/gamestate", json={"round": 5, "state": "playing", "player1_locked": True})

    response = client.post("/api/reset")
    data = response.get_json()

    assert response.status_code == 200
    assert data["state"] == "waiting"
    assert data["round"] == 1
    assert data["player1_locked"] is False
    assert data["player2_locked"] is False


def test_reset_clears_previously_placed_points(client):
    client.post("/api/points", json=VALID_PAYLOAD)
    assert game_state._placed_points  # sanity check the point was actually stored

    client.post("/api/reset")

    assert game_state._placed_points == {}


def test_reset_clears_previously_stored_round_results(client):
    client.post(
        "/api/round_result",
        json={
            "round_number": 1,
            "players": {
                "player1": {"points": 500, "distance": 100, "markerLocation": [1.0, 2.0]},
                "player2": {"points": 200, "distance": 500, "markerLocation": [3.0, 4.0]},
            },
        },
    )
    assert game_state._round_results  # sanity check the result was actually stored

    client.post("/api/reset")

    assert game_state._round_results == {}
    assert client.get("/api/round_results").get_json() == []
