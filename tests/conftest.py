"""Shared pytest fixtures.

game_state.py keeps its data in module-level dicts (no database), so every
test gets a clean slate by resetting those dicts directly before it runs.

It also mirrors that state to a JSON file on disk (see game_state.STATE_FILE)
so a server restart doesn't lose the game. Tests must never touch the real
project file, and must not see state left behind by an earlier test, so
`isolate_state_file` points game_state.STATE_FILE at a fresh path under
pytest's per-test tmp_path for every test.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import game_state  # noqa: E402
import map_build  # noqa: E402
import photo_config  # noqa: E402
import photo_storage  # noqa: E402
from app import app as flask_app  # noqa: E402


@pytest.fixture
def app():
    flask_app.config.update(TESTING=True)
    return flask_app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture(autouse=True)
def isolate_state_file(tmp_path, monkeypatch):
    """Point persistence at a throwaway file so tests never touch the real
    game_state_data.json on disk or leak state between tests."""
    monkeypatch.setattr(game_state, "STATE_FILE", str(tmp_path / "game_state.json"))


def _reset_module_state():
    game_state._gamestate.update(
        {
            "state": "waiting",
            "round": 1,
            "player1_locked": False,
            "player2_locked": False,
        }
    )
    game_state._placed_points.clear()
    game_state._round_results.clear()
    game_state._player_config.clear()
    game_state._player_config.update(game_state._DEFAULT_PLAYER_CONFIG)
    game_state._round_config.clear()
    game_state._round_config.update(game_state._DEFAULT_ROUND_CONFIG)
    game_state._timer_state.clear()
    game_state._timer_state.update(game_state._DEFAULT_TIMER_STATE)
    game_state._theme_config.clear()
    game_state._theme_config.update(game_state._DEFAULT_THEME_CONFIG)
    game_state._map_labels_config.clear()
    game_state._map_labels_config.update(game_state._DEFAULT_MAP_LABELS_CONFIG)
    game_state._subscribers.clear()


@pytest.fixture(autouse=True)
def reset_game_state(isolate_state_file):
    """Give every test a fresh in-memory game state, and clean up after."""
    with game_state._lock:
        _reset_module_state()
    yield
    with game_state._lock:
        _reset_module_state()


def _reset_map_module_state():
    # Plain dict.update() would shallow-copy DEFAULT_MAP_CONFIG's "regions"
    # list and _fresh_build_status()'s "log_tail" list by reference, so a
    # naive reset here would keep leaking test-to-test - see
    # map_build._fresh_build_status's docstring for the same issue.
    map_build._map_config.clear()
    map_build._map_config.update(
        {**map_build.DEFAULT_MAP_CONFIG, "regions": [dict(r) for r in map_build.DEFAULT_MAP_CONFIG["regions"]]}
    )
    map_build._build_status.clear()
    map_build._build_status.update(map_build._fresh_build_status())


@pytest.fixture(autouse=True)
def isolate_map_config(tmp_path, monkeypatch):
    """Point map config persistence at a throwaway file, reset in-memory
    map config + build status before/after every test, and replace the
    real (multi-GB, network-heavy) build runner with a no-op fake so tests
    never accidentally invoke it."""
    monkeypatch.setattr(map_build, "MAP_CONFIG_FILE", str(tmp_path / "map_config.json"))
    monkeypatch.setattr(map_build, "_build_runner", map_build._default_runner)
    _reset_map_module_state()
    yield
    _reset_map_module_state()


@pytest.fixture(autouse=True)
def isolate_photo_storage(tmp_path, monkeypatch):
    """Point round-photo persistence and uploaded files at throwaway paths
    so tests never touch the real static/config/photos.json or
    static/photos/ - same convention as the other isolate_* fixtures."""
    monkeypatch.setattr(photo_config, "PHOTOS_FILE", str(tmp_path / "photos.json"))
    monkeypatch.setattr(photo_storage, "PHOTOS_DIR", str(tmp_path / "photos"))
