"""Tests for placing guesses via POST /api/points."""

import pytest

VALID_PAYLOAD = {
    "round_number": 1,
    "placed_by": "player1",
    "coordinates": {"lat": 49.37, "lng": 9.54},
}


def test_valid_point_is_accepted(client):
    response = client.post("/api/points", json=VALID_PAYLOAD)
    data = response.get_json()

    assert response.status_code == 201
    assert data["round_number"] == VALID_PAYLOAD["round_number"]
    assert data["placed_by"] == "player1"
    assert data["coordinates"] == VALID_PAYLOAD["coordinates"]


def test_both_players_can_place_in_same_round(client):
    client.post("/api/points", json=VALID_PAYLOAD)
    other = dict(VALID_PAYLOAD, placed_by="player2")
    response = client.post("/api/points", json=other)

    assert response.status_code == 201


def test_replacing_a_guess_for_same_round_and_player_overwrites(client):
    client.post("/api/points", json=VALID_PAYLOAD)
    updated = dict(VALID_PAYLOAD, coordinates={"lat": 1.0, "lng": 2.0})
    response = client.post("/api/points", json=updated)

    assert response.status_code == 201
    assert response.get_json()["coordinates"] == {"lat": 1.0, "lng": 2.0}


@pytest.mark.parametrize(
    "bad_payload",
    [
        {"placed_by": "player1", "coordinates": {"lat": 1, "lng": 2}},  # missing round
        {"round_number": 1, "coordinates": {"lat": 1, "lng": 2}},  # missing placed_by
        {"round_number": 1, "placed_by": "player1"},  # missing coordinates
        {"round_number": 1, "placed_by": "someone_else", "coordinates": {"lat": 1, "lng": 2}},
        {"round_number": 1, "placed_by": "player1", "coordinates": None},
        {},
    ],
)
def test_invalid_payloads_are_rejected(client, bad_payload):
    response = client.post("/api/points", json=bad_payload)

    assert response.status_code == 400


def test_get_points_returns_placed_guesses_for_round(client):
    client.post("/api/points", json=VALID_PAYLOAD)
    other = dict(VALID_PAYLOAD, placed_by="player2")
    client.post("/api/points", json=other)

    response = client.get("/api/points/1")
    data = response.get_json()

    assert response.status_code == 200
    assert len(data) == 2
    placed_by = {record["placed_by"] for record in data}
    assert placed_by == {"player1", "player2"}


def test_get_points_only_returns_requested_round(client):
    client.post("/api/points", json=VALID_PAYLOAD)
    other_round = dict(VALID_PAYLOAD, round_number=2, placed_by="player2")
    client.post("/api/points", json=other_round)

    response = client.get("/api/points/2")
    data = response.get_json()

    assert response.status_code == 200
    assert len(data) == 1
    assert data[0]["placed_by"] == "player2"


def test_get_points_for_round_with_no_guesses_is_empty(client):
    response = client.get("/api/points/9")

    assert response.status_code == 200
    assert response.get_json() == []
