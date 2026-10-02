from __future__ import annotations

import asyncio
import uuid
from abc import ABC, abstractmethod
from io import BytesIO
from pathlib import Path
from typing import Any

import cloudinary
import cloudinary.uploader
from fastapi import HTTPException
from PIL import Image, UnidentifiedImageError

from urjaa_core.core.config import settings


class StorageService(ABC):
    @abstractmethod
    async def upload(self, file_bytes: bytes, filename: str, folder: str) -> dict[str, Any]:
        """Upload bytes and return canonical URL/public ID payload."""

    @abstractmethod
    async def upload_video(self, file_bytes: bytes, filename: str, folder: str) -> dict[str, Any]:
        """N-03: upload a hero video (MP4/WebM) and return canonical URL/public ID payload."""


class CloudinaryStorageService(StorageService):
    def __init__(self) -> None:
        cloud_name = settings.cloudinary_cloud_name.strip()
        api_key = settings.cloudinary_api_key.strip()
        api_secret = settings.cloudinary_api_secret.strip()

        if not cloud_name or not api_key or not api_secret:
            raise HTTPException(status_code=500, detail="Cloudinary is not configured")

        cloudinary.config(
            cloud_name=cloud_name,
            api_key=api_key,
            api_secret=api_secret,
            secure=True,
        )

    async def upload(self, file_bytes: bytes, filename: str, folder: str) -> dict[str, Any]:
        if not file_bytes:
            raise HTTPException(status_code=400, detail="Empty upload payload")

        def _upload() -> dict[str, Any]:
            return cloudinary.uploader.upload(
                file_bytes,
                resource_type="image",
                folder=folder,
                filename=filename,
                use_filename=True,
                unique_filename=True,
                overwrite=False,
            )

        result = await asyncio.to_thread(_upload)
        secure_url = result.get("secure_url")
        public_id = result.get("public_id")

        if not isinstance(secure_url, str) or not secure_url:
            raise HTTPException(status_code=502, detail="Cloudinary upload failed")
        if not isinstance(public_id, str) or not public_id:
            raise HTTPException(status_code=502, detail="Cloudinary upload failed")

        return {
            "url": secure_url,
            "public_id": public_id,
        }

    async def upload_video(self, file_bytes: bytes, filename: str, folder: str) -> dict[str, Any]:
        if not file_bytes:
            raise HTTPException(status_code=400, detail="Empty upload payload")

        def _upload() -> dict[str, Any]:
            return cloudinary.uploader.upload(
                file_bytes,
                resource_type="video",
                folder=folder,
                filename=filename,
                use_filename=True,
                unique_filename=True,
                overwrite=False,
            )

        result = await asyncio.to_thread(_upload)
        secure_url = result.get("secure_url")
        public_id = result.get("public_id")

        if not isinstance(secure_url, str) or not secure_url:
            raise HTTPException(status_code=502, detail="Cloudinary upload failed")
        if not isinstance(public_id, str) or not public_id:
            raise HTTPException(status_code=502, detail="Cloudinary upload failed")

        return {
            "url": secure_url,
            "public_id": public_id,
        }


# L-05/N-03: known upload folders, shared across the admin product-image
# route, the storefront commission-request route, and (N-03) the admin CMS
# media route. Allow-listed here (not just at the route layer) because this
# is the trust boundary that turns `folder` into a filesystem path — the
# commission route in particular passes the client's raw Form value straight
# through with no allow-list check of its own.
LOCAL_STORAGE_ALLOWED_FOLDERS = {"urjaa/products", "urjaa/commission-requests", "urjaa/cms"}

# N-03: hero video uploads only ever go to the CMS folder — no client choice
# of destination for videos (unlike images, which are reused across routes).
LOCAL_VIDEO_ALLOWED_FOLDERS = {"urjaa/cms"}

# Pillow format name -> file extension. Deliberately excludes GIF: D32/L-05
# scope is JPEG/PNG/WebP only.
_ALLOWED_IMAGE_EXTENSIONS = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp"}

MAX_VIDEO_BYTES = 25 * 1024 * 1024


def _sniff_video_extension(data: bytes) -> str | None:
    """N-03: magic-byte sniff, same trust-the-bytes-not-the-header philosophy
    as the image path below. MP4 containers carry an 'ftyp' box at offset 4;
    WebM (a Matroska/EBML container) starts with the EBML magic number."""
    if len(data) >= 8 and data[4:8] == b"ftyp":
        return "mp4"
    if len(data) >= 4 and data[:4] == b"\x1a\x45\xdf\xa3":
        return "webm"
    return None


class LocalStorageService(StorageService):
    """Writes uploads to local disk under MEDIA_ROOT, served back out by a
    static file mount (see urjaa-backend's /media route). D32: local disk for
    now, move to a CDN before real traffic.
    """

    def __init__(self) -> None:
        self.media_root = Path(settings.media_root)
        self.media_base_url = settings.media_base_url.rstrip("/")

    async def upload(self, file_bytes: bytes, filename: str, folder: str) -> dict[str, Any]:
        if not file_bytes:
            raise HTTPException(status_code=400, detail="Empty upload payload")
        if len(file_bytes) > 10 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="File must be 10MB or smaller")

        # Path traversal / arbitrary-folder defense: allow-list only, no "..".
        # `filename` (the client-supplied name) is never used for the path —
        # see the generated `name` below.
        folder = folder.strip().strip("/")
        if folder not in LOCAL_STORAGE_ALLOWED_FOLDERS:
            raise HTTPException(status_code=400, detail="Invalid upload folder")

        # Never trust Content-Type or the filename extension: actually decode
        # the bytes with Pillow (already a transitive dependency via
        # reportlab) so a renamed/relabelled non-image file is rejected here
        # regardless of what the client claimed.
        try:
            with Image.open(BytesIO(file_bytes)) as probe:
                probe.verify()
            with Image.open(BytesIO(file_bytes)) as img:
                image_format = img.format
                width, height = img.size
        except (UnidentifiedImageError, OSError, ValueError):
            raise HTTPException(status_code=400, detail="File content does not match a supported image format")

        extension = _ALLOWED_IMAGE_EXTENSIONS.get(image_format or "")
        if extension is None:
            raise HTTPException(status_code=400, detail="Only JPEG, PNG, or WebP images are allowed")

        name = f"{uuid.uuid4().hex}.{extension}"
        folder_dir = self.media_root / folder

        def _write() -> None:
            folder_dir.mkdir(parents=True, exist_ok=True)
            (folder_dir / name).write_bytes(file_bytes)

        await asyncio.to_thread(_write)

        return {
            "url": f"{self.media_base_url}/{folder}/{name}",
            "public_id": f"{folder}/{name}",
            "width": width,
            "height": height,
        }

    async def upload_video(self, file_bytes: bytes, filename: str, folder: str) -> dict[str, Any]:
        if not file_bytes:
            raise HTTPException(status_code=400, detail="Empty upload payload")
        if len(file_bytes) > MAX_VIDEO_BYTES:
            raise HTTPException(status_code=400, detail="File must be 25MB or smaller")

        folder = folder.strip().strip("/")
        if folder not in LOCAL_VIDEO_ALLOWED_FOLDERS:
            raise HTTPException(status_code=400, detail="Invalid upload folder")

        extension = _sniff_video_extension(file_bytes)
        if extension is None:
            raise HTTPException(status_code=400, detail="Only MP4 or WebM videos are allowed")

        name = f"{uuid.uuid4().hex}.{extension}"
        folder_dir = self.media_root / folder

        def _write() -> None:
            folder_dir.mkdir(parents=True, exist_ok=True)
            (folder_dir / name).write_bytes(file_bytes)

        await asyncio.to_thread(_write)

        return {
            "url": f"{self.media_base_url}/{folder}/{name}",
            "public_id": f"{folder}/{name}",
        }
