"""Tests for the /api/map/config endpoints (read + patch).

Covers validation, persistence, and the "photo coverage" guarantee: the
`effective_bbox` returned by the API must always widen the configured bbox
enough to include every photo location from static/config/photos.json,
regardless of what the admin configured.
"""

import json

import pytest

import map_build


def test_get_config_has_default_shape(client):
    response = client.get("/api/map/config")
    data = response.get_json()

    assert response.status_code == 200
    assert data["maxzoom"] == map_build.DEFAULT_MAP_CONFIG["maxzoom"]
    assert data["world_maxzoom"] == map_build.DEFAULT_MAP_CONFIG["world_maxzoom"]
    assert data["bbox"] == map_build.DEFAULT_MAP_CONFIG["bbox"]
    assert data["build_date"] == map_build.DEFAULT_MAP_CONFIG["build_date"]
    assert "photo_bbox" in data
    assert "effective_bbox" in data


def test_patch_updates_maxzoom_and_world_maxzoom(client):
    response = client.patch("/api/map/config", json={"maxzoom": 12, "world_maxzoom": 4})
    data = response.get_json()

    assert response.status_code == 200
    assert data["maxzoom"] == 12
    assert data["world_maxzoom"] == 4

    follow_up = client.get("/api/map/config").get_json()
    assert follow_up["maxzoom"] == 12
    assert follow_up["world_maxzoom"] == 4


def test_patch_updates_bbox(client):
    response = client.patch("/api/map/config", json={"bbox": "5,47,15,55"})
    data = response.get_json()

    assert response.status_code == 200
    assert data["bbox"] == "5,47,15,55"


def test_patch_updates_build_date(client):
    response = client.patch("/api/map/config", json={"build_date": "20260701"})
    data = response.get_json()

    assert data["build_date"] == "20260701"


def test_patch_ignores_unknown_fields(client):
    response = client.patch("/api/map/config", json={"totally_made_up_field": "hi"})
    data = response.get_json()

    assert response.status_code == 200
    assert "totally_made_up_field" not in data


def test_patch_with_empty_body_does_not_error(client):
    response = client.patch("/api/map/config", json={})

    assert response.status_code == 200


@pytest.mark.parametrize(
    "bad_payload",
    [
        {"maxzoom": -1},
        {"maxzoom": 15},
        {"maxzoom": "10"},
        {"maxzoom": True},
        {"maxzoom": 12.5},
        {"world_maxzoom": -1},
        {"world_maxzoom": 15},
        {"maxzoom": 5, "world_maxzoom": 5},  # world must be strictly smaller
        {"maxzoom": 5, "world_maxzoom": 8},
        {"bbox": "not-a-bbox"},
        {"bbox": "1,2,3"},
        {"bbox": "5,47,1,55"},  # min_lon > max_lon
        {"bbox": "5,60,15,50"},  # min_lat > max_lat
        {"bbox": "-200,47,15,55"},  # out of range longitude
        {"bbox": 12345},
        {"build_date": "2026-07-01"},
        {"build_date": "2026070"},
        {"build_date": 20260701},
    ],
)
def test_patch_rejects_invalid_field_values(client, bad_payload):
    response = client.patch("/api/map/config", json=bad_payload)

    assert response.status_code == 400
    assert "error" in response.get_json()

    unchanged = client.get("/api/map/config").get_json()
    assert unchanged["maxzoom"] == map_build.DEFAULT_MAP_CONFIG["maxzoom"]
    assert unchanged["world_maxzoom"] == map_build.DEFAULT_MAP_CONFIG["world_maxzoom"]
    assert unchanged["bbox"] == map_build.DEFAULT_MAP_CONFIG["bbox"]
    assert unchanged["build_date"] == map_build.DEFAULT_MAP_CONFIG["build_date"]


def test_patch_persists_to_disk(client):
    client.patch("/api/map/config", json={"maxzoom": 11, "bbox": "5,47,15,55"})

    with open(map_build.MAP_CONFIG_FILE) as f:
        on_disk = json.load(f)

    assert on_disk["maxzoom"] == 11
    assert on_disk["bbox"] == "5,47,15,55"


def test_load_map_config_from_disk_restores_persisted_values(client, tmp_path):
    client.patch("/api/map/config", json={"maxzoom": 9, "world_maxzoom": 3})

    # Simulate a process restart: wipe the in-memory config, then reload.
    map_build._map_config.clear()
    map_build._map_config.update(map_build.DEFAULT_MAP_CONFIG)
    map_build.load_map_config_from_disk()

    assert map_build._map_config["maxzoom"] == 9
    assert map_build._map_config["world_maxzoom"] == 3


# --- photo-coverage guarantee --------------------------------------------


def test_effective_bbox_matches_configured_bbox_when_it_already_covers_photos(client):
    # The default bbox (-25,32,45,72) already covers every location in the
    # real static/config/photos.json, so no widening should happen.
    data = client.get("/api/map/config").get_json()

    assert data["effective_bbox"] == data["bbox"]


def test_effective_bbox_widens_to_include_out_of_range_photo(client, monkeypatch, tmp_path):
    photos_file = tmp_path / "photos.json"
    photos_file.write_text(
        json.dumps(
            [
                {"id": 1, "location": {"lat": 1.0, "lng": 2.0}},
                {"id": 2, "location": {"lat": 60.0, "lng": 100.0}},  # far outside default bbox
            ]
        )
    )
    monkeypatch.setattr(map_build, "PHOTOS_FILE", str(photos_file))

    client.patch("/api/map/config", json={"bbox": "5,47,15,55"})
    data = client.get("/api/map/config").get_json()

    min_lon, min_lat, max_lon, max_lat = (float(v) for v in data["effective_bbox"].split(","))
    assert min_lon <= 2.0
    assert max_lon >= 100.0
    assert min_lat <= 1.0
    assert max_lat >= 60.0
    # The stored/configured bbox itself must stay untouched.
    assert data["bbox"] == "5,47,15,55"


def test_photo_bbox_is_none_when_photos_file_missing(client, monkeypatch, tmp_path):
    monkeypatch.setattr(map_build, "PHOTOS_FILE", str(tmp_path / "does_not_exist.json"))

    data = client.get("/api/map/config").get_json()

    assert data["photo_bbox"] is None
    assert data["effective_bbox"] == data["bbox"]
