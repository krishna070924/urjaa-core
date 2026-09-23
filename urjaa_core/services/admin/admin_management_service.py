from uuid import UUID
import re
import logging
from typing import Callable

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy import or_
from sqlalchemy.orm import Session

from urjaa_core.models.product import Product
from urjaa_core.models.product_image import ProductImage
from urjaa_core.models.product_attribute import ProductAttribute
from urjaa_core.models.product_collection import ProductCollection
from urjaa_core.models.product_tag import ProductTag
from urjaa_core.models.product_stone import ProductStone
from urjaa_core.models.product_variant import ProductVariant
from urjaa_core.models.attribute import Attribute
from urjaa_core.models.attribute_value import AttributeValue
from urjaa_core.models.base_metal import BaseMetal
from urjaa_core.models.category import Category
from urjaa_core.models.collection import Collection
from urjaa_core.models.metal_color import MetalColor
from urjaa_core.models.metal_purity import MetalPurity
from urjaa_core.models.metal_rate import MetalRate
from urjaa_core.models.stone import Stone
from urjaa_core.models.subcategory import Subcategory
from urjaa_core.models.tag import Tag
from urjaa_core.models.variant_type import VariantType
from urjaa_core.models.variant_attribute import VariantAttribute
from urjaa_core.models.sale import Sale
from urjaa_core.models.store import Store
from urjaa_core.repositories.admin.admin_management_repository import AdminManagementRepository
from urjaa_core.schemas.admin.management import (
    AttributeCreateRequest,
    AttributeUpdateRequest,
    AttributeValueCreateRequest,
    AttributeValueUpdateRequest,
    CategoryCreateRequest,
    CategoryUpdateRequest,
    CollectionCreateRequest,
    CollectionUpdateRequest,
    ImageCreateRequest,
    MetalColorCreateRequest,
    MetalColorUpdateRequest,
    MetalPurityCreateRequest,
    MetalPurityUpdateRequest,
    MetalRateBulkUpdateRequest,
    MetalTypeCreateRequest,
    MetalTypeUpdateRequest,
    ProductCreateRequest,
    ProductStonesUpdateRequest,
    ProductUpdateRequest,
    StoneCreateRequest,
    StoneUpdateRequest,
    SubcategoryCreateRequest,
    SubcategoryUpdateRequest,
    TagCreateRequest,
    TagUpdateRequest,
    VariantTypeCreateRequest,
    VariantTypeUpdateRequest,
    VariantCreateRequest,
    VariantUpdateRequest,
)


logger = logging.getLogger(__name__)


class AdminManagementService:
    GENDER_ATTRIBUTE_SLUG = "gender"
    GENDER_ATTRIBUTE_NAME = "Gender"
    DEFAULT_GENDER_KEY = "unisex"
    GENDER_VALUE_MAP = {
        "men": "Men",
        "women": "Women",
        "unisex": "Unisex",
    }

    @staticmethod
    def _normalize_gender_key(value: str | None) -> str:
        normalized = (value or "").strip().lower()
        if normalized in AdminManagementService.GENDER_VALUE_MAP:
            return normalized
        return AdminManagementService.DEFAULT_GENDER_KEY

    @staticmethod
    def _ensure_gender_attribute_values(db: Session) -> tuple[Attribute, dict[str, AttributeValue]]:
        attribute = AdminManagementRepository.get_attribute_by_slug(db, AdminManagementService.GENDER_ATTRIBUTE_SLUG)
        if not attribute:
            attribute = AdminManagementRepository.create_attribute(
                db,
                Attribute(
                    name=AdminManagementService.GENDER_ATTRIBUTE_NAME,
                    slug=AdminManagementService.GENDER_ATTRIBUTE_SLUG,
                    filterable=True,
                ),
            )
        elif not attribute.filterable:
            attribute.filterable = True

        existing_values: dict[str, AttributeValue] = {}
        for existing in attribute.values or []:
            key = (existing.value or "").strip().lower()
            if key:
                existing_values[key] = existing

        for key, label in AdminManagementService.GENDER_VALUE_MAP.items():
            if key in existing_values:
                continue

            created = AdminManagementRepository.create_attribute_value(
                db,
                AttributeValue(attribute_id=attribute.id, value=label),
            )
            existing_values[key] = created

        return attribute, existing_values

    @staticmethod
    def _set_product_gender_attribute(db: Session, product_id: UUID, gender: str | None) -> None:
        attribute, values = AdminManagementService._ensure_gender_attribute_values(db)
        gender_key = AdminManagementService._normalize_gender_key(gender)
        fallback_key = AdminManagementService.DEFAULT_GENDER_KEY
        target_value = values.get(gender_key) or values.get(fallback_key)
        if target_value is None:
            raise HTTPException(status_code=500, detail="Gender attribute values are not configured")

        existing_gender_rows = (
            db.query(ProductAttribute)
            .join(AttributeValue, AttributeValue.id == ProductAttribute.attribute_value_id)
            .filter(
                ProductAttribute.product_id == product_id,
                AttributeValue.attribute_id == attribute.id,
            )
            .all()
        )

        for row in existing_gender_rows:
            db.delete(row)

        db.flush()
        db.add(ProductAttribute(product_id=product_id, attribute_value_id=target_value.id))

    @staticmethod
    def get_products_global(db: Session, page: int = 1, limit: int = 200, search: str | None = None) -> tuple[list[dict], int]:
        if page < 1:
            raise HTTPException(status_code=400, detail="page must be >= 1")
        if limit < 1 or limit > 1000:
            raise HTTPException(status_code=400, detail="limit must be between 1 and 1000")

        all_products = AdminManagementRepository.get_all_products_with_relations(db)

        search_term = search.strip().lower() if search and search.strip() else None

        grouped: dict[str, dict] = {}
        for product in all_products:
            if search_term:
                name_match = search_term in (product.name or "").lower()
                desc_match = search_term in (product.description or "").lower()
                cat_name = product.subcategory.category.name if product.subcategory and product.subcategory.category else ""
                cat_match = search_term in cat_name.lower()
                if not (name_match or desc_match or cat_match):
                    continue
            normalized_name = (product.name or "").strip().lower()
            dedupe_key = f"name:{normalized_name}" if normalized_name else f"id:{product.id}"

            entry = grouped.get(dedupe_key)
            if entry is None:
                grouped[dedupe_key] = {
                    "representative": product,
                    "store_ids": {str(product.store_id)},
                    "store_product_refs": {(str(product.store_id), str(product.id))},
                }
                continue

            representative = entry["representative"]
            representative_updated = representative.updated_at or representative.created_at
            current_updated = product.updated_at or product.created_at
            if current_updated and (representative_updated is None or current_updated > representative_updated):
                entry["representative"] = product

            entry["store_ids"].add(str(product.store_id))
            entry["store_product_refs"].add((str(product.store_id), str(product.id)))

        deduped_items: list[dict] = []
        for entry in grouped.values():
            representative: Product = entry["representative"]
            store_ids = sorted(entry["store_ids"])
            store_product_refs = [
                {"store_id": store_id, "product_id": product_id}
                for store_id, product_id in sorted(entry["store_product_refs"])
            ]

            primary_image = next(
                (img.image_url for img in representative.images if img.image_url and img.is_primary),
                None,
            )
            fallback_image = next(
                (img.image_url for img in representative.images if img.image_url),
                None,
            )

            deduped_items.append(
                {
                    "product": representative,
                    "store_ids": store_ids,
                    "store_count": len(store_ids),
                    "image_url": primary_image or fallback_image,
                    "store_product_refs": store_product_refs,
                }
            )

        deduped_items.sort(
            key=lambda item: (
                item["product"].updated_at or item["product"].created_at,
                item["product"].created_at,
            ),
            reverse=True,
        )

        total = len(deduped_items)
        offset = (page - 1) * limit
        paged = deduped_items[offset: offset + limit]
        return paged, total

    @staticmethod
    def _parse_optional_int(value: str | None) -> int | None:
        if value is None or value == "":
            return None
        return int(value)

    @staticmethod
    def _parse_optional_float(value: str | None) -> float | None:
        if value is None or value == "":
            return None
        return float(value)

    @staticmethod
    def _parse_bool(value: str | None, default: bool = False) -> bool:
        if value is None or value == "":
            return default
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "y"}:
            return True
        if normalized in {"false", "0", "no", "n"}:
            return False
        raise ValueError("must be true/false")

    @staticmethod
    def _slugify(value: str) -> str:
        slug = re.sub(r"[^a-z0-9\s-]", "", value.strip().lower())
        slug = re.sub(r"\s+", "-", slug)
        slug = re.sub(r"-+", "-", slug).strip("-")
        return slug or "item"

    @staticmethod
    def _unique_slug(base_slug: str, slug_exists: Callable[[str], bool]) -> str:
        candidate = base_slug
        suffix = 1
        while slug_exists(candidate):
            candidate = f"{base_slug}-{suffix}"
            suffix += 1
        return candidate

    @staticmethod
    def delete_store(db: Session, store_id: UUID, active_store_id: UUID, force: bool = False) -> None:

        store = db.query(Store).filter(Store.id == store_id).first()
        if not store:
            raise HTTPException(status_code=404, detail="Store not found")

        total_stores = db.query(Store).count()
        if total_stores <= 1:
            raise HTTPException(status_code=400, detail="Cannot delete last store")

        if store_id == active_store_id and not force:
            raise HTTPException(status_code=409, detail="Switch to another store before deleting the active store")

        product_count = db.query(Product.id).filter(Product.store_id == store_id).count()
        variant_count = db.query(ProductVariant.id).filter(ProductVariant.store_id == store_id).count()
        sales_count = db.query(Sale.id).filter(Sale.store_id == store_id).count()

        has_dependencies = any([product_count, variant_count, sales_count])
        if has_dependencies and not force:
            raise HTTPException(
                status_code=409,
                detail="Store has dependent data. Retry with force=true to delete all dependent records.",
            )

        try:
            product_ids_query = db.query(Product.id).filter(Product.store_id == store_id)
            variant_ids_query = db.query(ProductVariant.id).filter(ProductVariant.store_id == store_id)

            # Sales must be removed before products/variants due FK constraints.
            deleted_sales_count = db.query(Sale).filter(
                or_(
                    Sale.store_id == store_id,
                    Sale.product_id.in_(product_ids_query),
                    Sale.variant_id.in_(variant_ids_query),
                )
            ).delete(synchronize_session=False)

            deleted_product_images_count = db.query(ProductImage).filter(
                ProductImage.product_id.in_(product_ids_query)
            ).delete(synchronize_session=False)

            deleted_product_variants_count = db.query(ProductVariant).filter(
                ProductVariant.store_id == store_id
            ).delete(synchronize_session=False)

            deleted_product_stones_count = db.query(ProductStone).filter(
                ProductStone.product_id.in_(product_ids_query)
            ).delete(synchronize_session=False)

            deleted_product_collections_count = db.query(ProductCollection).filter(
                ProductCollection.product_id.in_(product_ids_query)
            ).delete(synchronize_session=False)

            deleted_product_tags_count = db.query(ProductTag).filter(
                ProductTag.product_id.in_(product_ids_query)
            ).delete(synchronize_session=False)

            deleted_product_attributes_count = db.query(ProductAttribute).filter(
                ProductAttribute.product_id.in_(product_ids_query)
            ).delete(synchronize_session=False)

            deleted_products_count = db.query(Product).filter(
                Product.store_id == store_id
            ).delete(synchronize_session=False)

            deleted_customers_count = 0

            deleted_store_count = db.query(Store).filter(Store.id == store_id).delete(synchronize_session=False)
            if deleted_store_count != 1:
                raise HTTPException(status_code=404, detail="Store not found")

            logger.info(
                "force_delete_store deleting_store_id=%s deleted_products_count=%s deleted_sales_count=%s deleted_images_count=%s deleted_variants_count=%s deleted_stones_count=%s deleted_collections_count=%s deleted_tags_count=%s deleted_attributes_count=%s deleted_customers_count=%s",
                store_id,
                deleted_products_count,
                deleted_sales_count,
                deleted_product_images_count,
                deleted_product_variants_count,
                deleted_product_stones_count,
                deleted_product_collections_count,
                deleted_product_tags_count,
                deleted_product_attributes_count,
                deleted_customers_count,
            )

            db.commit()
        except Exception:
            db.rollback()
            raise

    @staticmethod
    def bulk_upload_products_from_csv_rows(db: Session, store_id: UUID, rows: list[dict[str, str]]) -> dict:
        if not rows:
            return {
                "success": False,
                "inserted_products": 0,
                "inserted_variants": 0,
                "errors": [
                    {
                        "row_number": 1,
                        "errors": ["CSV is empty"],
                    }
                ],
            }

        errors: list[dict] = []
        normalized_rows: list[dict] = []
        product_meta_by_slug: dict[str, dict] = {}
        seen_variant_skus: set[str] = set()
        # Tracks slugs assigned during this upload to ensure intra-batch uniqueness.
        upload_slug_pool: set[str] = set()
        # Maps lowercased product_name → auto-generated slug so all variant rows
        # for the same product resolve to the same internal slug.
        name_to_auto_slug: dict[str, str] = {}
        existing_variant_sku_cache: dict[str, bool] = {}
        category_cache: dict[str, Category | None] = {}
        subcategory_cache: dict[str, Subcategory | None] = {}

        # Slug is always auto-generated from product_name — never accepted from user input.
        # Category is resolved by name (case-insensitive). Subcategory is optional.
        required_fields = [
            "product_name",
            "variant_sku",
        ]

        def _slug_taken_globally(candidate: str) -> bool:
            """True if the slug is already claimed in the DB or by an earlier row in this batch."""
            return (
                candidate in upload_slug_pool
                or AdminManagementRepository.get_product_by_slug_global(db, candidate) is not None
            )

        def _resolve_category(normalized: dict) -> tuple[Category | None, list[str]]:
            """Return (category_obj, errors). Resolved exclusively by category_name (case-insensitive)."""
            errs: list[str] = []
            category_name = normalized.get("category_name", "").strip()

            if not category_name:
                errs.append("category_name is required")
                return None, errs

            cache_key = category_name.lower()
            if cache_key not in category_cache:
                category_cache[cache_key] = AdminManagementRepository.get_category_by_name(db, category_name)
            cat = category_cache[cache_key]
            if not cat:
                errs.append(f"Category not found: \"{category_name}\" — check the exact name in your catalog")
            return cat, errs

        def _resolve_subcategory(normalized: dict, category_id: int | None) -> tuple[Subcategory | None, list[str]]:
            """Return (subcategory_obj, errors). Optional; if provided must match by name under the resolved category."""
            errs: list[str] = []
            subcategory_name = normalized.get("subcategory_name", "").strip()

            if not subcategory_name:
                return None, errs

            cache_key = f"{subcategory_name.lower()}:cat{category_id}"
            if cache_key not in subcategory_cache:
                subcategory_cache[cache_key] = AdminManagementRepository.get_subcategory_by_name(
                    db, subcategory_name, category_id=category_id
                )
            sub = subcategory_cache[cache_key]
            if not sub:
                errs.append(f"Subcategory not found: \"{subcategory_name}\" under the specified category")
            return sub, errs

        for row_index, row in enumerate(rows, start=2):
            row_errors: list[str] = []
            normalized = {str(key).strip(): (value.strip() if isinstance(value, str) else "") for key, value in row.items()}

            missing_fields = [field for field in required_fields if not normalized.get(field)]
            if missing_fields:
                row_errors.append(f"Missing required fields: {', '.join(missing_fields)}")

            product_name = normalized.get("product_name", "")
            variant_sku = normalized.get("variant_sku", "")

            category, cat_errors = _resolve_category(normalized)
            row_errors.extend(cat_errors)

            subcategory = None
            if category is not None:
                subcategory, sub_errors = _resolve_subcategory(
                    normalized, category_id=category.id
                )
                row_errors.extend(sub_errors)

            # Slug is always auto-generated from product_name.
            # Rows sharing the same product_name map to the same product.
            product_slug = ""
            name_key = product_name.strip().lower()
            if name_key:
                if name_key in name_to_auto_slug:
                    product_slug = name_to_auto_slug[name_key]
                else:
                    base = AdminManagementService._slugify(product_name)
                    product_slug = AdminManagementService._unique_slug(base, _slug_taken_globally)
                    upload_slug_pool.add(product_slug)
                    name_to_auto_slug[name_key] = product_slug

            if variant_sku:
                lower_sku = variant_sku.lower()
                if lower_sku in seen_variant_skus:
                    row_errors.append(f"Duplicate variant_sku in CSV: {variant_sku}")
                else:
                    seen_variant_skus.add(lower_sku)

                if lower_sku not in existing_variant_sku_cache:
                    existing_variant_sku_cache[lower_sku] = (
                        AdminManagementRepository.get_variant_by_sku(db, variant_sku, store_id=store_id) is not None
                    )
                if existing_variant_sku_cache[lower_sku]:
                    row_errors.append(f"Variant SKU already exists: {variant_sku}")

            parsed_stock_quantity = 0
            parsed_stone_quantity = 0
            parsed_status = "draft"
            parsed_featured = False
            parsed_customizable = False
            parsed_base_metal_id = None
            parsed_metal_color_id = None
            parsed_metal_purity_id = None
            parsed_metal_weight_grams = None
            parsed_price_override = None
            parsed_stone_cost = 0.0
            parsed_making_charges = 0.0

            try:
                parsed_stock_quantity = int(normalized.get("stock_quantity") or "0")
                if parsed_stock_quantity < 0:
                    row_errors.append("stock_quantity must be >= 0")
            except ValueError:
                row_errors.append("stock_quantity must be an integer")

            try:
                parsed_stone_quantity = int(normalized.get("stone_quantity") or "0")
                if parsed_stone_quantity < 0:
                    row_errors.append("stone_quantity must be >= 0")
            except ValueError:
                row_errors.append("stone_quantity must be an integer")

            try:
                parsed_stone_cost = float(normalized.get("stone_cost") or "0")
                if parsed_stone_cost < 0:
                    row_errors.append("stone_cost must be >= 0")
            except ValueError:
                row_errors.append("stone_cost must be a number")

            try:
                parsed_making_charges = float(normalized.get("making_charges") or "0")
                if parsed_making_charges < 0:
                    row_errors.append("making_charges must be >= 0")
            except ValueError:
                row_errors.append("making_charges must be a number")

            raw_status = (normalized.get("status") or "draft").lower()
            if raw_status in {"draft", "active", "hidden", "archived"}:
                parsed_status = raw_status
            else:
                row_errors.append("status must be one of draft, active, hidden, archived")

            try:
                parsed_featured = AdminManagementService._parse_bool(normalized.get("featured"), default=False)
                parsed_customizable = AdminManagementService._parse_bool(normalized.get("customizable"), default=False)
            except ValueError:
                row_errors.append("featured/customizable must be boolean values")

            try:
                parsed_base_metal_id = AdminManagementService._parse_optional_int(normalized.get("base_metal_id"))
                parsed_metal_color_id = AdminManagementService._parse_optional_int(normalized.get("metal_color_id"))
                parsed_metal_purity_id = AdminManagementService._parse_optional_int(normalized.get("metal_purity_id"))
                parsed_metal_weight_grams = AdminManagementService._parse_optional_float(normalized.get("metal_weight_grams"))
                parsed_price_override = AdminManagementService._parse_optional_float(normalized.get("price_override"))
            except ValueError:
                row_errors.append("base_metal_id/metal_color_id/metal_purity_id must be integers; metal_weight_grams/price_override must be numeric")

            if product_slug:
                current_meta = {
                    "product_name": product_name,
                    "description": normalized.get("description") or None,
                    "subcategory_id": subcategory.id if subcategory else None,
                    "status": parsed_status,
                    "featured": parsed_featured,
                    "customizable": parsed_customizable,
                }

                existing_meta = product_meta_by_slug.get(product_slug)
                if existing_meta is None:
                    product_meta_by_slug[product_slug] = current_meta
                elif existing_meta != current_meta:
                    row_errors.append(
                        f"Rows with the same product_name \"{product_name}\" must have identical "
                        "product-level fields (description, status, subcategory, featured, customizable)"
                    )

            if row_errors:
                errors.append({"row_number": row_index, "errors": row_errors})
                continue

            normalized_rows.append(
                {
                    "product_slug": product_slug,
                    "variant": {
                        "base_metal_id": parsed_base_metal_id,
                        "metal_color_id": parsed_metal_color_id,
                        "metal_purity_id": parsed_metal_purity_id,
                        "metal_weight_grams": parsed_metal_weight_grams,
                        "price_override": parsed_price_override,
                        "stone_quantity": parsed_stone_quantity,
                        "stone_cost": parsed_stone_cost,
                        "making_charges": parsed_making_charges,
                        "stock_quantity": parsed_stock_quantity,
                        "sku_code": variant_sku,
                    },
                }
            )

        if errors:
            return {
                "success": False,
                "inserted_products": 0,
                "inserted_variants": 0,
                "errors": errors,
            }

        products_by_slug: dict[str, Product] = {}

        try:
            for slug, meta in product_meta_by_slug.items():
                product = Product(
                    store_id=store_id,
                    name=meta["product_name"],
                    slug=slug,
                    description=meta["description"],
                    subcategory_id=meta["subcategory_id"],
                    status=meta["status"],
                    featured=meta["featured"],
                    customizable=meta["customizable"],
                )
                created_product = AdminManagementRepository.create_product(db, product)
                AdminManagementService._set_product_gender_attribute(db, created_product.id, None)
                products_by_slug[slug] = created_product

            created_variant_count = 0
            for item in normalized_rows:
                product = products_by_slug[item["product_slug"]]
                variant_payload = item["variant"]
                variant = ProductVariant(
                    store_id=store_id,
                    product_id=product.id,
                    base_metal_id=variant_payload["base_metal_id"],
                    metal_color_id=variant_payload["metal_color_id"],
                    metal_purity_id=variant_payload["metal_purity_id"],
                    metal_weight_grams=variant_payload["metal_weight_grams"],
                    price_override=variant_payload["price_override"],
                    stone_quantity=variant_payload["stone_quantity"],
                    stone_cost=variant_payload["stone_cost"],
                    making_charges=variant_payload["making_charges"],
                    stock_quantity=variant_payload["stock_quantity"],
                    sku_code=variant_payload["sku_code"],
                )
                AdminManagementRepository.create_variant(db, variant)
                created_variant_count += 1

            db.commit()
            return {
                "success": True,
                "inserted_products": len(products_by_slug),
                "inserted_variants": created_variant_count,
                "errors": [],
            }
        except Exception:
            db.rollback()
            raise

    @staticmethod
    def get_dashboard_summary(db: Session, store_id: UUID) -> dict:
        low_stock_threshold = 5

        total_products = AdminManagementRepository.count_products(db, store_id=store_id)
        total_variants = AdminManagementRepository.count_variants(db, store_id=store_id)
        total_collections = AdminManagementRepository.count_collections(db)
        active_products = AdminManagementRepository.count_products_by_status(db, "active", store_id=store_id)
        low_stock_count = AdminManagementRepository.count_low_stock_variants(db, low_stock_threshold, store_id=store_id)

        recent_products = AdminManagementRepository.get_recent_products(db, store_id=store_id, limit=5)
        low_stock_rows = AdminManagementRepository.get_low_stock_variants(
            db,
            threshold=low_stock_threshold,
            store_id=store_id,
            limit=8,
        )

        gold_recent_rates = AdminManagementRepository.get_recent_metal_rates_by_name(db, "gold", limit=2)
        silver_recent_rates = AdminManagementRepository.get_recent_metal_rates_by_name(db, "silver", limit=2)

        gold_rate = gold_recent_rates[0] if gold_recent_rates else None
        silver_rate = silver_recent_rates[0] if silver_recent_rates else None

        gold_trend = 0
        if len(gold_recent_rates) > 1:
            gold_current = float(gold_recent_rates[0].rate_per_gram)
            gold_previous = float(gold_recent_rates[1].rate_per_gram)
            gold_trend = 1 if gold_current > gold_previous else (-1 if gold_current < gold_previous else 0)

        silver_trend = 0
        if len(silver_recent_rates) > 1:
            silver_current = float(silver_recent_rates[0].rate_per_gram)
            silver_previous = float(silver_recent_rates[1].rate_per_gram)
            silver_trend = 1 if silver_current > silver_previous else (-1 if silver_current < silver_previous else 0)
        gold_22k_purity = AdminManagementRepository.get_metal_purity_by_metal_and_label(db, "gold", "22")
        gold_18k_purity = AdminManagementRepository.get_metal_purity_by_metal_and_label(db, "gold", "18")

        base_gold = float(gold_rate.rate_per_gram) if gold_rate else None
        gold_22k_multiplier = (float(gold_22k_purity.numeric_purity) / 100) if gold_22k_purity and gold_22k_purity.numeric_purity is not None else None
        gold_18k_multiplier = (float(gold_18k_purity.numeric_purity) / 100) if gold_18k_purity and gold_18k_purity.numeric_purity is not None else None

        gold_22k = (base_gold * gold_22k_multiplier) if base_gold is not None and gold_22k_multiplier is not None else base_gold
        gold_18k = (base_gold * gold_18k_multiplier) if base_gold is not None and gold_18k_multiplier is not None else base_gold
        silver = float(silver_rate.rate_per_gram) if silver_rate else None

        avg_price, highest_price, lowest_price = AdminManagementRepository.get_variant_pricing_snapshot(db, store_id=store_id)
        sales_insights = AdminManagementRepository.get_sales_insights(db, store_id=store_id, top_limit=5)

        effective_from_candidates = [
            gold_rate.effective_from if gold_rate else None,
            silver_rate.effective_from if silver_rate else None,
        ]
        effective_from = max((value for value in effective_from_candidates if value is not None), default=None)

        return {
            "total_products": total_products,
            "total_variants": total_variants,
            "total_collections": total_collections,
            "active_products": active_products,
            "low_stock_count": low_stock_count,
            "total_revenue": sales_insights["total_revenue"],
            "total_profit": sales_insights["total_profit"],
            "profit_margin": sales_insights["profit_margin"],
            "store_revenue": sales_insights["store_revenue"],
            "website_revenue": sales_insights["website_revenue"],
            "total_sales_count": sales_insights["total_sales_count"],
            "top_selling_products": sales_insights["top_selling_products"],
            "low_stock_items": [
                {
                    "product_id": product.id,
                    "product_name": product.name,
                    "sku_code": variant.sku_code,
                    "stock_quantity": variant.stock_quantity,
                }
                for variant, product in low_stock_rows
            ],
            "recent_products": recent_products,
            "metal_rates": {
                "gold_22k": gold_22k,
                "gold_18k": gold_18k,
                "silver": silver,
                "gold_trend": gold_trend,
                "silver_trend": silver_trend,
                "effective_from": effective_from,
            },
            "pricing_snapshot": {
                "average_price": avg_price,
                "highest_price": highest_price,
                "lowest_price": lowest_price,
            },
        }

    @staticmethod
    def get_dashboard_trends(db: Session, store_id: UUID) -> dict:
        return {
            "daily_revenue": AdminManagementRepository.get_daily_revenue_trend(db, store_id=store_id, days=30)
        }

    @staticmethod
    def get_categories(db: Session, include_inactive: bool = False) -> list[Category]:
        return AdminManagementRepository.get_categories(db, include_inactive=include_inactive)

    @staticmethod
    def get_subcategories(db: Session) -> list[Subcategory]:
        return AdminManagementRepository.get_subcategories(db)

    @staticmethod
    def create_subcategory(db: Session, payload: SubcategoryCreateRequest) -> Subcategory:
        category = AdminManagementRepository.get_category_by_id(db, payload.category_id)
        if not category:
            raise HTTPException(status_code=404, detail="Category not found")

        name = payload.name.strip()
        slug = AdminManagementService._unique_slug(
            AdminManagementService._slugify(name),
            lambda candidate: AdminManagementRepository.get_subcategory_by_slug(db, candidate) is not None,
        )

        if payload.default_variant_type_id is not None:
            variant_type = AdminManagementRepository.get_variant_type_by_id(db, payload.default_variant_type_id)
            if not variant_type:
                raise HTTPException(status_code=404, detail="Variant type not found")

        subcategory = Subcategory(
            category_id=payload.category_id,
            name=name,
            slug=slug,
            default_variant_type_id=payload.default_variant_type_id,
        )
        try:
            created = AdminManagementRepository.create_subcategory(db, subcategory)
            db.commit()
            return created
        except Exception:
            db.rollback()
            raise

    @staticmethod
    def update_subcategory(db: Session, subcategory_id: int, payload: SubcategoryUpdateRequest) -> Subcategory:
        subcategory = AdminManagementRepository.get_subcategory_by_id(db, subcategory_id)
        if not subcategory:
            raise HTTPException(status_code=404, detail="Subcategory not found")

        if payload.category_id is not None:
            category = AdminManagementRepository.get_category_by_id(db, payload.category_id)
            if not category:
                raise HTTPException(status_code=404, detail="Category not found")
            subcategory.category_id = payload.category_id

        if payload.name is not None:
            next_name = payload.name.strip()
            if next_name != subcategory.name:
                subcategory.name = next_name
                subcategory.slug = AdminManagementService._unique_slug(
                    AdminManagementService._slugify(next_name),
                    lambda candidate: (
                        (existing := AdminManagementRepository.get_subcategory_by_slug(db, candidate)) is not None
                        and existing.id != subcategory.id
                    ),
                )

        if payload.default_variant_type_id is not None:
            variant_type = AdminManagementRepository.get_variant_type_by_id(db, payload.default_variant_type_id)
            if not variant_type:
                raise HTTPException(status_code=404, detail="Variant type not found")
            subcategory.default_variant_type_id = payload.default_variant_type_id

        try:
            db.commit()
            db.refresh(subcategory)
            return subcategory
        except Exception:
            db.rollback()
            raise

    @staticmethod
    def delete_subcategory(db: Session, subcategory_id: int) -> None:
        subcategory = AdminManagementRepository.get_subcategory_by_id(db, subcategory_id)
        if not subcategory:
            raise HTTPException(status_code=404, detail="Subcategory not found")

        try:
            AdminManagementRepository.delete_subcategory(db, subcategory)
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(status_code=409, detail="Subcategory is in use and cannot be deleted")
        except Exception:
            db.rollback()
            raise

    @staticmethod
    def get_variant_types(db: Session) -> list[VariantType]:
        return AdminManagementRepository.get_variant_types(db)

    @staticmethod
    def create_variant_type(db: Session, payload: VariantTypeCreateRequest) -> VariantType:
        name = payload.name.strip()
        slug = AdminManagementService._unique_slug(
            AdminManagementService._slugify(name),
            lambda candidate: AdminManagementRepository.get_variant_type_by_slug(db, candidate) is not None,
        )

        attribute_ids = list(dict.fromkeys(payload.attribute_ids or []))
        if attribute_ids:
            attributes = AdminManagementRepository.get_attributes_by_ids(db, attribute_ids)
            if len(attributes) != len(attribute_ids):
                raise HTTPException(status_code=400, detail="One or more attribute ids are invalid")

        variant_type = VariantType(
            name=name,
            slug=slug,
            description=payload.description,
            display_order=payload.display_order,
        )

        try:
            created = AdminManagementRepository.create_variant_type(db, variant_type)
            AdminManagementRepository.replace_variant_type_attributes(db, created.id, attribute_ids)
            db.commit()
            db.refresh(created)
            return created
        except Exception:
            db.rollback()
            raise

    @staticmethod
    def update_variant_type(db: Session, variant_type_id: int, payload: VariantTypeUpdateRequest) -> VariantType:
        variant_type = AdminManagementRepository.get_variant_type_by_id(db, variant_type_id)
        if not variant_type:
            raise HTTPException(status_code=404, detail="Variant type not found")

        if payload.name is not None:
            next_name = payload.name.strip()
            if next_name != variant_type.name:
                variant_type.name = next_name
                variant_type.slug = AdminManagementService._unique_slug(
                    AdminManagementService._slugify(next_name),
                    lambda candidate: (
                        (existing := AdminManagementRepository.get_variant_type_by_slug(db, candidate)) is not None
                        and existing.id != variant_type.id
                    ),
                )

        for field in ["description", "display_order"]:
            value = getattr(payload, field)
            if value is not None:
                setattr(variant_type, field, value)

        if payload.attribute_ids is not None:
            attribute_ids = list(dict.fromkeys(payload.attribute_ids))
            if attribute_ids:
                attributes = AdminManagementRepository.get_attributes_by_ids(db, attribute_ids)
                if len(attributes) != len(attribute_ids):
                    raise HTTPException(status_code=400, detail="One or more attribute ids are invalid")
            AdminManagementRepository.replace_variant_type_attributes(db, variant_type.id, attribute_ids)

        try:
            AdminManagementRepository.update_variant_type(db, variant_type)
            db.commit()
            db.refresh(variant_type)
            return variant_type
        except Exception:
            db.rollback()
            raise

    @staticmethod
    def get_variant_type_attributes(db: Session, variant_type_id: int) -> list[Attribute]:
        variant_type = AdminManagementRepository.get_variant_type_by_id(db, variant_type_id)
        if not variant_type:
            raise HTTPException(status_code=404, detail="Variant type not found")
        return [link.attribute for link in variant_type.attributes if link.attribute is not None]

    @staticmethod
    def delete_variant_type(db: Session, variant_type_id: int) -> None:
        variant_type = AdminManagementRepository.get_variant_type_by_id(db, variant_type_id)
        if not variant_type:
            raise HTTPException(status_code=404, detail="Variant type not found")

        try:
            # variant_type_attributes.variant_type_id is ON DELETE SET NULL, not
            # CASCADE - without this, deleting the VariantType leaves orphaned
            # variant_type_attributes rows (variant_type_id=NULL) that still
            # point at their attribute_id, permanently blocking that Attribute
            # from ever being deleted. Clear the junction explicitly first.
            AdminManagementRepository.replace_variant_type_attributes(db, variant_type_id, [])
            AdminManagementRepository.delete_variant_type(db, variant_type)
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(status_code=409, detail="Variant type is in use and cannot be deleted")
        except Exception:
            db.rollback()
            raise

    @staticmethod
    def get_collections(db: Session) -> list[Collection]:
        return AdminManagementRepository.get_collections(db)

    @staticmethod
    def get_tags(db: Session) -> list[Tag]:
        return AdminManagementRepository.get_tags(db)

    @staticmethod
    def get_stones(db: Session) -> list[Stone]:
        return AdminManagementRepository.get_stones(db)

    @staticmethod
    def get_attributes(db: Session) -> list[Attribute]:
        return AdminManagementRepository.get_attributes(db)

    @staticmethod
    def get_metal_purities(db: Session) -> list[MetalPurity]:
        return AdminManagementRepository.get_metal_purities(db)

    @staticmethod
    def get_metal_types(db: Session) -> list[BaseMetal]:
        return AdminManagementRepository.get_metal_types(db)

    @staticmethod
    def create_metal_type(db: Session, payload: MetalTypeCreateRequest) -> BaseMetal:
        existing = AdminManagementRepository.get_metal_type_by_name(db, payload.name)
        if existing:
            raise HTTPException(status_code=409, detail="Metal type already exists")

        metal_type = BaseMetal(name=payload.name)
        try:
            created = AdminManagementRepository.create_metal_type(db, metal_type)
            db.commit()
            return created
        except Exception:
            db.rollback()
            raise

    @staticmethod
    def update_metal_type(db: Session, metal_type_id: int, payload: MetalTypeUpdateRequest) -> BaseMetal:
        metal_type = AdminManagementRepository.get_metal_type_by_id(db, metal_type_id)
        if not metal_type:
            raise HTTPException(status_code=404, detail="Metal type not found")

        if payload.name is not None:
            existing = AdminManagementRepository.get_metal_type_by_name(db, payload.name)
            if existing and existing.id != metal_type.id:
                raise HTTPException(status_code=409, detail="Metal type already exists")
            metal_type.name = payload.name

        try:
            AdminManagementRepository.update_metal_type(db, metal_type)
            db.commit()
            return metal_type
        except Exception:
            db.rollback()
            raise

    @staticmethod
    def delete_metal_type(db: Session, metal_type_id: int) -> None:
        metal_type = AdminManagementRepository.get_metal_type_by_id(db, metal_type_id)
        if not metal_type:
            raise HTTPException(status_code=404, detail="Metal type not found")

        try:
            AdminManagementRepository.delete_metal_type(db, metal_type)
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(status_code=409, detail="Metal type is in use and cannot be deleted")
        except Exception:
            db.rollback()
            raise

    @staticmethod
    def create_metal_purity(db: Session, payload: MetalPurityCreateRequest) -> MetalPurity:
        metal_type = AdminManagementRepository.get_metal_type_by_id(db, payload.base_metal_id)
        if not metal_type:
            raise HTTPException(status_code=404, detail="Metal type not found")

        existing = AdminManagementRepository.get_metal_purity_by_values(db, payload.base_metal_id, payload.purity_label)
        if existing:
            raise HTTPException(status_code=409, detail="Metal purity already exists")

        metal_purity = MetalPurity(
            base_metal_id=payload.base_metal_id,
            purity_label=payload.purity_label,
            numeric_purity=payload.numeric_purity,
        )
        try:
            created = AdminManagementRepository.create_metal_purity(db, metal_purity)
            db.commit()
            return created
        except Exception:
            db.rollback()
            raise

    @staticmethod
    def update_metal_purity(db: Session, metal_purity_id: int, payload: MetalPurityUpdateRequest) -> MetalPurity:
        metal_purity = AdminManagementRepository.get_metal_purity_by_id(db, metal_purity_id)
        if not metal_purity:
            raise HTTPException(status_code=404, detail="Metal purity not found")

        next_base_metal_id = payload.base_metal_id if payload.base_metal_id is not None else metal_purity.base_metal_id
        next_purity_label = payload.purity_label if payload.purity_label is not None else metal_purity.purity_label

        if payload.base_metal_id is not None:
            metal_type = AdminManagementRepository.get_metal_type_by_id(db, payload.base_metal_id)
            if not metal_type:
                raise HTTPException(status_code=404, detail="Metal type not found")

        existing = AdminManagementRepository.get_metal_purity_by_values(db, next_base_metal_id, next_purity_label)
        if existing and existing.id != metal_purity.id:
            raise HTTPException(status_code=409, detail="Metal purity already exists")

        if payload.base_metal_id is not None:
            metal_purity.base_metal_id = payload.base_metal_id
        if payload.purity_label is not None:
            metal_purity.purity_label = payload.purity_label
        if payload.numeric_purity is not None:
            metal_purity.numeric_purity = payload.numeric_purity

        try:
            db.commit()
            db.refresh(metal_purity)
            return metal_purity
        except Exception:
            db.rollback()
            raise

    @staticmethod
    def delete_metal_purity(db: Session, metal_purity_id: int) -> None:
        metal_purity = AdminManagementRepository.get_metal_purity_by_id(db, metal_purity_id)
        if not metal_purity:
            raise HTTPException(status_code=404, detail="Metal purity not found")

        try:
            AdminManagementRepository.delete_metal_purity(db, metal_purity)
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(status_code=409, detail="Metal purity is in use and cannot be deleted")
        except Exception:
            db.rollback()
            raise

    @staticmethod
    def get_metal_colors(db: Session) -> list[MetalColor]:
        return AdminManagementRepository.get_metal_colors(db)

    @staticmethod
    def create_metal_color(db: Session, payload: MetalColorCreateRequest) -> MetalColor:
        existing = AdminManagementRepository.get_metal_color_by_name(db, payload.name)
        if existing:
            raise HTTPException(status_code=409, detail="Metal color already exists")

        metal_color = MetalColor(name=payload.name)
        try:
            created = AdminManagementRepository.create_metal_color(db, metal_color)
            db.commit()
            return created
        except Exception:
            db.rollback()
            raise

    @staticmethod
    def update_metal_color(db: Session, metal_color_id: int, payload: MetalColorUpdateRequest) -> MetalColor:
        metal_color = AdminManagementRepository.get_metal_color_by_id(db, metal_color_id)
        if not metal_color:
            raise HTTPException(status_code=404, detail="Metal color not found")

        if payload.name is not None:
            existing = AdminManagementRepository.get_metal_color_by_name(db, payload.name)
            if existing and existing.id != metal_color.id:
                raise HTTPException(status_code=409, detail="Metal color already exists")
            metal_color.name = payload.name

        try:
            AdminManagementRepository.update_metal_color(db, metal_color)
            db.commit()
            return metal_color
        except Exception:
            db.rollback()
            raise

    @staticmethod
    def delete_metal_color(db: Session, metal_color_id: int) -> None:
        metal_color = AdminManagementRepository.get_metal_color_by_id(db, metal_color_id)
        if not metal_color:
            raise HTTPException(status_code=404, detail="Metal color not found")

        try:
            AdminManagementRepository.delete_metal_color(db, metal_color)
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(status_code=409, detail="Metal color is in use and cannot be deleted")
        except Exception:
            db.rollback()
            raise

    @staticmethod
    def get_metal_rates(db: Session) -> list[MetalRate]:
        return AdminManagementRepository.get_metal_rates(db)

    @staticmethod
    def create_category(db: Session, payload: CategoryCreateRequest) -> Category:
        name = payload.name.strip()
        slug = AdminManagementService._unique_slug(
            AdminManagementService._slugify(name),
            lambda candidate: AdminManagementRepository.get_category_by_slug(db, candidate, include_inactive=True)
            is not None,
        )

        category = Category(name=name, slug=slug, display_order=payload.display_order)
        try:
            created = AdminManagementRepository.create_category(db, category)
            db.commit()
            return created
        except Exception:
            db.rollback()
            raise

    @staticmethod
    def update_category(db: Session, category_id: int, payload: CategoryUpdateRequest) -> Category:
        category = AdminManagementRepository.get_category_by_id_with_inactive(db, category_id)
        if not category:
            raise HTTPException(status_code=404, detail="Category not found")

        if payload.name is not None:
            next_name = payload.name.strip()
            if next_name != category.name:
                category.name = next_name
                category.slug = AdminManagementService._unique_slug(
                    AdminManagementService._slugify(next_name),
                    lambda candidate: (
                        (existing := AdminManagementRepository.get_category_by_slug(db, candidate, include_inactive=True))
                        is not None
                        and existing.id != category.id
                    ),
                )
        if payload.display_order is not None:
            category.display_order = payload.display_order

        try:
            db.commit()
            db.refresh(category)
            return category
        except Exception:
            db.rollback()
            raise

    @staticmethod
    def delete_category(db: Session, category_id: int) -> None:
        category = AdminManagementRepository.get_category_by_id_with_inactive(db, category_id)
        if not category:
            raise HTTPException(status_code=404, detail="Category not found")

        try:
            category.is_active = False
            category.is_deleted = True
            db.commit()
        except Exception:
            db.rollback()
            raise

    @staticmethod
    def permanently_delete_category(db: Session, category_id: int) -> None:
        category = AdminManagementRepository.get_category_by_id_with_inactive(db, category_id)
        if not category:
            raise HTTPException(status_code=404, detail="Category not found")

        linked_products = AdminManagementRepository.count_products_linked_to_category(db, category_id)
        if linked_products > 0:
            raise HTTPException(
                status_code=409,
                detail="Cannot permanently delete category with linked products",
            )

        try:
            AdminManagementRepository.delete_subcategories_by_category(db, category_id)
            AdminManagementRepository.delete_category(db, category)
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(status_code=409, detail="Category is in use and cannot be deleted")
        except Exception:
            db.rollback()
            raise

    @staticmethod
    def create_collection(db: Session, payload: CollectionCreateRequest) -> Collection:
        name = payload.name.strip()
        slug = AdminManagementService._unique_slug(
            AdminManagementService._slugify(name),
            lambda candidate: AdminManagementRepository.get_collection_by_slug(db, candidate) is not None,
        )

        collection = Collection(
            name=name,
            slug=slug,
            description=payload.description,
            banner_image=payload.banner_image,
            is_featured=payload.is_featured,
            display_order=payload.display_order,
        )
        try:
            created = AdminManagementRepository.create_collection(db, collection)
            db.commit()
            return created
        except Exception:
            db.rollback()
            raise

    @staticmethod
    def update_collection(db: Session, collection_id: int, payload: CollectionUpdateRequest) -> Collection:
        collection = AdminManagementRepository.get_collection_by_id(db, collection_id)
        if not collection:
            raise HTTPException(status_code=404, detail="Collection not found")

        if payload.name is not None:
            next_name = payload.name.strip()
            if next_name != collection.name:
                collection.name = next_name
                collection.slug = AdminManagementService._unique_slug(
                    AdminManagementService._slugify(next_name),
                    lambda candidate: (
                        (existing := AdminManagementRepository.get_collection_by_slug(db, candidate)) is not None
                        and existing.id != collection.id
                    ),
                )

        for field in ["description", "banner_image", "is_featured", "display_order"]:
            value = getattr(payload, field)
            if value is not None:
                setattr(collection, field, value)

        try:
            db.commit()
            db.refresh(collection)
            return collection
        except Exception:
            db.rollback()
            raise

    @staticmethod
    def delete_collection(db: Session, collection_id: int) -> None:
        collection = AdminManagementRepository.get_collection_by_id(db, collection_id)
        if not collection:
            raise HTTPException(status_code=404, detail="Collection not found")

        try:
            AdminManagementRepository.delete_collection(db, collection)
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(status_code=409, detail="Collection is in use and cannot be deleted")
        except Exception:
            db.rollback()
            raise

    @staticmethod
    def create_tag(db: Session, payload: TagCreateRequest) -> Tag:
        name = payload.name.strip()
        slug = AdminManagementService._unique_slug(
            AdminManagementService._slugify(name),
            lambda candidate: AdminManagementRepository.get_tag_by_slug(db, candidate) is not None,
        )

        tag = Tag(name=name, slug=slug, description=payload.description)
        try:
            created = AdminManagementRepository.create_tag(db, tag)
            db.commit()
            return created
        except Exception:
            db.rollback()
            raise

    @staticmethod
    def update_tag(db: Session, tag_id: int, payload: TagUpdateRequest) -> Tag:
        tag = AdminManagementRepository.get_tag_by_id(db, tag_id)
        if not tag:
            raise HTTPException(status_code=404, detail="Tag not found")

        if payload.name is not None:
            next_name = payload.name.strip()
            if next_name != tag.name:
                tag.name = next_name
                tag.slug = AdminManagementService._unique_slug(
                    AdminManagementService._slugify(next_name),
                    lambda candidate: (
                        (existing := AdminManagementRepository.get_tag_by_slug(db, candidate)) is not None
                        and existing.id != tag.id
                    ),
                )

        for field in ["description"]:
            value = getattr(payload, field)
            if value is not None:
                setattr(tag, field, value)

        try:
            db.commit()
            db.refresh(tag)
            return tag
        except Exception:
            db.rollback()
            raise

    @staticmethod
    def delete_tag(db: Session, tag_id: int) -> None:
        tag = AdminManagementRepository.get_tag_by_id(db, tag_id)
        if not tag:
            raise HTTPException(status_code=404, detail="Tag not found")

        try:
            AdminManagementRepository.delete_tag(db, tag)
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(status_code=409, detail="Tag is in use and cannot be deleted")
        except Exception:
            db.rollback()
            raise

    @staticmethod
    def create_stone(db: Session, payload: StoneCreateRequest) -> Stone:
        existing = AdminManagementRepository.get_stone_by_name(db, payload.name)
        if existing:
            raise HTTPException(status_code=409, detail="Stone already exists")

        stone = Stone(name=payload.name)
        try:
            created = AdminManagementRepository.create_stone(db, stone)
            db.commit()
            return created
        except Exception:
            db.rollback()
            raise

    @staticmethod
    def update_stone(db: Session, stone_id: int, payload: StoneUpdateRequest) -> Stone:
        stone = AdminManagementRepository.get_stone_by_id(db, stone_id)
        if not stone:
            raise HTTPException(status_code=404, detail="Stone not found")

        if payload.name is not None:
            existing = AdminManagementRepository.get_stone_by_name(db, payload.name)
            if existing and existing.id != stone.id:
                raise HTTPException(status_code=409, detail="Stone already exists")
            stone.name = payload.name

        try:
            db.commit()
            db.refresh(stone)
            return stone
        except Exception:
            db.rollback()
            raise

    @staticmethod
    def delete_stone(db: Session, stone_id: int) -> None:
        stone = AdminManagementRepository.get_stone_by_id(db, stone_id)
        if not stone:
            raise HTTPException(status_code=404, detail="Stone not found")

        try:
            AdminManagementRepository.delete_stone(db, stone)
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(status_code=409, detail="Stone is in use and cannot be deleted")
        except Exception:
            db.rollback()
            raise

    @staticmethod
    def create_attribute(db: Session, payload: AttributeCreateRequest) -> Attribute:
        name = payload.name.strip()
        slug = AdminManagementService._unique_slug(
            AdminManagementService._slugify(name),
            lambda candidate: AdminManagementRepository.get_attribute_by_slug(db, candidate) is not None,
        )

        attribute = Attribute(name=name, slug=slug, filterable=payload.filterable)
        try:
            created = AdminManagementRepository.create_attribute(db, attribute)
            db.commit()
            return created
        except Exception:
            db.rollback()
            raise

    @staticmethod
    def update_attribute(db: Session, attribute_id: int, payload: AttributeUpdateRequest) -> Attribute:
        attribute = AdminManagementRepository.get_attribute_by_id(db, attribute_id)
        if not attribute:
            raise HTTPException(status_code=404, detail="Attribute not found")

        if payload.name is not None:
            next_name = payload.name.strip()
            if next_name != attribute.name:
                attribute.name = next_name
                attribute.slug = AdminManagementService._unique_slug(
                    AdminManagementService._slugify(next_name),
                    lambda candidate: (
                        (existing := AdminManagementRepository.get_attribute_by_slug(db, candidate)) is not None
                        and existing.id != attribute.id
                    ),
                )

        for field in ["filterable"]:
            value = getattr(payload, field)
            if value is not None:
                setattr(attribute, field, value)

        try:
            db.commit()
            db.refresh(attribute)
            return attribute
        except Exception:
            db.rollback()
            raise

    @staticmethod
    def delete_attribute(db: Session, attribute_id: int) -> None:
        attribute = AdminManagementRepository.get_attribute_by_id(db, attribute_id)
        if not attribute:
            raise HTTPException(status_code=404, detail="Attribute not found")

        try:
            AdminManagementRepository.delete_attribute(db, attribute)
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(status_code=409, detail="Attribute is in use and cannot be deleted")
        except Exception:
            db.rollback()
            raise

    @staticmethod
    def get_attribute_values(db: Session) -> list:
        return AdminManagementRepository.get_attribute_values(db)

    @staticmethod
    def create_attribute_value(db: Session, payload: AttributeValueCreateRequest) -> AttributeValue:
        attribute = AdminManagementRepository.get_attribute_by_id(db, payload.attribute_id)
        if not attribute:
            raise HTTPException(status_code=404, detail="Attribute not found")

        existing = AdminManagementRepository.get_attribute_value_by_attribute_and_value(db, payload.attribute_id, payload.value)
        if existing:
            raise HTTPException(status_code=409, detail="Attribute value already exists")

        value = AttributeValue(attribute_id=payload.attribute_id, value=payload.value)
        try:
            created = AdminManagementRepository.create_attribute_value(db, value)
            db.commit()
            return created
        except Exception:
            db.rollback()
            raise

    @staticmethod
    def update_attribute_value(db: Session, value_id: int, payload: AttributeValueUpdateRequest) -> AttributeValue:
        value = AdminManagementRepository.get_attribute_value_by_id(db, value_id)
        if not value:
            raise HTTPException(status_code=404, detail="Attribute value not found")

        target_attribute_id = payload.attribute_id if payload.attribute_id is not None else value.attribute_id
        target_value = payload.value if payload.value is not None else value.value
        existing = AdminManagementRepository.get_attribute_value_by_attribute_and_value(db, target_attribute_id, target_value)
        if existing and existing.id != value.id:
            raise HTTPException(status_code=409, detail="Attribute value already exists")

        if payload.attribute_id is not None:
            attribute = AdminManagementRepository.get_attribute_by_id(db, payload.attribute_id)
            if not attribute:
                raise HTTPException(status_code=404, detail="Attribute not found")
            value.attribute_id = payload.attribute_id

        if payload.value is not None:
            value.value = payload.value

        try:
            db.commit()
            db.refresh(value)
            return value
        except Exception:
            db.rollback()
            raise

    @staticmethod
    def delete_attribute_value(db: Session, value_id: int) -> None:
        value = AdminManagementRepository.get_attribute_value_by_id(db, value_id)
        if not value:
            raise HTTPException(status_code=404, detail="Attribute value not found")

        try:
            AdminManagementRepository.delete_attribute_value(db, value)
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(status_code=409, detail="Attribute value is in use and cannot be deleted")
        except Exception:
            db.rollback()
            raise

    @staticmethod
    def update_metal_rates(db: Session, payload: MetalRateBulkUpdateRequest) -> list[MetalRate]:
        updated_items: list[MetalRate] = []

        for item in payload.rates:
            rate = AdminManagementRepository.get_metal_rate_by_id(db, item.id)
            if not rate:
                raise HTTPException(status_code=404, detail=f"Metal rate id {item.id} not found")
            rate.rate_per_gram = item.rate_per_gram
            rate.effective_from = item.effective_from
            updated_items.append(rate)

        if payload.gold_rate_per_gram is not None or payload.silver_rate_per_gram is not None:
            metal_rates = AdminManagementRepository.get_metal_rates(db)
            gold_rate = next(
                (item for item in metal_rates if item.base_metal and item.base_metal.name and item.base_metal.name.lower() == "gold"),
                None,
            )
            silver_rate = next(
                (item for item in metal_rates if item.base_metal and item.base_metal.name and item.base_metal.name.lower() == "silver"),
                None,
            )

            if payload.gold_rate_per_gram is not None:
                if not gold_rate:
                    raise HTTPException(status_code=404, detail="Gold metal rate not found")
                gold_rate.rate_per_gram = payload.gold_rate_per_gram
                if payload.effective_from is not None:
                    gold_rate.effective_from = payload.effective_from
                if gold_rate not in updated_items:
                    updated_items.append(gold_rate)

            if payload.silver_rate_per_gram is not None:
                if not silver_rate:
                    raise HTTPException(status_code=404, detail="Silver metal rate not found")
                silver_rate.rate_per_gram = payload.silver_rate_per_gram
                if payload.effective_from is not None:
                    silver_rate.effective_from = payload.effective_from
                if silver_rate not in updated_items:
                    updated_items.append(silver_rate)

        try:
            db.commit()
            for rate in updated_items:
                db.refresh(rate)
            return updated_items
        except Exception:
            db.rollback()
            raise

    @staticmethod
    def get_products(
        db: Session,
        store_id: UUID | None = None,
        page: int = 1,
        limit: int = 20,
        search: str | None = None,
    ) -> tuple[list[Product], int]:
        if page < 1:
            raise HTTPException(status_code=400, detail="page must be >= 1")
        if limit < 1 or limit > 100:
            raise HTTPException(status_code=400, detail="limit must be between 1 and 100")
        return AdminManagementRepository.get_products_page(db, page, limit, store_id=store_id, search=search or None)

    @staticmethod
    def get_product_detail(db: Session, store_id: UUID, product_id: UUID) -> Product:
        product = AdminManagementRepository.get_product_with_relations(db, product_id, store_id=store_id)
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")
        return product

    @staticmethod
    def _field_error(field: str, message: str) -> HTTPException:
        return HTTPException(status_code=422, detail=[{"loc": [field], "msg": message}])

    @staticmethod
    def _validate_subcategory_category(
        db: Session,
        subcategory_id: int,
        category_id: int,
    ) -> None:
        subcategory = AdminManagementRepository.get_subcategory_by_id(db, subcategory_id)
        if not subcategory:
            raise AdminManagementService._field_error("subcategory_id", "Subcategory not found")
        if subcategory.category_id != category_id:
            raise AdminManagementService._field_error(
                "subcategory_id", "subcategory_id does not belong to category_id"
            )

    @staticmethod
    def create_product(db: Session, store_id: UUID, payload: ProductCreateRequest) -> Product:
        name = payload.name.strip()
        if not name:
            raise AdminManagementService._field_error("name", "Product name is required")

        requested_slug = AdminManagementService._slugify(payload.slug or name)
        slug = AdminManagementService._unique_slug(
            requested_slug,
            lambda candidate: AdminManagementRepository.get_product_by_slug_global(db, candidate) is not None,
        )

        AdminManagementService._validate_subcategory_category(
            db=db,
            subcategory_id=payload.subcategory_id,
            category_id=payload.category_id,
        )

        product = Product(
            store_id=store_id,
            name=name,
            slug=slug,
            description=payload.description,
            subcategory_id=payload.subcategory_id,
            featured=payload.featured,
            customizable=payload.customizable,
            status=payload.status,
        )

        normalized_collection_ids = list(dict.fromkeys(payload.collection_ids or []))
        if payload.collection_id is not None and payload.collection_id not in normalized_collection_ids:
            normalized_collection_ids.insert(0, payload.collection_id)

        normalized_tag_ids = list(dict.fromkeys(payload.tag_ids or []))

        collection_rows: list[Collection] = []
        if normalized_collection_ids:
            collection_rows = AdminManagementRepository.get_collections_by_ids(db, normalized_collection_ids)
            if len(collection_rows) != len(normalized_collection_ids):
                raise AdminManagementService._field_error("collection_ids", "One or more collection ids are invalid")

        tag_rows: list[Tag] = []
        if normalized_tag_ids:
            tag_rows = AdminManagementRepository.get_tags_by_ids(db, normalized_tag_ids)
            if len(tag_rows) != len(normalized_tag_ids):
                raise AdminManagementService._field_error("tag_ids", "One or more tag ids are invalid")

        normalized_images: list[dict] = []
        for index, image_item in enumerate(payload.images or []):
            image_url = (image_item.image_url or "").strip()
            if not image_url:
                continue

            normalized_images.append(
                {
                    "image_url": image_url,
                    "is_primary": bool(image_item.is_primary),
                    "display_order": image_item.display_order if image_item.display_order is not None else index,
                }
            )

        primary_count = sum(1 for item in normalized_images if item["is_primary"])
        if primary_count > 1:
            raise AdminManagementService._field_error("images", "Only one image can be marked as primary")
        if normalized_images and primary_count == 0:
            normalized_images[0]["is_primary"] = True

        normalized_variants: list[dict] = []
        seen_payload_skus: set[str] = set()

        for index, variant_item in enumerate(payload.variants or []):
            candidate_sku = (variant_item.sku_code or "").strip()

            if not candidate_sku:
                candidate_sku = f"{slug}-{index + 1:03d}"

            normalized_sku = re.sub(r"[^a-zA-Z0-9_-]", "-", candidate_sku).strip("-_")
            normalized_sku = re.sub(r"-+", "-", normalized_sku)
            normalized_sku = normalized_sku.upper() or f"{slug.upper().replace('-', '_')}_{index + 1:03d}"
            normalized_sku = normalized_sku[:100]

            dedupe_key = normalized_sku.lower()
            if dedupe_key in seen_payload_skus:
                raise AdminManagementService._field_error(
                    "variants", f"Duplicate variant SKU in request: {normalized_sku}"
                )

            existing_variant = AdminManagementRepository.get_variant_by_sku(db, normalized_sku, store_id=store_id)
            if existing_variant is not None:
                raise AdminManagementService._field_error(
                    "variants", f"Variant SKU already exists: {normalized_sku}"
                )

            seen_payload_skus.add(dedupe_key)
            normalized_variants.append(
                {
                    "stock_quantity": variant_item.stock_quantity,
                    "price_override": variant_item.price_override,
                    "sku_code": normalized_sku,
                }
            )

        try:
            created = AdminManagementRepository.create_product(db, product)
            AdminManagementService._set_product_gender_attribute(db, created.id, payload.gender)

            if collection_rows:
                created.collections = collection_rows

            if tag_rows:
                created.tags = tag_rows

            for variant_item in normalized_variants:
                AdminManagementRepository.create_variant(
                    db,
                    ProductVariant(
                        store_id=store_id,
                        product_id=created.id,
                        stock_quantity=variant_item["stock_quantity"],
                        price_override=variant_item["price_override"],
                        sku_code=variant_item["sku_code"],
                    ),
                )

            for image_item in normalized_images:
                AdminManagementRepository.create_image(
                    db,
                    ProductImage(
                        product_id=created.id,
                        image_url=image_item["image_url"],
                        is_primary=image_item["is_primary"],
                        display_order=image_item["display_order"],
                    ),
                )

            if normalized_images:
                AdminManagementService._normalize_image_orders(db, created.id)

            db.commit()
            db.refresh(created)
            return created
        except Exception:
            db.rollback()
            raise

    @staticmethod
    def update_product(db: Session, store_id: UUID, product_id: UUID, payload: ProductUpdateRequest) -> Product:
        product = AdminManagementRepository.get_product_by_id(db, product_id, store_id=store_id)
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")

        target_subcategory_id = payload.subcategory_id or product.subcategory_id
        current_category_id = product.subcategory.category_id if product.subcategory else None
        target_category_id = payload.category_id or current_category_id
        if target_subcategory_id and target_category_id:
            AdminManagementService._validate_subcategory_category(
                db=db,
                subcategory_id=target_subcategory_id,
                category_id=target_category_id,
            )

        if payload.name is not None:
            next_name = payload.name.strip()
            if next_name != product.name:
                product.name = next_name
                if product.status == "draft":
                    product.slug = AdminManagementService._unique_slug(
                        AdminManagementService._slugify(next_name),
                        lambda candidate: (
                            (existing := AdminManagementRepository.get_product_by_slug(db, candidate, store_id=store_id))
                            is not None
                            and existing.id != product.id
                        ),
                    )

        for field in ["description", "featured", "customizable", "status"]:
            value = getattr(payload, field)
            if value is not None:
                setattr(product, field, value)

        if payload.subcategory_id is not None:
            product.subcategory_id = payload.subcategory_id

        if payload.gender is not None:
            AdminManagementService._set_product_gender_attribute(db, product.id, payload.gender)

        try:
            db.commit()
            db.refresh(product)
            return product
        except Exception:
            db.rollback()
            raise

    @staticmethod
    def delete_product(db: Session, store_id: UUID, product_id: UUID, force: bool = False) -> None:
        product = AdminManagementRepository.get_product_by_id(db, product_id, store_id=store_id)
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")

        try:
            # Keep deletes ordered to prevent FK failures.
            deleted_sales = db.query(Sale).filter(Sale.product_id == product_id).delete(synchronize_session=False)
            deleted_images = db.query(ProductImage).filter(ProductImage.product_id == product_id).delete(synchronize_session=False)
            variant_ids_subquery = db.query(ProductVariant.id).filter(
                ProductVariant.product_id == product_id,
                ProductVariant.store_id == store_id,
            ).subquery()
            db.query(VariantAttribute).filter(
                VariantAttribute.variant_id.in_(db.query(variant_ids_subquery.c.id))
            ).delete(synchronize_session=False)
            deleted_variants = db.query(ProductVariant).filter(
                ProductVariant.product_id == product_id,
                ProductVariant.store_id == store_id,
            ).delete(synchronize_session=False)
            deleted_stones = db.query(ProductStone).filter(ProductStone.product_id == product_id).delete(synchronize_session=False)
            deleted_collections = db.query(ProductCollection).filter(ProductCollection.product_id == product_id).delete(synchronize_session=False)
            deleted_tags = db.query(ProductTag).filter(ProductTag.product_id == product_id).delete(synchronize_session=False)
            deleted_attributes = db.query(ProductAttribute).filter(ProductAttribute.product_id == product_id).delete(synchronize_session=False)

            deleted_dependencies_count = (
                deleted_sales
                + deleted_images
                + deleted_variants
                + deleted_stones
                + deleted_collections
                + deleted_tags
                + deleted_attributes
            )

            logger.info(
                "delete_product product_id=%s store_id=%s deleted_dependencies_count=%s",
                product_id,
                store_id,
                deleted_dependencies_count,
            )

            AdminManagementRepository.delete_product(db, product)
            db.commit()
        except Exception:
            db.rollback()
            raise

    @staticmethod
    def _validate_variant_attribute_value_ids(db: Session, attribute_value_ids: list[int]) -> list[AttributeValue]:
        """A variant can't carry two different values of the same Attribute
        (e.g. Ring Size 6 and Ring Size 7 at once). Returns the resolved,
        de-duplicated AttributeValue rows for the caller to persist."""
        normalized_ids = list(dict.fromkeys(attribute_value_ids or []))
        if not normalized_ids:
            return []

        values = AdminManagementRepository.get_attribute_values_by_ids(db, normalized_ids)
        if len(values) != len(normalized_ids):
            raise HTTPException(status_code=400, detail="One or more attribute value ids are invalid")

        seen_attributes: dict[int, AttributeValue] = {}
        for value in values:
            collision = seen_attributes.get(value.attribute_id)
            if collision is not None:
                attribute_name = value.attribute.name if value.attribute else str(value.attribute_id)
                raise AdminManagementService._field_error(
                    "attribute_value_ids",
                    f"Variant cannot have two values for attribute '{attribute_name}'",
                )
            seen_attributes[value.attribute_id] = value

        return values

    @staticmethod
    def create_variant(
        db: Session,
        store_id: UUID,
        product_id: UUID,
        payload: VariantCreateRequest,
    ) -> ProductVariant:
        product = AdminManagementRepository.get_product_by_id(db, product_id, store_id=store_id)
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")

        existing_sku = AdminManagementRepository.get_variant_by_sku(db, payload.sku_code, store_id=store_id)
        if existing_sku:
            raise HTTPException(status_code=409, detail="Variant SKU already exists")

        attribute_values = AdminManagementService._validate_variant_attribute_value_ids(
            db, payload.attribute_value_ids
        )

        if payload.base_metal_id is not None:
            metal_type = AdminManagementRepository.get_metal_type_by_id(db, payload.base_metal_id)
            if not metal_type:
                raise HTTPException(status_code=404, detail="Metal type not found")
        else:
            metal_type = None
        if payload.metal_color_id is not None:
            metal_color = AdminManagementRepository.get_metal_color_by_id(db, payload.metal_color_id)
            if not metal_color:
                raise HTTPException(status_code=404, detail="Metal color not found")
        if payload.metal_purity_id is not None:
            metal_purity = AdminManagementRepository.get_metal_purity_by_id(db, payload.metal_purity_id)
            if not metal_purity:
                raise HTTPException(status_code=404, detail="Metal purity not found")

        variant = ProductVariant(
            store_id=store_id,
            product_id=product_id,
            base_metal_id=payload.base_metal_id,
            metal_type=payload.metal_type or (metal_type.name if metal_type else None),
            metal_color_id=payload.metal_color_id,
            metal_purity_id=payload.metal_purity_id,
            weight=payload.weight if payload.weight is not None else payload.metal_weight_grams,
            metal_weight_grams=payload.metal_weight_grams if payload.metal_weight_grams is not None else payload.weight,
            stone_quantity=payload.stone_quantity,
            stone_cost=payload.stone_cost,
            making_charges=payload.making_charges,
            cost_price=payload.cost_price,
            price_override=payload.price_override,
            stock_quantity=payload.stock_quantity,
            sku_code=payload.sku_code,
        )

        try:
            created = AdminManagementRepository.create_variant(db, variant)
            AdminManagementRepository.replace_variant_attributes(
                db, created.id, [value.id for value in attribute_values]
            )
            db.commit()
            db.refresh(created)
            return created
        except Exception:
            db.rollback()
            raise

    @staticmethod
    def update_variant(
        db: Session,
        store_id: UUID,
        variant_id: UUID,
        payload: VariantUpdateRequest,
    ) -> ProductVariant:
        variant = AdminManagementRepository.get_variant_by_id(db, variant_id, store_id=store_id)
        if not variant:
            raise HTTPException(status_code=404, detail="Variant not found")

        if payload.sku_code and payload.sku_code != variant.sku_code:
            existing_sku = AdminManagementRepository.get_variant_by_sku(db, payload.sku_code, store_id=store_id)
            if existing_sku:
                raise HTTPException(status_code=409, detail="Variant SKU already exists")

        if payload.base_metal_id is not None:
            metal_type = AdminManagementRepository.get_metal_type_by_id(db, payload.base_metal_id)
            if not metal_type:
                raise HTTPException(status_code=404, detail="Metal type not found")
            variant.metal_type = metal_type.name
        if payload.metal_color_id is not None:
            metal_color = AdminManagementRepository.get_metal_color_by_id(db, payload.metal_color_id)
            if not metal_color:
                raise HTTPException(status_code=404, detail="Metal color not found")
        if payload.metal_purity_id is not None:
            metal_purity = AdminManagementRepository.get_metal_purity_by_id(db, payload.metal_purity_id)
            if not metal_purity:
                raise HTTPException(status_code=404, detail="Metal purity not found")

        attribute_values = AdminManagementService._validate_variant_attribute_value_ids(
            db, payload.attribute_value_ids
        )

        for field in [
            "base_metal_id",
            "metal_type",
            "metal_color_id",
            "metal_purity_id",
            "weight",
            "metal_weight_grams",
            "stone_quantity",
            "stone_cost",
            "making_charges",
            "cost_price",
            "price_override",
            "stock_quantity",
            "sku_code",
        ]:
            value = getattr(payload, field)
            if value is not None:
                setattr(variant, field, value)

        if payload.weight is not None and payload.metal_weight_grams is None:
            variant.metal_weight_grams = payload.weight
        if payload.metal_weight_grams is not None and payload.weight is None:
            variant.weight = payload.metal_weight_grams

        try:
            AdminManagementRepository.replace_variant_attributes(
                db, variant.id, [value.id for value in attribute_values]
            )
            db.commit()
            db.refresh(variant)
            return variant
        except Exception:
            db.rollback()
            raise

    @staticmethod
    def delete_variant(db: Session, store_id: UUID, variant_id: UUID) -> None:
        variant = AdminManagementRepository.get_variant_by_id(db, variant_id, store_id=store_id)
        if not variant:
            raise HTTPException(status_code=404, detail="Variant not found")

        try:
            AdminManagementRepository.delete_variant(db, variant)
            db.commit()
        except Exception:
            db.rollback()
            raise

    @staticmethod
    def _normalize_image_orders(db: Session, product_id: UUID) -> None:
        images = AdminManagementRepository.get_product_images(db, product_id)
        for index, image in enumerate(images):
            image.display_order = index

    @staticmethod
    def create_image(
        db: Session,
        store_id: UUID,
        product_id: UUID,
        payload: ImageCreateRequest,
    ) -> ProductImage:
        product = AdminManagementRepository.get_product_by_id(db, product_id, store_id=store_id)
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")

        display_order = payload.display_order
        if display_order is None:
            display_order = AdminManagementRepository.get_max_image_order(db, product_id) + 1

        try:
            if payload.is_primary:
                AdminManagementRepository.unset_primary_images(db, product_id)

            image = ProductImage(
                product_id=product_id,
                image_url=payload.image_url,
                is_primary=payload.is_primary,
                display_order=display_order,
            )
            created = AdminManagementRepository.create_image(db, image)
            AdminManagementService._normalize_image_orders(db, product_id)
            db.commit()
            db.refresh(created)
            return created
        except Exception:
            db.rollback()
            raise

    @staticmethod
    def delete_image(db: Session, store_id: UUID, image_id: int) -> None:
        image = AdminManagementRepository.get_image_by_id(db, image_id)
        if not image:
            raise HTTPException(status_code=404, detail="Image not found")

        product = AdminManagementRepository.get_product_by_id(db, image.product_id, store_id=store_id)
        if not product:
            raise HTTPException(status_code=404, detail="Image not found")

        product_id = image.product_id
        deleted_primary = bool(image.is_primary)

        try:
            AdminManagementRepository.delete_image(db, image)
            AdminManagementService._normalize_image_orders(db, product_id)

            if deleted_primary:
                images = AdminManagementRepository.get_product_images(db, product_id)
                if images:
                    images[0].is_primary = True

            db.commit()
        except Exception:
            db.rollback()
            raise

    @staticmethod
    def set_primary_image(db: Session, store_id: UUID, image_id: int) -> ProductImage:
        image = AdminManagementRepository.get_image_by_id(db, image_id)
        if not image:
            raise HTTPException(status_code=404, detail="Image not found")

        product = AdminManagementRepository.get_product_by_id(db, image.product_id, store_id=store_id)
        if not product:
            raise HTTPException(status_code=404, detail="Image not found")

        try:
            AdminManagementRepository.unset_primary_images(db, image.product_id)
            image.is_primary = True
            db.commit()
            db.refresh(image)
            return image
        except Exception:
            db.rollback()
            raise

    @staticmethod
    def reorder_images(db: Session, store_id: UUID, product_id: UUID, image_ids: list[int]) -> None:
        product = AdminManagementRepository.get_product_by_id(db, product_id, store_id=store_id)
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")

        unique_ids: list[int] = []
        for image_id in image_ids:
            if image_id not in unique_ids:
                unique_ids.append(image_id)

        images = AdminManagementRepository.get_product_images(db, product_id)
        image_map = {image.id: image for image in images}

        missing = [image_id for image_id in unique_ids if image_id not in image_map]
        if missing:
            raise HTTPException(status_code=400, detail=f"Invalid image ids: {missing}")

        remaining_ids = [image.id for image in images if image.id not in unique_ids]
        ordered_ids = unique_ids + remaining_ids

        try:
            for index, image_id in enumerate(ordered_ids):
                image_map[image_id].display_order = index
            db.commit()
        except Exception:
            db.rollback()
            raise

    @staticmethod
    def update_product_collections(db: Session, store_id: UUID, product_id: UUID, ids: list[int]) -> Product:
        product = AdminManagementRepository.get_product_by_id(db, product_id, store_id=store_id)
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")

        collections = AdminManagementRepository.get_collections_by_ids(db, ids)
        if len(collections) != len(set(ids)):
            raise HTTPException(status_code=400, detail="One or more collection ids are invalid")

        try:
            product.collections = collections
            db.commit()
            db.refresh(product)
            return product
        except Exception:
            db.rollback()
            raise

    @staticmethod
    def update_product_tags(db: Session, store_id: UUID, product_id: UUID, ids: list[int]) -> Product:
        product = AdminManagementRepository.get_product_by_id(db, product_id, store_id=store_id)
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")

        tags = AdminManagementRepository.get_tags_by_ids(db, ids)
        if len(tags) != len(set(ids)):
            raise HTTPException(status_code=400, detail="One or more tag ids are invalid")

        try:
            product.tags = tags
            db.commit()
            db.refresh(product)
            return product
        except Exception:
            db.rollback()
            raise

    @staticmethod
    def update_product_attributes(db: Session, store_id: UUID, product_id: UUID, ids: list[int]) -> Product:
        product = AdminManagementRepository.get_product_by_id(db, product_id, store_id=store_id)
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")

        normalized_ids = list(dict.fromkeys(ids))
        attribute_values = AdminManagementRepository.get_attribute_values_by_ids(db, normalized_ids)
        if len(attribute_values) != len(normalized_ids):
            raise HTTPException(status_code=400, detail="One or more attribute value ids are invalid")

        gender_attribute, gender_values = AdminManagementService._ensure_gender_attribute_values(db)
        default_gender = gender_values.get(AdminManagementService.DEFAULT_GENDER_KEY)
        if default_gender is None:
            raise HTTPException(status_code=500, detail="Default gender attribute value is not configured")

        selected_gender_ids = {
            value.id
            for value in attribute_values
            if value.attribute_id == gender_attribute.id
        }

        final_ids = [value_id for value_id in normalized_ids if value_id not in selected_gender_ids]

        selected_gender_id = next(
            (value_id for value_id in normalized_ids if value_id in selected_gender_ids),
            default_gender.id,
        )
        final_ids.append(selected_gender_id)

        try:
            AdminManagementRepository.replace_product_attributes(db, product_id, final_ids)
            db.commit()
            db.refresh(product)
            return product
        except Exception:
            db.rollback()
            raise

    @staticmethod
    def update_product_stones(
        db: Session,
        store_id: UUID,
        product_id: UUID,
        payload: ProductStonesUpdateRequest,
    ) -> Product:
        product = AdminManagementRepository.get_product_by_id(db, product_id, store_id=store_id)
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")

        requested_ids = [item.stone_id for item in payload.stones]
        stones = AdminManagementRepository.get_stones_by_ids(db, requested_ids)
        if len(stones) != len(set(requested_ids)):
            raise HTTPException(status_code=400, detail="One or more stone ids are invalid")

        stone_rows = [
            {
                "stone_id": item.stone_id,
                "quantity": item.quantity,
                "total_carat_weight": item.total_carat_weight,
            }
            for item in payload.stones
        ]

        try:
            AdminManagementRepository.replace_product_stones(db, product_id, stone_rows)
            db.commit()
            db.refresh(product)
            return product
        except Exception:
            db.rollback()
            raise
