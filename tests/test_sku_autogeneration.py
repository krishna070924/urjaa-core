"""H-04 self-check against the live dev database, as the admin app role.
The service commits internally, so the session is joined to an outer
transaction via savepoints and everything is rolled back at the end.

Run: .venv/bin/python tests/test_sku_autogeneration.py
"""
import os
import re
import uuid
from concurrent.futures import ThreadPoolExecutor

os.environ.setdefault("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/urjaa")

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from urjaa_core.core.database import SessionLocal, engine
from urjaa_core.models import Product, Store, Subcategory
from urjaa_core.schemas.admin.management import VariantCreateRequest
from urjaa_core.services.admin.admin_management_service import AdminManagementService as svc


def draw(_):
    with SessionLocal() as db:
        db.execute(text("SET ROLE urjaa_admin_svc"))
        return svc._next_sku(db, Product())


def main() -> None:
    # Concurrency: 40 simultaneous draws on separate connections never collide.
    with ThreadPoolExecutor(max_workers=10) as pool:
        skus = list(pool.map(draw, range(40)))
    assert len(set(skus)) == 40 and all(re.fullmatch(r"URJ-\d{6}", s) for s in skus), skus
    print("40 concurrent draws, all unique   OK")

    conn = engine.connect()
    outer = conn.begin()
    db = Session(bind=conn, join_transaction_mode="create_savepoint")
    try:
        db.execute(text("SET ROLE urjaa_admin_svc"))
        store = db.query(Store).first()
        sub = db.query(Subcategory).filter(Subcategory.category.has(name="Rings")).first()
        product = Product(store_id=store.id, name="SKU check", slug=f"sku-{uuid.uuid4().hex[:8]}", subcategory_id=sub.id if sub else None)
        db.add(product)
        db.flush()

        made = [svc.create_variant(db, store.id, product.id, VariantCreateRequest()).sku_code for _ in range(5)]
        prefix = "RIN" if sub else "URJ"
        assert len(set(made)) == 5 and all(s.startswith(prefix + "-") for s in made), made
        print(f"5 blank SKUs generated           OK  {made[0]} .. {made[-1]}")

        own = f"MY-{uuid.uuid4().hex[:6]}"
        assert svc.create_variant(db, store.id, product.id, VariantCreateRequest(sku_code=own)).sku_code == own
        print("explicit SKU honoured             OK")

        try:
            svc.create_variant(db, store.id, product.id, VariantCreateRequest(sku_code=own.lower()))
            raise AssertionError("duplicate accepted")
        except HTTPException as exc:
            assert exc.status_code == 409 and own.lower() in exc.detail, exc.detail
        print("duplicate -> readable 409         OK")
    finally:
        db.close()
        outer.rollback()
        conn.close()


if __name__ == "__main__":
    main()
