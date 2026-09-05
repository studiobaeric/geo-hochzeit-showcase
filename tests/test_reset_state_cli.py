"""Tests for game_state.reset_to_defaults(), photo_config.clear_round_photos()
(which restores the default round photos rather than emptying them) and the
tools/reset_state.py CLI built on top of them."""

import io
import os
import threading

from werkzeug.serving import make_server

import game_state
import photo_config
import photo_storage
import tools.reset_state as reset_state
from app import app as flask_app


def _upload_player_photo(client, role, name="photo.jpg"):
    response = client.post(
        f"/api/player-config/photo/{role}",
        data={"photo": (io.BytesIO(b"fake-bytes"), name)},
        content_type="multipart/form-data",
    )
    assert response.status_code == 201
    return response.get_json()


def _create_round_photo(client, name="round.jpg"):
    response = client.post(
        "/api/round-photos",
        data={
            "photo": (io.BytesIO(b"fake-bytes"), name),
            "lat": "10.0",
            "lng": "20.0",
            "description": "test",
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 201
    return response.get_json()


def test_reset_to_defaults_restores_player_and_round_config(client):
    client.patch("/api/player-config", json={"player1_name": "Alice", "player2_name": "Bob"})
    client.patch("/api/round-config", json={"mode": "countdown", "duration_seconds": 120})
    client.patch("/api/gamestate", json={"round": 3, "state": "playing"})

    previous = game_state.reset_to_defaults()

    assert previous["player1_name"] == "Alice"
    assert game_state._player_config == game_state._DEFAULT_PLAYER_CONFIG
    assert game_state._round_config == game_state._DEFAULT_ROUND_CONFIG
    assert game_state._gamestate == game_state._DEFAULT_GAMESTATE


def test_reset_to_defaults_deletes_uploaded_player_photos(client):
    record = _upload_player_photo(client, "player1")
    photo_path = os.path.join(photo_storage.PHOTOS_DIR, record["player1_photo"])
    hq_path = os.path.join(photo_storage.PHOTOS_DIR, record["player1_photo_hq"])
    assert os.path.exists(photo_path)
    assert os.path.exists(hq_path)

    game_state.reset_to_defaults()

    assert not os.path.exists(photo_path)
    assert not os.path.exists(hq_path)
    assert game_state._player_config["player1_photo"] == ""
    assert game_state._player_config["player1_photo_hq"] == ""


def test_clear_round_photos_removes_uploaded_files_and_restores_defaults(client):
    record = _create_round_photo(client)
    photo_path = os.path.join(photo_storage.PHOTOS_DIR, record["filename"])
    assert os.path.exists(photo_path)

    removed = photo_config.clear_round_photos()

    assert removed == 1
    assert not os.path.exists(photo_path)
    assert client.get("/api/round-photos").get_json() == [
        photo_config._with_url(p) for p in photo_config._DEFAULT_ROUND_PHOTOS
    ]


def test_clear_round_photos_does_not_delete_default_photo_files(client, tmp_path):
    default_filename = photo_config._DEFAULT_ROUND_PHOTOS[0]["filename"]
    default_photo_path = os.path.join(photo_storage.PHOTOS_DIR, default_filename)
    os.makedirs(photo_storage.PHOTOS_DIR, exist_ok=True)
    with open(default_photo_path, "wb") as f:
        f.write(b"fake-bytes")

    photo_config.clear_round_photos()

    assert os.path.exists(default_photo_path)


def test_clear_round_photos_on_empty_list_restores_defaults():
    removed = photo_config.clear_round_photos()

    assert removed == 0
    with photo_config._lock:
        assert photo_config._load_locked() == photo_config._DEFAULT_ROUND_PHOTOS


def test_deleting_a_default_round_photo_does_not_remove_its_file(client):
    default = photo_config._DEFAULT_ROUND_PHOTOS[0]
    os.makedirs(photo_storage.PHOTOS_DIR, exist_ok=True)
    default_photo_path = os.path.join(photo_storage.PHOTOS_DIR, default["filename"])
    default_hq_path = os.path.join(photo_storage.PHOTOS_DIR, default["filename_hq"])
    for path in (default_photo_path, default_hq_path):
        with open(path, "wb") as f:
            f.write(b"fake-bytes")
    with photo_config._lock:
        photo_config._save_locked([dict(default)])

    response = client.delete(f"/api/round-photos/{default['id']}")

    assert response.status_code == 200
    assert client.get("/api/round-photos").get_json() == []
    assert os.path.exists(default_photo_path)
    assert os.path.exists(default_hq_path)


def test_reset_recovers_a_default_round_photo_deleted_via_the_config_ui(client):
    """A player removing a default round photo in /config only drops it
    from the active round list - clear_round_photos() can still bring it
    back later because its files were never deleted (see
    test_deleting_a_default_round_photo_does_not_remove_its_file)."""
    default = photo_config._DEFAULT_ROUND_PHOTOS[0]
    os.makedirs(photo_storage.PHOTOS_DIR, exist_ok=True)
    for filename in (default["filename"], default["filename_hq"]):
        with open(os.path.join(photo_storage.PHOTOS_DIR, filename), "wb") as f:
            f.write(b"fake-bytes")
    with photo_config._lock:
        photo_config._save_locked([dict(default)])
    client.delete(f"/api/round-photos/{default['id']}")
    assert client.get("/api/round-photos").get_json() == []

    photo_config.clear_round_photos()

    assert client.get("/api/round-photos").get_json() == [
        photo_config._with_url(p) for p in photo_config._DEFAULT_ROUND_PHOTOS
    ]


def test_reset_to_defaults_endpoint(client):
    """POST /api/reset-to-defaults is the HTTP counterpart of the two reset
    functions below, used by reset_state.py so an already-running server
    resets its own live state instead of needing a restart."""
    client.patch("/api/player-config", json={"player1_name": "Alice"})
    _create_round_photo(client)

    response = client.post("/api/reset-to-defaults")
    data = response.get_json()

    assert response.status_code == 200
    assert data["previous_player_config"]["player1_name"] == "Alice"
    assert data["round_photos_removed"] == 1
    assert game_state._player_config["player1_name"] == "player1"
    assert client.get("/api/round-photos").get_json() == [
        photo_config._with_url(p) for p in photo_config._DEFAULT_ROUND_PHOTOS
    ]


def _run_flask_app_in_background(monkeypatch):
    """Serve the real `app` module (sharing this test process's monkey-
    patched game_state/photo_config/photo_storage module state) on a real,
    ephemeral local port, so reset_state.py's HTTP client has an actual
    running server to talk to. Returns the werkzeug server so the caller
    can server.shutdown() it when done."""
    server = make_server("127.0.0.1", 0, flask_app)
    monkeypatch.setattr(reset_state, "SERVER_URL", f"http://127.0.0.1:{server.server_port}")
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    return server, thread


def test_cli_reset_without_confirmation_resets_everything_via_running_server(client, monkeypatch, capsys):
    client.patch("/api/player-config", json={"player1_name": "Alice"})
    _create_round_photo(client)
    server, thread = _run_flask_app_in_background(monkeypatch)

    try:
        reset_state.reset(confirm=False)
    finally:
        server.shutdown()
        thread.join()

    assert game_state._player_config["player1_name"] == "player1"
    assert client.get("/api/round-photos").get_json() == [
        photo_config._with_url(p) for p in photo_config._DEFAULT_ROUND_PHOTOS
    ]
    output = capsys.readouterr().out
    assert "Reset to default state" in output
    assert "via the running server" in output


def test_cli_reset_falls_back_to_files_when_no_server_is_running(client, monkeypatch, capsys):
    monkeypatch.setattr(reset_state, "SERVER_URL", "http://127.0.0.1:1")
    client.patch("/api/player-config", json={"player1_name": "Alice"})
    _create_round_photo(client)

    reset_state.reset(confirm=False)

    assert game_state._player_config["player1_name"] == "player1"
    assert client.get("/api/round-photos").get_json() == [
        photo_config._with_url(p) for p in photo_config._DEFAULT_ROUND_PHOTOS
    ]
    output = capsys.readouterr().out
    assert "Reset to default state" in output
    assert "no running server found" in output.lower()
    assert "restarted" in output.lower()


def test_cli_reset_aborts_when_confirmation_declined(client, monkeypatch, capsys):
    client.patch("/api/player-config", json={"player1_name": "Alice"})
    monkeypatch.setattr("builtins.input", lambda prompt="": "n")

    reset_state.reset(confirm=True)

    assert game_state._player_config["player1_name"] == "Alice"
    assert "Aborted" in capsys.readouterr().out


def test_cli_reset_proceeds_when_confirmation_accepted(client, monkeypatch):
    client.patch("/api/player-config", json={"player1_name": "Alice"})
    monkeypatch.setattr("builtins.input", lambda prompt="": "y")

    reset_state.reset(confirm=True)

    assert game_state._player_config["player1_name"] == "player1"
