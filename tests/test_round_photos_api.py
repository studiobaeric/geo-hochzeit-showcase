"""Tests for the /api/round-photos endpoints (list, upload, patch, delete,
EXIF-location sniffing)."""

import io
import json
import struct

import pytest
from PIL import Image

import photo_config
import photo_storage


def _to_dms_rationals(value):
    """Decimal degrees -> ((deg,1),(min,1),(sec_num,sec_den)) EXIF rationals."""
    degrees = int(value)
    minutes_float = (value - degrees) * 60
    minutes = int(minutes_float)
    seconds = round((minutes_float - minutes) * 60 * 100)
    return [(degrees, 1), (minutes, 1), (seconds, 100)]


def _build_gps_exif_blob(lat, lng):
    """Raw TIFF/EXIF bytes (as Pillow's own Image.Exif.tobytes() would
    produce) containing just a GPSInfo IFD - built by hand with struct
    since Pillow itself has no public API to construct GPS EXIF on a
    from-scratch image (only to read it back from a real photo)."""
    lat_ref = b"N" if lat >= 0 else b"S"
    lng_ref = b"E" if lng >= 0 else b"W"
    lat_dms = _to_dms_rationals(abs(lat))
    lng_dms = _to_dms_rationals(abs(lng))

    tiff_header = b"II" + struct.pack("<H", 42) + struct.pack("<I", 8)

    ifd0_offset = 8
    ifd0_size = 2 + 12 * 1 + 4
    gps_ifd_offset = ifd0_offset + ifd0_size

    gps_entry_count = 4
    gps_ifd_size = 2 + 12 * gps_entry_count + 4
    data_offset = gps_ifd_offset + gps_ifd_size
    lat_data_offset = data_offset
    lng_data_offset = data_offset + 24

    def rational_bytes(dms):
        return b"".join(struct.pack("<II", num, den) for num, den in dms)

    def ascii_entry(tag, value):
        val = (value + b"\x00").ljust(4, b"\x00")[:4]
        return struct.pack("<HHI4s", tag, 2, len(value) + 1, val)

    def offset_entry(tag, typ, count, offset):
        return struct.pack("<HHI4s", tag, typ, count, struct.pack("<I", offset))

    ifd0 = struct.pack("<H", 1)
    ifd0 += struct.pack("<HHI4s", 0x8825, 4, 1, struct.pack("<I", gps_ifd_offset))
    ifd0 += struct.pack("<I", 0)

    gps_ifd = struct.pack("<H", gps_entry_count)
    gps_ifd += ascii_entry(1, lat_ref)
    gps_ifd += offset_entry(2, 5, 3, lat_data_offset)
    gps_ifd += ascii_entry(3, lng_ref)
    gps_ifd += offset_entry(4, 5, 3, lng_data_offset)
    gps_ifd += struct.pack("<I", 0)

    data = rational_bytes(lat_dms) + rational_bytes(lng_dms)

    return b"Exif\x00\x00" + tiff_header + ifd0 + gps_ifd + data


def _make_jpeg_bytes(gps=None):
    """A tiny valid JPEG, optionally carrying EXIF GPS coordinates.

    `gps` is (lat, lng) in decimal degrees; South/West are encoded via the
    ref tags, exactly like a real camera would.
    """
    image = Image.new("RGB", (4, 4), color="red")
    buffer = io.BytesIO()

    if gps is None:
        image.save(buffer, format="JPEG")
    else:
        lat, lng = gps
        image.save(buffer, format="JPEG", exif=_build_gps_exif_blob(lat, lng))

    buffer.seek(0)
    return buffer.read()


def _upload(client, gps=None, description="Schloss", lat=49.0, lng=9.0, filename="photo.jpg"):
    data = {
        "photo": (io.BytesIO(_make_jpeg_bytes(gps)), filename),
        "description": description,
        "lat": str(lat),
        "lng": str(lng),
    }
    return client.post("/api/round-photos", data=data, content_type="multipart/form-data")


def test_list_is_empty_initially(client):
    response = client.get("/api/round-photos")

    assert response.status_code == 200
    assert response.get_json() == []


def test_upload_creates_a_photo_entry(client):
    response = _upload(client, description="Schloss Aschhausen", lat=49.369, lng=9.5436)
    data = response.get_json()

    assert response.status_code == 201
    assert data["id"] == 1
    assert data["description"] == "Schloss Aschhausen"
    assert data["location"] == {"lat": 49.369, "lng": 9.5436}
    assert data["url"] == f"/static/photos/{data['filename']}"

    listed = client.get("/api/round-photos").get_json()
    assert len(listed) == 1
    assert listed[0]["id"] == 1


def test_upload_writes_the_file_to_disk(client):
    response = _upload(client)
    filename = response.get_json()["filename"]

    import os

    assert os.path.isfile(os.path.join(photo_storage.PHOTOS_DIR, filename))


def test_upload_writes_to_photos_json(client):
    _upload(client, description="Erstes Bild")

    with open(photo_config.PHOTOS_FILE, encoding="utf-8") as f:
        on_disk = json.load(f)

    assert len(on_disk) == 1
    assert on_disk[0]["description"] == "Erstes Bild"


def test_ids_increment_across_uploads(client):
    first = _upload(client).get_json()
    second = _upload(client).get_json()

    assert first["id"] == 1
    assert second["id"] == 2


def test_no_upper_limit_on_number_of_photos(client):
    for _ in range(25):
        response = _upload(client)
        assert response.status_code == 201

    assert len(client.get("/api/round-photos").get_json()) == 25


def test_upload_without_file_is_rejected(client):
    response = client.post(
        "/api/round-photos",
        data={"description": "x", "lat": "1", "lng": "1"},
        content_type="multipart/form-data",
    )

    assert response.status_code == 400
    assert "error" in response.get_json()
    assert client.get("/api/round-photos").get_json() == []


@pytest.mark.parametrize(
    "bad_kwargs",
    [
        {"lat": 91, "lng": 0},
        {"lat": -91, "lng": 0},
        {"lat": 0, "lng": 181},
        {"lat": 0, "lng": -181},
    ],
)
def test_upload_rejects_out_of_range_coordinates(client, bad_kwargs):
    response = _upload(client, **bad_kwargs)

    assert response.status_code == 400
    assert client.get("/api/round-photos").get_json() == []


def test_upload_rejects_non_numeric_coordinates(client):
    data = {
        "photo": (io.BytesIO(_make_jpeg_bytes()), "photo.jpg"),
        "description": "x",
        "lat": "not-a-number",
        "lng": "9",
    }
    response = client.post("/api/round-photos", data=data, content_type="multipart/form-data")

    assert response.status_code == 400


def test_upload_rejects_disallowed_file_type(client):
    data = {
        "photo": (io.BytesIO(b"just some text"), "notes.txt"),
        "description": "x",
        "lat": "1",
        "lng": "1",
    }
    response = client.post("/api/round-photos", data=data, content_type="multipart/form-data")

    assert response.status_code == 400
    assert client.get("/api/round-photos").get_json() == []


def test_patch_updates_description_and_location(client):
    created = _upload(client).get_json()

    response = client.patch(
        f"/api/round-photos/{created['id']}",
        json={"description": "Neuer Text", "location": {"lat": 10.0, "lng": 20.0}},
    )
    data = response.get_json()

    assert response.status_code == 200
    assert data["description"] == "Neuer Text"
    assert data["location"] == {"lat": 10.0, "lng": 20.0}

    follow_up = client.get("/api/round-photos").get_json()[0]
    assert follow_up["location"] == {"lat": 10.0, "lng": 20.0}


def test_patch_partial_update_leaves_other_field_untouched(client):
    created = _upload(client, description="Original", lat=1.0, lng=2.0).get_json()

    response = client.patch(f"/api/round-photos/{created['id']}", json={"description": "Neu"})
    data = response.get_json()

    assert data["description"] == "Neu"
    assert data["location"] == {"lat": 1.0, "lng": 2.0}


def test_patch_unknown_id_returns_404(client):
    response = client.patch("/api/round-photos/999", json={"description": "x"})

    assert response.status_code == 404


def test_patch_rejects_invalid_location(client):
    created = _upload(client).get_json()

    response = client.patch(
        f"/api/round-photos/{created['id']}", json={"location": {"lat": 200, "lng": 0}}
    )

    assert response.status_code == 400


def test_delete_removes_entry_and_file(client):
    created = _upload(client).get_json()
    filename = created["filename"]

    response = client.delete(f"/api/round-photos/{created['id']}")

    assert response.status_code == 200
    assert response.get_json() == {"deleted": True, "id": created["id"]}
    assert client.get("/api/round-photos").get_json() == []

    import os

    assert not os.path.isfile(os.path.join(photo_storage.PHOTOS_DIR, filename))


def test_delete_unknown_id_returns_404(client):
    response = client.delete("/api/round-photos/999")

    assert response.status_code == 404


def test_exif_location_extracts_gps_from_photo(client):
    data = {"photo": (io.BytesIO(_make_jpeg_bytes(gps=(49.3690, 9.5436))), "gps.jpg")}
    response = client.post(
        "/api/round-photos/exif-location", data=data, content_type="multipart/form-data"
    )
    payload = response.get_json()

    assert response.status_code == 200
    assert payload["lat"] == pytest.approx(49.369, abs=1e-3)
    assert payload["lng"] == pytest.approx(9.5436, abs=1e-3)


def test_exif_location_returns_nulls_when_no_gps_present(client):
    data = {"photo": (io.BytesIO(_make_jpeg_bytes()), "no-gps.jpg")}
    response = client.post(
        "/api/round-photos/exif-location", data=data, content_type="multipart/form-data"
    )
    payload = response.get_json()

    assert response.status_code == 200
    assert payload == {"lat": None, "lng": None}


def test_exif_location_without_file_is_rejected(client):
    response = client.post(
        "/api/round-photos/exif-location", data={}, content_type="multipart/form-data"
    )

    assert response.status_code == 400
