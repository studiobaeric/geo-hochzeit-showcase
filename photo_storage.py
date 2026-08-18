"""Shared helpers for handling uploaded photo files.

Used by both photo_config.py (round photos) and game_state.py (player
profile photos) so upload validation, unique-filename handling, and EXIF
GPS extraction live in exactly one place.
"""

import os
import re
import shutil
import sys
import uuid

from PIL import ExifTags, Image, ImageOps

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

# Uploads land as full-resolution phone camera photos (several MB, thousands
# of pixels per side) but are only ever displayed in small in-game photo/badge
# containers - downscale + recompress on upload so every later page load
# doesn't ship the original multi-MB file to the browser.
MAX_DIMENSION = 1600
JPEG_QUALITY = 80

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


def _validate_upload(file_storage, prefix):
    """Validate an upload and return (ext, filename) - the extension and a
    unique, sanitized filename to save it under (not yet written to disk).

    Raises UploadError if the upload is missing, not an allowed image type,
    or too large - the caller can turn that straight into a 400 response.
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
    return ext, filename


def save_upload(file_storage, prefix):
    """Validate and persist an uploaded image to PHOTOS_DIR.

    Returns the saved (unique, sanitized) filename. See _validate_upload()
    for the errors this can raise.
    """
    ext, filename = _validate_upload(file_storage, prefix)

    os.makedirs(PHOTOS_DIR, exist_ok=True)
    path = os.path.join(PHOTOS_DIR, filename)
    file_storage.save(path)
    _downscale_and_recompress(path, ext)
    return filename


def save_upload_with_hq(file_storage, prefix):
    """Like save_upload(), but also keeps an unmodified full-resolution copy.

    Round photos are shown small almost everywhere (players' photo view, the
    config UI's thumbnail list) but also get projected full-screen on the
    moderator's beamer during a round, where the downscaled copy would look
    soft - so this keeps both: an untouched original for that one place, and
    the downscaled/recompressed copy save_upload() would have produced for
    everywhere else.

    Returns (filename, filename_hq) - `filename` is the downscaled copy
    (same as save_upload()'s return value), `filename_hq` is the untouched
    original upload. See _validate_upload() for the errors this can raise.
    """
    ext, filename = _validate_upload(file_storage, prefix)

    os.makedirs(PHOTOS_DIR, exist_ok=True)
    hq_filename = f"{filename.rsplit('.', 1)[0]}_full.{ext}"
    hq_path = os.path.join(PHOTOS_DIR, hq_filename)
    file_storage.save(hq_path)

    path = os.path.join(PHOTOS_DIR, filename)
    shutil.copyfile(hq_path, path)
    _downscale_and_recompress(path, ext)
    return filename, hq_filename


def _downscale_and_recompress(path, ext):
    """Shrink an oversized image in place and recompress it.

    Best-effort: if anything goes wrong (unexpected pixel data, an animated
    GIF, etc.) the file at `path` is left untouched rather than losing the
    photo.
    """
    if ext == "gif":
        # Animated GIFs would lose their frames if reopened/resaved through
        # a single-frame Image - leave them as uploaded.
        return

    try:
        with Image.open(path) as image:
            image = ImageOps.exif_transpose(image)
            image.load()

            width, height = image.size
            longest_side = max(width, height)
            if longest_side > MAX_DIMENSION:
                scale = MAX_DIMENSION / longest_side
                new_size = (max(1, round(width * scale)), max(1, round(height * scale)))
                image = image.resize(new_size, Image.LANCZOS)

            if ext in ("jpg", "jpeg"):
                if image.mode not in ("RGB", "L"):
                    image = image.convert("RGB")
                image.save(path, format="JPEG", quality=JPEG_QUALITY, optimize=True)
            elif ext == "png":
                image.save(path, format="PNG", optimize=True)
            elif ext == "webp":
                image.save(path, format="WEBP", quality=JPEG_QUALITY)
    except Exception:
        pass


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
