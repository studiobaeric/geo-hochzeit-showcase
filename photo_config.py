"""Round-photo management (upload, position, description), exposed via the
web config UI.

static/config/photos.json is the single source of truth for round photos -
it's also read directly by static/js/game.js, static/js/moderator.js and
static/js/end_of_game.js (to show a round's photo / look one up by round
number) and by map_build.py (to widen the downloaded map so it covers every
photo location). This module is just the API that lets /config create,
update and delete entries in that same file, instead of hand-editing it.

No in-memory cache: the file is read fresh on every request and rewritten
whole on every change, guarded by `_lock` for read-modify-write safety -
mirrors game_state.py's / map_build.py's persistence conventions. There is
intentionally no cap on how many photos can be added.
"""

import json
import logging
import os
import sys
import tempfile
import threading

from flask import Blueprint, jsonify, request

import photo_storage

bp = Blueprint("photos", __name__, url_prefix="/api")

logger = logging.getLogger(__name__)

_lock = threading.Lock()

# Released binaries (see tools/build_release.py) ship this module frozen
# into the executable, so __file__ resolves inside PyInstaller's onefile
# temp extraction dir rather than next to the actual executable - mirrors
# app.py's frozen-path handling (see there for details).
if getattr(sys, "frozen", False):
    PROJECT_ROOT = os.path.dirname(sys.executable)
else:
    PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

# Overridable via env var (and directly in tests), same convention as
# map_build.MAP_CONFIG_FILE / game_state.STATE_FILE.
PHOTOS_FILE = os.environ.get(
    "ROUND_PHOTOS_FILE", os.path.join(PROJECT_ROOT, "static", "config", "photos.json")
)

_MAX_DESCRIPTION_LENGTH = 200

# The round photos this app ships with out of the box - the same entries a
# fresh checkout's static/config/photos.json starts with, backed by the
# sample files committed under static/photos/. clear_round_photos() restores
# this list (and leaves these files alone) instead of wiping round photos to
# an empty list, so a reset leaves the app ready to demo/reconfigure again
# instead of with no round photos at all. Only self-uploaded photos (which
# always get a generated filename, see photo_storage.save_upload_with_hq)
# are actually deleted.
#
# Like uploaded round photos (see save_upload_with_hq), each default ships
# both a downscaled/recompressed "filename" for everyday display and an
# untouched "filename_hq" full-resolution copy for the moderator's beamer
# view (#86).
_DEFAULT_ROUND_PHOTOS = [
    {
        "id": 1,
        "filename": "schloss_aschhausen.jpg",
        "filename_hq": "schloss_aschhausen_full.jpg",
        "location": {"lat": 49.3690, "lng": 9.5436},
        "description": "Schloss Aschhausen",
    },
    {
        "id": 2,
        "filename": "hamburg.jpg",
        "filename_hq": "hamburg_full.jpg",
        "location": {"lat": 53.5437, "lng": 10.0153},
        "description": "Harry Potter Theater Hamburg",
    },
    {
        "id": 3,
        "filename": "arena_oberhof.jpg",
        "filename_hq": "arena_oberhof_full.jpg",
        "location": {"lat": 50.7089, "lng": 10.6958},
        "description": "Lotto Thüringen Arena Oberhof",
    },
    {
        "id": 4,
        "filename": "stresa.jpg",
        "filename_hq": "stresa_full.jpg",
        "location": {"lat": 45.8956, "lng": 8.5253},
        "description": "Lago Maggiore - Stresa",
    },
    {
        "id": 5,
        "filename": "funchal.jpg",
        "filename_hq": "funchal_full.jpg",
        "location": {"lat": 32.6478, "lng": -16.9006},
        "description": "Funchal, Madeira",
    },
]


def _default_photo_filenames():
    """All filenames (small + hq) belonging to the shipped default round
    photos - see _DEFAULT_ROUND_PHOTOS."""
    names = set()
    for photo in _DEFAULT_ROUND_PHOTOS:
        names.add(photo["filename"])
        if photo.get("filename_hq"):
            names.add(photo["filename_hq"])
    return names


def _remove_photo_file(filename):
    """Best-effort delete of a round-photo file from PHOTOS_DIR - except a
    shipped default photo, which is never deleted from disk so it stays
    available for clear_round_photos() to restore even after its
    photos.json entry was removed (e.g. deleted via the config UI)."""
    if filename in _default_photo_filenames():
        return
    photo_path = os.path.join(photo_storage.PHOTOS_DIR, filename)
    try:
        os.remove(photo_path)
    except OSError as e:
        logger.warning("Could not remove photo file %s: %s", photo_path, e)


def _load_locked():
    """Read PHOTOS_FILE. Caller must hold `_lock`.

    A missing/unreadable/malformed file is treated as "no photos yet"
    rather than an error, same as the other config modules' load helpers.
    """
    if not os.path.isfile(PHOTOS_FILE):
        return []
    try:
        with open(PHOTOS_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("Could not read %s: %s", PHOTOS_FILE, e)
        return []
    return data if isinstance(data, list) else []


def _save_locked(photos):
    """Write `photos` to PHOTOS_FILE. Caller must hold `_lock`.

    Best-effort like the other config modules' persistence: a write
    failure is logged but never allowed to break the request that
    triggered it.
    """
    directory = os.path.dirname(PHOTOS_FILE) or "."
    tmp_path = None
    try:
        os.makedirs(directory, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(prefix=".photos_", dir=directory)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(photos, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, PHOTOS_FILE)
    except OSError as e:
        logger.warning("Could not persist %s: %s", PHOTOS_FILE, e)
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


def _with_url(photo):
    record = dict(photo)
    record["url"] = f"/static/photos/{photo['filename']}"
    if photo.get("filename_hq"):
        record["hq_url"] = f"/static/photos/{photo['filename_hq']}"
    return record


def _validate_lat_lng(lat, lng):
    if isinstance(lat, bool) or not isinstance(lat, (int, float)) or not (-90 <= lat <= 90):
        return "lat must be a number between -90 and 90"
    if isinstance(lng, bool) or not isinstance(lng, (int, float)) or not (-180 <= lng <= 180):
        return "lng must be a number between -180 and 180"
    return None


def _validate_description(description):
    if not isinstance(description, str) or len(description) > _MAX_DESCRIPTION_LENGTH:
        return f"description must be a string of at most {_MAX_DESCRIPTION_LENGTH} characters"
    return None


def clear_round_photos():
    """Remove every self-uploaded round photo (files + PHOTOS_FILE entries)
    and restore the shipped default round photos (_DEFAULT_ROUND_PHOTOS).
    Their files are never deleted (see _remove_photo_file), so this can
    always restore them even if a default entry was previously removed via
    the config UI. Used by tools/reset_state.py to prep the system for a
    new event's set of rounds. Returns how many (non-default) photos were
    removed.
    """
    default_filenames = {photo["filename"] for photo in _DEFAULT_ROUND_PHOTOS}

    with _lock:
        photos = _load_locked()
        _save_locked([dict(photo) for photo in _DEFAULT_ROUND_PHOTOS])

    removed = [photo for photo in photos if photo.get("filename") not in default_filenames]
    for photo in removed:
        for filename in (photo.get("filename"), photo.get("filename_hq")):
            if filename:
                _remove_photo_file(filename)

    return len(removed)


@bp.route("/round-photos", methods=["GET"])
def list_round_photos():
    with _lock:
        photos = _load_locked()
    return jsonify([_with_url(p) for p in photos])


@bp.route("/round-photos/reorder", methods=["POST"])
def reorder_round_photos():
    """Persist a new round order. `game.js` picks round N's photo by array
    index (allPhotos[round - 1]), so reordering this list is what actually
    reorders the rounds - there's no separate "round number" field."""
    payload = request.get_json(force=True) or {}
    order = payload.get("order")
    if not isinstance(order, list) or any(isinstance(i, bool) or not isinstance(i, int) for i in order):
        return jsonify({"error": "order must be a list of photo ids"}), 400

    with _lock:
        photos = _load_locked()
        by_id = {p.get("id"): p for p in photos}
        if set(order) != set(by_id.keys()) or len(order) != len(photos):
            return jsonify({"error": "order must contain exactly the existing photo ids"}), 400

        photos = [by_id[photo_id] for photo_id in order]
        _save_locked(photos)

    return jsonify([_with_url(p) for p in photos])


@bp.route("/round-photos/exif-location", methods=["POST"])
def round_photo_exif_location():
    """Sniff GPS coordinates out of an in-flight upload's EXIF data, without
    persisting anything. Called from the "add photo" form as soon as a file
    is picked, so the position field can be prefilled before the user
    actually submits it - which may still edit it freely either way."""
    photo_file = request.files.get("photo")
    if photo_file is None or not photo_file.filename:
        return jsonify({"error": "no photo file was uploaded"}), 400

    location = photo_storage.extract_gps_location(photo_file)
    if location is None:
        return jsonify({"lat": None, "lng": None})
    lat, lng = location
    return jsonify({"lat": lat, "lng": lng})


@bp.route("/round-photos", methods=["POST"])
def create_round_photo():
    photo_file = request.files.get("photo")
    description = (request.form.get("description") or "").strip()

    try:
        lat = float(request.form.get("lat"))
        lng = float(request.form.get("lng"))
    except (TypeError, ValueError):
        return jsonify({"error": "lat and lng are required numbers"}), 400

    error = _validate_lat_lng(lat, lng) or _validate_description(description)
    if error:
        return jsonify({"error": error}), 400

    try:
        filename, filename_hq = photo_storage.save_upload_with_hq(photo_file, prefix="round")
    except photo_storage.UploadError as e:
        return jsonify({"error": str(e)}), 400

    with _lock:
        photos = _load_locked()
        next_id = max((p.get("id", 0) for p in photos), default=0) + 1
        record = {
            "id": next_id,
            "filename": filename,
            "filename_hq": filename_hq,
            "location": {"lat": lat, "lng": lng},
            "description": description,
        }
        photos.append(record)
        _save_locked(photos)

    return jsonify(_with_url(record)), 201


@bp.route("/round-photos/<int:photo_id>", methods=["PATCH"])
def update_round_photo(photo_id):
    updates = request.get_json(force=True) or {}

    description = updates.get("description")
    if description is not None:
        error = _validate_description(description)
        if error:
            return jsonify({"error": error}), 400

    location = updates.get("location")
    if location is not None:
        if not isinstance(location, dict) or "lat" not in location or "lng" not in location:
            return jsonify({"error": "location must be an object with lat and lng"}), 400
        error = _validate_lat_lng(location.get("lat"), location.get("lng"))
        if error:
            return jsonify({"error": error}), 400

    with _lock:
        photos = _load_locked()
        record = next((p for p in photos if p.get("id") == photo_id), None)
        if record is None:
            return jsonify({"error": "photo not found"}), 404

        if description is not None:
            record["description"] = description.strip()
        if location is not None:
            record["location"] = {"lat": location["lat"], "lng": location["lng"]}

        _save_locked(photos)
        result = dict(record)

    return jsonify(_with_url(result))


@bp.route("/round-photos/<int:photo_id>", methods=["DELETE"])
def delete_round_photo(photo_id):
    with _lock:
        photos = _load_locked()
        record = next((p for p in photos if p.get("id") == photo_id), None)
        if record is None:
            return jsonify({"error": "photo not found"}), 404

        photos = [p for p in photos if p.get("id") != photo_id]
        _save_locked(photos)

    filenames = [record["filename"]]
    if record.get("filename_hq"):
        filenames.append(record["filename_hq"])

    for name in filenames:
        _remove_photo_file(name)

    return jsonify({"deleted": True, "id": photo_id})
