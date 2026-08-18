"""Tests for photo_storage's on-upload downscale + recompress step.

Uploaded photos come straight off phone cameras (multi-MB, thousands of
pixels per side) but are only ever shown in small in-game photo/badge
containers, so save_upload() shrinks oversized images and recompresses them
in place - see photo_storage._downscale_and_recompress.
"""

import io

from PIL import Image
from werkzeug.datastructures import FileStorage

import photo_storage


def _file_storage(image, filename, **save_kwargs):
    buffer = io.BytesIO()
    image.save(buffer, **save_kwargs)
    buffer.seek(0)
    return FileStorage(stream=buffer, filename=filename)


def _saved_image(filename):
    return Image.open(photo_storage.PHOTOS_DIR + "/" + filename)


def test_oversized_jpeg_is_downscaled_to_max_dimension():
    image = Image.new("RGB", (3000, 2000), color="red")
    upload = _file_storage(image, "big.jpg", format="JPEG", quality=95)

    filename = photo_storage.save_upload(upload, prefix="round")

    with _saved_image(filename) as saved:
        assert max(saved.size) == photo_storage.MAX_DIMENSION
        assert saved.size == (photo_storage.MAX_DIMENSION, 1067)


def test_oversized_upload_ends_up_smaller_on_disk():
    image = Image.new("RGB", (3000, 2000), color="red")
    upload = _file_storage(image, "big.jpg", format="JPEG", quality=100)
    original_size = upload.stream.getbuffer().nbytes
    upload.stream.seek(0)

    filename = photo_storage.save_upload(upload, prefix="round")

    import os

    saved_size = os.path.getsize(os.path.join(photo_storage.PHOTOS_DIR, filename))
    assert saved_size < original_size


def test_small_jpeg_is_not_upscaled():
    image = Image.new("RGB", (400, 300), color="blue")
    upload = _file_storage(image, "small.jpg", format="JPEG")

    filename = photo_storage.save_upload(upload, prefix="round")

    with _saved_image(filename) as saved:
        assert saved.size == (400, 300)


def test_small_png_keeps_its_dimensions_and_format():
    image = Image.new("RGBA", (200, 150), color=(0, 255, 0, 128))
    upload = _file_storage(image, "small.png", format="PNG")

    filename = photo_storage.save_upload(upload, prefix="round")

    with _saved_image(filename) as saved:
        assert saved.format == "PNG"
        assert saved.size == (200, 150)


def test_oversized_png_is_downscaled():
    image = Image.new("RGBA", (2400, 1200), color=(0, 255, 0, 128))
    upload = _file_storage(image, "big.png", format="PNG")

    filename = photo_storage.save_upload(upload, prefix="round")

    with _saved_image(filename) as saved:
        assert max(saved.size) == photo_storage.MAX_DIMENSION


def test_animated_gif_is_left_untouched():
    frame1 = Image.new("RGB", (10, 10), color="red")
    frame2 = Image.new("RGB", (10, 10), color="blue")
    buffer = io.BytesIO()
    frame1.save(buffer, format="GIF", save_all=True, append_images=[frame2])
    buffer.seek(0)
    upload = FileStorage(stream=buffer, filename="anim.gif")

    filename = photo_storage.save_upload(upload, prefix="round")

    with _saved_image(filename) as saved:
        assert saved.n_frames == 2


def test_exif_orientation_is_baked_in_and_stripped():
    # Orientation 6 = rotate 270 (i.e. the pixel data is stored sideways and
    # a viewer must rotate 90 CW to display it upright).
    image = Image.new("RGB", (300, 200), color="red")
    exif = Image.Exif()
    exif[0x0112] = 6
    upload = _file_storage(image, "rotated.jpg", format="JPEG", exif=exif)

    filename = photo_storage.save_upload(upload, prefix="round")

    with _saved_image(filename) as saved:
        # exif_transpose() bakes the rotation into the pixel data, so the
        # saved image is now physically portrait (dimensions swapped) and
        # carries no orientation tag telling a viewer to rotate it again.
        assert saved.size == (200, 300)
        assert saved.getexif().get(0x0112) is None
