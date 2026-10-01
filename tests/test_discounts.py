"""K-03 self-check against the live dev database, as the admin/storefront app
roles. Savepoint-joined Session, everything rolled back at the end -- same
pattern as tests/test_sku_autogeneration.py.

Covers (per ticket): best-wins between a product-specific and an
applies_to_all discount, outside-window -> no discount, inactive -> none,
final-price rounding (ROUND_HALF_UP), order creation from a cart snapshots
the discounted unit price plus original/percent, a price_override product is
discounted too (D27), and a Price-on-Request product is unaffected.

Run: .venv/bin/python tests/test_discounts.py
"""
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

os.environ.setdefault("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/urjaa")

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from urjaa_core.core.database import engine
from urjaa_core.models import (
    Address,
    BaseMetal,
    Cart,
    CartItem,
    Discount,
    MetalRate,
    Product,
    ProductVariant,
    Store,
    User,
)
from urjaa_core.schemas.admin.discounts import DiscountCreateRequest, DiscountUpdateRequest
from urjaa_core.services.admin.discount_service import AdminDiscountService
from urjaa_core.services.order_service import OrderService
from urjaa_core.services.pricing_service import PricingService, round_money


def _make_product(db, store, *, name, price_override=None, base_metal_id=None, weight=None, making=None):
    product = Product(id=uuid4(), store_id=store.id, name=name, slug=f"{name.lower().replace(' ', '-')}-{uuid4().hex[:8]}", status="active")
    db.add(product)
    db.flush()
    variant = ProductVariant(
        id=uuid4(),
        store_id=store.id,
        product_id=product.id,
        price_override=price_override,
        base_metal_id=base_metal_id,
        metal_weight_grams=weight,
        making_charges=making,
        stock_quantity=10,
        sku_code=f"K03-{uuid4().hex[:10]}",
        status="active",
    )
    db.add(variant)
    db.flush()
    return product, variant


def main() -> None:
    conn = engine.connect()
    outer = conn.begin()
    db = Session(bind=conn, join_transaction_mode="create_savepoint")
    try:
        db.execute(text("SET ROLE urjaa_admin_svc"))

        store = Store(id=uuid4(), name=f"K03 Test Store {uuid4().hex[:6]}")
        db.add(store)
        db.flush()

        gold = BaseMetal(name=f"K03Gold{uuid4().hex[:6]}")
        no_rate_metal = BaseMetal(name=f"K03NoRate{uuid4().hex[:6]}")
        db.add_all([gold, no_rate_metal])
        db.flush()
        db.add(MetalRate(base_metal_id=gold.id, rate_per_gram=Decimal("5000.00"), effective_from=datetime.utcnow() - timedelta(days=1)))
        db.flush()

        # price_override product
        product_a, variant_a = _make_product(db, store, name="K03 Override Ring", price_override=Decimal("1000.00"))
        # computed-price product (metal + making -> calculate_variant_price's full formula)
        product_b, variant_b = _make_product(db, store, name="K03 Computed Ring", base_metal_id=gold.id, weight=Decimal("2.000"), making=Decimal("100.00"))
        # rounding-boundary product: 99.99 at 50% -> exactly 49.995 pre-round
        product_d, variant_d = _make_product(db, store, name="K03 Rounding Ring", price_override=Decimal("99.99"))
        # Price-on-Request: base metal with no MetalRate row at all
        product_c, variant_c = _make_product(db, store, name="K03 PoR Ring", base_metal_id=no_rate_metal.id, weight=Decimal("1.000"))

        now = datetime.now(timezone.utc)
        expected_base_b = round_money(Decimal("2.000") * Decimal("5000.00") + Decimal("100.00"))

        # --- D29 best-wins: product-specific 20% vs store-wide 50% -> 50% wins
        specific = AdminDiscountService.create_discount(
            db, store_id=store.id,
            payload=DiscountCreateRequest(name="K03 Specific 20", percent=Decimal("20"), product_ids=[product_b.id]),
        )
        store_wide = AdminDiscountService.create_discount(
            db, store_id=store.id,
            payload=DiscountCreateRequest(name="K03 Storewide 50", percent=Decimal("50"), applies_to_all=True),
        )
        assert specific["status"] == "active" and store_wide["status"] == "active"
        db.flush()

        db.execute(text("SET ROLE urjaa_storefront"))

        priced_b = PricingService.price_variant(variant_b, db)
        assert priced_b.original_price == expected_base_b, priced_b
        assert priced_b.discount_percent == Decimal("50.00"), priced_b
        assert priced_b.price == round_money(expected_base_b * Decimal("50") / Decimal("100")), priced_b
        print(f"OK best-wins: specific 20% vs store-wide 50% on same product -> {priced_b.discount_percent}% (store-wide) applied")

        # price_override product discounted too (D27: whole computed price, override included)
        priced_a = PricingService.price_variant(variant_a, db)
        assert priced_a.original_price == Decimal("1000.00") and priced_a.discount_percent == Decimal("50.00")
        assert priced_a.price == Decimal("500.00"), priced_a
        print("OK price_override product is discounted by the store-wide rule too")

        # Price-on-Request unaffected: no base price -> no discount, ever
        priced_c = PricingService.price_variant(variant_c, db)
        assert priced_c.price is None and priced_c.original_price is None and priced_c.discount_percent is None
        print("OK Price-on-Request (no metal rate) product is unaffected by discounts")

        db.execute(text("SET ROLE urjaa_admin_svc"))

        # Turn off the store-wide rule so the remaining checks are isolated.
        db.query(Discount).filter(Discount.id == store_wide["id"]).update({"is_active": False})
        db.flush()

        # --- inactive -> none
        db.execute(text("SET ROLE urjaa_storefront"))
        priced_b_after = PricingService.price_variant(variant_b, db)
        assert priced_b_after.discount_percent == Decimal("20.00"), priced_b_after  # falls back to the specific one
        print("OK deactivated discount no longer applies (falls back to the next-best)")

        db.execute(text("SET ROLE urjaa_admin_svc"))
        db.query(Discount).filter(Discount.id == specific["id"]).update({"is_active": False})
        db.flush()

        db.execute(text("SET ROLE urjaa_storefront"))
        priced_b_none = PricingService.price_variant(variant_b, db)
        assert priced_b_none.price == expected_base_b and priced_b_none.discount_percent is None
        print("OK both discounts inactive -> no discount, final price is the plain computed price")

        # --- outside window -> no discount
        db.execute(text("SET ROLE urjaa_admin_svc"))
        future = AdminDiscountService.create_discount(
            db, store_id=store.id,
            payload=DiscountCreateRequest(
                name="K03 Future 70", percent=Decimal("70"), product_ids=[product_d.id],
                starts_at=now + timedelta(days=5), ends_at=now + timedelta(days=10),
            ),
        )
        expired = AdminDiscountService.create_discount(
            db, store_id=store.id,
            payload=DiscountCreateRequest(
                name="K03 Expired 70", percent=Decimal("70"), product_ids=[product_d.id],
                starts_at=now - timedelta(days=10), ends_at=now - timedelta(days=1),
            ),
        )
        assert future["status"] == "scheduled" and expired["status"] == "expired"
        db.flush()

        db.execute(text("SET ROLE urjaa_storefront"))
        priced_d_outside = PricingService.price_variant(variant_d, db)
        assert priced_d_outside.price == Decimal("99.99") and priced_d_outside.discount_percent is None
        print("OK scheduled (not started) and expired discounts do not apply")

        # --- update: clearing an end date works; a partial update that breaks the window is a 422
        db.execute(text("SET ROLE urjaa_admin_svc"))
        cleared = AdminDiscountService.update_discount(
            db, store_id=store.id, discount_id=expired["id"], payload=DiscountUpdateRequest(ends_at=None)
        )
        assert cleared["ends_at"] is None and cleared["status"] == "active", cleared
        try:
            AdminDiscountService.update_discount(
                db, store_id=store.id, discount_id=future["id"],
                payload=DiscountUpdateRequest(ends_at=now + timedelta(days=1)),
            )
            raise AssertionError("end before start accepted")
        except HTTPException as exc:
            assert exc.status_code == 422, exc.status_code
        AdminDiscountService.update_discount(
            db, store_id=store.id, discount_id=expired["id"], payload=DiscountUpdateRequest(is_active=False)
        )
        print("OK update can clear an end date; end-before-start on partial update -> 422")

        # --- final price rounding: 99.99 at 50% = 49.995 pre-round -> ROUND_HALF_UP -> 50.00
        db.execute(text("SET ROLE urjaa_admin_svc"))
        AdminDiscountService.create_discount(
            db, store_id=store.id,
            payload=DiscountCreateRequest(name="K03 Rounding 50", percent=Decimal("50"), product_ids=[product_d.id]),
        )
        db.flush()

        db.execute(text("SET ROLE urjaa_storefront"))
        priced_d = PricingService.price_variant(variant_d, db)
        assert priced_d.original_price == Decimal("99.99")
        assert priced_d.price == Decimal("50.00"), priced_d  # not 49.99 (float) or 49.995 (unrounded)
        print(f"OK final price rounded once with ROUND_HALF_UP: 99.99 @ 50% -> {priced_d.price}")

        # --- order created from a cart uses the discounted unit price and
        # snapshots original_unit_price + discount_percent (K-03 point 4)
        db.execute(text("SET ROLE urjaa_admin_svc"))
        AdminDiscountService.create_discount(
            db, store_id=store.id,
            payload=DiscountCreateRequest(name="K03 Cart 25", percent=Decimal("25"), product_ids=[product_b.id]),
        )
        user = User(id=uuid4(), email=f"k03-{uuid4().hex[:10]}@test.local", password_hash="x", full_name="K03 Tester")
        db.add(user)
        db.flush()
        address = Address(
            id=uuid4(), user_id=user.id, name="K03 Tester", phone="9999999999",
            address_line_1="1 Test Lane", city="Testville", state="TS", pincode="000000", country="IN",
        )
        db.add(address)
        cart = Cart(id=uuid4(), user_id=user.id)
        db.add(cart)
        db.flush()
        db.add(CartItem(id=uuid4(), cart_id=cart.id, product_id=product_b.id, variant_id=variant_b.id, quantity=2))
        db.flush()

        db.execute(text("SET ROLE urjaa_storefront"))
        order = OrderService.create_order_from_cart(db, current_user=user, address_id=address.id)
        assert len(order.items) == 1, order.items
        item = order.items[0]
        expected_unit = round_money(expected_base_b * Decimal("75") / Decimal("100"))
        assert item.unit_price == expected_unit, item.unit_price
        assert item.original_unit_price == expected_base_b, item.original_unit_price
        assert item.discount_percent == Decimal("25.00"), item.discount_percent
        assert order.total_amount == round_money(expected_unit * 2), order.total_amount
        print(
            f"OK order from cart: unit_price={item.unit_price} (original={item.original_unit_price}, "
            f"-{item.discount_percent}%), total_amount={order.total_amount} -- this is what Razorpay would charge"
        )

        print("\nAll K-03 discount checks passed.")
    finally:
        db.execute(text("RESET ROLE"))
        db.close()
        outer.rollback()
        conn.close()


if __name__ == "__main__":
    main()
