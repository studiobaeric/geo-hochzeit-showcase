"""Tests for the /api/round_result and /api/round_results endpoints.

These store the per-round points/distance/marker data the endscreen needs,
so the full game (not just the current round/lock state) can be
reconstructed from the persisted JSON after a restart.
"""

import pytest

VALID_PAYLOAD = {
    "round_number": 1,
    "players": {
        "player1": {"points": 850, "distance": 1234.5, "markerLocation": [49.37, 9.54]},
        "player2": {"points": 100, "distance": None, "markerLocation": None},
    },
}


def test_valid_round_result_is_accepted(client):
    response = client.post("/api/round_result", json=VALID_PAYLOAD)
    data = response.get_json()

    assert response.status_code == 201
    assert data == VALID_PAYLOAD


def test_round_results_starts_empty(client):
    response = client.get("/api/round_results")

    assert response.status_code == 200
    assert response.get_json() == []


def test_posted_round_result_is_returned_by_get(client):
    client.post("/api/round_result", json=VALID_PAYLOAD)

    response = client.get("/api/round_results")
    data = response.get_json()

    assert response.status_code == 200
    assert data == [VALID_PAYLOAD]


def test_round_results_are_returned_sorted_by_round_number(client):
    client.post("/api/round_result", json={**VALID_PAYLOAD, "round_number": 3})
    client.post("/api/round_result", json={**VALID_PAYLOAD, "round_number": 1})
    client.post("/api/round_result", json={**VALID_PAYLOAD, "round_number": 2})

    response = client.get("/api/round_results")
    rounds = [record["round_number"] for record in response.get_json()]

    assert rounds == [1, 2, 3]


def test_replacing_a_round_result_overwrites_it(client):
    client.post("/api/round_result", json=VALID_PAYLOAD)
    updated = {
        **VALID_PAYLOAD,
        "players": {
            "player1": {"points": 1000, "distance": 0, "markerLocation": [49.37, 9.54]},
            "player2": {"points": 100, "distance": 90000, "markerLocation": [1.0, 2.0]},
        },
    }

    response = client.post("/api/round_result", json=updated)
    data = client.get("/api/round_results").get_json()

    assert response.status_code == 201
    assert len(data) == 1
    assert data[0]["players"]["player1"]["points"] == 1000


@pytest.mark.parametrize(
    "bad_payload",
    [
        {},
        {"round_number": 0, "players": VALID_PAYLOAD["players"]},
        {"round_number": "one", "players": VALID_PAYLOAD["players"]},
        {"round_number": True, "players": VALID_PAYLOAD["players"]},
        {"round_number": 1, "players": {"player1": VALID_PAYLOAD["players"]["player1"]}},
        {"round_number": 1, "players": {"player1": {}, "player2": {}, "extra": {}}},
        {"round_number": 1, "players": "not-a-dict"},
        {"round_number": 1, "players": {"player1": "not-a-dict", "player2": {}}},
        {
            "round_number": 1,
            "players": {
                "player1": {"points": -1, "distance": None, "markerLocation": None},
                "player2": {"points": 0, "distance": None, "markerLocation": None},
            },
        },
        {
            "round_number": 1,
            "players": {
                "player1": {"points": True, "distance": None, "markerLocation": None},
                "player2": {"points": 0, "distance": None, "markerLocation": None},
            },
        },
        {
            "round_number": 1,
            "players": {
                "player1": {"points": 0, "distance": -5, "markerLocation": None},
                "player2": {"points": 0, "distance": None, "markerLocation": None},
            },
        },
        {
            "round_number": 1,
            "players": {
                "player1": {"points": 0, "distance": None, "markerLocation": [1.0]},
                "player2": {"points": 0, "distance": None, "markerLocation": None},
            },
        },
    ],
)
def test_invalid_round_result_payloads_are_rejected(client, bad_payload):
    response = client.post("/api/round_result", json=bad_payload)

    assert response.status_code == 400
    assert "error" in response.get_json()
    assert client.get("/api/round_results").get_json() == []
