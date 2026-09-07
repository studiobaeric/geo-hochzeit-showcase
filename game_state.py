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
import sys
import tempfile
import threading
import time

from flask import Blueprint, Response, jsonify, request, stream_with_context

import photo_config
import photo_storage

bp = Blueprint("api", __name__, url_prefix="/api")

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_subscribers = []

_DEFAULT_GAMESTATE = {
    "state": "waiting",
    "round": 1,
    "player1_locked": False,
    "player2_locked": False,
}

# Display names + profile photos shown in the UI, editable at runtime via
# the config menu (/config -> PATCH /api/player-config, POST
# /api/player-config/photo/<role>). The "player1"/"player2" role keys
# themselves stay fixed - only the human-readable labels and photo
# filenames change. An empty photo string means "no custom photo uploaded
# yet" - the frontend then falls back to static/config/players.js's
# PHOTO_1/PHOTO_2.
#
# *_photo is a downscaled/recompressed copy (used everywhere - the player
# badges are small), *_photo_hq is the untouched original upload, used only
# by the moderator's screen (projected via beamer, so it needs full
# quality). Only upload_player_photo() below ever sets the _hq fields -
# they're not accepted through the plain PATCH endpoint.
_DEFAULT_PLAYER_CONFIG = {
    "player1_name": "player1",
    "player2_name": "player2",
    "player1_photo": "",
    "player2_photo": "",
    "player1_photo_hq": "",
    "player2_photo_hq": "",
}

_MAX_PLAYER_NAME_LENGTH = 40

# Per-round timeframe settings, editable at runtime via the config menu
# (/config -> PATCH /api/round-config). "manual" leaves round timing
# entirely to the moderator (the pre-existing behavior); "countdown" turns
# on the moderator's time-control panel and the synced player countdown.
# extend_seconds is how much the moderator's "+Xs" button on the timer
# panel adds per click (see /api/timer/extend).
_DEFAULT_ROUND_CONFIG = {
    "mode": "manual",
    "duration_seconds": 60,
    "extend_seconds": 30,
}

_ROUND_MODES = {"manual", "countdown"}
_MIN_ROUND_DURATION = 5
_MAX_ROUND_DURATION = 3600

# Light/dark color theme, editable at runtime via the config menu
# (/config -> PATCH /api/theme-config). Stored server-side (rather than in
# each browser's localStorage) so a change made on one device applies to
# every device, per #18.
_DEFAULT_THEME_CONFIG = {
    "mode": "dark",
}

_THEME_MODES = {"light", "dark"}

# UI language, editable at runtime via the config menu (/config -> PATCH
# /api/locale-config), per #98. Stored server-side like theme_config so a
# choice made on one device (e.g. the moderator's laptop) applies to every
# connected screen. "de" is the reference locale that every template/JS
# string is authored in first - see static/i18n/de.json - with other
# locales (currently just "en") added as complete key-for-key translations
# of it; a key missing from a non-German file falls back to German rather
# than breaking the UI (see i18n.py).
_DEFAULT_LOCALE_CONFIG = {
    "locale": "de",
}

_SUPPORTED_LOCALES = {"de", "en"}

# Whether the offline basemap hides place-name labels (settlement/region/
# country names), editable at runtime via the config menu (/config -> PATCH
# /api/map-labels-config), per #38. This only toggles which layers of the
# already-downloaded basemap-style.json are rendered - see
# static/js/basemap.js's applyPlaceLabelVisibility - no new map data needs
# to be built or downloaded for it.
_DEFAULT_MAP_LABELS_CONFIG = {
    "hide_city_labels": False,
}

# How a round's distance-to-target is turned into points, editable at
# runtime via the config menu (/config -> PATCH /api/scoring-config), per
# #127. The server only stores/validates these settings - the actual
# algorithms live in static/js/scoring-config.js's calculateRoundPoints(),
# since that's where a placed guess's distance is already computed
# (moderator.js).
_DEFAULT_SCORING_CONFIG = {
    "algorithm": "exponential",
    "max_points": 1000,
    "min_points": 100,
    "perfect_radius_meters": 500,
    "distance_scale_meters": 100000,
    "max_distance_meters": 20000,
}

_SCORING_ALGORITHMS = {"exponential", "linear", "step"}
_MIN_SCORING_POINTS = 0
_MAX_SCORING_POINTS = 1_000_000
_MIN_SCORING_DISTANCE = 1
_MAX_SCORING_DISTANCE = 20_000_000  # generous upper bound; well past Earth's ~20,000km half-circumference

# Live state of the current round's countdown. Unlike _round_config (a
# durable setting), this is transient per-round state: it resets to
# "not running" on every round advance, game reset, and server restart -
# a stale countdown from before a restart would be meaningless anyway,
# and the moderator is expected to press Start again.
_DEFAULT_TIMER_STATE = {
    "running": False,
    "paused": False,
    "ends_at": None,  # epoch seconds (server clock); authoritative while running and not paused
    "remaining_seconds": None,  # seconds left; authoritative while paused
}

_MIN_EXTEND_SECONDS = 1
_MAX_EXTEND_SECONDS = 600

# Released binaries (see tools/build_release.py) ship this module frozen
# into the executable, so __file__ resolves inside PyInstaller's onefile
# temp extraction dir rather than next to the actual executable - mirrors
# app.py's frozen-path handling (see there for details). Without this, the
# persisted game_state.json would be written into that temp dir, which
# PyInstaller wipes on exit, so the game state would never actually survive
# a restart of the packaged binary.
if getattr(sys, "frozen", False):
    _PROJECT_ROOT = os.path.dirname(sys.executable)
else:
    _PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

# Where the game state is mirrored to disk. Overridable via env var (and, in
# tests, by assigning `game_state.STATE_FILE` directly) so test runs and
# alternate deployments don't fight over one shared file.
STATE_FILE = os.environ.get(
    "GAME_STATE_FILE",
    os.path.join(_PROJECT_ROOT, "data", "game_state.json"),
)

_gamestate = dict(_DEFAULT_GAMESTATE)
_player_config = dict(_DEFAULT_PLAYER_CONFIG)
_round_config = dict(_DEFAULT_ROUND_CONFIG)
_timer_state = dict(_DEFAULT_TIMER_STATE)
_theme_config = dict(_DEFAULT_THEME_CONFIG)
_map_labels_config = dict(_DEFAULT_MAP_LABELS_CONFIG)
_scoring_config = dict(_DEFAULT_SCORING_CONFIG)
_locale_config = dict(_DEFAULT_LOCALE_CONFIG)

# keyed by (round_number, placed_by)
_placed_points = {}

# keyed by round_number
_round_results = {}

_GAMESTATE_FIELDS = {"state", "round", "player1_locked", "player2_locked"}
# "finished" is broadcast once the moderator advances past the last round -
# see multiplayer.js's finishGame() - so players' /game pages know to
# navigate to /results instead of waiting for a round that never comes.
_VALID_STATES = {"waiting", "playing", "finished"}
_PLAYER_ROLES = {"player1", "player2"}


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


def _serialize_round_results(round_results):
    return sorted(round_results.values(), key=lambda record: record["round_number"])


def _deserialize_round_results(records):
    result = {}
    for record in records:
        try:
            round_number = record["round_number"]
            players = record["players"]
        except (KeyError, TypeError):
            continue
        if not isinstance(round_number, int) or not isinstance(players, dict):
            continue
        result[round_number] = {"round_number": round_number, "players": players}
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
        "round_results": _serialize_round_results(_round_results),
        "player_config": _player_config,
        "round_config": _round_config,
        "timer_state": _timer_state,
        "theme_config": _theme_config,
        "map_labels_config": _map_labels_config,
        "scoring_config": _scoring_config,
        "locale_config": _locale_config,
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
    global _gamestate, _placed_points, _round_results, _player_config, _round_config, _timer_state, _theme_config, _map_labels_config, _scoring_config, _locale_config

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

    loaded_round_results = payload.get("round_results")
    if isinstance(loaded_round_results, list):
        _round_results = _deserialize_round_results(loaded_round_results)

    loaded_player_config = payload.get("player_config")
    if isinstance(loaded_player_config, dict):
        known_config = {k: v for k, v in loaded_player_config.items() if k in _DEFAULT_PLAYER_CONFIG}
        error = _validate_player_config_updates(known_config)
        if error is None:
            # Missing fields (e.g. player1_photo/player2_photo in a state
            # file written before photo uploads existed) fall back to their
            # default rather than discarding the whole record - an older
            # file must not silently reset player names that were already
            # customized.
            _player_config = {**_DEFAULT_PLAYER_CONFIG, **known_config}
        else:
            logger.warning(
                "Ignoring corrupted persisted player_config in %s: %s",
                STATE_FILE,
                error or "invalid fields",
            )

    loaded_round_config = payload.get("round_config")
    if isinstance(loaded_round_config, dict):
        known_round_config = {k: v for k, v in loaded_round_config.items() if k in _DEFAULT_ROUND_CONFIG}
        error = _validate_round_config_updates(known_round_config)
        if error is None and _DEFAULT_ROUND_CONFIG.keys() == known_round_config.keys():
            _round_config = dict(known_round_config)
        else:
            logger.warning(
                "Ignoring corrupted persisted round_config in %s: %s",
                STATE_FILE,
                error or "missing fields",
            )

    loaded_theme_config = payload.get("theme_config")
    if isinstance(loaded_theme_config, dict):
        known_theme_config = {k: v for k, v in loaded_theme_config.items() if k in _DEFAULT_THEME_CONFIG}
        error = _validate_theme_config_updates(known_theme_config)
        if error is None and _DEFAULT_THEME_CONFIG.keys() == known_theme_config.keys():
            _theme_config = dict(known_theme_config)
        else:
            logger.warning(
                "Ignoring corrupted persisted theme_config in %s: %s",
                STATE_FILE,
                error or "missing fields",
            )

    loaded_map_labels_config = payload.get("map_labels_config")
    if isinstance(loaded_map_labels_config, dict):
        known_map_labels_config = {
            k: v for k, v in loaded_map_labels_config.items() if k in _DEFAULT_MAP_LABELS_CONFIG
        }
        error = _validate_map_labels_config_updates(known_map_labels_config)
        if error is None and _DEFAULT_MAP_LABELS_CONFIG.keys() == known_map_labels_config.keys():
            _map_labels_config = dict(known_map_labels_config)
        else:
            logger.warning(
                "Ignoring corrupted persisted map_labels_config in %s: %s",
                STATE_FILE,
                error or "missing fields",
            )

    loaded_scoring_config = payload.get("scoring_config")
    if isinstance(loaded_scoring_config, dict):
        known_scoring_config = {k: v for k, v in loaded_scoring_config.items() if k in _DEFAULT_SCORING_CONFIG}
        error = _validate_scoring_config_updates(known_scoring_config)
        if error is None and _DEFAULT_SCORING_CONFIG.keys() == known_scoring_config.keys():
            _scoring_config = dict(known_scoring_config)
        else:
            logger.warning(
                "Ignoring corrupted persisted scoring_config in %s: %s",
                STATE_FILE,
                error or "missing fields",
            )

    loaded_locale_config = payload.get("locale_config")
    if isinstance(loaded_locale_config, dict):
        known_locale_config = {k: v for k, v in loaded_locale_config.items() if k in _DEFAULT_LOCALE_CONFIG}
        error = _validate_locale_config_updates(known_locale_config)
        if error is None and _DEFAULT_LOCALE_CONFIG.keys() == known_locale_config.keys():
            _locale_config = dict(known_locale_config)
        else:
            logger.warning(
                "Ignoring corrupted persisted locale_config in %s: %s",
                STATE_FILE,
                error or "missing fields",
            )

    # The timer's running state is intentionally not restored from disk - a
    # countdown that survives a process restart could point at an ends_at
    # far in the past. Every restart starts with a fresh, stopped timer
    # (_DEFAULT_TIMER_STATE, already the in-memory default).


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

    for lock_field in ("player1_locked", "player2_locked"):
        if lock_field in updates and not isinstance(updates[lock_field], bool):
            return f"{lock_field} must be a boolean"

    return None


def _validate_round_result(data):
    round_number = data.get("round_number")
    if isinstance(round_number, bool) or not isinstance(round_number, int) or round_number < 1:
        return "round_number must be a positive integer"

    players = data.get("players")
    if not isinstance(players, dict) or set(players.keys()) != _PLAYER_ROLES:
        return f"players must contain exactly: {', '.join(sorted(_PLAYER_ROLES))}"

    for role, result in players.items():
        if not isinstance(result, dict):
            return f"players.{role} must be an object"

        points = result.get("points")
        if isinstance(points, bool) or not isinstance(points, (int, float)) or points < 0:
            return f"players.{role}.points must be a non-negative number"

        distance = result.get("distance")
        if distance is not None and (
            isinstance(distance, bool) or not isinstance(distance, (int, float)) or distance < 0
        ):
            return f"players.{role}.distance must be a non-negative number or null"

        marker_location = result.get("markerLocation")
        if marker_location is not None and (
            not isinstance(marker_location, list)
            or len(marker_location) != 2
            or any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in marker_location)
        ):
            return f"players.{role}.markerLocation must be [lat, lng] or null"

    return None


@bp.route("/gamestate", methods=["PATCH"])
def patch_gamestate():
    updates = request.get_json(force=True) or {}

    error = _validate_gamestate_updates(updates)
    if error:
        return jsonify({"error": error}), 400

    with _lock:
        round_changed = "round" in updates and updates["round"] != _gamestate.get("round")
        for key, value in updates.items():
            if key in _GAMESTATE_FIELDS:
                _gamestate[key] = value
        record = dict(_gamestate)

        # A new round always starts with a fresh, stopped timer - the
        # moderator presses Start again rather than inheriting whatever was
        # left running/paused from the previous round.
        timer_record = None
        if round_changed:
            _timer_state.update(dict(_DEFAULT_TIMER_STATE))
            timer_record = _timer_record_locked()

        _persist_locked()
    _broadcast("gamestate", record)
    if timer_record is not None:
        _broadcast("timer", timer_record)
    return jsonify(record)


_PLAYER_NAME_FIELDS = ("player1_name", "player2_name")
_PLAYER_PHOTO_FIELDS = ("player1_photo", "player2_photo")


def _validate_player_config_updates(updates):
    for field in _PLAYER_NAME_FIELDS:
        if field in updates:
            value = updates[field]
            if not isinstance(value, str) or not value.strip():
                return f"{field} must be a non-empty string"
            if len(value.strip()) > _MAX_PLAYER_NAME_LENGTH:
                return f"{field} must be at most {_MAX_PLAYER_NAME_LENGTH} characters"

    for field in _PLAYER_PHOTO_FIELDS:
        if field in updates and not isinstance(updates[field], str):
            return f"{field} must be a string"

    return None


# The fallback profile-photo filenames static/config/players.js's
# PHOTO_1/PHOTO_2 point at before any photo has been uploaded through the
# config menu (see the module docstring's note on player1_photo/
# player2_photo's empty-string default). Mirrored here - same convention as
# photo_config._DEFAULT_ROUND_PHOTOS - so _remove_photo_file() never
# deletes them, no matter what a client sets player1_photo/player2_photo
# to; they must stay on disk to be usable as a fallback.
_DEFAULT_PLAYER_PHOTO_FILENAMES = {"picture_of_player1.jpg", "picture_of_player2.jpg"}


def _remove_photo_file(filename):
    """Best-effort delete of a previously-uploaded photo from PHOTOS_DIR.

    Never raises - called after a player photo is replaced or reset, so a
    missing/already-gone file (or a locked one on Windows) must not break
    the request that triggered it. Never deletes one of the shipped
    default profile photos (_DEFAULT_PLAYER_PHOTO_FILENAMES) either.
    """
    if filename in _DEFAULT_PLAYER_PHOTO_FILENAMES:
        return
    path = os.path.join(photo_storage.PHOTOS_DIR, filename)
    try:
        os.remove(path)
    except OSError as e:
        logger.warning("Could not remove photo file %s: %s", path, e)


@bp.route("/player-config", methods=["GET"])
def get_player_config():
    with _lock:
        return jsonify(_player_config)


@bp.route("/player-config", methods=["PATCH"])
def patch_player_config():
    updates = request.get_json(force=True) or {}

    error = _validate_player_config_updates(updates)
    if error:
        return jsonify({"error": error}), 400

    files_to_remove = []
    with _lock:
        for key, value in updates.items():
            if key in _PLAYER_NAME_FIELDS:
                _player_config[key] = value.strip()
            elif key in _PLAYER_PHOTO_FIELDS:
                old_value = _player_config[key]
                _player_config[key] = value
                if not value:
                    # Resetting the default photo should also drop the
                    # matching hq copy and delete both files - otherwise the
                    # moderator screen would keep showing the old upload
                    # after a reset, and the files would linger on disk.
                    hq_key = f"{key}_hq"
                    old_hq = _player_config[hq_key]
                    _player_config[hq_key] = ""
                    files_to_remove += [f for f in (old_value, old_hq) if f]
        record = dict(_player_config)
        _persist_locked()

    for filename in files_to_remove:
        _remove_photo_file(filename)
    _broadcast("player_config", record)
    return jsonify(record)


@bp.route("/player-config/photo/<role>", methods=["POST"])
def upload_player_photo(role):
    if role not in _PLAYER_ROLES:
        return jsonify({"error": f"role must be one of: {', '.join(sorted(_PLAYER_ROLES))}"}), 400

    try:
        filename, filename_hq = photo_storage.save_upload_with_hq(request.files.get("photo"), prefix=role)
    except photo_storage.UploadError as e:
        return jsonify({"error": str(e)}), 400

    with _lock:
        old_filename = _player_config[f"{role}_photo"]
        old_filename_hq = _player_config[f"{role}_photo_hq"]
        _player_config[f"{role}_photo"] = filename
        _player_config[f"{role}_photo_hq"] = filename_hq
        record = dict(_player_config)
        _persist_locked()

    # Replacing a photo shouldn't leave the previous upload's files behind.
    for old in (old_filename, old_filename_hq):
        if old:
            _remove_photo_file(old)
    _broadcast("player_config", record)
    return jsonify(record), 201


def _validate_round_config_updates(updates):
    if "mode" in updates and updates["mode"] not in _ROUND_MODES:
        return f"mode must be one of: {', '.join(sorted(_ROUND_MODES))}"

    if "duration_seconds" in updates:
        value = updates["duration_seconds"]
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or value < _MIN_ROUND_DURATION
            or value > _MAX_ROUND_DURATION
        ):
            return (
                f"duration_seconds must be an integer between "
                f"{_MIN_ROUND_DURATION} and {_MAX_ROUND_DURATION}"
            )

    if "extend_seconds" in updates:
        value = updates["extend_seconds"]
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or value < _MIN_EXTEND_SECONDS
            or value > _MAX_EXTEND_SECONDS
        ):
            return (
                f"extend_seconds must be an integer between "
                f"{_MIN_EXTEND_SECONDS} and {_MAX_EXTEND_SECONDS}"
            )

    return None


@bp.route("/round-config", methods=["GET"])
def get_round_config():
    with _lock:
        return jsonify(_round_config)


@bp.route("/round-config", methods=["PATCH"])
def patch_round_config():
    updates = request.get_json(force=True) or {}

    error = _validate_round_config_updates(updates)
    if error:
        return jsonify({"error": error}), 400

    with _lock:
        for key, value in updates.items():
            if key in _DEFAULT_ROUND_CONFIG:
                _round_config[key] = value
        record = dict(_round_config)
        _persist_locked()
    _broadcast("round_config", record)
    return jsonify(record)


def _validate_theme_config_updates(updates):
    if "mode" in updates and updates["mode"] not in _THEME_MODES:
        return f"mode must be one of: {', '.join(sorted(_THEME_MODES))}"

    return None


@bp.route("/theme-config", methods=["GET"])
def get_theme_config():
    with _lock:
        return jsonify(_theme_config)


@bp.route("/theme-config", methods=["PATCH"])
def patch_theme_config():
    updates = request.get_json(force=True) or {}

    error = _validate_theme_config_updates(updates)
    if error:
        return jsonify({"error": error}), 400

    with _lock:
        for key, value in updates.items():
            if key in _DEFAULT_THEME_CONFIG:
                _theme_config[key] = value
        record = dict(_theme_config)
        _persist_locked()
    _broadcast("theme_config", record)
    return jsonify(record)


def _validate_locale_config_updates(updates):
    if "locale" in updates and updates["locale"] not in _SUPPORTED_LOCALES:
        return f"locale must be one of: {', '.join(sorted(_SUPPORTED_LOCALES))}"

    return None


def get_locale():
    """Current UI locale, for app.py's Jinja context processor. Doesn't
    need `_lock`: reading a dict's existing string value is atomic under
    the GIL, and this is called on every page render so taking the lock
    for it would be needless contention."""
    return _locale_config["locale"]


@bp.route("/locale-config", methods=["GET"])
def get_locale_config():
    with _lock:
        return jsonify(_locale_config)


@bp.route("/locale-config", methods=["PATCH"])
def patch_locale_config():
    updates = request.get_json(force=True) or {}

    error = _validate_locale_config_updates(updates)
    if error:
        return jsonify({"error": error}), 400

    with _lock:
        for key, value in updates.items():
            if key in _DEFAULT_LOCALE_CONFIG:
                _locale_config[key] = value
        record = dict(_locale_config)
        _persist_locked()
    _broadcast("locale_config", record)
    return jsonify(record)


def _validate_map_labels_config_updates(updates):
    if "hide_city_labels" in updates and not isinstance(updates["hide_city_labels"], bool):
        return "hide_city_labels must be a boolean"

    return None


@bp.route("/map-labels-config", methods=["GET"])
def get_map_labels_config():
    with _lock:
        return jsonify(_map_labels_config)


@bp.route("/map-labels-config", methods=["PATCH"])
def patch_map_labels_config():
    updates = request.get_json(force=True) or {}

    error = _validate_map_labels_config_updates(updates)
    if error:
        return jsonify({"error": error}), 400

    with _lock:
        for key, value in updates.items():
            if key in _DEFAULT_MAP_LABELS_CONFIG:
                _map_labels_config[key] = value
        record = dict(_map_labels_config)
        _persist_locked()
    _broadcast("map_labels_config", record)
    return jsonify(record)


def _validate_scoring_config_updates(updates):
    if "algorithm" in updates and updates["algorithm"] not in _SCORING_ALGORITHMS:
        return f"algorithm must be one of: {', '.join(sorted(_SCORING_ALGORITHMS))}"

    for field in ("max_points", "min_points"):
        if field in updates:
            value = updates[field]
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < _MIN_SCORING_POINTS
                or value > _MAX_SCORING_POINTS
            ):
                return f"{field} must be an integer between {_MIN_SCORING_POINTS} and {_MAX_SCORING_POINTS}"

    for field in ("perfect_radius_meters", "distance_scale_meters", "max_distance_meters"):
        if field in updates:
            value = updates[field]
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < _MIN_SCORING_DISTANCE
                or value > _MAX_SCORING_DISTANCE
            ):
                return f"{field} must be an integer between {_MIN_SCORING_DISTANCE} and {_MAX_SCORING_DISTANCE}"

    merged = {**_scoring_config, **updates}
    if merged["min_points"] > merged["max_points"]:
        return "min_points must not be greater than max_points"
    if merged["max_distance_meters"] <= merged["perfect_radius_meters"]:
        return "max_distance_meters must be greater than perfect_radius_meters"

    return None


@bp.route("/scoring-config", methods=["GET"])
def get_scoring_config():
    with _lock:
        return jsonify(_scoring_config)


@bp.route("/scoring-config", methods=["PATCH"])
def patch_scoring_config():
    updates = request.get_json(force=True) or {}

    error = _validate_scoring_config_updates(updates)
    if error:
        return jsonify({"error": error}), 400

    with _lock:
        for key, value in updates.items():
            if key in _DEFAULT_SCORING_CONFIG:
                _scoring_config[key] = value
        record = dict(_scoring_config)
        _persist_locked()
    _broadcast("scoring_config", record)
    return jsonify(record)


@bp.route("/points", methods=["POST"])
def post_point():
    data = request.get_json(force=True) or {}
    round_number = data.get("round_number")
    placed_by = data.get("placed_by")
    coordinates = data.get("coordinates")

    if round_number is None or placed_by not in _PLAYER_ROLES or not coordinates:
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


@bp.route("/round_result", methods=["POST"])
def post_round_result():
    data = request.get_json(force=True) or {}

    error = _validate_round_result(data)
    if error:
        return jsonify({"error": error}), 400

    record = {"round_number": data["round_number"], "players": data["players"]}
    with _lock:
        _round_results[record["round_number"]] = record
        _persist_locked()

    return jsonify(record), 201


@bp.route("/round_results", methods=["GET"])
def get_round_results():
    with _lock:
        records = _serialize_round_results(_round_results)
    return jsonify(records)


def _timer_record_locked():
    """Snapshot of `_timer_state` plus the server's current clock reading.

    `ends_at`/`remaining_seconds` are only meaningful relative to the
    server's own clock. Clients compute their own countdown display from
    them, so without a shared reference point a client whose system clock
    drifts from the server's - or a phone that's just plain wrong - shows a
    countdown that starts already off and disagrees with when the
    moderator (who drives round-end off their own clock) actually ends the
    round (#71). Sending `server_time` with every timer record lets each
    client compute its own offset and correct for it. Caller must hold
    `_lock`.
    """
    record = dict(_timer_state)
    record["server_time"] = time.time()
    return record


@bp.route("/timer", methods=["GET"])
def get_timer_state():
    with _lock:
        return jsonify(_timer_record_locked())


@bp.route("/timer/start", methods=["POST"])
def start_timer():
    with _lock:
        if _round_config["mode"] != "countdown":
            return jsonify({"error": "timer is only available in countdown mode"}), 400

        _timer_state.update(
            {
                "running": True,
                "paused": False,
                "ends_at": time.time() + _round_config["duration_seconds"],
                "remaining_seconds": None,
            }
        )
        record = _timer_record_locked()
        _persist_locked()
    _broadcast("timer", record)
    return jsonify(record)


@bp.route("/timer/pause", methods=["POST"])
def pause_timer():
    with _lock:
        if not _timer_state["running"] or _timer_state["paused"]:
            return jsonify({"error": "timer is not running or already paused"}), 400

        remaining = max(0.0, _timer_state["ends_at"] - time.time())
        _timer_state.update({"paused": True, "ends_at": None, "remaining_seconds": remaining})
        record = _timer_record_locked()
        _persist_locked()
    _broadcast("timer", record)
    return jsonify(record)


@bp.route("/timer/resume", methods=["POST"])
def resume_timer():
    with _lock:
        if not _timer_state["running"] or not _timer_state["paused"]:
            return jsonify({"error": "timer is not paused"}), 400

        _timer_state.update(
            {
                "paused": False,
                "ends_at": time.time() + (_timer_state["remaining_seconds"] or 0),
                "remaining_seconds": None,
            }
        )
        record = _timer_record_locked()
        _persist_locked()
    _broadcast("timer", record)
    return jsonify(record)


@bp.route("/timer/extend", methods=["POST"])
def extend_timer():
    data = request.get_json(force=True) or {}
    seconds = data.get("seconds")

    if (
        isinstance(seconds, bool)
        or not isinstance(seconds, int)
        or seconds < _MIN_EXTEND_SECONDS
        or seconds > _MAX_EXTEND_SECONDS
    ):
        return (
            jsonify(
                {
                    "error": (
                        f"seconds must be an integer between "
                        f"{_MIN_EXTEND_SECONDS} and {_MAX_EXTEND_SECONDS}"
                    )
                }
            ),
            400,
        )

    with _lock:
        if not _timer_state["running"]:
            return jsonify({"error": "timer is not running"}), 400

        if _timer_state["paused"]:
            _timer_state["remaining_seconds"] = (_timer_state["remaining_seconds"] or 0) + seconds
        else:
            _timer_state["ends_at"] = (_timer_state["ends_at"] or time.time()) + seconds
        record = _timer_record_locked()
        _persist_locked()
    _broadcast("timer", record)
    return jsonify(record)


@bp.route("/timer/stop", methods=["POST"])
def stop_timer():
    with _lock:
        _timer_state.update(dict(_DEFAULT_TIMER_STATE))
        record = _timer_record_locked()
        _persist_locked()
    _broadcast("timer", record)
    return jsonify(record)


@bp.route("/reset", methods=["POST"])
def reset():
    with _lock:
        _gamestate.update(
            {
                "state": "waiting",
                "round": 1,
                "player1_locked": False,
                "player2_locked": False,
            }
        )
        _placed_points.clear()
        _round_results.clear()
        _timer_state.update(dict(_DEFAULT_TIMER_STATE))
        record = dict(_gamestate)
        timer_record = _timer_record_locked()
        _persist_locked()
    _broadcast("gamestate", record)
    _broadcast("timer", timer_record)
    return jsonify(record)


def reset_to_defaults():
    """Reset game progress, player names/photos and round-timing config back
    to their out-of-the-box defaults, and persist the result.

    Unlike the `/api/reset` endpoint above (which only clears the current
    round's progress so the moderator can restart play), this also wipes
    player_config/round_config - used by tools/reset_state.py to prep the
    whole system for a new event rather than just a new round. Returns the
    player_config that was in effect before the reset, so the caller can
    clean up any uploaded photo files it referenced (this function only
    removes the *_photo/_hq files it itself clears via patch_player_config's
    file-cleanup convention).
    """
    with _lock:
        previous_player_config = dict(_player_config)
        _gamestate.update(dict(_DEFAULT_GAMESTATE))
        _placed_points.clear()
        _round_results.clear()
        _timer_state.update(dict(_DEFAULT_TIMER_STATE))
        _player_config.clear()
        _player_config.update(_DEFAULT_PLAYER_CONFIG)
        _round_config.clear()
        _round_config.update(_DEFAULT_ROUND_CONFIG)
        gamestate_record = dict(_gamestate)
        timer_record = _timer_record_locked()
        player_config_record = dict(_player_config)
        round_config_record = dict(_round_config)
        _persist_locked()

    for key in _PLAYER_PHOTO_FIELDS:
        hq_key = f"{key}_hq"
        for filename in (previous_player_config.get(key), previous_player_config.get(hq_key)):
            if filename:
                _remove_photo_file(filename)

    _broadcast("gamestate", gamestate_record)
    _broadcast("timer", timer_record)
    _broadcast("player_config", player_config_record)
    _broadcast("round_config", round_config_record)
    return previous_player_config


@bp.route("/reset-to-defaults", methods=["POST"])
def reset_to_defaults_endpoint():
    """HTTP counterpart of reset_to_defaults() + photo_config.clear_round_
    photos(), so tools/reset_state.py can reset an already-running server
    over its own API instead of only editing files on disk.

    A file-only reset leaves a running server's in-memory state stale
    (game_state.py loads player_config/round_config/gamestate from disk
    only once, at import time) - it would keep serving old data, including
    photo filenames the reset just deleted from disk, until restarted. This
    runs the exact same reset function calls, just inside this process, so
    the change is live immediately: the in-memory state updates, gets
    persisted, and the *_config broadcasts above reach every connected
    client the same way any other config change does.
    """
    previous_player_config = reset_to_defaults()
    round_photos_removed = photo_config.clear_round_photos()
    return jsonify(
        {
            "previous_player_config": previous_player_config,
            "round_photos_removed": round_photos_removed,
        }
    )


@bp.route("/events")
def events():
    subscriber = queue.Queue()
    with _lock:
        _subscribers.append(subscriber)

    def stream():
        try:
            with _lock:
                snapshot = dict(_gamestate)
                config_snapshot = dict(_player_config)
                round_config_snapshot = dict(_round_config)
                timer_snapshot = _timer_record_locked()
                theme_snapshot = dict(_theme_config)
                map_labels_snapshot = dict(_map_labels_config)
                scoring_snapshot = dict(_scoring_config)
                locale_snapshot = dict(_locale_config)
            yield f"event: gamestate\ndata: {json.dumps(snapshot)}\n\n"
            yield f"event: player_config\ndata: {json.dumps(config_snapshot)}\n\n"
            yield f"event: round_config\ndata: {json.dumps(round_config_snapshot)}\n\n"
            yield f"event: timer\ndata: {json.dumps(timer_snapshot)}\n\n"
            yield f"event: theme_config\ndata: {json.dumps(theme_snapshot)}\n\n"
            yield f"event: map_labels_config\ndata: {json.dumps(map_labels_snapshot)}\n\n"
            yield f"event: scoring_config\ndata: {json.dumps(scoring_snapshot)}\n\n"
            yield f"event: locale_config\ndata: {json.dumps(locale_snapshot)}\n\n"
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
