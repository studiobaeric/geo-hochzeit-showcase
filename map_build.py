"""Map-data settings + basemap build trigger, exposed via the web config UI.

Building the offline PMTiles basemap (see `tools/build_basemap.py`) used to
be a manual, terminal-only step during initial setup. This module lets the
`/config` page define one or more map *regions* - each with its own
bounding box and zoom cap, e.g. a coarse worldwide overview plus one or more
specific areas in high detail - and trigger the existing build script as a
background process. The script itself does the actual (network-heavy,
multi-GB) work; this just configures and drives it.

Regions are ordered by zoom ascending and merged so each one only
contributes the zoom levels above the previous region's cap, restricted to
its own bbox (see tools/build_basemap.py for the merge strategy).

Whatever bbox is configured for the most detailed region, the bbox actually
used for a build is always widened (if needed) to cover every photo
location in static/config/photos.json with a safety margin, so a round's
photo location is never left outside the high-detail map data - see
`_photos_bbox`/`_union_bbox`. The user-configured bbox on disk is left
untouched; only the box passed to the build script is widened.

Mirrors game_state.py's conventions: module-level dicts as the source of
truth, JSON-file mirroring for persistence, and a file path overridable via
env var (and directly in tests) so test runs don't touch real project files.
"""

import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import threading
import time

from flask import Blueprint, jsonify, request

bp = Blueprint("map", __name__, url_prefix="/api/map")

logger = logging.getLogger(__name__)

_lock = threading.Lock()

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

MAP_CONFIG_FILE = os.environ.get(
    "MAP_CONFIG_FILE", os.path.join(PROJECT_ROOT, "data", "map_config.json")
)
PHOTOS_FILE = os.path.join(PROJECT_ROOT, "static", "config", "photos.json")

DEFAULT_MAP_CONFIG = {
    "regions": [
        {"name": "Welt", "bbox": "-180,-90,180,90", "maxzoom": 5},
        {"name": "Europa", "bbox": "-25,32,45,72", "maxzoom": 13},
    ],
    "build_date": "20260608",
}

_MIN_ZOOM = 0
_MAX_ZOOM = 14
_MAX_REGIONS = 8
_MAX_REGION_NAME_LENGTH = 60
_PHOTO_BBOX_PADDING_DEGREES = 0.5
_MAX_LOG_LINES = 200
_BUILD_DATE_RE = re.compile(r"\d{8}")

_DEFAULT_BUILD_STATUS = {
    "status": "idle",  # idle | running | success | error
    "started_at": None,
    "finished_at": None,
    "exit_code": None,
    "log_tail": [],
    "config_used": None,
    "error": None,
}

_map_config = dict(DEFAULT_MAP_CONFIG)
_build_status = dict(_DEFAULT_BUILD_STATUS)


# --- bounding-box helpers ----------------------------------------------


def _parse_bbox(value):
    if not isinstance(value, str):
        return None
    parts = value.split(",")
    if len(parts) != 4:
        return None
    try:
        min_lon, min_lat, max_lon, max_lat = (float(p) for p in parts)
    except ValueError:
        return None
    return min_lon, min_lat, max_lon, max_lat


def _validate_bbox(value):
    parsed = _parse_bbox(value)
    if parsed is None:
        return "bbox must be 'min_lon,min_lat,max_lon,max_lat'"
    min_lon, min_lat, max_lon, max_lat = parsed
    if not (-180 <= min_lon < max_lon <= 180):
        return "bbox longitudes must satisfy -180 <= min_lon < max_lon <= 180"
    if not (-90 <= min_lat < max_lat <= 90):
        return "bbox latitudes must satisfy -90 <= min_lat < max_lat <= 90"
    return None


def _format_bbox(bbox):
    return ",".join(f"{v:g}" for v in bbox)


def _photos_bbox(padding=_PHOTO_BBOX_PADDING_DEGREES):
    """Bounding box (with padding) covering every photo in photos.json.

    Returns None if the file is missing/unreadable or has no usable
    coordinates - a build then simply falls back to the configured bbox.
    """
    try:
        with open(PHOTOS_FILE) as f:
            photos = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("Could not read %s for photo bbox: %s", PHOTOS_FILE, e)
        return None

    if not isinstance(photos, list):
        return None

    lats, lons = [], []
    for photo in photos:
        if not isinstance(photo, dict):
            continue
        location = photo.get("location")
        if not isinstance(location, dict):
            continue
        lat, lng = location.get("lat"), location.get("lng")
        if (
            isinstance(lat, (int, float)) and not isinstance(lat, bool)
            and isinstance(lng, (int, float)) and not isinstance(lng, bool)
        ):
            lats.append(lat)
            lons.append(lng)

    if not lats:
        return None

    min_lon = max(-180.0, min(lons) - padding)
    max_lon = min(180.0, max(lons) + padding)
    min_lat = max(-90.0, min(lats) - padding)
    max_lat = min(90.0, max(lats) + padding)
    return min_lon, min_lat, max_lon, max_lat


def _union_bbox(bbox_str, photo_bbox):
    """Widen `bbox_str` just enough to also cover `photo_bbox`, if needed."""
    configured = _parse_bbox(bbox_str)
    if configured is None or photo_bbox is None:
        return bbox_str
    min_lon = min(configured[0], photo_bbox[0])
    min_lat = min(configured[1], photo_bbox[1])
    max_lon = max(configured[2], photo_bbox[2])
    max_lat = max(configured[3], photo_bbox[3])
    return _format_bbox((min_lon, min_lat, max_lon, max_lat))


# --- map config: validation, persistence, API ---------------------------


def _validate_regions(regions):
    if not isinstance(regions, list) or not regions:
        return "regions must be a non-empty list"
    if len(regions) > _MAX_REGIONS:
        return f"regions must contain at most {_MAX_REGIONS} entries"

    seen_maxzoom = set()
    for region in regions:
        if not isinstance(region, dict):
            return "each region must be an object"

        name = region.get("name")
        if (
            not isinstance(name, str)
            or not name.strip()
            or len(name.strip()) > _MAX_REGION_NAME_LENGTH
        ):
            return f"region name must be a non-empty string of at most {_MAX_REGION_NAME_LENGTH} characters"

        bbox_error = _validate_bbox(region.get("bbox"))
        if bbox_error:
            return f"region '{name}': {bbox_error}"

        maxzoom = region.get("maxzoom")
        if (
            isinstance(maxzoom, bool)
            or not isinstance(maxzoom, int)
            or maxzoom < _MIN_ZOOM
            or maxzoom > _MAX_ZOOM
        ):
            return f"region '{name}': maxzoom must be an integer between {_MIN_ZOOM} and {_MAX_ZOOM}"

        if maxzoom in seen_maxzoom:
            return (
                f"region '{name}': maxzoom {maxzoom} is already used by another region - "
                "each region needs its own, increasing zoom cap"
            )
        seen_maxzoom.add(maxzoom)

    return None


def _validate_map_config_updates(updates):
    if "regions" in updates:
        error = _validate_regions(updates["regions"])
        if error:
            return error

    if "build_date" in updates:
        value = updates["build_date"]
        if not isinstance(value, str) or not _BUILD_DATE_RE.fullmatch(value):
            return "build_date must be a string in YYYYMMDD format"

    return None


def _normalize_regions(regions):
    normalized = [
        {"name": r["name"].strip(), "bbox": r["bbox"], "maxzoom": r["maxzoom"]} for r in regions
    ]
    normalized.sort(key=lambda r: r["maxzoom"])
    return normalized


def _persist_map_config_locked():
    """Write `_map_config` to MAP_CONFIG_FILE. Caller must hold `_lock`.

    Best-effort like game_state._persist_locked: a write failure is logged
    but never allowed to break the request that triggered it.
    """
    if not MAP_CONFIG_FILE:
        return

    directory = os.path.dirname(MAP_CONFIG_FILE) or "."
    tmp_path = None
    try:
        os.makedirs(directory, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(prefix=".map_config_", dir=directory)
        with os.fdopen(fd, "w") as f:
            json.dump(_map_config, f)
        os.replace(tmp_path, MAP_CONFIG_FILE)
    except OSError as e:
        logger.warning("Could not persist map config to %s: %s", MAP_CONFIG_FILE, e)
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


def load_map_config_from_disk():
    """Replace in-memory map config with whatever is in MAP_CONFIG_FILE.

    A missing/unreadable/invalid file is treated as "nothing to load" and
    leaves the current in-memory defaults untouched, same as game_state's
    load_state_from_disk.
    """
    if not MAP_CONFIG_FILE or not os.path.isfile(MAP_CONFIG_FILE):
        return

    try:
        with open(MAP_CONFIG_FILE) as f:
            payload = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("Could not read persisted map config from %s: %s", MAP_CONFIG_FILE, e)
        return

    if not isinstance(payload, dict):
        return

    known = {k: v for k, v in payload.items() if k in DEFAULT_MAP_CONFIG}
    if DEFAULT_MAP_CONFIG.keys() != known.keys():
        return
    if _validate_map_config_updates(known) is not None:
        return

    known["regions"] = _normalize_regions(known["regions"])
    _map_config.clear()
    _map_config.update(known)


def _config_with_bbox_info(config):
    """Config annotated with per-region `effective_bbox` + top-level `photo_bbox`.

    Regions come back sorted ascending by maxzoom. Only the most detailed
    (last/highest-maxzoom) region's `effective_bbox` is widened to cover
    every photo location - that's the region that actually determines how
    much detail a photo's surroundings get.
    """
    record = dict(config)
    regions = [dict(r) for r in config["regions"]]
    regions.sort(key=lambda r: r["maxzoom"])

    photo_bbox = _photos_bbox()
    for region in regions:
        region["effective_bbox"] = region["bbox"]
    if regions:
        regions[-1]["effective_bbox"] = _union_bbox(regions[-1]["bbox"], photo_bbox)

    record["regions"] = regions
    record["photo_bbox"] = _format_bbox(photo_bbox) if photo_bbox else None
    return record


@bp.route("/config", methods=["GET"])
def get_map_config():
    with _lock:
        config = dict(_map_config)
    return jsonify(_config_with_bbox_info(config))


@bp.route("/config", methods=["PATCH"])
def patch_map_config():
    updates = request.get_json(force=True) or {}

    error = _validate_map_config_updates(updates)
    if error:
        return jsonify({"error": error}), 400

    with _lock:
        if "regions" in updates:
            _map_config["regions"] = _normalize_regions(updates["regions"])
        if "build_date" in updates:
            _map_config["build_date"] = updates["build_date"]
        config = dict(_map_config)
        _persist_map_config_locked()

    return jsonify(_config_with_bbox_info(config))


# --- basemap build: runner, background execution, API -------------------


def _script_path():
    """tools/build_basemap.py - one script, works identically on every OS
    (see its own module docstring for why the old per-platform bash/
    PowerShell scripts were replaced)."""
    path = os.path.join(PROJECT_ROOT, "tools", "build_basemap.py")
    return path if os.path.isfile(path) else None


def _write_regions_file(regions):
    """Write `name<TAB>effective_bbox<TAB>maxzoom` lines for the build script."""
    fd, path = tempfile.mkstemp(prefix="map_regions_", suffix=".tsv")
    try:
        with os.fdopen(fd, "w", newline="\n") as f:
            for region in regions:
                name = region["name"].replace("\t", " ").replace("\n", " ")
                f.write(f"{name}\t{region['effective_bbox']}\t{region['maxzoom']}\n")
    except Exception:
        os.remove(path)
        raise
    return path


def _build_command(script):
    # Run with the same interpreter Flask itself is running under, so there's
    # no dependency on a "python"/"python3" launcher being on PATH, and no
    # ambiguity about which installed Python version gets used.
    return [sys.executable, script]


def _default_runner(config, log_callback):
    """Run tools/build_basemap.py as a subprocess.

    Writes the configured regions to a temp TSV file, streams the script's
    combined stdout/stderr line by line to `log_callback`, and returns the
    process exit code (1 if the script is missing, without spawning
    anything - this shouldn't normally happen since it ships with the repo).
    """
    script = _script_path()
    if script is None:
        log_callback("Build-Skript tools/build_basemap.py wurde nicht gefunden.")
        return 1

    regions_file = _write_regions_file(config["regions"])
    try:
        env = os.environ.copy()
        env["REGIONS_FILE"] = regions_file
        env["BUILD_DATE"] = config["build_date"]

        process = subprocess.Popen(
            _build_command(script),
            cwd=PROJECT_ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        for line in process.stdout:
            log_callback(line.rstrip("\n"))
        process.wait()
        return process.returncode
    finally:
        try:
            os.remove(regions_file)
        except OSError:
            pass


# Overridable indirection point: tests monkeypatch this to a fast fake so
# the real (multi-GB, network-heavy) script never runs under pytest.
_build_runner = _default_runner


def _append_log_line(line):
    with _lock:
        _build_status["log_tail"].append(line)
        if len(_build_status["log_tail"]) > _MAX_LOG_LINES:
            del _build_status["log_tail"][: len(_build_status["log_tail"]) - _MAX_LOG_LINES]


def _run_build(config_used):
    try:
        exit_code = _build_runner(config_used, _append_log_line)
    except Exception as e:  # defensive: a crashing runner must still resolve "running"
        logger.exception("Basemap build runner raised an exception")
        with _lock:
            _build_status.update(
                {"status": "error", "finished_at": time.time(), "exit_code": None, "error": str(e)}
            )
        return

    with _lock:
        _build_status.update(
            {
                "status": "success" if exit_code == 0 else "error",
                "finished_at": time.time(),
                "exit_code": exit_code,
                "error": None if exit_code == 0 else f"Skript beendet mit Exit-Code {exit_code}",
            }
        )


@bp.route("/build", methods=["POST"])
def start_build():
    with _lock:
        if _build_status["status"] == "running":
            return jsonify({"error": "a build is already running"}), 409

        config_used = _config_with_bbox_info(dict(_map_config))
        _build_status.clear()
        _build_status.update(_DEFAULT_BUILD_STATUS)
        _build_status.update(
            {"status": "running", "started_at": time.time(), "config_used": config_used}
        )
        record = dict(_build_status)

    thread = threading.Thread(target=_run_build, args=(config_used,), daemon=True)
    thread.start()
    return jsonify(record), 202


@bp.route("/build/status", methods=["GET"])
def get_build_status():
    with _lock:
        return jsonify(dict(_build_status))


load_map_config_from_disk()
