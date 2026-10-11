"""Store bills linked to customers (orders.user_id), customer matching by phone,
and the store credit page (ledger + manual credit/deduction). Live dev DB as the
admin app role, savepoint-joined Session, all rolled back -- same pattern as
tests/test_store_returns_exchange.py.

Run: .venv/bin/python tests/test_store_customers_credit.py
"""
import os
import sys
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/urjaa")

from fastapi import HTTPException  # noqa: E402
from pydantic import ValidationError  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from urjaa_core.core.admin_auth import (  # noqa: E402
    ADMIN_PERMISSION_MANAGE_SALES,
    ADMIN_PERMISSION_VIEW_SALES,
    DEFAULT_ROLE_PERMISSIONS,
    _resolve_required_permissions,
)
from urjaa_core.core.database import engine  # noqa: E402
from urjaa_core.models import AdminUser, Store  # noqa: E402
from urjaa_core.models.base_metal import BaseMetal  # noqa: E402
from urjaa_core.models.metal_rate import MetalRate  # noqa: E402
from urjaa_core.models.order import Order  # noqa: E402
from urjaa_core.models.product import Product  # noqa: E402
from urjaa_core.models.product_variant import ProductVariant  # noqa: E402
from urjaa_core.models.sale import Sale  # noqa: E402
from urjaa_core.schemas.admin.sales import (  # noqa: E402
    BulkSaleCreateRequest,
    BulkSaleItemRequest,
    CustomerCreateRequest,
    CustomerUpdateRequest,
    SalePaymentRequest,
    SaleReturnCreateRequest,
    SaleReturnLineRequest,
    StoreCreditAdjustRequest,
)
from urjaa_core.services import analytics_service  # noqa: E402
from urjaa_core.services.admin import store_return_service  # noqa: E402
from urjaa_core.services.admin.sales_service import SalesService, phone_key  # noqa: E402
from urjaa_core.services.order_service import OrderService  # noqa: E402


def expect(status: int, fn, needle: str) -> None:
    try:
        fn()
    except HTTPException as exc:
        assert exc.status_code == status and needle in exc.detail, (exc.status_code, exc.detail)
    else:
        raise AssertionError(f"expected {status} containing {needle!r}")


def main() -> None:
    assert phone_key("+91 98765-43210") == phone_key("09876543210") == phone_key("9876543210") == "9876543210"
    assert phone_key("12345") is None
    for bad in (dict(amount="10.001"), dict(amount="0"), dict(reason="  ")):
        try:
            StoreCreditAdjustRequest(**{"direction": "issue", "amount": "10", "reason": "goodwill", **bad})
        except ValidationError:
            pass
        else:
            raise AssertionError(bad)

    conn = engine.connect()
    outer = conn.begin()
    db = Session(bind=conn, join_transaction_mode="create_savepoint")
    try:
        db.execute(text("SET ROLE urjaa_admin_svc"))
        store = db.query(Store).first()
        admin = db.query(AdminUser).first()
        assert store and admin, "dev DB needs at least one store and admin user"

        # ── Customer matching: same number in any format + same name = same record ──
        mobile = f"6{uuid4().int % 10**9:09d}"
        first = SalesService.create_customer(db, store.id, CustomerCreateRequest(name="Asha  Rao", phone=f"+91 {mobile[:5]}-{mobile[5:]}"))
        assert first["phone"] == mobile, first  # stored as the bare 10 digits
        again = SalesService.create_customer(db, store.id, CustomerCreateRequest(name="asha rao", phone=f"0{mobile}"))
        assert again["id"] == first["id"], "same phone + same name must reuse the customer"
        expect(409, lambda: SalesService.create_customer(db, store.id, CustomerCreateRequest(name="Ravi Rao", phone=mobile)),
               "already saved for Asha  Rao")
        shared = SalesService.create_customer(
            db, store.id, CustomerCreateRequest(name="Ravi Rao", phone=mobile, allow_shared_phone=True)
        )
        assert shared["id"] != first["id"], "staff confirmed: different person, same number"
        email = f"qa-{uuid4().hex[:8]}@example.com"
        SalesService.update_customer(db, store.id, first["id"], CustomerUpdateRequest(email=email))
        expect(409, lambda: SalesService.create_customer(db, store.id, CustomerCreateRequest(name="Someone Else", email=email.upper())),
               "email is already saved")
        found = SalesService.list_customers_with_options(db, None, 1, 20, search=f"+91 {mobile[:5]} {mobile[5:]}")
        assert {item["id"] for item in found["items"]} == {first["id"], shared["id"]}, found

        # ── A store bill is linked to its customer ──
        metal = BaseMetal(name=f"QACust-{uuid4().hex[:6]}")
        db.add(metal)
        db.flush()
        db.add(MetalRate(base_metal_id=metal.id, rate_per_gram=Decimal("5000"), effective_from=datetime.now(timezone.utc)))
        product = Product(id=uuid4(), store_id=store.id, name="QA Cust Ring", slug=f"qa-cust-{uuid4().hex[:8]}", status="active")
        db.add(product)
        db.flush()
        variant = ProductVariant(
            id=uuid4(), store_id=store.id, product_id=product.id, base_metal_id=metal.id, metal_type=metal.name,
            weight=Decimal("2"), making_charges=Decimal("100"), stock_quantity=5, sku_code=f"QA-{uuid4().hex[:10]}", status="active",
        )
        db.add(variant)
        db.flush()

        bill = SalesService.create_bulk_sale(
            db, store_id=store.id, admin_id=admin.id,
            payload=BulkSaleCreateRequest(
                customer_id=first["id"], payment=SalePaymentRequest(method="cash"),
                items=[BulkSaleItemRequest(product_id=product.id, variant_id=variant.id, quantity=2, final_price=20000)],
            ),
        )
        order = db.get(Order, bill["order_id"])
        assert (order.user_id, order.full_name, order.phone, order.email) == (first["id"], "Asha  Rao", mobile, email), order.__dict__
        walk_in = SalesService.create_bulk_sale(
            db, store_id=store.id, admin_id=admin.id,
            payload=BulkSaleCreateRequest(
                payment=SalePaymentRequest(method="cash"),
                items=[BulkSaleItemRequest(product_id=product.id, variant_id=variant.id, quantity=1, final_price=9000)],
            ),
        )
        assert db.get(Order, walk_in["order_id"]).user_id is None

        # Half comes back to store credit: analytics and the customer page count it net.
        line = db.query(Sale).filter(Sale.order_id == order.id).one()
        store_return_service.create_return(
            db, store.id, order.id,
            SaleReturnCreateRequest(reason="size", refund_method="store_credit", lines=[SaleReturnLineRequest(sale_id=line.id, quantity=1)]),
            admin.id,
        )  # 10,000 + GST 300 = 10,300 credit
        analytics_service.clear_cache()
        assert analytics_service.compute_rfm_scores(store.id, db)[first["id"]].total_spend == 10000
        analytics_service.clear_cache()
        listed = next(i for i in SalesService.list_customers_with_options(db, None, 1, 20, search=mobile)["items"] if i["id"] == first["id"])
        assert (listed["bills_count"], listed["net_spend"], listed["store_credit_balance"]) == (1, 10000.0, 10300.0), listed
        # The storefront's My Orders never shows store bills (no order_items there).
        assert OrderService.list_user_orders(db, user_id=first["id"], page=1, limit=10)["total"] == 0

        # ── Store credit: manual issue / deduction, never below zero ──
        def adjust(direction, amount, reason="goodwill"):
            return SalesService.adjust_store_credit(
                db, store.id, first["id"], StoreCreditAdjustRequest(direction=direction, amount=amount, reason=reason), admin.id
            )

        assert adjust("issue", "500.50", "Festival goodwill")["store_credit_balance"] == 10800.5
        expect(422, lambda: adjust("deduct", "10800.51"), "below zero")
        assert adjust("deduct", "800.50", "Entered twice by mistake")["store_credit_balance"] == 10000.0
        assert SalesService.store_credit_balance(db, first["id"]) == Decimal("10000.00")
        expect(404, lambda: SalesService.adjust_store_credit(
            db, store.id, uuid4(), StoreCreditAdjustRequest(direction="issue", amount="1", reason="nobody"), admin.id), "not found")

        account = SalesService.get_customer_account(db, first["id"])
        assert account["customer"]["store_credit_balance"] == 10000.0
        assert [b["invoice_number"] for b in account["bills"]] == [order.invoice_number]
        assert account["bills"][0]["bill_total"] == 20600.0 and account["bills"][0]["net_amount"] == 10000.0
        assert account["bills"][0]["returns"][0]["refund_amount"] == 10300.0
        kinds = [(e["kind"], e["amount"], e["balance_after"]) for e in account["ledger"]]
        assert kinds == [("manual_deduction", -800.5, 10000.0), ("manual_issue", 500.5, 10800.5), ("return_credit", 10300.0, 10300.0)], kinds
        ret_entry = account["ledger"][-1]
        assert ret_entry["credit_note_number"].startswith("CN-") and ret_entry["invoice_number"] == order.invoice_number
        assert account["ledger"][0]["note"] == "Entered twice by mistake" and account["ledger"][0]["staff"] == admin.email

        # ── Permissions: viewing = view_sales or manage_sales; giving credit = manage_sales ──
        cid = first["id"]
        assert _resolve_required_permissions(f"/admin/sales/customers/{cid}/account", "GET") == {
            ADMIN_PERMISSION_VIEW_SALES, ADMIN_PERMISSION_MANAGE_SALES}
        assert _resolve_required_permissions(f"/admin/sales/customers/{cid}/store-credit", "POST") == {ADMIN_PERMISSION_MANAGE_SALES}
        assert _resolve_required_permissions(f"/admin/sales/customers/{cid}", "PUT") == {ADMIN_PERMISSION_MANAGE_SALES}
        assert ADMIN_PERMISSION_MANAGE_SALES in DEFAULT_ROLE_PERMISSIONS["staff"]
        assert ADMIN_PERMISSION_MANAGE_SALES not in DEFAULT_ROLE_PERMISSIONS["viewer"]

        print("OK: phone matching (reuse / ask / shared), bills linked + net in RFM and customer list, "
              "manual credit/deduction ledger, never below zero, permissions, storefront unaffected")
    finally:
        db.close()
        outer.rollback()
        conn.close()


if __name__ == "__main__":
    main()
