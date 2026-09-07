"""Tests for the /api/scoring-config endpoints (read + patch), per #127."""

import pytest

DEFAULT_SCORING_CONFIG = {
    "algorithm": "exponential",
    "max_points": 1000,
    "min_points": 100,
    "perfect_radius_meters": 500,
    "distance_scale_meters": 100000,
    "max_distance_meters": 20000,
}


def test_get_scoring_config_has_default_shape(client):
    response = client.get("/api/scoring-config")
    data = response.get_json()

    assert response.status_code == 200
    assert data == DEFAULT_SCORING_CONFIG


def test_patch_updates_algorithm(client):
    response = client.patch("/api/scoring-config", json={"algorithm": "step"})
    data = response.get_json()

    assert response.status_code == 200
    assert data == {**DEFAULT_SCORING_CONFIG, "algorithm": "step"}


def test_patch_updates_individual_fields(client):
    response = client.patch(
        "/api/scoring-config",
        json={
            "max_points": 2000,
            "min_points": 200,
            "perfect_radius_meters": 10,
            "distance_scale_meters": 5000,
            "max_distance_meters": 50000,
        },
    )
    data = response.get_json()

    assert response.status_code == 200
    assert data == {
        "algorithm": "exponential",
        "max_points": 2000,
        "min_points": 200,
        "perfect_radius_meters": 10,
        "distance_scale_meters": 5000,
        "max_distance_meters": 50000,
    }

    follow_up = client.get("/api/scoring-config").get_json()
    assert follow_up == data


def test_patch_ignores_unknown_fields(client):
    response = client.patch("/api/scoring-config", json={"totally_made_up_field": "hi"})
    data = response.get_json()

    assert response.status_code == 200
    assert "totally_made_up_field" not in data


def test_patch_with_empty_body_does_not_error(client):
    response = client.patch("/api/scoring-config", json={})

    assert response.status_code == 200


@pytest.mark.parametrize(
    "bad_payload",
    [
        {"algorithm": "made-up"},
        {"algorithm": 123},
        {"algorithm": None},
        {"max_points": -1},
        {"max_points": "1000"},
        {"max_points": True},
        {"max_points": 12.5},
        {"min_points": -1},
        {"min_points": "100"},
        {"min_points": True},
        {"perfect_radius_meters": 0},
        {"perfect_radius_meters": "500"},
        {"perfect_radius_meters": True},
        {"distance_scale_meters": 0},
        {"max_distance_meters": 0},
        # min_points greater than max_points, whether resolved against the
        # existing config or entirely from this one payload.
        {"min_points": 5000},
        {"max_points": 500, "min_points": 600},
        # max_distance_meters at or below perfect_radius_meters, whether
        # resolved against the existing config or entirely from this one
        # payload - would otherwise collapse the linear algorithm's falloff
        # to (near) nothing instead of being rejected.
        {"max_distance_meters": 500},
        {"perfect_radius_meters": 20000, "max_distance_meters": 20000},
    ],
)
def test_patch_rejects_invalid_field_values(client, bad_payload):
    response = client.patch("/api/scoring-config", json=bad_payload)

    assert response.status_code == 400
    assert "error" in response.get_json()

    # Rejected updates must not partially apply.
    unchanged = client.get("/api/scoring-config").get_json()
    assert unchanged == DEFAULT_SCORING_CONFIG


def test_patch_persists_to_disk(client):
    import json

    import game_state

    client.patch("/api/scoring-config", json={"algorithm": "linear", "max_distance_meters": 30000})

    with open(game_state.STATE_FILE) as f:
        on_disk = json.load(f)

    assert on_disk["scoring_config"] == {**DEFAULT_SCORING_CONFIG, "algorithm": "linear", "max_distance_meters": 30000}


def test_reset_does_not_clear_scoring_config(client):
    client.patch("/api/scoring-config", json={"algorithm": "step"})

    client.post("/api/reset")

    data = client.get("/api/scoring-config").get_json()
    assert data["algorithm"] == "step"
