"""N-01 self-check against the live dev database, as the admin app role.
Same pattern as test_sku_autogeneration.py: joined to an outer transaction
via savepoints, everything rolled back at the end. Service calls that commit
internally (create_variant) advance to their own savepoint; add_units/
update_unit don't commit on their own (the API route does that), so this
test commits explicitly after each one it wants to survive a later rollback.

Run: .venv/bin/python tests/test_gifting.py
"""
import os
import uuid
from decimal import Decimal

os.environ.setdefault("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/urjaa")

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from urjaa_core.core.database import engine
from urjaa_core.models import BaseMetal, Metal, MetalPurity, MetalRate, Product, Store
from urjaa_core.schemas.admin.management import VariantCreateRequest
from urjaa_core.services import physical_unit_service
from urjaa_core.services.admin.admin_management_service import AdminManagementService as svc
from urjaa_core.services.pricing_service import PricingService, round_money


def main() -> None:
    conn = engine.connect()
    outer = conn.begin()
    db = Session(bind=conn, join_transaction_mode="create_savepoint")
    try:
        db.execute(text("SET ROLE urjaa_admin_svc"))
        store = db.query(Store).first()
        product = Product(store_id=store.id, name="Gifting check", slug=f"gifting-{uuid.uuid4().hex[:8]}")
        db.add(product)
        db.flush()

        # -- D37: fixed price (no metal) prices at its override --------------
        fixed = svc.create_variant(db, store.id, product.id, VariantCreateRequest(price_override=4999))
        assert fixed.metal_id is None and fixed.base_metal_id is None
        assert PricingService.calculate_variant_price(fixed, db) == Decimal("4999.00")
        print("fixed-price variant (no metal) prices at override   OK")

        # -- D37: by metal weight prices weight x rate x purity + making -----
        metal = (
            db.query(Metal)
            .join(BaseMetal, BaseMetal.id == Metal.base_metal_id)
            .join(MetalPurity, MetalPurity.id == Metal.metal_purity_id)
            .filter(BaseMetal.name == "Silver", MetalPurity.purity_label == "999")
            .first()
        )
        assert metal is not None, "999 Silver combination missing -- run the Gifting dev-data block first"
        rate = (
            db.query(MetalRate.rate_per_gram)
            .filter(MetalRate.base_metal_id == metal.base_metal_id)
            .order_by(MetalRate.effective_from.desc())
            .limit(1)
            .scalar()
        )
        purity = db.query(MetalPurity.numeric_purity).filter(MetalPurity.id == metal.metal_purity_id).scalar()

        weighed = svc.create_variant(
            db, store.id, product.id, VariantCreateRequest(metal_id=metal.id, weight=10, making_charges=50)
        )
        assert weighed.price_override is None
        expected = round_money(Decimal(10) * Decimal(rate) * Decimal(purity) / Decimal(100) + Decimal(50))
        got = PricingService.calculate_variant_price(weighed, db)
        assert got == expected, (got, expected)
        print(f"by-metal-weight variant prices weight x rate         OK  {got}")

        # -- Piece serial number: saved/trimmed, HUID stays optional ---------
        first = physical_unit_service.add_units(
            db, store.id, fixed.id, [{"serial_number": "  WATCH-001  ".strip() or None, "huid_number": None}]
        )
        db.commit()
        assert first[0].serial_number == "WATCH-001" and first[0].huid_number is None
        print("serial number saved trimmed, HUID optional           OK")

        # -- Unique per variant, not global ------------------------------------
        try:
            physical_unit_service.add_units(db, store.id, fixed.id, [{"serial_number": "WATCH-001"}])
            raise AssertionError("duplicate serial on the same variant was accepted")
        except HTTPException as exc:
            assert exc.status_code == 409, exc.detail
        print("duplicate serial, same variant -> 409                OK")

        other = physical_unit_service.add_units(db, store.id, weighed.id, [{"serial_number": "WATCH-001"}])
        db.commit()
        assert other[0].serial_number == "WATCH-001"
        print("same serial, different variant -> allowed            OK")
    finally:
        db.close()
        outer.rollback()
        conn.close()


if __name__ == "__main__":
    main()
