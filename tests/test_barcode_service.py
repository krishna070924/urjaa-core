"""Task 01 self-check: BarcodeService.generate_variant_barcode must produce a
genuinely scannable Code128 PNG, not just any PNG. Decodes the rendered PNG's
actual pixels with an independent barcode reader (zxing-cpp — bundles its own
native lib via the wheel, no system zbar install needed) and confirms it
reads back the exact SKU string that went in. Proves the image is real,
correct Code128, not just that bytes came out the other end.
"""

from io import BytesIO

from PIL import Image

from urjaa_core.services.admin.barcode_service import BarcodeService


def _decode(png_bytes: bytes):
    import zxingcpp

    results = zxingcpp.read_barcodes(Image.open(BytesIO(png_bytes)))
    assert len(results) == 1, f"expected exactly one barcode, got {results}"
    return results[0]


def test_generate_variant_barcode_returns_png_bytes():
    png = BarcodeService.generate_variant_barcode("VRT-TEST-001")
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    assert len(png) > 100


def test_generate_variant_barcode_round_trips_to_exact_sku():
    for sku in ["VRT-TEST-001", "VRT-TEST-XYZ-42", "GOLD-RING-9K-16"]:
        png = BarcodeService.generate_variant_barcode(sku)
        result = _decode(png)
        assert "128" in str(result.format)
        assert result.text == sku


def test_generate_variant_barcode_rejects_empty_sku():
    try:
        BarcodeService.generate_variant_barcode("")
        raise AssertionError("expected HTTPException for empty sku_code")
    except Exception as exc:
        assert getattr(exc, "status_code", None) == 400


if __name__ == "__main__":
    test_generate_variant_barcode_returns_png_bytes()
    test_generate_variant_barcode_round_trips_to_exact_sku()
    test_generate_variant_barcode_rejects_empty_sku()
    print("ok")
