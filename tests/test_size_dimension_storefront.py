"""J-01 self-check: the storefront size picker needs three things from core
that did not exist before this change — none of them required a migration,
H-01 already shipped `size_value` and `subcategory.size_label`/`size_unit`:

1. `Product.size_label` / `size_unit` properties (so `ProductDetailResponse`
   can expose them without the storefront parsing `attribute_label`).
2. `CatalogQueryBuilder.filter_size` (so `?size=6` actually narrows results).
3. `CatalogAggregationRepository.get_size_counts` (the PLP facet), grouped by
   subcategory label/unit too so two subcategories that happen to share a raw
   value (a ring's "6" vs a bangle's "6") don't merge into one facet bucket.

Part 1 is a pure property check (SimpleNamespace, no DB), same pattern as
tests/test_variant_attribute_label.py. Part 2 runs against the live dev
database inside a rolled-back transaction, same pattern as
tests/test_sku_autogeneration.py — the dev catalogue is otherwise empty, so
this both proves the feature works and leaves no data behind.

Run: urjaa-core/.venv/bin/python tests/test_size_dimension_storefront.py
(PYTHONPATH pointed at this worktree)
"""
import os
import uuid
from types import SimpleNamespace

os.environ.setdefault("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/urjaa")

from sqlalchemy import text
from sqlalchemy.orm import Session

from urjaa_core.core.database import engine
from urjaa_core.models import Category, Product, ProductVariant, Store, Subcategory
from urjaa_core.models.product import Product as ProductModel
from urjaa_core.repositories.catalog_aggregation_repository import CatalogAggregationRepository
from urjaa_core.repositories.catalog_query_builder import CatalogQueryBuilder

_size_label = ProductModel.size_label.fget
_size_unit = ProductModel.size_unit.fget


def test_size_label_properties_pure() -> None:
    with_sub = SimpleNamespace(subcategory=SimpleNamespace(size_label="Ring Size", size_unit="US"))
    assert _size_label(with_sub) == "Ring Size"
    assert _size_unit(with_sub) == "US"

    no_sub = SimpleNamespace(subcategory=None)
    assert _size_label(no_sub) is None
    assert _size_unit(no_sub) is None

    # A subcategory that doesn't vary by size (the common case) — both null.
    unsized_sub = SimpleNamespace(subcategory=SimpleNamespace(size_label=None, size_unit=None))
    assert _size_label(unsized_sub) is None
    assert _size_unit(unsized_sub) is None

    print("Product.size_label/size_unit          OK")


def test_size_filter_and_facet_live() -> None:
    conn = engine.connect()
    outer = conn.begin()
    db = Session(bind=conn, join_transaction_mode="create_savepoint")
    try:
        db.execute(text("SET ROLE urjaa_admin_svc"))
        store = db.query(Store).first()
        assert store is not None, "dev DB has no seeded store"

        suffix = uuid.uuid4().hex[:8]
        category = Category(name=f"J01 Test {suffix}", slug=f"j01-test-{suffix}")
        db.add(category)
        db.flush()

        subcategory = Subcategory(
            name=f"J01 Rings {suffix}",
            slug=f"j01-rings-{suffix}",
            category_id=category.id,
            size_label="Ring Size",
            size_unit="US",
        )
        db.add(subcategory)
        db.flush()

        product = Product(
            store_id=store.id,
            name=f"J01 size check {suffix}",
            slug=f"j01-size-check-{suffix}",
            subcategory_id=subcategory.id,
            status="active",
        )
        db.add(product)
        db.flush()

        variant_6 = ProductVariant(
            store_id=store.id,
            product_id=product.id,
            sku_code=f"J01-{suffix}-A",
            size_value="6",
            stock_quantity=1,
        )
        variant_7 = ProductVariant(
            store_id=store.id,
            product_id=product.id,
            sku_code=f"J01-{suffix}-B",
            size_value="7",
            stock_quantity=1,
        )
        db.add_all([variant_6, variant_7])
        db.flush()

        # --- filter_size: ?size=6 narrows to exactly this product ---
        id_query = db.query(Product.id)
        matched = (
            CatalogQueryBuilder(id_query, store_id=store.id)
            .apply_filters({"subcategory": subcategory.slug, "size": "6"})
            .only_active()
            .build()
            .distinct()
            .all()
        )
        assert [row[0] for row in matched] == [product.id], matched
        print("filter_size narrows to size=6          OK")

        no_match = (
            CatalogQueryBuilder(db.query(Product.id), store_id=store.id)
            .apply_filters({"subcategory": subcategory.slug, "size": "12"})
            .only_active()
            .build()
            .distinct()
            .all()
        )
        assert no_match == [], no_match
        print("filter_size excludes non-matching size OK")

        # --- get_size_counts: one facet bucket per size_value, labelled ---
        base_query = CatalogAggregationRepository.build_base_subquery(
            db, store.id, {"subcategory": subcategory.slug}, None
        )
        buckets = {b["size"]: b for b in CatalogAggregationRepository.get_size_counts(db, base_query)}
        assert buckets.keys() == {"6", "7"}, buckets
        assert buckets["6"]["label"] == "Ring Size" and buckets["6"]["unit"] == "US"
        assert buckets["6"]["count"] == 1 and buckets["7"]["count"] == 1
        print("get_size_counts facet buckets           OK", buckets)
    finally:
        db.close()
        outer.rollback()
        conn.close()


if __name__ == "__main__":
    test_size_label_properties_pure()
    test_size_filter_and_facet_live()
    print("ok")
