from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from typing import Any

import cloudinary
import cloudinary.uploader
from fastapi import HTTPException

from urjaa_core.core.config import settings


class StorageService(ABC):
    @abstractmethod
    async def upload(self, file_bytes: bytes, filename: str, folder: str) -> dict[str, str]:
        """Upload bytes and return canonical URL/public ID payload."""


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

    async def upload(self, file_bytes: bytes, filename: str, folder: str) -> dict[str, str]:
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
