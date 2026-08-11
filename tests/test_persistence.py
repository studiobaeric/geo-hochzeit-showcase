"""Tests for JSON-file persistence of the game state (game_state.py).

Covers: state surviving a simulated process restart, various malformed/
missing-file configurations being handled gracefully, and that mutating
API calls actually write through to disk.
"""

import json

import game_state

VALID_PAYLOAD = {
    "round_number": 2,
    "placed_by": "tobias",
    "coordinates": {"lat": 10.0, "lng": 20.0},
}


def _read_state_file():
    with open(game_state.STATE_FILE) as f:
        return json.load(f)


# --- API calls write through to disk -----------------------------------


def test_patch_gamestate_persists_to_disk(client):
    client.patch("/api/gamestate", json={"round": 3, "state": "playing"})

    on_disk = _read_state_file()
    assert on_disk["gamestate"]["round"] == 3
    assert on_disk["gamestate"]["state"] == "playing"


def test_post_point_persists_to_disk(client):
    client.post("/api/points", json=VALID_PAYLOAD)

    on_disk = _read_state_file()
    assert on_disk["placed_points"] == [VALID_PAYLOAD]


def test_reset_persists_default_state_to_disk(client):
    client.patch("/api/gamestate", json={"round": 5, "state": "playing"})
    client.post("/api/points", json=VALID_PAYLOAD)

    client.post("/api/reset")

    on_disk = _read_state_file()
    assert on_disk["gamestate"] == {
        "state": "waiting",
        "round": 1,
        "jana_locked": False,
        "tobias_locked": False,
    }
    assert on_disk["placed_points"] == []


# --- Reload round-trips (simulating a server restart) -------------------


def test_reload_restores_gamestate_after_simulated_restart(client):
    client.patch("/api/gamestate", json={"round": 4, "state": "playing", "jana_locked": True})

    # Simulate the process restarting: wipe the in-memory copy, then load
    # exactly what a fresh import of game_state would do.
    with game_state._lock:
        game_state._gamestate.clear()
        game_state._gamestate.update(dict(game_state._DEFAULT_GAMESTATE))
        game_state._placed_points.clear()

    game_state.load_state_from_disk()

    assert game_state._gamestate == {
        "state": "playing",
        "round": 4,
        "jana_locked": True,
        "tobias_locked": False,
    }


def test_reload_restores_placed_points_for_multiple_rounds_and_players(client):
    client.post("/api/points", json=VALID_PAYLOAD)
    client.post("/api/points", json={**VALID_PAYLOAD, "round_number": 2, "placed_by": "jana"})
    client.post("/api/points", json={**VALID_PAYLOAD, "round_number": 3, "placed_by": "jana"})

    with game_state._lock:
        game_state._placed_points.clear()

    game_state.load_state_from_disk()

    assert game_state._placed_points[(2, "tobias")]["coordinates"] == VALID_PAYLOAD["coordinates"]
    assert game_state._placed_points[(2, "jana")]["round_number"] == 2
    assert game_state._placed_points[(3, "jana")]["round_number"] == 3
    assert len(game_state._placed_points) == 3


def test_reloaded_gamestate_is_served_over_the_api(client):
    client.patch("/api/gamestate", json={"round": 7})

    with game_state._lock:
        game_state._gamestate.update(dict(game_state._DEFAULT_GAMESTATE))
    game_state.load_state_from_disk()

    response = client.get("/api/gamestate")
    assert response.get_json()["round"] == 7


# --- Missing / corrupted / malformed files are handled gracefully -------


def test_load_with_no_file_present_keeps_defaults(tmp_path):
    game_state.STATE_FILE = str(tmp_path / "does_not_exist.json")

    game_state.load_state_from_disk()

    assert game_state._gamestate == game_state._DEFAULT_GAMESTATE
    assert game_state._placed_points == {}


def test_load_with_empty_state_file_path_is_a_noop(tmp_path):
    game_state.STATE_FILE = ""

    # Should not raise even though there is nothing to read.
    game_state.load_state_from_disk()

    assert game_state._gamestate == game_state._DEFAULT_GAMESTATE


def test_load_with_invalid_json_keeps_defaults(tmp_path):
    state_file = tmp_path / "corrupt.json"
    state_file.write_text("{not valid json::")
    game_state.STATE_FILE = str(state_file)

    game_state.load_state_from_disk()

    assert game_state._gamestate == game_state._DEFAULT_GAMESTATE
    assert game_state._placed_points == {}


def test_load_with_json_that_is_not_an_object_keeps_defaults(tmp_path):
    state_file = tmp_path / "list.json"
    state_file.write_text("[1, 2, 3]")
    game_state.STATE_FILE = str(state_file)

    game_state.load_state_from_disk()

    assert game_state._gamestate == game_state._DEFAULT_GAMESTATE


def test_load_with_invalid_gamestate_values_falls_back_to_defaults(tmp_path):
    state_file = tmp_path / "bad_values.json"
    state_file.write_text(
        json.dumps({"gamestate": {"state": "bogus", "round": 2, "jana_locked": False, "tobias_locked": False}})
    )
    game_state.STATE_FILE = str(state_file)

    game_state.load_state_from_disk()

    assert game_state._gamestate == game_state._DEFAULT_GAMESTATE


def test_load_with_incomplete_gamestate_falls_back_to_defaults(tmp_path):
    state_file = tmp_path / "incomplete.json"
    state_file.write_text(json.dumps({"gamestate": {"round": 9}}))
    game_state.STATE_FILE = str(state_file)

    game_state.load_state_from_disk()

    assert game_state._gamestate == game_state._DEFAULT_GAMESTATE


def test_load_with_malformed_placed_point_entries_skips_them(tmp_path):
    state_file = tmp_path / "bad_points.json"
    state_file.write_text(
        json.dumps(
            {
                "gamestate": game_state._DEFAULT_GAMESTATE,
                "placed_points": [
                    {"round_number": 1, "placed_by": "jana", "coordinates": {"lat": 1, "lng": 2}},
                    {"placed_by": "tobias", "coordinates": {"lat": 1, "lng": 2}},  # missing round_number
                    "not even a dict",
                ],
            }
        )
    )
    game_state.STATE_FILE = str(state_file)

    game_state.load_state_from_disk()

    assert list(game_state._placed_points.keys()) == [(1, "jana")]


# --- Disabled / unwritable persistence never breaks the request ---------


def test_persist_with_empty_state_file_is_a_noop(client):
    game_state.STATE_FILE = ""

    response = client.patch("/api/gamestate", json={"round": 2})

    assert response.status_code == 200
    assert response.get_json()["round"] == 2


def test_persist_creates_missing_parent_directories(client, tmp_path):
    game_state.STATE_FILE = str(tmp_path / "nested" / "dir" / "game_state.json")

    client.patch("/api/gamestate", json={"round": 2})

    on_disk = _read_state_file()
    assert on_disk["gamestate"]["round"] == 2


def test_persist_does_not_leave_temp_files_behind(client, tmp_path):
    game_state.STATE_FILE = str(tmp_path / "game_state.json")

    client.patch("/api/gamestate", json={"round": 2})
    client.post("/api/points", json=VALID_PAYLOAD)

    leftovers = [p for p in tmp_path.iterdir() if p.name != "game_state.json"]
    assert leftovers == []
