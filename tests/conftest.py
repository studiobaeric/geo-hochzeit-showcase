"""Shared pytest fixtures.

game_state.py keeps its data in module-level dicts (no database), so every
test gets a clean slate by resetting those dicts directly before it runs.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import game_state  # noqa: E402
from app import app as flask_app  # noqa: E402


@pytest.fixture
def app():
    flask_app.config.update(TESTING=True)
    return flask_app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture(autouse=True)
def reset_game_state():
    """Give every test a fresh in-memory game state, and clean up after."""
    with game_state._lock:
        game_state._gamestate.update(
            {
                "state": "waiting",
                "round": 1,
                "jana_locked": False,
                "tobias_locked": False,
            }
        )
        game_state._placed_points.clear()
        game_state._subscribers.clear()
    yield
    with game_state._lock:
        game_state._gamestate.update(
            {
                "state": "waiting",
                "round": 1,
                "jana_locked": False,
                "tobias_locked": False,
            }
        )
        game_state._placed_points.clear()
        game_state._subscribers.clear()
