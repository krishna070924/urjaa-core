"""Duplicating a product keeps each variant's metal, size and spec note, and
each stone row's cost (H-09/H-10 fields). Live dev DB, rolled back.

Run: .venv/bin/python tests/test_duplicate_keeps_dimensions.py
"""
import os
import uuid
from decimal import Decimal

os.environ.setdefault("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/urjaa")

from sqlalchemy import text
from sqlalchemy.orm import Session

from urjaa_core.core.database import engine
from urjaa_core.models import Product, ProductStone, ProductVariant, Stone, Store
from urjaa_core.models.metal import Metal
from urjaa_core.services.admin.admin_management_service import AdminManagementService as svc


def main() -> None:
    conn = engine.connect()
    outer = conn.begin()
    db = Session(bind=conn, join_transaction_mode="create_savepoint")
    try:
        db.execute(text("SET ROLE urjaa_admin_svc"))
        store = db.query(Store).first()
        metal = db.query(Metal).filter(Metal.display_name == "22K Yellow Gold").one()
        ruby = db.query(Stone).filter(Stone.name == "Ruby").one()
        src = Product(store_id=store.id, name="Dup check", slug=f"dup-{uuid.uuid4().hex[:8]}")
        db.add(src)
        db.flush()
        db.add(ProductVariant(store_id=store.id, product_id=src.id, metal_id=metal.id, size_value="7",
                              spec_note="engraved", sku_code=f"DUP-{uuid.uuid4().hex[:8]}"))
        db.add(ProductStone(product_id=src.id, stone_id=ruby.id, quantity=1, cost=Decimal("40000"),
                            certificate_number="GIA-1", certification_agency="GIA"))
        db.flush()

        copy = svc.duplicate_product(db, store.id, src.id)
        db.expire_all()
        v = db.query(ProductVariant).filter(ProductVariant.product_id == copy.id).one()
        assert (v.metal_id, v.size_value, v.spec_note) == (metal.id, "7", "engraved"), (v.metal_id, v.size_value, v.spec_note)
        s = db.query(ProductStone).filter(ProductStone.product_id == copy.id).one()
        assert s.cost == Decimal("40000") and s.certificate_number is None, (s.cost, s.certificate_number)
        print("duplicate keeps metal/size/spec + stone cost, drops certificate  OK")
    finally:
        db.close()
        outer.rollback()
        conn.close()


if __name__ == "__main__":
    main()
