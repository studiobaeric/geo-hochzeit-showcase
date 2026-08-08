"""In-memory game state + realtime push, replacing the PocketBase backend.

The game has no real user accounts (role is just a sessionStorage string
picked on the start screen), so this only needs to replicate the two
PocketBase collections the game actually reads/writes: `gamestate` (one
singleton record) and `placed_points` (one record per round+player).
Realtime sync happens over Server-Sent Events instead of PocketBase's
websocket subscriptions.
"""

import json
import queue
import threading

from flask import Blueprint, Response, jsonify, request, stream_with_context

bp = Blueprint("api", __name__, url_prefix="/api")

_lock = threading.Lock()
_subscribers = []

_gamestate = {
    "state": "waiting",
    "round": 1,
    "jana_locked": False,
    "tobias_locked": False,
}

# keyed by (round_number, placed_by)
_placed_points = {}

_GAMESTATE_FIELDS = {"state", "round", "jana_locked", "tobias_locked"}


def _broadcast(event, record):
    message = f"event: {event}\ndata: {json.dumps(record)}\n\n"
    with _lock:
        subscribers = list(_subscribers)
    for subscriber in subscribers:
        subscriber.put(message)


@bp.route("/gamestate", methods=["GET"])
def get_gamestate():
    with _lock:
        return jsonify(_gamestate)


@bp.route("/gamestate", methods=["PATCH"])
def patch_gamestate():
    updates = request.get_json(force=True) or {}
    with _lock:
        for key, value in updates.items():
            if key in _GAMESTATE_FIELDS:
                _gamestate[key] = value
        record = dict(_gamestate)
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

    _broadcast("placed_point", record)
    return jsonify(record), 201


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
