"""POS rebuild self-check (migration 0032) against the live dev database, as
the admin app role. Savepoint-joined Session, everything rolled back at the
end -- same pattern as tests/test_custom_orders.py.

Covers: GST stored on the order = 3% of the post-discount subtotal and
printed as CGST/SGST; a line left for alteration creates a linked Custom
Order (order_taken) and prints "Alteration: ..." under that line; an
alteration without a customer (walk-in) or without a valid phone is a 422
and nothing is written.

Run: .venv/bin/python tests/test_pos_gst_alterations.py
"""
import base64
import os
import re
import sys
import zlib
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/urjaa")

from fastapi import HTTPException  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from urjaa_core.core.database import engine  # noqa: E402
from urjaa_core.models import AdminUser, Store  # noqa: E402
from urjaa_core.models.base_metal import BaseMetal  # noqa: E402
from urjaa_core.models.custom_order import CustomOrder  # noqa: E402
from urjaa_core.models.metal_rate import MetalRate  # noqa: E402
from urjaa_core.models.order import Order  # noqa: E402
from urjaa_core.models.product import Product  # noqa: E402
from urjaa_core.models.product_variant import ProductVariant  # noqa: E402
from urjaa_core.models.user import User  # noqa: E402
from urjaa_core.schemas.admin.sales import (  # noqa: E402
    BulkSaleCreateRequest,
    BulkSaleItemRequest,
    SaleAlterationRequest,
)
from urjaa_core.services.admin.sales_service import SalesService  # noqa: E402


def _pdf_text(pdf_bytes: bytes) -> bytes:
    return b"".join(
        zlib.decompress(base64.a85decode(raw.rstrip(b"\r\n").removesuffix(b"~>")))
        for raw in re.findall(rb"stream\r?\n(.*?)endstream", pdf_bytes, re.DOTALL)
    )


def _expect_422(db, store_id, payload, needle: str) -> None:
    # create_bulk_sale runs in its own savepoint, rolled back on the raise.
    try:
        SalesService.create_bulk_sale(db, store_id=store_id, payload=payload)
    except HTTPException as exc:
        assert exc.status_code == 422, exc.status_code
        assert needle in exc.detail, exc.detail
    else:
        raise AssertionError("expected a 422")


def main() -> None:
    conn = engine.connect()
    outer = conn.begin()
    db = Session(bind=conn, join_transaction_mode="create_savepoint")
    try:
        db.execute(text("SET ROLE urjaa_admin_svc"))
        store = db.query(Store).first()
        admin = db.query(AdminUser).first()
        assert store and admin, "dev DB needs at least one store and admin user"

        metal = BaseMetal(name=f"QAGold-{uuid4().hex[:6]}")
        db.add(metal)
        db.flush()
        db.add(MetalRate(base_metal_id=metal.id, rate_per_gram=Decimal("5000"), effective_from=datetime.now(timezone.utc)))
        product = Product(id=uuid4(), store_id=store.id, name="QA Band", slug=f"qa-band-{uuid4().hex[:8]}", status="active")
        db.add(product)
        db.flush()
        variants = [
            ProductVariant(
                id=uuid4(), store_id=store.id, product_id=product.id, base_metal_id=metal.id,
                metal_type=metal.name, weight=Decimal("2"), making_charges=Decimal("100"),
                stock_quantity=5, sku_code=f"QA-{uuid4().hex[:10]}", status="active",
            )
            for _ in range(2)
        ]
        db.add_all(variants)
        customer = User(
            email=f"qa-pos-{uuid4().hex[:8]}@store.local", password_hash="x", full_name="QA Pos Customer",
            phone="+91 98765 43210", source="STORE", provider="local", is_active=True,
        )
        no_phone = User(
            email=f"qa-pos-{uuid4().hex[:8]}@store.local", password_hash="x", full_name="QA No Phone",
            source="STORE", provider="local", is_active=True,
        )
        db.add_all([customer, no_phone])
        db.flush()

        ready_by = date.today() + timedelta(days=7)
        alteration_line = BulkSaleItemRequest(
            product_id=product.id, variant_id=variants[1].id, quantity=1, final_price=8000,
            alteration=SaleAlterationRequest(what="resize to 14", ready_by=ready_by),
        )

        # Walk-in + alteration -> 422, nothing written.
        _expect_422(db, store.id, BulkSaleCreateRequest(items=[alteration_line]), "Walk-in")
        # Customer without a usable phone -> 422.
        _expect_422(db, store.id, BulkSaleCreateRequest(customer_id=no_phone.id, items=[alteration_line]), "mobile number")
        db.refresh(variants[1])
        assert variants[1].stock_quantity == 5, "rejected sale must not touch stock"

        # Two lines: 15,000 after a 500 discount, 8,000 left for alteration.
        payload = BulkSaleCreateRequest(
            customer_id=customer.id,
            items=[
                BulkSaleItemRequest(product_id=product.id, variant_id=variants[0].id, quantity=1, final_price=15000, discount_amount=500),
                alteration_line,
            ],
        )
        result = SalesService.create_bulk_sale(db, store_id=store.id, payload=payload, admin_id=admin.id)

        # GST: 3% of the post-discount subtotal (23,000) = 690, stored on the order.
        order = db.query(Order).filter(Order.id == result["order_id"]).one()
        assert float(order.total_amount) == 23000.0, order.total_amount  # ex-GST, Insights unchanged
        assert float(order.tax_amount) == 690.0, order.tax_amount
        assert result["tax_amount"] == 690.0 and result["grand_total"] == 23690.0, result
        assert result["invoice_number"] == order.invoice_number

        # Alteration -> linked custom order in order_taken, customer copied over.
        assert len(result["alterations"]) == 1, result["alterations"]
        custom = db.get(CustomOrder, result["alterations"][0]["custom_order_id"])
        assert custom.sale_order_id == order.id
        assert custom.status.code == "order_taken"
        assert (custom.customer_name, custom.customer_phone) == ("QA Pos Customer", "9876543210")
        assert custom.expected_date == ready_by
        assert custom.design_notes == f"Alteration — QA Band (bill {order.invoice_number}): resize to 14", custom.design_notes
        assert custom.taken_by_admin_id == admin.id

        # Invoice: GST split + alteration line printed.
        _, pdf_bytes = SalesService.build_invoice_pdf(db, store_id=store.id, order_id=order.id)
        content = _pdf_text(pdf_bytes)
        for needle in (
            b"HSN 7113", b"Taxable value", b"INR 23,000.00", b"CGST 1.5%", b"SGST 1.5%", b"INR 345.00",
            b"INR 23,690.00", f"Alteration: resize to 14, ready by {ready_by:%d %b %Y}".encode(),
        ):
            assert needle in content, needle
        assert content.count(b"Alteration:") == 1

        # Odd paise: halves are rounded once each, so CGST + SGST == stored tax.
        odd = SalesService.create_bulk_sale(
            db, store_id=store.id,
            payload=BulkSaleCreateRequest(items=[BulkSaleItemRequest(product_id=product.id, variant_id=variants[0].id, quantity=1, final_price=1001)]),
        )
        assert odd["tax_amount"] == 30.04 and odd["grand_total"] == 1031.04, odd

        print("OK: GST 690 stored (CGST/SGST 345 each), alteration custom order linked, invoice lines printed, walk-in rejected")
    finally:
        db.close()
        outer.rollback()
        conn.close()


if __name__ == "__main__":
    main()
