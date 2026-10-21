"""
Product image storage.

Images live on disk under `settings.UPLOAD_DIR`, never in the database: a
photo stored in a row makes every SELECT on inventory_items carry it, and the
Postgres backup grows with the pictures. The row keeps a short relative key
("items/<uuid>.jpg") and the file keeps the bytes.

REQUIRES BUSINESS CONFIRMATION: the accepted formats. JPEG, PNG and WebP
cover phone photos and screenshots, which is what the Add Product form is
for. If the old ERP holds scanned TIFFs or PDFs for items, add them here
rather than letting the upload fail with a format error.

The size ceiling is MAX_UPLOAD_SIZE_MB from .env, not a value invented here.
"""

import uuid
from pathlib import Path

from fastapi import HTTPException, Request, UploadFile

from app.core.config import settings

# Where the static mount in app/main.py exposes UPLOAD_DIR.
MEDIA_URL_PREFIX = "/media"

# Subdirectory of UPLOAD_DIR holding item images.
ITEM_IMAGE_DIR = "items"

# The extension is chosen from the file's own signature, never from the name
# the browser sent: an upload called "photo.png" that is really something else
# is rejected instead of being stored under a name that lies about it.
_SIGNATURES: tuple[tuple[bytes, str], ...] = (
    (b"\xff\xd8\xff", ".jpg"),
    (b"\x89PNG\r\n\x1a\n", ".png"),
)
_EXTENSIONS = {ext for _, ext in _SIGNATURES} | {".webp"}


def _detect_extension(head: bytes) -> str | None:
    """The extension implied by the file's magic bytes, or None if it is not
    an image format we accept."""
    for signature, ext in _SIGNATURES:
        if head.startswith(signature):
            return ext
    # WebP is a RIFF container: "RIFF" <4-byte size> "WEBP".
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return ".webp"
    return None


def _item_dir() -> Path:
    return Path(settings.UPLOAD_DIR) / ITEM_IMAGE_DIR


def save_item_image(file: UploadFile, item_id: uuid.UUID) -> str:
    """Validate and store one product image, returning its storage key."""
    return save_image(file, ITEM_IMAGE_DIR, item_id)


def delete_item_image(item_id: uuid.UUID) -> None:
    delete_image(ITEM_IMAGE_DIR, item_id)


def save_image(file: UploadFile, subdir: str, owner_id: uuid.UUID) -> str:
    """Validate and store one image under UPLOAD_DIR/<subdir>, named after
    the record that owns it, returning its storage key.

    Any image already held for the owner is removed first, including one saved
    under a different extension, so a record never ends up with two files and
    a stale one cannot be served after a replacement.
    """
    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    # One byte over the limit is enough to know it is too big, so an oversized
    # upload is never read into memory in full.
    data = file.file.read(max_bytes + 1)

    if not data:
        raise HTTPException(400, "The uploaded file is empty.")
    if len(data) > max_bytes:
        raise HTTPException(
            413, f"That image is larger than {settings.MAX_UPLOAD_SIZE_MB} MB."
        )

    extension = _detect_extension(data[:16])
    if extension is None:
        raise HTTPException(
            400,
            "That file is not a JPEG, PNG or WebP image. Save the picture in "
            "one of those formats and try again.",
        )

    directory = Path(settings.UPLOAD_DIR) / subdir
    directory.mkdir(parents=True, exist_ok=True)
    delete_image(subdir, owner_id)
    (directory / f"{owner_id}{extension}").write_bytes(data)

    return f"{subdir}/{owner_id}{extension}"


def delete_image(subdir: str, owner_id: uuid.UUID) -> None:
    """Remove the owner's image file, whichever extension it was stored with.
    Silent when there is nothing to remove."""
    directory = Path(settings.UPLOAD_DIR) / subdir
    for extension in _EXTENSIONS:
        (directory / f"{owner_id}{extension}").unlink(missing_ok=True)


def image_url(request: Request, storage_key: str | None) -> str | None:
    """Absolute URL for a stored image.

    Absolute rather than relative so the browser can drop it straight into an
    <img src>: the frontend runs on a different port from the API and would
    otherwise have to know where media is mounted.
    """
    if not storage_key:
        return None
    return f"{str(request.base_url).rstrip('/')}{MEDIA_URL_PREFIX}/{storage_key}"
