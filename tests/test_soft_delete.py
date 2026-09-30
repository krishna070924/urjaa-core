"""H-08 self-check against the live dev database.

Proves: a soft-deleted product (deleted_at set) disappears from every
storefront read path (list, detail, search) and the default admin list,
while an order_item that already references it keeps loading fine.

AdminManagementService.delete_product commits internally, so the session is
joined to an outer transaction via savepoints (same pattern as
test_sku_autogeneration.py) and everything is rolled back at the end.

Run: .venv/bin/python tests/test_soft_delete.py
"""
import os
import uuid
from decimal import Decimal

os.environ.setdefault("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/urjaa")

from sqlalchemy import text
from sqlalchemy.orm import Session

from urjaa_core.core.database import engine
from urjaa_core.models import Order, OrderItem, Product, ProductVariant, Store
from urjaa_core.services.admin.admin_management_service import AdminManagementService as admin_svc
from urjaa_core.services.product_service import ProductService
from urjaa_core.services.search_service import SearchService


def main() -> None:
    conn = engine.connect()
    outer = conn.begin()
    db = Session(bind=conn, join_transaction_mode="create_savepoint")
    try:
        db.execute(text("SET ROLE urjaa_admin_svc"))
        store = db.query(Store).first()

        slug = f"soft-delete-{uuid.uuid4().hex[:8]}"
        name = f"Soft Delete Check {uuid.uuid4().hex[:6]}"
        product = Product(store_id=store.id, name=name, slug=slug, status="active")
        db.add(product)
        db.flush()
        variant = ProductVariant(
            store_id=store.id, product_id=product.id, stock_quantity=3,
            sku_code=f"H08-{uuid.uuid4().hex[:8]}",
        )
        db.add(variant)
        db.flush()

        order = Order(store_id=store.id, total_amount=Decimal("1"))
        db.add(order)
        db.flush()
        item = OrderItem(
            order_id=order.id, store_id=store.id, product_id=product.id, variant_id=variant.id,
            product_name=product.name, quantity=1, unit_price=Decimal("1"), line_total=Decimal("1"),
        )
        db.add(item)
        db.flush()

        # --- Before delete: visible on storefront and in the admin list ---
        db.execute(text("SET ROLE urjaa_storefront"))
        assert ProductService.get_product(db, store_id=store.id, slug=slug) is not None
        listing = ProductService.get_products(db, store_id=store.id, page=1, limit=100)
        assert any(p.id == product.id for p in listing["items"]), "product missing from storefront list before delete"

        db.execute(text("SET ROLE urjaa_admin_svc"))
        admin_items, _ = admin_svc.get_products(db, store_id=store.id, page=1, limit=100)
        assert any(p.id == product.id for p in admin_items), "product missing from admin list before delete"
        print("product visible before delete   OK")

        # --- Soft delete it ---
        admin_svc.delete_product(db, store_id=store.id, product_id=product.id)
        db.refresh(product)
        assert product.deleted_at is not None, "delete_product must set deleted_at (soft delete)"
        assert db.get(ProductVariant, variant.id) is not None, "soft delete must not remove variants"
        print("admin delete sets deleted_at    OK")

        # --- Storefront: gone from list, detail 404s (None), gone from search ---
        db.execute(text("SET ROLE urjaa_storefront"))
        listing = ProductService.get_products(db, store_id=store.id, page=1, limit=100)
        assert not any(p.id == product.id for p in listing["items"]), "deleted product still in storefront list"

        assert ProductService.get_product(db, store_id=store.id, slug=slug) is None, "deleted product still resolves by slug"

        results, _ = SearchService.search_products(
            db, store_id=store.id, query=name, filters={}, attributes=None, page=1, limit=20,
        )
        assert not any(p.id == product.id for p in results), "deleted product still in search results"
        print("storefront list/detail/search hide it   OK")

        # --- Admin: gone from the default list ---
        db.execute(text("SET ROLE urjaa_admin_svc"))
        admin_items, _ = admin_svc.get_products(db, store_id=store.id, page=1, limit=100)
        assert not any(p.id == product.id for p in admin_items), "deleted product still in admin list"
        print("admin list hides it             OK")

        # --- Order history: unaffected ---
        db.expire(item)
        reloaded_item = db.get(OrderItem, item.id)
        assert reloaded_item is not None and reloaded_item.product_id == product.id
        assert reloaded_item.product is not None and reloaded_item.product.deleted_at is not None
        assert reloaded_item.variant is not None
        print("order history still loads it    OK")
    finally:
        db.close()
        outer.rollback()
        conn.close()


if __name__ == "__main__":
    main()
    print("OK")
