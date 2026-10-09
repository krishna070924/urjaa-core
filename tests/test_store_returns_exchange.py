"""Store returns, credit notes, store credit, payment capture and old-jewellery
exchange (migrations 0034/0035) against the live dev database, as the admin
app role. Savepoint-joined Session, everything rolled back at the end -- same
pattern as tests/test_pos_gst_alterations.py.

Run: .venv/bin/python tests/test_store_returns_exchange.py
"""
import os
import sys
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/urjaa")

from fastapi import HTTPException  # noqa: E402
from sqlalchemy import func, text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from test_pos_gst_alterations import _pdf_text  # noqa: E402
from urjaa_core.core.admin_auth import ADMIN_PERMISSION_MANAGE_SALES, DEFAULT_ROLE_PERMISSIONS, _resolve_required_permissions  # noqa: E402
from urjaa_core.core.database import engine  # noqa: E402
from urjaa_core.models import AdminUser, Store  # noqa: E402
from urjaa_core.models.base_metal import BaseMetal  # noqa: E402
from urjaa_core.models.custom_order import CustomOrder  # noqa: E402
from urjaa_core.models.metal_rate import MetalRate  # noqa: E402
from urjaa_core.models.order import Order  # noqa: E402
from urjaa_core.models.product import Product  # noqa: E402
from urjaa_core.models.product_variant import ProductVariant  # noqa: E402
from urjaa_core.models.sale import NET_SALE_AMOUNT, Sale  # noqa: E402
from urjaa_core.models.user import User  # noqa: E402
from urjaa_core.models.variant_physical_unit import UnitStatus, VariantPhysicalUnit  # noqa: E402
from urjaa_core.schemas.admin.sales import (  # noqa: E402
    BulkSaleCreateRequest,
    BulkSaleItemRequest,
    OldGoldItemRequest,
    SaleAlterationRequest,
    SalePaymentRequest,
    SaleReturnCreateRequest,
    SaleReturnLineRequest,
)
from urjaa_core.services.admin import store_return_service  # noqa: E402
from urjaa_core.services.admin.sales_service import SalesService  # noqa: E402


def expect_422(fn, needle: str) -> None:
    try:
        fn()
    except HTTPException as exc:
        assert exc.status_code == 422, (exc.status_code, exc.detail)
        assert needle in exc.detail, exc.detail
    else:
        raise AssertionError(f"expected a 422 containing {needle!r}")


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
        product = Product(id=uuid4(), store_id=store.id, name="QA Return Ring", slug=f"qa-ret-{uuid4().hex[:8]}", status="active")
        db.add(product)
        db.flush()

        def variant(stock: int) -> ProductVariant:
            v = ProductVariant(
                id=uuid4(), store_id=store.id, product_id=product.id, base_metal_id=metal.id,
                metal_type=metal.name, weight=Decimal("2"), making_charges=Decimal("100"),
                stock_quantity=stock, sku_code=f"QA-{uuid4().hex[:10]}", status="active",
            )
            db.add(v)
            db.flush()
            return v

        counted, tracked, other = variant(5), variant(0), variant(5)
        in_stock = db.query(UnitStatus.id).filter(UnitStatus.code == "in_stock").scalar()
        units = [
            VariantPhysicalUnit(variant_id=tracked.id, status_id=in_stock, huid_number=f"Q{uuid4().hex[:5].upper()}")
            for _ in range(3)
        ]
        db.add_all(units)
        db.flush()
        db.refresh(tracked)
        assert tracked.stock_quantity == 3, tracked.stock_quantity

        customer = User(
            email=f"qa-ret-{uuid4().hex[:8]}@store.local", password_hash="x", full_name="QA Return Customer",
            phone="9876543210", source="STORE", provider="local", is_active=True,
        )
        db.add(customer)
        db.flush()

        def sale(payload, **kw):
            return SalesService.create_bulk_sale(db, store_id=store.id, payload=payload, admin_id=admin.id, **kw)

        # ── A. Sale with old jewellery exchange + split payment ──
        old = OldGoldItemRequest(
            description="QA old bangle", base_metal_id=metal.id, purity=91.6, gross_weight=10, stone_weight=1,
            rate_per_gram=5000, deduction_amount=500, deduction_reason="melting loss",
        )
        items = [
            BulkSaleItemRequest(product_id=product.id, variant_id=counted.id, quantity=2, final_price=20000, discount_amount=1000),
            BulkSaleItemRequest(product_id=product.id, variant_id=tracked.id, quantity=2, final_price=30000, unit_ids=[units[0].id, units[1].id]),
            BulkSaleItemRequest(
                product_id=product.id, variant_id=other.id, quantity=1, final_price=8000,
                alteration=SaleAlterationRequest(what="resize to 12", ready_by=date.today() + timedelta(days=5)),
            ),
        ]
        # net 58,000; GST 1,740; grand 59,740; old 9 g x 5,000 - 500 = 44,500; to pay 15,240
        expect_422(lambda: sale(BulkSaleCreateRequest(items=items[:1], old_gold=[old])), "walk-in")
        expect_422(
            lambda: sale(BulkSaleCreateRequest(customer_id=customer.id, items=items, old_gold=[old],
                                               payment=SalePaymentRequest(method="split", cash=10000, upi=5000))),
            "add up to",
        )
        expect_422(
            lambda: sale(BulkSaleCreateRequest(customer_id=customer.id, items=items[:1], old_gold=[old.model_copy(update={"deduction_reason": None})])),
            "reason for the deduction",
        )
        db.refresh(counted)
        assert counted.stock_quantity == 5, "rejected sales must not touch stock"

        result = sale(BulkSaleCreateRequest(
            customer_id=customer.id, items=items, old_gold=[old],
            payment=SalePaymentRequest(method="split", cash=10000, upi=5240, reference="UPI123"),
        ))
        assert (result["tax_amount"], result["grand_total"]) == (1740.0, 59740.0), result  # GST unchanged by old gold
        assert (result["old_gold_total"], result["amount_to_pay"], result["payable_to_customer"]) == (44500.0, 15240.0, 0.0), result
        order = db.get(Order, result["order_id"])
        assert float(order.total_amount) == 58000.0 and float(order.tax_amount) == 1740.0
        assert order.payment_method == "split" and order.payment_details == {"cash": 10000.0, "upi": 5240.0, "reference": "UPI123"}
        assert float(order.old_gold_items[0].net_weight) == 9.0 and float(order.old_gold_items[0].value) == 44500.0
        content = _pdf_text(SalesService.build_invoice_pdf(db, store_id=store.id, order_id=order.id)[1])
        for needle in (b"Old jewellery taken in exchange", b"Less: old jewellery exchange", b"- INR 44,500.00",
                       b"melting loss", b"Amount to pay", b"INR 15,240.00", b"Paid by: Split: Cash INR 10,000.00, UPI INR 5,240.00"):
            assert needle in content, needle

        lines = {s.variant_id: s for s in db.query(Sale).filter(Sale.order_id == order.id)}
        count_line, tracked_line, alt_line = lines[counted.id], lines[tracked.id], lines[other.id]
        alt_order = db.query(CustomOrder).filter(CustomOrder.sale_id == alt_line.id).one()

        info = store_return_service.get_return_info(db, store.id, order.id)
        tracked_info = next(line for line in info["lines"] if line["sale_id"] == tracked_line.id)
        assert tracked_info["tracked"] and {p["id"] for p in tracked_info["pieces"]} == {units[0].id, units[1].id}
        assert next(line for line in info["lines"] if line["sale_id"] == alt_line.id)["alterations"][0]["id"] == alt_order.id

        # ── B. Return: 1 counted + 1 tracked piece + the alteration line, to store credit ──
        def ret(**kw):
            base = dict(reason="changed_mind", refund_method="store_credit",
                        lines=[SaleReturnLineRequest(sale_id=count_line.id, quantity=1)])
            return store_return_service.create_return(db, store.id, order.id, SaleReturnCreateRequest(**{**base, **kw}), admin.id)

        expect_422(lambda: ret(lines=[SaleReturnLineRequest(sale_id=count_line.id, quantity=3)]), "only 2 of 2")
        expect_422(lambda: ret(deduction_amount=100), "reason for the deduction")
        expect_422(lambda: ret(lines=[SaleReturnLineRequest(sale_id=tracked_line.id, quantity=1, unit_ids=[units[2].id])]), "pieces sold")
        expect_422(lambda: ret(deduction_amount=999999, deduction_reason="x"), "more than the value")

        done = ret(
            lines=[
                SaleReturnLineRequest(sale_id=count_line.id, quantity=1),
                SaleReturnLineRequest(sale_id=tracked_line.id, quantity=1, unit_ids=[units[0].id]),
                SaleReturnLineRequest(sale_id=alt_line.id, quantity=1),
            ],
            deduction_amount=1000, deduction_reason="polish charge", refund_reference="CRN-1",
        )
        # value 10,000 + 15,000 + 8,000 = 33,000; GST 495 + 495; refund 33,990 - 1,000 = 32,990
        assert (done["taxable_value"], done["cgst"], done["sgst"], done["refund_amount"]) == (33000.0, 495.0, 495.0, 32990.0), done
        assert done["credit_note_number"].startswith("CN-") and done["cancelled_custom_order_ids"] == [alt_order.id]
        for obj in (counted, tracked, other, units[0], count_line, alt_order):
            db.refresh(obj)
        assert counted.stock_quantity == 4, counted.stock_quantity  # 5 - 2 + 1
        assert tracked.stock_quantity == 2, tracked.stock_quantity  # 3 - 2 + 1 (trigger)
        assert units[0].status_id == in_stock and units[0].sale_id is None
        assert (count_line.returned_quantity, float(count_line.returned_amount)) == (1, 10000.0)
        assert alt_order.status.code == "cancelled" and alt_order.events[-1].note.startswith("Item returned")
        assert SalesService.store_credit_balance(db, customer.id) == Decimal("32990.00")
        expect_422(lambda: ret(lines=[SaleReturnLineRequest(sale_id=count_line.id, quantity=2)]), "only 1 of 2")

        content = _pdf_text(store_return_service.build_credit_note_pdf(db, store.id, done["id"])[1])
        for needle in (done["credit_note_number"].encode(), order.invoice_number.encode(), b"CGST 1.5% reversed",
                       b"SGST 1.5% reversed", b"INR 495.00", b"Less: deduction", b"polish charge", b"- INR 1,000.00",
                       b"INR 32,990.00", b"Refunded by: Store credit", b"Ref CRN-1", units[0].huid_number.encode()):
            assert needle in content, needle

        # Insights: returned value comes off the line's revenue.
        net = db.query(func.sum(NET_SALE_AMOUNT)).filter(Sale.order_id == order.id).scalar()
        assert float(net) == 58000 - 33000, net
        history = SalesService.get_sales_history(db, store.id, page=1, limit=50, customer_id=customer.id)
        row = next(item for item in history["items"] if item["id"] == count_line.id)
        assert row["returned_quantity"] == 1 and row["credit_notes"][0]["credit_note_number"] == done["credit_note_number"]

        # ── C. Store credit: use it on the next bill (= exchange), never below zero ──
        new_item = [BulkSaleItemRequest(product_id=product.id, variant_id=counted.id, quantity=1, final_price=40000)]
        # grand 41,200
        expect_422(lambda: sale(BulkSaleCreateRequest(items=new_item, store_credit_used=100)), "walk-in")
        expect_422(lambda: sale(BulkSaleCreateRequest(customer_id=customer.id, items=new_item, store_credit_used=40000)), "only ₹32,990.00")
        expect_422(lambda: sale(BulkSaleCreateRequest(customer_id=customer.id, items=new_item, store_credit_used=50000)), "more than the amount to pay")
        used = sale(BulkSaleCreateRequest(customer_id=customer.id, items=new_item, store_credit_used=32990,
                                          payment=SalePaymentRequest(method="card", reference="4242")))
        assert (used["store_credit_used"], used["amount_to_pay"]) == (32990.0, 8210.0), used
        assert SalesService.store_credit_balance(db, customer.id) == 0
        content = _pdf_text(SalesService.build_invoice_pdf(db, store_id=store.id, order_id=used["order_id"])[1])
        assert b"Less: store credit" in content and b"INR 8,210.00" in content and b"Paid by: Card" in content
        expect_422(lambda: sale(BulkSaleCreateRequest(customer_id=customer.id, items=new_item, store_credit_used=1)), "only ₹0.00")

        # ── D. Old jewellery worth more than the bill -> payable to customer ──
        small = [BulkSaleItemRequest(product_id=product.id, variant_id=counted.id, quantity=1, final_price=10000)]
        big_old = old.model_copy(update={"gross_weight": 5, "stone_weight": 1, "deduction_amount": 0, "deduction_reason": None})
        # grand 10,300; old 4 g x 5,000 = 20,000 -> payable 9,700
        expect_422(lambda: sale(BulkSaleCreateRequest(customer_id=customer.id, items=small, old_gold=[big_old])), "difference")
        payout = sale(BulkSaleCreateRequest(customer_id=customer.id, items=small, old_gold=[big_old], payout_method="store_credit"))
        assert (payout["payable_to_customer"], payout["amount_to_pay"]) == (9700.0, 0.0), payout
        assert SalesService.store_credit_balance(db, customer.id) == Decimal("9700.00")
        cash_payout = sale(BulkSaleCreateRequest(customer_id=customer.id, items=small, old_gold=[big_old], payout_method="cash"))
        assert db.get(Order, cash_payout["order_id"]).payment_details == {"payout": {"method": "cash", "amount": 9700.0}}

        # ── E. Walk-in bill: store credit only once a customer is attached ──
        walkin = sale(BulkSaleCreateRequest(items=small, payment=SalePaymentRequest(method="cash")))
        walkin_line = db.query(Sale).filter(Sale.order_id == walkin["order_id"]).one()
        walk_req = dict(reason="defect", lines=[SaleReturnLineRequest(sale_id=walkin_line.id, quantity=1)])
        expect_422(
            lambda: store_return_service.create_return(db, store.id, walkin["order_id"], SaleReturnCreateRequest(refund_method="store_credit", **walk_req), admin.id),
            "walk-in",
        )
        store_return_service.create_return(
            db, store.id, walkin["order_id"],
            SaleReturnCreateRequest(refund_method="store_credit", customer_id=customer.id, **walk_req), admin.id,
        )
        assert SalesService.store_credit_balance(db, customer.id) == Decimal("9700.00") + Decimal("10300.00")

        # Permissions: recording a return needs manage_sales; staff has it.
        assert _resolve_required_permissions(f"/admin/sales/{uuid4()}/returns", "POST") == {ADMIN_PERMISSION_MANAGE_SALES}
        for path, method in [(f"/admin/sales/{uuid4()}/returns", "GET"), (f"/admin/sales/{uuid4()}/returns", "POST"),
                             ("/admin/sales/returns/7/credit-note", "GET")]:
            assert set(_resolve_required_permissions(path, method)) & DEFAULT_ROLE_PERMISSIONS["staff"], path

        print("OK: old-gold + split bill, returns (count + HUID) with credit note, store credit use/payout, walk-in guard, Insights net")
    finally:
        db.close()
        outer.rollback()
        conn.close()


if __name__ == "__main__":
    main()
