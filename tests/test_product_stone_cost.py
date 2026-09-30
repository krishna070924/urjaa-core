"""H-09 self-check against the live dev database. Everything runs in one
transaction that is rolled back, so no fixtures are left behind.

Run: DATABASE_URL=postgresql://postgres:postgres@localhost:5432/urjaa \
       .venv/bin/python tests/test_product_stone_cost.py
"""
import os
import uuid
from decimal import Decimal

os.environ.setdefault("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/urjaa")

from sqlalchemy.exc import IntegrityError

from urjaa_core.core.database import SessionLocal
from urjaa_core.models import Product, ProductStone, ProductVariant, Stone, Store
from urjaa_core.models.metal import Metal
from urjaa_core.services.pricing_service import PricingService


def main() -> None:
    db = SessionLocal()
    try:
        store = db.query(Store).first()
        ruby = db.query(Stone).filter(Stone.name == "Ruby").first()
        metal = db.query(Metal).filter(Metal.display_name == "22K Yellow Gold").first()
        assert store and ruby and metal, "run scripts/seed_dev_catalogue.sql first"

        product = Product(store_id=store.id, name="Stone cost check", slug=f"stone-cost-{uuid.uuid4().hex[:8]}")
        db.add(product)
        db.flush()

        variant = ProductVariant(
            store_id=store.id, product_id=product.id, metal_id=metal.id,
            base_metal_id=metal.base_metal_id, metal_purity_id=metal.metal_purity_id,
            metal_weight_grams=Decimal("5.000"), making_charges=Decimal("8000"),
            stone_cost=Decimal("12000"), sku_code=f"H09-{uuid.uuid4().hex[:8]}",
        )
        db.add(variant)
        db.flush()
        db.refresh(product)

        # 1. No per-stone cost recorded -> legacy variant.stone_cost is used.
        legacy = PricingService.calculate_variant_price(variant, db)
        weight_value = legacy - Decimal("12000") - Decimal("8000")
        print(f"legacy fallback price          {legacy}")

        # 2. Two rubies on one product — impossible before H-09.
        db.add_all([
            ProductStone(product_id=product.id, stone_id=ruby.id, quantity=1,
                         total_carat_weight=Decimal("1.200"), cost=Decimal("40000")),
            ProductStone(product_id=product.id, stone_id=ruby.id, quantity=2,
                         total_carat_weight=Decimal("0.600"), cost=Decimal("15000")),
        ])
        db.flush()
        db.expire(product)
        print("two rubies on one product       allowed  OK")

        # 3. Per-stone costs present -> their sum replaces variant.stone_cost.
        summed = PricingService.calculate_variant_price(variant, db)
        assert summed == weight_value + Decimal("55000") + Decimal("8000"), summed
        print(f"summed stone cost price         {summed}  OK (55000 of stones, not 12000)")

        # 4. Negative cost rejected by the DB.
        db.add(ProductStone(product_id=product.id, stone_id=ruby.id, quantity=1, cost=Decimal("-1")))
        try:
            db.flush()
            raise AssertionError("negative cost was accepted")
        except IntegrityError:
            print("negative stone cost             rejected OK")
        print("ALL OK")
    finally:
        db.rollback()
        db.close()


if __name__ == "__main__":
    main()
