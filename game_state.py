"""In-memory game state + realtime push, replacing the PocketBase backend.

The game has no real user accounts (role is just a sessionStorage string
picked on the start screen), so this only needs to replicate the two
PocketBase collections the game actually reads/writes: `gamestate` (one
singleton record) and `placed_points` (one record per round+player).
Realtime sync happens over Server-Sent Events instead of PocketBase's
websocket subscriptions.

The two dicts below are the source of truth while the process is running,
but they are also mirrored to a JSON file on every change (see `_persist`)
so a server restart/crash doesn't wipe the current game. The file is
reloaded once at import time.
"""

import json
import logging
import os
import queue
import tempfile
import threading

from flask import Blueprint, Response, jsonify, request, stream_with_context

bp = Blueprint("api", __name__, url_prefix="/api")

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_subscribers = []

_DEFAULT_GAMESTATE = {
    "state": "waiting",
    "round": 1,
    "jana_locked": False,
    "tobias_locked": False,
}

# Where the game state is mirrored to disk. Overridable via env var (and, in
# tests, by assigning `game_state.STATE_FILE` directly) so test runs and
# alternate deployments don't fight over one shared file.
STATE_FILE = os.environ.get(
    "GAME_STATE_FILE",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "game_state.json"),
)

_gamestate = dict(_DEFAULT_GAMESTATE)

# keyed by (round_number, placed_by)
_placed_points = {}

_GAMESTATE_FIELDS = {"state", "round", "jana_locked", "tobias_locked"}
_VALID_STATES = {"waiting", "playing"}


def _broadcast(event, record):
    message = f"event: {event}\ndata: {json.dumps(record)}\n\n"
    with _lock:
        subscribers = list(_subscribers)
    for subscriber in subscribers:
        subscriber.put(message)


def _serialize_placed_points(points):
    return list(points.values())


def _deserialize_placed_points(records):
    result = {}
    for record in records:
        try:
            key = (record["round_number"], record["placed_by"])
        except (KeyError, TypeError):
            continue
        result[key] = record
    return result


def _persist_locked():
    """Write the current state to STATE_FILE. Caller must hold `_lock`.

    Persistence is best-effort: a write failure (e.g. read-only filesystem,
    disk full) is logged but never allowed to break the request that
    triggered it - the in-memory state stays authoritative either way.
    """
    if not STATE_FILE:
        return

    payload = {
        "gamestate": _gamestate,
        "placed_points": _serialize_placed_points(_placed_points),
    }

    directory = os.path.dirname(STATE_FILE) or "."
    tmp_path = None
    try:
        os.makedirs(directory, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(prefix=".game_state_", dir=directory)
        with os.fdopen(fd, "w") as f:
            json.dump(payload, f)
        os.replace(tmp_path, STATE_FILE)
    except OSError as e:
        logger.warning("Could not persist game state to %s: %s", STATE_FILE, e)
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


def load_state_from_disk():
    """Replace in-memory state with whatever is in STATE_FILE, if valid.

    Safe to call at any time (e.g. at import time, or explicitly from
    tests): a missing file, unreadable file, or file with corrupted/invalid
    contents is treated the same as "nothing to load" and leaves the
    current in-memory defaults untouched.
    """
    global _gamestate, _placed_points

    if not STATE_FILE or not os.path.isfile(STATE_FILE):
        return

    try:
        with open(STATE_FILE) as f:
            payload = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("Could not read persisted game state from %s: %s", STATE_FILE, e)
        return

    if not isinstance(payload, dict):
        logger.warning("Ignoring persisted game state: not a JSON object")
        return

    loaded_gamestate = payload.get("gamestate")
    if isinstance(loaded_gamestate, dict):
        known_updates = {k: v for k, v in loaded_gamestate.items() if k in _GAMESTATE_FIELDS}
        error = _validate_gamestate_updates(known_updates)
        if error is None and _GAMESTATE_FIELDS.issubset(known_updates):
            _gamestate = dict(known_updates)
        else:
            logger.warning(
                "Ignoring corrupted persisted gamestate in %s: %s",
                STATE_FILE,
                error or "missing fields",
            )

    loaded_points = payload.get("placed_points")
    if isinstance(loaded_points, list):
        _placed_points = _deserialize_placed_points(loaded_points)


@bp.route("/gamestate", methods=["GET"])
def get_gamestate():
    with _lock:
        return jsonify(_gamestate)


def _validate_gamestate_updates(updates):
    if "round" in updates:
        round_value = updates["round"]
        if isinstance(round_value, bool) or not isinstance(round_value, int) or round_value < 1:
            return "round must be a positive integer"

    if "state" in updates and updates["state"] not in _VALID_STATES:
        return f"state must be one of: {', '.join(sorted(_VALID_STATES))}"

    for lock_field in ("jana_locked", "tobias_locked"):
        if lock_field in updates and not isinstance(updates[lock_field], bool):
            return f"{lock_field} must be a boolean"

    return None


@bp.route("/gamestate", methods=["PATCH"])
def patch_gamestate():
    updates = request.get_json(force=True) or {}

    error = _validate_gamestate_updates(updates)
    if error:
        return jsonify({"error": error}), 400

    with _lock:
        for key, value in updates.items():
            if key in _GAMESTATE_FIELDS:
                _gamestate[key] = value
        record = dict(_gamestate)
        _persist_locked()
    _broadcast("gamestate", record)
    return jsonify(record)


@bp.route("/points", methods=["POST"])
def post_point():
    data = request.get_json(force=True) or {}
    round_number = data.get("round_number")
    placed_by = data.get("placed_by")
    coordinates = data.get("coordinates")

    if round_number is None or placed_by not in ("jana", "tobias") or not coordinates:
        return jsonify({"error": "invalid payload"}), 400

    record = {
        "round_number": round_number,
        "placed_by": placed_by,
        "coordinates": coordinates,
    }
    with _lock:
        _placed_points[(round_number, placed_by)] = record
        _persist_locked()

    _broadcast("placed_point", record)
    return jsonify(record), 201


@bp.route("/points/<int:round_number>", methods=["GET"])
def get_points(round_number):
    with _lock:
        records = [
            record
            for (recorded_round, _), record in _placed_points.items()
            if recorded_round == round_number
        ]
    return jsonify(records)


@bp.route("/reset", methods=["POST"])
def reset():
    with _lock:
        _gamestate.update(
            {
                "state": "waiting",
                "round": 1,
                "jana_locked": False,
                "tobias_locked": False,
            }
        )
        _placed_points.clear()
        record = dict(_gamestate)
        _persist_locked()
    _broadcast("gamestate", record)
    return jsonify(record)


@bp.route("/events")
def events():
    subscriber = queue.Queue()
    with _lock:
        _subscribers.append(subscriber)

    def stream():
        try:
            with _lock:
                snapshot = dict(_gamestate)
            yield f"event: gamestate\ndata: {json.dumps(snapshot)}\n\n"
            while True:
                try:
                    yield subscriber.get(timeout=15)
                except queue.Empty:
                    yield ": keep-alive\n\n"
        finally:
            with _lock:
                if subscriber in _subscribers:
                    _subscribers.remove(subscriber)

    return Response(
        stream_with_context(stream()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# Recover whatever game was in progress before the process last exited.
load_state_from_disk()
