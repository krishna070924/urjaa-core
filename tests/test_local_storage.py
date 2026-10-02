"""L-05 self-check: LocalStorageService only writes to disk after decoding
real image bytes with Pillow (never trusting Content-Type or the filename
extension), rejects anything outside the JPEG/PNG/WebP allow-list, the 10MB
cap, and folder path traversal, and never uses the client-supplied filename
for the path it writes to.

No DB needed. Run: .venv/bin/python tests/test_local_storage.py
"""
import asyncio
import tempfile
from io import BytesIO
from pathlib import Path

from fastapi import HTTPException
from PIL import Image

from urjaa_core.services.storage_service import LocalStorageService


def _png_bytes() -> bytes:
    buf = BytesIO()
    Image.new("RGB", (32, 32), color="red").save(buf, format="PNG")
    return buf.getvalue()


def _jpeg_bytes() -> bytes:
    buf = BytesIO()
    Image.new("RGB", (32, 32), color="blue").save(buf, format="JPEG")
    return buf.getvalue()


def _webp_bytes() -> bytes:
    buf = BytesIO()
    Image.new("RGB", (32, 32), color="green").save(buf, format="WEBP")
    return buf.getvalue()


def _service(media_root: Path) -> LocalStorageService:
    service = LocalStorageService()
    service.media_root = media_root
    service.media_base_url = "http://localhost:8000/media"
    return service


def _expect_rejected(coro, status_code: int = 400) -> None:
    try:
        asyncio.run(coro)
        raise AssertionError("expected HTTPException")
    except HTTPException as exc:
        assert exc.status_code == status_code, exc.detail


def test_valid_images_saved_with_correct_url() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        service = _service(Path(tmp))
        for make_bytes, ext in [(_png_bytes, "png"), (_jpeg_bytes, "jpg"), (_webp_bytes, "webp")]:
            result = asyncio.run(
                service.upload(file_bytes=make_bytes(), filename="whatever.exe", folder="urjaa/products")
            )
            assert result["url"].startswith("http://localhost:8000/media/urjaa/products/")
            assert result["url"].endswith(f".{ext}")
            assert result["width"] == 32 and result["height"] == 32

            saved_name = result["url"].rsplit("/", 1)[-1]
            assert (Path(tmp) / "urjaa" / "products" / saved_name).is_file()


def test_non_image_bytes_rejected_even_with_image_content_type() -> None:
    # Simulates a client lying with a `Content-Type: image/png` header — the
    # storage service only ever sees raw bytes, so it must reject on actual
    # content, not the caller's claim.
    with tempfile.TemporaryDirectory() as tmp:
        service = _service(Path(tmp))
        _expect_rejected(
            service.upload(file_bytes=b"not actually a png, just text", filename="fake.png", folder="urjaa/products")
        )


def test_oversized_upload_rejected() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        service = _service(Path(tmp))
        oversized = _png_bytes() + b"\x00" * (10 * 1024 * 1024)
        _expect_rejected(service.upload(file_bytes=oversized, filename="big.png", folder="urjaa/products"))


def test_folder_traversal_rejected() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        service = _service(Path(tmp))
        _expect_rejected(service.upload(file_bytes=_png_bytes(), filename="x.png", folder="../x"))
        _expect_rejected(
            service.upload(file_bytes=_png_bytes(), filename="x.png", folder="urjaa/products/../../etc")
        )


def test_generated_name_ignores_client_filename() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        service = _service(Path(tmp))
        result = asyncio.run(
            service.upload(file_bytes=_png_bytes(), filename="../../etc/passwd.png", folder="urjaa/products")
        )
        saved_name = result["url"].rsplit("/", 1)[-1]
        assert "passwd" not in saved_name
        assert ".." not in result["url"]
        assert (Path(tmp) / "urjaa" / "products" / saved_name).is_file()


if __name__ == "__main__":
    test_valid_images_saved_with_correct_url()
    test_non_image_bytes_rejected_even_with_image_content_type()
    test_oversized_upload_rejected()
    test_folder_traversal_rejected()
    test_generated_name_ignores_client_filename()
    print("ok")
