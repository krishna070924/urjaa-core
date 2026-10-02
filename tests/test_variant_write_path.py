"""H-10 self-check against the live dev database, as the admin app role.
AdminManagementService.create_variant/update_variant/update_product_stones
commit internally, so (same reasoning as tests/test_sku_autogeneration.py)
the session is joined to an outer transaction via savepoints and everything
is rolled back at the end -- no fixtures left behind.

H-05 gave the admin API read access to metal_id/size_value/spec_note and
product_stones.cost; this ticket (H-10) is the write side. Proves:

1. create_variant(metal_id=...) also writes the legacy base_metal_id/
   metal_color_id/metal_purity_id from the Metal row (D25) so old readers
   stay consistent.
2. create_variant(legacy triad of an existing combo) resolves metal_id.
2b. A legacy triad with no matching `metals` row leaves metal_id null --
    legacy-only requests keep working unchanged.
3. metal_id + a conflicting legacy id -> 422.
4. Unknown metal_id -> 404.
5. size_value round-trips (stripped) and attribute_label reflects it (D21).
6. update_variant resolves metal_id from a legacy triad too.
7. Per-stone cost persists via update_product_stones and
   PricingService.calculate_variant_price changes by exactly that amount
   (H-09 pricing itself is untouched -- this only proves the field is now
   writable end to end).

Run: .venv/bin/python tests/test_variant_write_path.py
"""
import os
import uuid
from decimal import Decimal

os.environ.setdefault("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/urjaa")

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from urjaa_core.core.database import engine
from urjaa_core.models import Metal, MetalColor, MetalPurity, Product, ProductStone, Stone, Store, Subcategory
from urjaa_core.schemas.admin.management import (
    ProductStonesUpdateRequest,
    StoneAssignmentItem,
    VariantCreateRequest,
    VariantUpdateRequest,
)
from urjaa_core.services.admin.admin_management_service import AdminManagementService as svc
from urjaa_core.services.pricing_service import PricingService


def main() -> None:
    conn = engine.connect()
    outer = conn.begin()
    db = Session(bind=conn, join_transaction_mode="create_savepoint")
    try:
        db.execute(text("SET ROLE urjaa_admin_svc"))

        store = db.query(Store).first()
        gold_22k = db.query(Metal).filter(Metal.display_name == "22K Yellow Gold").first()
        gold_14k_white = db.query(Metal).filter(Metal.display_name == "14K White Gold").first()
        sized_subcategory = db.query(Subcategory).filter(Subcategory.size_label.isnot(None)).first()
        ruby = db.query(Stone).first()
        assert gold_22k and gold_14k_white and sized_subcategory and ruby, (
            "run scripts/seed_dev_catalogue.sql first"
        )
        # Case (2b) below needs a (colour, purity) pair under Gold with no
        # `metals` row -- found dynamically rather than hardcoded, so a later
        # seed addition (e.g. N-01's 24K Yellow Gold) can't silently turn a
        # hardcoded "known missing" triad into a false assertion.
        gold_colour_ids = [c.id for c in db.query(MetalColor).filter(MetalColor.base_metal_id == gold_22k.base_metal_id)]
        gold_purity_ids = [p.id for p in db.query(MetalPurity).filter(MetalPurity.base_metal_id == gold_22k.base_metal_id)]
        existing_gold_combos = {
            (m.metal_color_id, m.metal_purity_id)
            for m in db.query(Metal).filter(Metal.base_metal_id == gold_22k.base_metal_id)
        }
        missing_combo = next(
            (c, p) for c in gold_colour_ids for p in gold_purity_ids if (c, p) not in existing_gold_combos
        )

        product = Product(
            store_id=store.id, name="H10 check", slug=f"h10-{uuid.uuid4().hex[:8]}",
            status="active", subcategory_id=sized_subcategory.id,
        )
        db.add(product)
        db.flush()

        # 1. metal_id given -> legacy ids also written from the Metal row.
        v1 = svc.create_variant(db, store.id, product.id, VariantCreateRequest(metal_id=gold_22k.id))
        assert v1.metal_id == gold_22k.id
        assert v1.base_metal_id == gold_22k.base_metal_id
        assert v1.metal_color_id == gold_22k.metal_color_id
        assert v1.metal_purity_id == gold_22k.metal_purity_id
        print("create(metal_id)              -> legacy ids also set   OK")

        # 2. Legacy triad of an existing combo resolves metal_id.
        v2 = svc.create_variant(
            db, store.id, product.id,
            VariantCreateRequest(
                base_metal_id=gold_14k_white.base_metal_id,
                metal_color_id=gold_14k_white.metal_color_id,
                metal_purity_id=gold_14k_white.metal_purity_id,
            ),
        )
        assert v2.metal_id == gold_14k_white.id, v2.metal_id
        print("create(legacy triad, known combo)  -> metal_id resolved OK")

        # 2b. Legacy triad naming individually-valid ids with no `metals` row
        # for that exact combination -> metal_id stays null.
        v2b = svc.create_variant(
            db, store.id, product.id,
            VariantCreateRequest(
                base_metal_id=gold_22k.base_metal_id, metal_color_id=missing_combo[0], metal_purity_id=missing_combo[1]
            ),
        )
        assert v2b.metal_id is None, v2b.metal_id
        print("create(legacy triad, no combo)     -> metal_id null     OK")

        # 3. metal_id + a conflicting legacy id -> 422.
        try:
            svc.create_variant(
                db, store.id, product.id,
                VariantCreateRequest(metal_id=gold_22k.id, metal_purity_id=gold_14k_white.metal_purity_id),
            )
            raise AssertionError("conflicting ids accepted")
        except HTTPException as exc:
            assert exc.status_code == 422, exc.status_code
        print("create(metal_id + conflicting leg) -> 422               OK")

        # 4. Unknown metal_id -> 404.
        try:
            svc.create_variant(db, store.id, product.id, VariantCreateRequest(metal_id=999999))
            raise AssertionError("unknown metal_id accepted")
        except HTTPException as exc:
            assert exc.status_code == 404, exc.status_code
        print("create(unknown metal_id)           -> 404               OK")

        # 5. size_value round-trips (stripped) and attribute_label reflects it.
        v5 = svc.create_variant(db, store.id, product.id, VariantCreateRequest(size_value="  7  ", spec_note="engraved"))
        assert v5.size_value == "7", v5.size_value
        assert v5.spec_note == "engraved", v5.spec_note
        assert v5.attribute_label and "7" in v5.attribute_label, v5.attribute_label
        print(f"size_value round-trips, attribute_label reflects it     OK  {v5.attribute_label!r}")

        # 6. update_variant resolves metal_id from a legacy triad too.
        blank = svc.create_variant(db, store.id, product.id, VariantCreateRequest())
        assert blank.metal_id is None
        updated = svc.update_variant(
            db, store.id, blank.id,
            VariantUpdateRequest(
                base_metal_id=gold_22k.base_metal_id,
                metal_color_id=gold_22k.metal_color_id,
                metal_purity_id=gold_22k.metal_purity_id,
            ),
        )
        assert updated.metal_id == gold_22k.id, updated.metal_id
        print("update(legacy triad)               -> metal_id resolved OK")

        # 6b. Changing only the colour must move metal_id to the new combination.
        y18 = db.query(Metal).filter(Metal.display_name == "18K Yellow Gold").one()
        w18 = db.query(Metal).filter(Metal.display_name == "18K White Gold").one()
        v6 = svc.create_variant(db, store.id, product.id, VariantCreateRequest(metal_id=y18.id))
        v6 = svc.update_variant(db, store.id, v6.id, VariantUpdateRequest(metal_color_id=w18.metal_color_id))
        assert v6.metal_id == w18.id, v6.metal_id
        print("update(colour only)                -> metal_id follows OK")

        # 7. Per-stone cost persists and PricingService reflects it.
        priced = svc.create_variant(
            db, store.id, product.id,
            VariantCreateRequest(metal_id=gold_22k.id, metal_weight_grams=5, making_charges=1000),
        )
        db.refresh(product)
        before = PricingService.calculate_variant_price(priced, db)
        assert before is not None, "seeded Gold rate missing -- run scripts/seed_dev_catalogue.sql first"

        svc.update_product_stones(
            db, store.id, product.id,
            ProductStonesUpdateRequest(stones=[StoneAssignmentItem(stone_id=ruby.id, quantity=1, cost=Decimal("9999.99"))]),
        )
        row = db.query(ProductStone).filter_by(product_id=product.id).one()
        assert row.cost == Decimal("9999.99"), row.cost

        db.expire(product)
        after = PricingService.calculate_variant_price(priced, db)
        assert after == before + Decimal("9999.99"), (before, after)
        print(f"stone cost persists, price +9999.99                     OK  {before} -> {after}")

        print("ALL OK")
    finally:
        db.close()
        outer.rollback()
        conn.close()


if __name__ == "__main__":
    main()
