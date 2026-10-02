"""K-08 self-check against the live dev database, as the admin app role.
Savepoint-joined Session, everything rolled back at the end -- same pattern
as tests/test_sku_autogeneration.py.

Covers: category_id and subcategory_id filters on AdminManagementService
.get_products narrow to the right products, collection_id filters via the
product_collections bridge, a soft-deleted product is excluded from every
filtered view, and pagination totals/pages stay correct under a filter.

Run: .venv/bin/python tests/test_admin_product_filters.py
"""
import os
from datetime import datetime, timezone
from uuid import uuid4

os.environ.setdefault("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/urjaa")

from sqlalchemy import text
from sqlalchemy.orm import Session

from urjaa_core.core.database import engine
from urjaa_core.models import Category, Collection, Product, ProductCollection, Store, Subcategory
from urjaa_core.services.admin.admin_management_service import AdminManagementService as svc


def _make_product(db, store, subcategory, *, name, collection=None, deleted=False):
    product = Product(
        id=uuid4(),
        store_id=store.id,
        name=name,
        slug=f"{name.lower().replace(' ', '-')}-{uuid4().hex[:8]}",
        subcategory_id=subcategory.id,
        status="active",
        deleted_at=datetime.now(timezone.utc) if deleted else None,
    )
    db.add(product)
    db.flush()
    if collection is not None:
        db.add(ProductCollection(product_id=product.id, collection_id=collection.id))
        db.flush()
    return product


def main() -> None:
    conn = engine.connect()
    outer = conn.begin()
    db = Session(bind=conn, join_transaction_mode="create_savepoint")
    try:
        db.execute(text("SET ROLE urjaa_admin_svc"))

        store = Store(id=uuid4(), name=f"K08 Test Store {uuid4().hex[:6]}")
        db.add(store)

        cat_a = Category(name=f"K08 Cat A {uuid4().hex[:6]}", slug=f"k08-cat-a-{uuid4().hex[:8]}")
        cat_b = Category(name=f"K08 Cat B {uuid4().hex[:6]}", slug=f"k08-cat-b-{uuid4().hex[:8]}")
        db.add_all([cat_a, cat_b])
        db.flush()

        sub_a1 = Subcategory(category_id=cat_a.id, name="A1", slug=f"k08-sub-a1-{uuid4().hex[:8]}")
        sub_a2 = Subcategory(category_id=cat_a.id, name="A2", slug=f"k08-sub-a2-{uuid4().hex[:8]}")
        sub_b1 = Subcategory(category_id=cat_b.id, name="B1", slug=f"k08-sub-b1-{uuid4().hex[:8]}")
        db.add_all([sub_a1, sub_a2, sub_b1])
        db.flush()

        coll_x = Collection(name=f"K08 Coll X {uuid4().hex[:6]}", slug=f"k08-coll-x-{uuid4().hex[:8]}")
        coll_y = Collection(name=f"K08 Coll Y {uuid4().hex[:6]}", slug=f"k08-coll-y-{uuid4().hex[:8]}")
        db.add_all([coll_x, coll_y])
        db.flush()

        # p1: cat_a/sub_a1, collection X -- active
        p1 = _make_product(db, store, sub_a1, name="K08 P1", collection=coll_x)
        # p2: cat_a/sub_a2, collection Y -- active
        p2 = _make_product(db, store, sub_a2, name="K08 P2", collection=coll_y)
        # p3: cat_b/sub_b1, collection X -- active
        p3 = _make_product(db, store, sub_b1, name="K08 P3", collection=coll_x)
        # p4: cat_a/sub_a1, collection X -- soft-deleted (must never show up)
        _make_product(db, store, sub_a1, name="K08 P4 Deleted", collection=coll_x, deleted=True)
        db.flush()

        # --- category_id: both subcategories under cat_a, excludes the soft-deleted p4
        items, total = svc.get_products(db, store_id=store.id, page=1, limit=20, category_id=cat_a.id)
        assert total == 2, total
        assert {p.id for p in items} == {p1.id, p2.id}, {p.id for p in items}
        print("OK category_id filters to both subcategories under the category, deleted product excluded")

        # --- subcategory_id: narrower than category
        items, total = svc.get_products(db, store_id=store.id, page=1, limit=20, subcategory_id=sub_a1.id)
        assert total == 1 and items[0].id == p1.id, (total, items)
        print("OK subcategory_id narrows to just that subcategory")

        # --- collection_id: via the product_collections bridge, across categories, deleted excluded
        items, total = svc.get_products(db, store_id=store.id, page=1, limit=20, collection_id=coll_x.id)
        assert total == 2, total
        assert {p.id for p in items} == {p1.id, p3.id}, {p.id for p in items}
        print("OK collection_id filters via product_collections bridge, deleted product excluded")

        items, total = svc.get_products(db, store_id=store.id, page=1, limit=20, collection_id=coll_y.id)
        assert total == 1 and items[0].id == p2.id, (total, items)
        print("OK second collection isolates its own product")

        # --- deleted product never shows up unfiltered either
        items, total = svc.get_products(db, store_id=store.id, page=1, limit=20)
        assert total == 3 and all(p.id != "K08 P4 Deleted" for p in items), total
        print("OK unfiltered store list also excludes the soft-deleted product")

        # --- pagination totals/pages stay correct under a filter (cat_a: p1, p2 -> 2 total, limit=1 -> 2 pages)
        page1_items, page1_total = svc.get_products(db, store_id=store.id, page=1, limit=1, category_id=cat_a.id)
        page2_items, page2_total = svc.get_products(db, store_id=store.id, page=2, limit=1, category_id=cat_a.id)
        assert page1_total == 2 and page2_total == 2, (page1_total, page2_total)
        assert len(page1_items) == 1 and len(page2_items) == 1, (page1_items, page2_items)
        assert {page1_items[0].id, page2_items[0].id} == {p1.id, p2.id}
        print("OK pagination total/pages stay correct under a category filter (2 total, 1/page -> 2 pages, no overlap)")

        print("\nAll K-08 admin product filter checks passed.")
    finally:
        db.execute(text("RESET ROLE"))
        db.close()
        outer.rollback()
        conn.close()


if __name__ == "__main__":
    main()
