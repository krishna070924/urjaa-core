"""H-05 self-check against the live dev database, as the admin app role.

AdminManagementService.update_product_stones commits internally, so (same
reasoning as tests/test_sku_autogeneration.py) the session is joined to an
outer transaction via savepoints and everything is rolled back at the end --
no fixtures left behind.

Proves three things that shipped across H-01/H-02/H-03/H-07 but were never
wired into the admin-facing schemas or the contract docs:

1. AdminVariantResponse reports the current variant shape -- size_value,
   metal_id, and the *_name/_label properties that resolve through it --
   instead of only the legacy base_metal_id/metal_color_id/metal_purity_id.
2. An order line's reserved physical piece exposes its HUID through
   AdminOrderItemResponse.huid_numbers; the storefront-facing
   OrderItemResponse does NOT carry it -- HUIDs are staff-only (D22).
3. Stone certification fields (cut/clarity/.../certification_agency) --
   B-03's admin-backend-local duplicate -- now round-trip through core's
   AdminManagementService.update_product_stones.

Run: .venv/bin/python tests/test_h05_contract_schemas.py
"""
import os
import uuid
from decimal import Decimal

os.environ.setdefault("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/urjaa")

from sqlalchemy import text
from sqlalchemy.orm import Session

from urjaa_core.core.database import engine
from urjaa_core.models import (
    Metal,
    Order,
    OrderItem,
    Product,
    ProductStone,
    ProductVariant,
    Stone,
    Store,
    Subcategory,
    UnitStatus,
    VariantPhysicalUnit,
)
from urjaa_core.schemas.admin.management import (
    AdminVariantResponse,
    ProductStonesUpdateRequest,
    StoneAssignmentItem,
)
from urjaa_core.schemas.admin.sales import AdminOrderItemResponse
from urjaa_core.schemas.order import OrderItemResponse
from urjaa_core.services import physical_unit_service as units
from urjaa_core.services.admin.admin_management_service import AdminManagementService as svc


def main() -> None:
    conn = engine.connect()
    outer = conn.begin()
    db = Session(bind=conn, join_transaction_mode="create_savepoint")
    try:
        db.execute(text("SET ROLE urjaa_admin_svc"))

        store = db.query(Store).first()
        metal = db.query(Metal).first()
        assert metal is not None, "expected at least one seeded `metals` row (H-07)"
        sized_subcategory = db.query(Subcategory).filter(Subcategory.size_label.isnot(None)).first()

        product = Product(
            store_id=store.id,
            name="H05 check",
            slug=f"h05-{uuid.uuid4().hex[:8]}",
            status="active",
            subcategory_id=sized_subcategory.id if sized_subcategory else None,
        )
        db.add(product)
        db.flush()

        variant = ProductVariant(
            store_id=store.id,
            product_id=product.id,
            stock_quantity=4,
            sku_code=f"H05-{uuid.uuid4().hex[:8]}",
            metal_id=metal.id,
            size_value="6",
            spec_note="engraved",
        )
        db.add(variant)
        db.flush()

        # --- 1. AdminVariantResponse reports the current shape -------------
        out = AdminVariantResponse.model_validate(variant, from_attributes=True)
        assert out.size_value == "6" and out.spec_note == "engraved", out
        assert out.metal_id == metal.id, out
        assert out.base_metal_name == metal.base_metal.name, out
        assert out.metal_color_name == (metal.metal_color.name if metal.metal_color else None), out
        assert out.metal_purity_label == metal.metal_purity.purity_label, out
        assert out.attribute_label and "6" in out.attribute_label, out
        print(f"AdminVariantResponse: size_value/metal_id/*_name present   OK  {out.attribute_label!r}")

        # --- 2. Order item HUID is admin-only -------------------------------
        in_stock = db.query(UnitStatus).filter_by(code="in_stock").one().id
        piece = VariantPhysicalUnit(variant_id=variant.id, status_id=in_stock, huid_number="H05AA1")
        db.add(piece)
        db.flush()

        order = Order(store_id=store.id, total_amount=Decimal("1"))
        db.add(order)
        db.flush()
        line = OrderItem(
            order_id=order.id, store_id=store.id, product_id=product.id, variant_id=variant.id,
            product_name="x", quantity=1, unit_price=Decimal("1"), line_total=Decimal("1"),
        )
        db.add(line)
        db.flush()
        units.take_units(db, variant.id, 1, order_item=line)
        db.refresh(line)

        admin_item = AdminOrderItemResponse.model_validate(line, from_attributes=True)
        assert admin_item.huid_numbers == ["H05AA1"], admin_item.huid_numbers
        print(f"AdminOrderItemResponse exposes reserved HUID               OK  {admin_item.huid_numbers}")

        storefront_item = OrderItemResponse.model_validate(line, from_attributes=True)
        assert not hasattr(storefront_item, "huid_numbers"), "HUID leaked onto the storefront schema"
        print("storefront OrderItemResponse has no huid_numbers field     OK")

        # --- 3. B-03 stone certification folded back into core -------------
        stone = Stone(name=f"H05Stone-{uuid.uuid4().hex[:6]}")
        db.add(stone)
        db.flush()
        payload = ProductStonesUpdateRequest(
            stones=[
                StoneAssignmentItem(
                    stone_id=stone.id, quantity=1, total_carat_weight=1.1,
                    cut="Oval", clarity="VS1", color="Red", origin="Burma",
                    certificate_number="GIA-1", certification_agency="GIA",
                )
            ]
        )
        svc.update_product_stones(db, store_id=store.id, product_id=product.id, payload=payload)
        row = db.query(ProductStone).filter_by(product_id=product.id).one()
        assert row.certification_agency == "GIA" and row.cut == "Oval", row
        print("core update_product_stones persists certification fields   OK")
    finally:
        db.close()
        outer.rollback()
        conn.close()


if __name__ == "__main__":
    main()
    print("ALL OK")
