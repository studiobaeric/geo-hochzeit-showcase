"""Sanity checks on the game's config data (static/config/photos.json).

Not a strict schema test - just enough to catch an obvious typo (missing
field, swapped lat/lng, malformed JSON) before it breaks the game at the
wedding.
"""

import json
from pathlib import Path

import pytest

PHOTOS_PATH = Path(__file__).resolve().parent.parent / "static" / "config" / "photos.json"


@pytest.fixture(scope="module")
def photos():
    with open(PHOTOS_PATH, encoding="utf-8") as f:
        return json.load(f)


def test_photos_json_is_a_non_empty_list(photos):
    assert isinstance(photos, list)
    assert len(photos) > 0


def test_every_photo_has_required_fields(photos):
    for photo in photos:
        assert "id" in photo
        assert "filename" in photo
        assert "location" in photo
        assert "lat" in photo["location"]
        assert "lng" in photo["location"]


def test_photo_coordinates_look_plausible(photos):
    for photo in photos:
        lat = photo["location"]["lat"]
        lng = photo["location"]["lng"]

        assert -90 <= lat <= 90
        assert -180 <= lng <= 180


def test_photo_ids_are_unique(photos):
    ids = [photo["id"] for photo in photos]
    assert len(ids) == len(set(ids))


def test_referenced_photo_files_exist(photos):
    photos_dir = PHOTOS_PATH.parent.parent / "photos"
    missing = [p["filename"] for p in photos if not (photos_dir / p["filename"]).exists()]

    assert not missing, f"photos.json references missing files: {missing}"
