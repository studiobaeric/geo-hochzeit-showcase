"""Tests for the /api/map/config endpoints (read + patch).

Covers validation, persistence, and the "photo coverage" guarantee: the
most detailed (highest-maxzoom) region's `effective_bbox` must always
widen its configured bbox enough to include every photo location from
static/config/photos.json, regardless of what the admin configured.
"""

import json

import pytest

import map_build


def test_get_config_has_default_shape(client):
    response = client.get("/api/map/config")
    data = response.get_json()

    assert response.status_code == 200
    assert data["build_date"] == map_build.DEFAULT_MAP_CONFIG["build_date"]
    assert len(data["regions"]) == 2
    names = [r["name"] for r in data["regions"]]
    assert names == ["Welt", "Europa"]
    assert "photo_bbox" in data
    for region in data["regions"]:
        assert "effective_bbox" in region


def test_regions_are_returned_sorted_by_maxzoom(client):
    client.patch(
        "/api/map/config",
        json={
            "regions": [
                {"name": "Detail", "bbox": "5,47,15,55", "maxzoom": 13},
                {"name": "Welt", "bbox": "-180,-90,180,90", "maxzoom": 5},
            ]
        },
    )

    data = client.get("/api/map/config").get_json()

    assert [r["name"] for r in data["regions"]] == ["Welt", "Detail"]


def test_patch_updates_regions(client):
    new_regions = [
        {"name": "Welt", "bbox": "-180,-90,180,90", "maxzoom": 4},
        {"name": "Deutschland", "bbox": "5.5,47,15.5,55", "maxzoom": 12},
    ]
    response = client.patch("/api/map/config", json={"regions": new_regions})
    data = response.get_json()

    assert response.status_code == 200
    assert [r["name"] for r in data["regions"]] == ["Welt", "Deutschland"]
    assert data["regions"][1]["bbox"] == "5.5,47,15.5,55"
    assert data["regions"][1]["maxzoom"] == 12

    follow_up = client.get("/api/map/config").get_json()
    assert [r["maxzoom"] for r in follow_up["regions"]] == [4, 12]


def test_patch_supports_more_than_two_regions(client):
    regions = [
        {"name": "Welt", "bbox": "-180,-90,180,90", "maxzoom": 5},
        {"name": "Europa", "bbox": "-25,32,45,72", "maxzoom": 11},
        {"name": "Madeira Closeup", "bbox": "-17.5,32.5,-16.5,33", "maxzoom": 14},
    ]
    response = client.patch("/api/map/config", json={"regions": regions})
    data = response.get_json()

    assert response.status_code == 200
    assert len(data["regions"]) == 3
    assert [r["name"] for r in data["regions"]] == ["Welt", "Europa", "Madeira Closeup"]


def test_patch_updates_build_date(client):
    response = client.patch("/api/map/config", json={"build_date": "20260701"})
    data = response.get_json()

    assert data["build_date"] == "20260701"


def test_default_build_date_is_empty_meaning_automatic(client):
    # "" means "resolve the newest available build at build time" (see
    # tools/build_basemap.py) - never a fixed date baked into source, since
    # one shipped once before and 404'd once Protomaps' retention window
    # (~5 days) rolled past it.
    data = client.get("/api/map/config").get_json()

    assert data["build_date"] == ""


def test_patch_accepts_empty_build_date(client):
    client.patch("/api/map/config", json={"build_date": "20260701"})

    response = client.patch("/api/map/config", json={"build_date": ""})
    data = response.get_json()

    assert response.status_code == 200
    assert data["build_date"] == ""


def test_patch_ignores_unknown_fields(client):
    response = client.patch("/api/map/config", json={"totally_made_up_field": "hi"})
    data = response.get_json()

    assert response.status_code == 200
    assert "totally_made_up_field" not in data


def test_patch_with_empty_body_does_not_error(client):
    response = client.patch("/api/map/config", json={})

    assert response.status_code == 200


def test_patch_trims_region_names(client):
    response = client.patch(
        "/api/map/config",
        json={"regions": [{"name": "  Welt  ", "bbox": "-180,-90,180,90", "maxzoom": 5}]},
    )
    data = response.get_json()

    assert data["regions"][0]["name"] == "Welt"


@pytest.mark.parametrize(
    "bad_payload",
    [
        {"regions": []},
        {"regions": "not-a-list"},
        {"regions": [{"name": "", "bbox": "-1,-1,1,1", "maxzoom": 5}]},
        {"regions": [{"name": "   ", "bbox": "-1,-1,1,1", "maxzoom": 5}]},
        {"regions": [{"name": "x" * 61, "bbox": "-1,-1,1,1", "maxzoom": 5}]},
        {"regions": [{"name": "A", "bbox": "not-a-bbox", "maxzoom": 5}]},
        {"regions": [{"name": "A", "bbox": "1,2,3", "maxzoom": 5}]},
        {"regions": [{"name": "A", "bbox": "5,47,1,55", "maxzoom": 5}]},  # min_lon > max_lon
        {"regions": [{"name": "A", "bbox": "-200,47,15,55", "maxzoom": 5}]},  # out of range
        {"regions": [{"name": "A", "bbox": "-1,-1,1,1", "maxzoom": -1}]},
        {"regions": [{"name": "A", "bbox": "-1,-1,1,1", "maxzoom": 15}]},
        {"regions": [{"name": "A", "bbox": "-1,-1,1,1", "maxzoom": "10"}]},
        {"regions": [{"name": "A", "bbox": "-1,-1,1,1", "maxzoom": True}]},
        {"regions": [{"name": "A", "bbox": "-1,-1,1,1", "maxzoom": 12.5}]},
        # duplicate maxzoom across regions
        {
            "regions": [
                {"name": "A", "bbox": "-10,-10,10,10", "maxzoom": 5},
                {"name": "B", "bbox": "-5,-5,5,5", "maxzoom": 5},
            ]
        },
        # too many regions
        {
            "regions": [
                {"name": f"R{i}", "bbox": "-1,-1,1,1", "maxzoom": i} for i in range(9)
            ]
        },
        {"regions": [{"bbox": "-1,-1,1,1", "maxzoom": 5}]},  # missing name
        {"regions": [{"name": "A", "maxzoom": 5}]},  # missing bbox
        {"regions": [{"name": "A", "bbox": "-1,-1,1,1"}]},  # missing maxzoom
        {"regions": ["not-a-dict"]},
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
    assert unchanged["build_date"] == map_build.DEFAULT_MAP_CONFIG["build_date"]
    assert [r["name"] for r in unchanged["regions"]] == ["Welt", "Europa"]


def test_patch_persists_to_disk(client):
    client.patch(
        "/api/map/config",
        json={"regions": [{"name": "Solo", "bbox": "5,47,15,55", "maxzoom": 11}]},
    )

    with open(map_build.MAP_CONFIG_FILE) as f:
        on_disk = json.load(f)

    assert on_disk["regions"] == [{"name": "Solo", "bbox": "5,47,15,55", "maxzoom": 11}]


def test_load_map_config_from_disk_restores_persisted_values(client, tmp_path):
    client.patch(
        "/api/map/config",
        json={"regions": [{"name": "Solo", "bbox": "5,47,15,55", "maxzoom": 9}]},
    )

    # Simulate a process restart: wipe the in-memory config, then reload.
    map_build._map_config.clear()
    map_build._map_config.update(map_build.DEFAULT_MAP_CONFIG)
    map_build.load_map_config_from_disk()

    assert map_build._map_config["regions"] == [{"name": "Solo", "bbox": "5,47,15,55", "maxzoom": 9}]


# --- photo-coverage guarantee --------------------------------------------


def test_effective_bbox_matches_configured_bbox_when_it_already_covers_photos(client):
    # The default "Europa" region (-25,32,45,72) already covers every
    # location in the real static/config/photos.json, so no widening
    # should happen to the most detailed region.
    data = client.get("/api/map/config").get_json()

    top_region = max(data["regions"], key=lambda r: r["maxzoom"])
    assert top_region["effective_bbox"] == top_region["bbox"]


def test_effective_bbox_widens_only_the_most_detailed_region(client, monkeypatch, tmp_path):
    photos_file = tmp_path / "photos.json"
    photos_file.write_text(
        json.dumps(
            [
                {"id": 1, "location": {"lat": 1.0, "lng": 2.0}},
                {"id": 2, "location": {"lat": 60.0, "lng": 100.0}},  # far outside any region
            ]
        )
    )
    monkeypatch.setattr(map_build, "PHOTOS_FILE", str(photos_file))

    client.patch(
        "/api/map/config",
        json={
            "regions": [
                {"name": "Welt", "bbox": "-180,-90,180,90", "maxzoom": 5},
                {"name": "Detail", "bbox": "5,47,15,55", "maxzoom": 13},
            ]
        },
    )
    data = client.get("/api/map/config").get_json()

    welt, detail = data["regions"]
    assert welt["name"] == "Welt"
    assert detail["name"] == "Detail"

    # The low-detail "Welt" region is untouched...
    assert welt["effective_bbox"] == welt["bbox"]

    # ...but the most detailed region is widened to include both photos.
    min_lon, min_lat, max_lon, max_lat = (float(v) for v in detail["effective_bbox"].split(","))
    assert min_lon <= 2.0
    assert max_lon >= 100.0
    assert min_lat <= 1.0
    assert max_lat >= 60.0
    # The stored/configured bbox itself must stay untouched.
    assert detail["bbox"] == "5,47,15,55"


def test_photo_bbox_is_none_when_photos_file_missing(client, monkeypatch, tmp_path):
    monkeypatch.setattr(map_build, "PHOTOS_FILE", str(tmp_path / "does_not_exist.json"))

    data = client.get("/api/map/config").get_json()

    assert data["photo_bbox"] is None
    top_region = max(data["regions"], key=lambda r: r["maxzoom"])
    assert top_region["effective_bbox"] == top_region["bbox"]
