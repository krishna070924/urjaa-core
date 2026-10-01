"""H-11 self-check against the live dev database, as the admin app role.
Savepoint-joined Session, rolled back at the end -- same pattern as
tests/test_sku_autogeneration.py / tests/test_size_dimension_storefront.py.

Covers:
1. Subcategory size_label/size_unit round-trip through create/update
   (trimmed, blank -> None), and size_unit without size_label -> 422 on both
   create and update.
2. Product create/update/duplicate write gender_id (D21/H-08), not a new EAV
   gender row -- H-06 will delete those tables; nothing new should land there.
3. The admin API's gender response value derives correctly from gender_id
   (mirrors urjaa-admin-backend's _gender_value; that repo's own code isn't
   importable from here, so this proves the core data it reads is correct).
4. Storefront filter_attributes({"gender": [...]}) and
   CatalogAggregationRepository.get_gender_counts read gender_id, not EAV.

Run: urjaa-core/.venv/bin/python tests/test_subcategory_size_and_gender.py
(PYTHONPATH pointed at this worktree)
"""
import os
import uuid

os.environ.setdefault("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/urjaa")

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from urjaa_core.core.database import engine
from urjaa_core.models import Category, Product, Store, Subcategory
from urjaa_core.models.attribute import Attribute
from urjaa_core.models.attribute_value import AttributeValue
from urjaa_core.models.product_attribute import ProductAttribute
from urjaa_core.repositories.catalog_aggregation_repository import CatalogAggregationRepository
from urjaa_core.repositories.catalog_query_builder import CatalogQueryBuilder
from urjaa_core.schemas.admin.management import (
    ProductCreateRequest,
    ProductUpdateRequest,
    SubcategoryCreateRequest,
    SubcategoryUpdateRequest,
)
from urjaa_core.services.admin.admin_management_service import AdminManagementService as svc


def _gender_value(product) -> str | None:
    """Mirrors urjaa-admin-backend's app/api/routes/admin_management.py
    _gender_value (H-11)."""
    return product.gender.name.lower() if product.gender else None


def _eav_gender_row_count(db: Session, product_id) -> int:
    return (
        db.query(ProductAttribute)
        .join(AttributeValue, AttributeValue.id == ProductAttribute.attribute_value_id)
        .join(Attribute, Attribute.id == AttributeValue.attribute_id)
        .filter(ProductAttribute.product_id == product_id, Attribute.slug == "gender")
        .count()
    )


def main() -> None:
    conn = engine.connect()
    outer = conn.begin()
    db = Session(bind=conn, join_transaction_mode="create_savepoint")
    try:
        db.execute(text("SET ROLE urjaa_admin_svc"))
        store = db.query(Store).first()
        assert store is not None, "dev DB has no seeded store"

        suffix = uuid.uuid4().hex[:8]
        category = Category(name=f"H11 Test {suffix}", slug=f"h11-test-{suffix}")
        db.add(category)
        db.flush()

        # --- 1. Subcategory size round-trip ---
        created_sub = svc.create_subcategory(
            db,
            SubcategoryCreateRequest(
                category_id=category.id, name=f"H11 Rings {suffix}", size_label="Ring Size", size_unit="US"
            ),
        )
        assert created_sub.size_label == "Ring Size" and created_sub.size_unit == "US"
        print("subcategory size_label/size_unit create round-trip    OK")

        blank_sub = svc.create_subcategory(
            db,
            SubcategoryCreateRequest(category_id=category.id, name=f"H11 Plain {suffix}", size_label="  ", size_unit=None),
        )
        assert blank_sub.size_label is None and blank_sub.size_unit is None
        print("blank size_label trims to None                        OK")

        try:
            svc.create_subcategory(
                db, SubcategoryCreateRequest(category_id=category.id, name=f"H11 Bad {suffix}", size_unit="US")
            )
            raise AssertionError("expected 422")
        except HTTPException as exc:
            assert exc.status_code == 422, exc.detail
        print("size_unit without size_label -> 422 (create)          OK")

        updated_sub = svc.update_subcategory(db, created_sub.id, SubcategoryUpdateRequest(size_unit="UK"))
        assert updated_sub.size_label == "Ring Size" and updated_sub.size_unit == "UK"
        print("size_unit update onto an already-labelled subcategory OK")

        try:
            svc.update_subcategory(db, blank_sub.id, SubcategoryUpdateRequest(size_unit="US"))
            raise AssertionError("expected 422")
        except HTTPException as exc:
            assert exc.status_code == 422, exc.detail
        print("size_unit without size_label -> 422 (update)          OK")

        # --- 2 & 3. Product create/update/duplicate write gender_id, not EAV ---
        product = svc.create_product(
            db,
            store.id,
            ProductCreateRequest(
                name=f"H11 product {suffix}", category_id=category.id, subcategory_id=created_sub.id, gender="men"
            ),
        )
        db.refresh(product)
        assert product.gender_id is not None and product.gender.name == "Men"
        assert _gender_value(product) == "men"
        assert _eav_gender_row_count(db, product.id) == 0
        print("create_product writes gender_id, no EAV row           OK")

        updated_product = svc.update_product(
            db, store.id, product.id, ProductUpdateRequest(gender="women", status="active")
        )
        db.refresh(updated_product)
        assert updated_product.gender.name == "Women"
        assert _gender_value(updated_product) == "women"
        assert _eav_gender_row_count(db, product.id) == 0
        print("update_product writes gender_id, no EAV row           OK")

        duplicate = svc.duplicate_product(db, store.id, product.id)
        assert duplicate.gender_id == updated_product.gender_id
        print("duplicate_product carries gender_id forward           OK")

        try:
            svc._resolve_gender_id(db, "nonbinary")
            raise AssertionError("expected 422")
        except HTTPException as exc:
            assert exc.status_code == 422, exc.detail
        print("unknown gender -> 422                                 OK")

        # --- 4. Storefront detail/filter by gender (not EAV) ---
        matched = (
            CatalogQueryBuilder(db.query(Product.id), store_id=store.id)
            .apply_filters({"subcategory": created_sub.slug})
            .filter_attributes({"gender": ["women"]})
            .only_active()
            .build()
            .distinct()
            .all()
        )
        assert [row[0] for row in matched] == [product.id], matched
        print("storefront filter_attributes(gender=women) matches    OK")

        no_match = (
            CatalogQueryBuilder(db.query(Product.id), store_id=store.id)
            .apply_filters({"subcategory": created_sub.slug})
            .filter_attributes({"gender": ["men"]})
            .only_active()
            .build()
            .distinct()
            .all()
        )
        assert product.id not in [row[0] for row in no_match], no_match
        print("storefront filter_attributes(gender=men) excludes     OK")

        base_query = CatalogAggregationRepository.build_base_subquery(
            db, store.id, {"subcategory": created_sub.slug}, None
        )
        buckets = {b["value"]: b for b in CatalogAggregationRepository.get_gender_counts(db, base_query)}
        assert buckets.get("Women", {}).get("count") == 1, buckets
        print("get_gender_counts facet                                OK", buckets)
    finally:
        db.close()
        outer.rollback()
        conn.close()


if __name__ == "__main__":
    main()
    print("ok")
