"""Review 10: products created in one bulk upload share a timestamp; the admin
product list must still page through them with no repeats or gaps.

Run: .venv/bin/python tests/test_product_list_stable_order.py
"""
import os

os.environ.setdefault("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/urjaa")

from datetime import datetime
from uuid import uuid4

from sqlalchemy.orm import Session

from urjaa_core.core.database import engine
from urjaa_core.models.product import Product
from urjaa_core.models.store import Store
from urjaa_core.services.admin.admin_management_service import AdminManagementService


def main() -> None:
    conn = engine.connect()
    outer = conn.begin()
    db = Session(bind=conn, join_transaction_mode="create_savepoint")
    try:
        store = db.query(Store).first()
        same = datetime(2030, 1, 1, 12, 0, 0)  # newer than real data -> first pages
        tag = uuid4().hex[:6]
        for i in range(45):
            db.add(Product(id=uuid4(), store_id=store.id, name=f"QA stable {tag} {i:02d}", slug=f"qa-stable-{tag}-{i}",
                           status="active", created_at=same, updated_at=same))
        db.flush()
        seen = []
        for page in (1, 2, 3):
            items, _ = AdminManagementService.get_products_global(db, page=page, limit=20)
            seen += [item["product"].name for item in items if item["product"].name.startswith(f"QA stable {tag}")]
        assert len(seen) == 45 and len(set(seen)) == 45, (len(seen), len(set(seen)))
        again, _ = AdminManagementService.get_products_global(db, page=2, limit=20)
        first, _ = AdminManagementService.get_products_global(db, page=2, limit=20)
        assert [i["product"].id for i in again] == [i["product"].id for i in first]
        print("product list: equal timestamps page without repeats, stable order  OK")
    finally:
        db.close()
        outer.rollback()
        conn.close()


if __name__ == "__main__":
    main()
