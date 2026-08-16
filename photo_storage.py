"""Shared helpers for handling uploaded photo files.

Used by both photo_config.py (round photos) and game_state.py (player
profile photos) so upload validation, unique-filename handling, and EXIF
GPS extraction live in exactly one place.
"""

import os
import re
import sys
import uuid

from PIL import ExifTags, Image

# Released binaries (see tools/build_release.py) ship this module frozen
# into the executable, so __file__ resolves inside PyInstaller's onefile
# temp extraction dir rather than next to the actual executable - mirrors
# app.py's frozen-path handling (see there for details). Without this,
# uploaded photos would be saved into the temp extraction dir instead of
# next to the static/ folder Flask actually serves, so they'd never show up.
if getattr(sys, "frozen", False):
    PROJECT_ROOT = os.path.dirname(sys.executable)
else:
    PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

# Overridable via env var (and directly in tests) so test runs don't touch
# the real project's static/photos/ folder - same convention as
# game_state.STATE_FILE / map_build.MAP_CONFIG_FILE.
PHOTOS_DIR = os.environ.get("PHOTOS_DIR", os.path.join(PROJECT_ROOT, "static", "photos"))

ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "gif", "webp"}
MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # generous for straight-off-the-camera wedding photos

_SAFE_CHARS_RE = re.compile(r"[^a-zA-Z0-9_-]+")

# Raw EXIF GPS tag id (0x8825) for Pillow versions whose ExifTags.IFD enum
# doesn't expose it by name.
_GPS_IFD_TAG = 0x8825


class UploadError(ValueError):
    """Raised for a rejected upload (bad type, too large, missing file)."""


def _extension(filename):
    if not filename or "." not in filename:
        return None
    ext = filename.rsplit(".", 1)[1].lower()
    return ext if ext in ALLOWED_EXTENSIONS else None


def save_upload(file_storage, prefix):
    """Validate and persist an uploaded image to PHOTOS_DIR.

    Returns the saved (unique, sanitized) filename. Raises UploadError if
    the upload is missing, not an allowed image type, or too large - the
    caller can turn that straight into a 400 response.
    """
    if file_storage is None or not file_storage.filename:
        raise UploadError("no photo file was uploaded")

    ext = _extension(file_storage.filename)
    if ext is None:
        raise UploadError(f"unsupported file type - allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}")

    file_storage.stream.seek(0, os.SEEK_END)
    size = file_storage.stream.tell()
    file_storage.stream.seek(0)
    if size == 0:
        raise UploadError("uploaded file is empty")
    if size > MAX_UPLOAD_BYTES:
        raise UploadError(f"file exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit")

    safe_prefix = _SAFE_CHARS_RE.sub("_", prefix).strip("_") or "photo"
    filename = f"{safe_prefix}_{uuid.uuid4().hex}.{ext}"

    os.makedirs(PHOTOS_DIR, exist_ok=True)
    file_storage.save(os.path.join(PHOTOS_DIR, filename))
    return filename


def _to_degrees(value):
    """Convert an EXIF ((deg_num, deg_den), (min_num, min_den), (sec_num, sec_den))
    (or plain-float) GPS coordinate triple into decimal degrees."""
    try:
        d, m, s = (float(v) for v in value)
    except (TypeError, ValueError):
        return None
    return d + (m / 60.0) + (s / 3600.0)


def extract_gps_location(file_storage):
    """Best-effort (lat, lng) from a photo's EXIF GPS tags, or None.

    Never raises - a photo without GPS metadata (or without any readable
    EXIF at all, e.g. a screenshot or a re-saved/edited image) is the
    common case, not an error; the config UI just asks the user to enter
    the position by hand in that case.
    """
    try:
        file_storage.stream.seek(0)
        image = Image.open(file_storage.stream)
        exif = image.getexif()
        gps_ifd = exif.get_ifd(_GPS_IFD_TAG)
        if not gps_ifd:
            return None

        gps = {ExifTags.GPSTAGS.get(tag, tag): value for tag, value in gps_ifd.items()}
        lat = _to_degrees(gps.get("GPSLatitude"))
        lng = _to_degrees(gps.get("GPSLongitude"))
        if lat is None or lng is None:
            return None

        if gps.get("GPSLatitudeRef") == "S":
            lat = -lat
        if gps.get("GPSLongitudeRef") == "W":
            lng = -lng

        if not (-90 <= lat <= 90) or not (-180 <= lng <= 180):
            return None
        return lat, lng
    except Exception:
        return None
    finally:
        try:
            file_storage.stream.seek(0)
        except Exception:
            pass
