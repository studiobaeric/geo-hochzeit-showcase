"""Tests for POST /api/player-config/photo/<role> (player profile photo
uploads)."""

import io
import os

from PIL import Image

import game_state
import photo_storage


def _jpeg_bytes():
    buffer = io.BytesIO()
    Image.new("RGB", (4, 4), color="blue").save(buffer, format="JPEG")
    buffer.seek(0)
    return buffer.read()


def _upload(client, role, filename="me.jpg"):
    data = {"photo": (io.BytesIO(_jpeg_bytes()), filename)}
    return client.post(f"/api/player-config/photo/{role}", data=data, content_type="multipart/form-data")


def test_upload_sets_player1_photo(client):
    response = _upload(client, "player1")
    data = response.get_json()

    assert response.status_code == 201
    assert data["player1_photo"]
    assert data["player2_photo"] == ""

    follow_up = client.get("/api/player-config").get_json()
    assert follow_up["player1_photo"] == data["player1_photo"]


def test_upload_sets_player2_photo_independently(client):
    _upload(client, "player1")
    response = _upload(client, "player2")
    data = response.get_json()

    assert data["player1_photo"]
    assert data["player2_photo"]
    assert data["player1_photo"] != data["player2_photo"]


def test_upload_writes_file_to_disk(client):
    response = _upload(client, "player1")
    filename = response.get_json()["player1_photo"]

    assert os.path.isfile(os.path.join(photo_storage.PHOTOS_DIR, filename))


def test_upload_also_keeps_a_full_resolution_copy(client):
    data = _upload(client, "player1").get_json()

    assert data["player1_photo_hq"]
    assert data["player1_photo_hq"] != data["player1_photo"]
    assert os.path.isfile(os.path.join(photo_storage.PHOTOS_DIR, data["player1_photo_hq"]))

    follow_up = client.get("/api/player-config").get_json()
    assert follow_up["player1_photo_hq"] == data["player1_photo_hq"]


def test_replacing_a_photo_deletes_the_previous_files(client):
    first = _upload(client, "player1").get_json()
    first_filename = first["player1_photo"]
    first_filename_hq = first["player1_photo_hq"]

    second = _upload(client, "player1").get_json()

    assert second["player1_photo"] != first_filename
    assert not os.path.isfile(os.path.join(photo_storage.PHOTOS_DIR, first_filename))
    assert not os.path.isfile(os.path.join(photo_storage.PHOTOS_DIR, first_filename_hq))
    assert os.path.isfile(os.path.join(photo_storage.PHOTOS_DIR, second["player1_photo"]))
    assert os.path.isfile(os.path.join(photo_storage.PHOTOS_DIR, second["player1_photo_hq"]))


def test_uploading_one_role_does_not_delete_the_other_roles_files(client):
    player1 = _upload(client, "player1").get_json()

    _upload(client, "player2")

    assert os.path.isfile(os.path.join(photo_storage.PHOTOS_DIR, player1["player1_photo"]))
    assert os.path.isfile(os.path.join(photo_storage.PHOTOS_DIR, player1["player1_photo_hq"]))


def test_upload_rejects_unknown_role(client):
    response = _upload(client, "player3")

    assert response.status_code == 400
    assert "error" in response.get_json()


def test_upload_rejects_missing_file(client):
    response = client.post("/api/player-config/photo/player1", data={}, content_type="multipart/form-data")

    assert response.status_code == 400


def test_upload_rejects_disallowed_file_type(client):
    data = {"photo": (io.BytesIO(b"not an image"), "notes.txt")}
    response = client.post("/api/player-config/photo/player1", data=data, content_type="multipart/form-data")

    assert response.status_code == 400
    unchanged = client.get("/api/player-config").get_json()
    assert unchanged["player1_photo"] == ""


def test_reset_does_not_clear_player_photos(client):
    _upload(client, "player1")

    client.post("/api/reset")

    data = client.get("/api/player-config").get_json()
    assert data["player1_photo"]


def test_patch_can_reset_photo_to_empty(client):
    _upload(client, "player1")

    response = client.patch("/api/player-config", json={"player1_photo": ""})
    data = response.get_json()

    assert data["player1_photo"] == ""
    assert data["player1_photo_hq"] == ""


def test_patch_reset_deletes_the_photo_files(client):
    uploaded = _upload(client, "player1").get_json()

    client.patch("/api/player-config", json={"player1_photo": ""})

    assert not os.path.isfile(os.path.join(photo_storage.PHOTOS_DIR, uploaded["player1_photo"]))
    assert not os.path.isfile(os.path.join(photo_storage.PHOTOS_DIR, uploaded["player1_photo_hq"]))


def _put_default_photo_on_disk(filename):
    os.makedirs(photo_storage.PHOTOS_DIR, exist_ok=True)
    with open(os.path.join(photo_storage.PHOTOS_DIR, filename), "wb") as f:
        f.write(b"fake-bytes")


def test_clearing_a_default_photo_via_patch_does_not_delete_its_file(client):
    default_filename = "picture_of_player1.jpg"
    _put_default_photo_on_disk(default_filename)
    client.patch("/api/player-config", json={"player1_photo": default_filename})

    client.patch("/api/player-config", json={"player1_photo": ""})

    assert os.path.isfile(os.path.join(photo_storage.PHOTOS_DIR, default_filename))


def test_uploading_over_a_default_photo_does_not_delete_its_file(client):
    default_filename = "picture_of_player1.jpg"
    _put_default_photo_on_disk(default_filename)
    client.patch("/api/player-config", json={"player1_photo": default_filename})

    _upload(client, "player1")

    assert os.path.isfile(os.path.join(photo_storage.PHOTOS_DIR, default_filename))


def test_reset_to_defaults_does_not_delete_default_photo_files(client):
    default_filename = "picture_of_player2.jpg"
    _put_default_photo_on_disk(default_filename)
    client.patch("/api/player-config", json={"player2_photo": default_filename})

    game_state.reset_to_defaults()

    assert os.path.isfile(os.path.join(photo_storage.PHOTOS_DIR, default_filename))
