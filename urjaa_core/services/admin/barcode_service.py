from io import BytesIO
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session

from urjaa_core.models.product_variant import ProductVariant
from urjaa_core.repositories.admin.admin_management_repository import AdminManagementRepository
from urjaa_core.services.pricing_service import PricingService

LABEL_WIDTH = 200
LABEL_HEIGHT = 110
LABELS_PER_ROW = 3
PAGE_MARGIN = 30


class BarcodeService:
    """Generates Code128 barcodes from ProductVariant.sku_code (already
    DB-unique — no separate barcode identity column, see DESIGN.md)."""

    @staticmethod
    def generate_variant_barcode(sku_code: str) -> bytes:
        if not sku_code:
            raise HTTPException(status_code=400, detail="Variant has no SKU to encode")

        try:
            from barcode import Code128
            from barcode.writer import ImageWriter
        except ImportError:
            raise HTTPException(
                status_code=500,
                detail="Barcode generation is currently unavailable. Please contact support.",
            )

        buffer = BytesIO()
        Code128(sku_code, writer=ImageWriter()).write(buffer, options={"write_text": True})
        return buffer.getvalue()

    @staticmethod
    def get_variant_barcode_image(db: Session, store_id: UUID, variant_id: UUID) -> bytes:
        variant = AdminManagementRepository.get_variant_by_id(db, variant_id, store_id=store_id)
        if not variant:
            raise HTTPException(status_code=404, detail="Variant not found")
        return BarcodeService.generate_variant_barcode(variant.sku_code)

    @staticmethod
    def get_label_sheet_for_variants(db: Session, store_id: UUID, variant_ids: list[UUID]) -> tuple[str, bytes]:
        if not variant_ids:
            raise HTTPException(status_code=400, detail="No variant IDs provided")

        variants = (
            db.query(ProductVariant)
            .filter(ProductVariant.id.in_(variant_ids), ProductVariant.store_id == store_id)
            .all()
        )
        if not variants:
            raise HTTPException(status_code=404, detail="No matching variants found")

        return BarcodeService.build_label_sheet_pdf(variants, db)

    @staticmethod
    def build_label_sheet_pdf(variants: list[ProductVariant], db: Session) -> tuple[str, bytes]:
        try:
            from reportlab.lib.pagesizes import A4
            from reportlab.lib.utils import ImageReader
            from reportlab.pdfgen import canvas
        except ImportError:
            raise HTTPException(
                status_code=500,
                detail="Label sheet generation is currently unavailable. Please contact support.",
            )

        buffer = BytesIO()
        pdf = canvas.Canvas(buffer, pagesize=A4)
        page_width, page_height = A4

        x = PAGE_MARGIN
        y = page_height - PAGE_MARGIN - LABEL_HEIGHT
        col = 0

        for variant in variants:
            if not variant.sku_code:
                continue

            barcode_png = BarcodeService.generate_variant_barcode(variant.sku_code)
            price = PricingService.calculate_variant_price(variant, db)

            pdf.rect(x, y, LABEL_WIDTH - 10, LABEL_HEIGHT - 10)
            pdf.setFont("Helvetica-Bold", 9)
            pdf.drawString(x + 5, y + LABEL_HEIGHT - 20, (variant.product.name if variant.product else "")[:28])
            pdf.drawImage(
                ImageReader(BytesIO(barcode_png)),
                x + 5,
                y + 20,
                width=LABEL_WIDTH - 20,
                height=45,
                preserveAspectRatio=True,
            )
            pdf.setFont("Helvetica", 8)
            pdf.drawString(x + 5, y + 8, f"SKU: {variant.sku_code}")
            if price is not None:
                pdf.drawRightString(x + LABEL_WIDTH - 15, y + 8, f"INR {float(price):,.2f}")

            col += 1
            if col >= LABELS_PER_ROW:
                col = 0
                x = PAGE_MARGIN
                y -= LABEL_HEIGHT
                if y < PAGE_MARGIN:
                    pdf.showPage()
                    y = page_height - PAGE_MARGIN - LABEL_HEIGHT
            else:
                x += LABEL_WIDTH

        pdf.showPage()
        pdf.save()

        return "barcode_labels.pdf", buffer.getvalue()
