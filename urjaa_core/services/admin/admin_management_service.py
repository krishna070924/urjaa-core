from uuid import UUID
import re
import logging
from typing import Callable

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy import func, or_, text
from sqlalchemy.orm import Session

from urjaa_core.models.product import Product
from urjaa_core.models.product_image import ProductImage
from urjaa_core.models.product_collection import ProductCollection
from urjaa_core.models.product_tag import ProductTag
from urjaa_core.models.product_stone import ProductStone
from urjaa_core.models.product_variant import ProductVariant
from urjaa_core.services import physical_unit_service
from urjaa_core.models.base_metal import BaseMetal
from urjaa_core.models.category import Category
from urjaa_core.models.collection import Collection
from urjaa_core.models.gender import Gender
from urjaa_core.models.metal import Metal
from urjaa_core.models.metal_color import MetalColor
from urjaa_core.models.metal_purity import MetalPurity
from urjaa_core.models.metal_rate import MetalRate
from urjaa_core.models.stone import Stone
from urjaa_core.models.subcategory import Subcategory
from urjaa_core.models.tag import Tag
from urjaa_core.models.sale import Sale
from urjaa_core.models.store import Store
from urjaa_core.repositories.admin.admin_management_repository import AdminManagementRepository
from urjaa_core.schemas.admin.management import (
    CategoryCreateRequest,
    CategoryUpdateRequest,
    CollectionCreateRequest,
    CollectionUpdateRequest,
    ImageCreateRequest,
    MetalColorCreateRequest,
    MetalColorUpdateRequest,
    MetalCombinationGenerateRequest,
    MetalPurityCreateRequest,
    MetalPurityUpdateRequest,
    MetalRateBulkUpdateRequest,
    MetalRateCreateRequest,
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
    VariantCreateRequest,
    VariantUpdateRequest,
)


logger = logging.getLogger(__name__)


class AdminManagementService:
    DEFAULT_GENDER_KEY = "unisex"

    VARIANT_CONSTRAINT_MESSAGES = {
        "chk_variant_weight_positive": (
            "Weight must be greater than 0 if provided — leave it blank instead of 0"
        ),
        "chk_variant_making_non_negative": "Making charges cannot be negative",
        "product_variants_stock_quantity_non_negative": "Stock quantity cannot be negative",
        "product_variants_sku_code_key": "That SKU is already used by another item. Change it, or leave SKU blank to generate one.",
    }

    @staticmethod
    def _variant_integrity_error_detail(exc: IntegrityError) -> str:
        constraint_name = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
        if not constraint_name:
            message = str(exc.orig)
            constraint_name = next(
                (name for name in AdminManagementService.VARIANT_CONSTRAINT_MESSAGES if name in message),
                None,
            )
        return AdminManagementService.VARIANT_CONSTRAINT_MESSAGES.get(
            constraint_name, "Invalid variant data — check numeric fields are valid"
        )

    @staticmethod
    def _next_sku(db: Session, product: Product) -> str:
        """Format: first 3 letters of the product's category + a 6-digit
        sequence, e.g. RIN-000042 (URJ when uncategorised).

        Metal and size are deliberately NOT encoded: a SKU must stay valid when
        a variant is edited. The sequence is atomic, so concurrent saves cannot
        collide; the loop only skips a number a hand-typed SKU already took. The
        unique constraint remains the final arbiter."""
        subcategory = product.subcategory
        category = subcategory.category.name if subcategory and subcategory.category else ""
        prefix = re.sub(r"[^A-Za-z]", "", category)[:3].upper() or "URJ"
        while True:
            number = db.execute(text("SELECT nextval('variant_sku_seq')")).scalar()
            sku = f"{prefix}-{number:06d}"
            if not db.query(ProductVariant.id).filter(func.lower(ProductVariant.sku_code) == sku.lower()).first():
                return sku

    @staticmethod
    def _resolve_gender_id(db: Session, gender: str) -> int:
        """H-11: the request's men/women/unisex, matched case-insensitively
        against the `genders` lookup (D21/H-08) -- create/update/duplicate/CSV
        import all write gender_id through this now, not EAV."""
        row = db.query(Gender).filter(func.lower(Gender.name) == gender.strip().lower()).first()
        if row is None:
            raise AdminManagementService._field_error("gender", f"Unknown gender: {gender!r}")
        return row.id

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

            deleted_products_count = db.query(Product).filter(
                Product.store_id == store_id
            ).delete(synchronize_session=False)

            deleted_customers_count = 0

            deleted_store_count = db.query(Store).filter(Store.id == store_id).delete(synchronize_session=False)
            if deleted_store_count != 1:
                raise HTTPException(status_code=404, detail="Store not found")

            logger.info(
                "force_delete_store deleting_store_id=%s deleted_products_count=%s deleted_sales_count=%s deleted_images_count=%s deleted_variants_count=%s deleted_stones_count=%s deleted_collections_count=%s deleted_tags_count=%s deleted_customers_count=%s",
                store_id,
                deleted_products_count,
                deleted_sales_count,
                deleted_product_images_count,
                deleted_product_variants_count,
                deleted_product_stones_count,
                deleted_product_collections_count,
                deleted_product_tags_count,
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
        # variant_sku is optional: blank rows get a generated SKU (H-04).
        required_fields = [
            "product_name",
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

            # H-10: CSV only carries the legacy triad, never metal_id itself --
            # resolve it the same way a legacy-only API request does (D25).
            parsed_metal_id = AdminManagementService._resolve_metal_id_from_legacy(
                db, parsed_base_metal_id, parsed_metal_color_id, parsed_metal_purity_id
            )

            normalized_rows.append(
                {
                    "product_slug": product_slug,
                    "variant": {
                        "metal_id": parsed_metal_id,
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
        # CSV doesn't carry a gender column -- every imported product gets the
        # same default (H-11: written to gender_id now, not EAV).
        default_gender_id = AdminManagementService._resolve_gender_id(db, AdminManagementService.DEFAULT_GENDER_KEY)

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
                    gender_id=default_gender_id,
                )
                created_product = AdminManagementRepository.create_product(db, product)
                products_by_slug[slug] = created_product

            created_variant_count = 0
            for item in normalized_rows:
                product = products_by_slug[item["product_slug"]]
                variant_payload = item["variant"]
                variant = ProductVariant(
                    store_id=store_id,
                    product_id=product.id,
                    metal_id=variant_payload["metal_id"],
                    base_metal_id=variant_payload["base_metal_id"],
                    metal_color_id=variant_payload["metal_color_id"],
                    metal_purity_id=variant_payload["metal_purity_id"],
                    metal_weight_grams=variant_payload["metal_weight_grams"],
                    price_override=variant_payload["price_override"],
                    stone_quantity=variant_payload["stone_quantity"],
                    stone_cost=variant_payload["stone_cost"],
                    making_charges=variant_payload["making_charges"],
                    stock_quantity=variant_payload["stock_quantity"],
                    sku_code=variant_payload["sku_code"] or AdminManagementService._next_sku(db, product),
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

        if payload.size_unit and not payload.size_label:
            raise AdminManagementService._field_error("size_unit", "size_unit requires size_label")

        subcategory = Subcategory(
            category_id=payload.category_id,
            name=name,
            slug=slug,
            size_label=payload.size_label,
            size_unit=payload.size_unit,
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

        if payload.size_label is not None:
            subcategory.size_label = payload.size_label
        if payload.size_unit is not None:
            subcategory.size_unit = payload.size_unit

        if subcategory.size_unit and not subcategory.size_label:
            raise AdminManagementService._field_error("size_unit", "size_unit requires size_label")

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
    def get_collections(db: Session) -> list[Collection]:
        return AdminManagementRepository.get_collections(db)

    @staticmethod
    def get_tags(db: Session) -> list[Tag]:
        return AdminManagementRepository.get_tags(db)

    @staticmethod
    def get_stones(db: Session) -> list[Stone]:
        return AdminManagementRepository.get_stones(db)

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
        metal_type = AdminManagementRepository.get_metal_type_by_id(db, payload.base_metal_id)
        if not metal_type:
            raise HTTPException(status_code=404, detail="Metal type not found")

        existing = AdminManagementRepository.get_metal_color_by_name(db, payload.name, payload.base_metal_id)
        if existing:
            raise HTTPException(status_code=409, detail="Metal color already exists")

        metal_color = MetalColor(name=payload.name, base_metal_id=payload.base_metal_id)
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

        next_base_metal_id = payload.base_metal_id if payload.base_metal_id is not None else metal_color.base_metal_id
        next_name = payload.name if payload.name is not None else metal_color.name

        reassigning = payload.base_metal_id is not None and payload.base_metal_id != metal_color.base_metal_id
        if reassigning:
            metal_type = AdminManagementRepository.get_metal_type_by_id(db, payload.base_metal_id)
            if not metal_type:
                raise HTTPException(status_code=404, detail="Metal type not found")

            # K-02: a colour's base metal can't change out from under a
            # combination or variant that already relies on it under the
            # current metal — that pairing would become invalid silently.
            in_use = (
                db.query(Metal.id).filter(Metal.metal_color_id == metal_color.id).first() is not None
                or db.query(ProductVariant.id).filter(ProductVariant.metal_color_id == metal_color.id).first()
                is not None
            )
            if in_use:
                raise HTTPException(
                    status_code=409,
                    detail=f"Metal color {metal_color.name!r} is in use under its current base metal "
                    "and cannot be reassigned",
                )

        existing = AdminManagementRepository.get_metal_color_by_name(db, next_name, next_base_metal_id)
        if existing and existing.id != metal_color.id:
            raise HTTPException(status_code=409, detail="Metal color already exists")

        if payload.base_metal_id is not None:
            metal_color.base_metal_id = payload.base_metal_id
        if payload.name is not None:
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
    def get_metals(db: Session) -> list[Metal]:
        return AdminManagementRepository.get_metals(db)

    @staticmethod
    def generate_metal_combinations(
        db: Session, payload: MetalCombinationGenerateRequest
    ) -> tuple[list[dict], list[dict]]:
        """D26: create every missing (colour x purity) combination for one
        base metal. Existing combinations are left untouched — that's what
        makes running this twice produce zero new rows.

        Colours/purities that don't belong to the chosen base metal are
        rejected the same way `_validate_metal_colour_pairing` rejects them
        on a variant (D23), just surfaced as a 422 here since this endpoint
        validates a batch of ids rather than one FK on a single record.
        """
        base_metal = AdminManagementRepository.get_metal_type_by_id(db, payload.base_metal_id)
        if not base_metal:
            raise HTTPException(status_code=404, detail="Metal type not found")

        colour_ids = list(dict.fromkeys(payload.metal_color_ids))
        purity_ids = list(dict.fromkeys(payload.metal_purity_ids))

        colours = AdminManagementRepository.get_metal_colors_by_ids(db, colour_ids)
        if len(colours) != len(colour_ids):
            raise HTTPException(status_code=404, detail="One or more metal colours not found")
        for colour in colours:
            if colour.base_metal_id is not None and colour.base_metal_id != base_metal.id:
                raise AdminManagementService._field_error(
                    "metal_color_ids",
                    f"Metal colour {colour.name!r} does not belong to the selected base metal",
                )

        purities = AdminManagementRepository.get_metal_purities_by_ids(db, purity_ids)
        if len(purities) != len(purity_ids):
            raise HTTPException(status_code=404, detail="One or more metal purities not found")
        for purity in purities:
            if purity.base_metal_id is not None and purity.base_metal_id != base_metal.id:
                raise AdminManagementService._field_error(
                    "metal_purity_ids",
                    f"Metal purity {purity.purity_label!r} does not belong to the selected base metal",
                )

        colour_by_id = {colour.id: colour.name for colour in colours}
        purity_by_id = {purity.id: purity.purity_label for purity in purities}

        existing = AdminManagementRepository.get_metals_by_selectors(db, base_metal.id, colour_ids, purity_ids)
        existing_by_key = {(m.metal_color_id, m.metal_purity_id): m for m in existing}

        # "22K Yellow Gold" — same "<purity> <colour> <base metal>" order as
        # scripts/seed_dev_catalogue.sql. display_name stays editable
        # afterwards, so this default doesn't need to be perfect.
        # A metal with a single colour (Silver, Platinum) reads "925 Silver",
        # not "925 Silver Silver" — same rule as the seed script.
        single_colour = db.query(MetalColor).filter(MetalColor.base_metal_id == base_metal.id).count() == 1
        rows_to_insert = [
            {
                "base_metal_id": base_metal.id,
                "metal_color_id": colour.id,
                "metal_purity_id": purity.id,
                "display_name": " ".join(
                    part for part in (purity.purity_label, None if single_colour else colour.name, base_metal.name) if part
                ),
            }
            for colour in colours
            for purity in purities
            if (colour.id, purity.id) not in existing_by_key
        ]

        try:
            created_rows = AdminManagementRepository.bulk_insert_metals(db, rows_to_insert)
            db.commit()
        except Exception:
            db.rollback()
            raise

        def _to_response(metal_color_id: int, metal_purity_id: int, display_name: str | None, metal_id: int) -> dict:
            return {
                "id": metal_id,
                "base_metal_id": base_metal.id,
                "base_metal_name": base_metal.name,
                "metal_color_id": metal_color_id,
                "metal_color_name": colour_by_id.get(metal_color_id),
                "metal_purity_id": metal_purity_id,
                "metal_purity_label": purity_by_id.get(metal_purity_id),
                "display_name": display_name,
            }

        created = [
            _to_response(row["metal_color_id"], row["metal_purity_id"], row["display_name"], row["id"])
            for row in created_rows
        ]
        skipped = [
            _to_response(metal.metal_color_id, metal.metal_purity_id, metal.display_name, metal.id)
            for metal in existing_by_key.values()
        ]
        return created, skipped

    @staticmethod
    def delete_metal_combination(db: Session, metal_id: int) -> None:
        metal = AdminManagementRepository.get_metal_by_id(db, metal_id)
        if not metal:
            raise HTTPException(status_code=404, detail="Metal combination not found")

        try:
            AdminManagementRepository.delete_metal(db, metal)
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(
                status_code=409,
                detail="Metal combination is used by one or more variants and cannot be deleted",
            )
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
    def create_metal_rate(db: Session, payload: MetalRateCreateRequest) -> MetalRate:
        metal_type = AdminManagementRepository.get_metal_type_by_id(db, payload.base_metal_id)
        if not metal_type:
            raise HTTPException(status_code=404, detail="Metal type not found")

        metal_rate = MetalRate(
            base_metal_id=payload.base_metal_id,
            rate_per_gram=payload.rate_per_gram,
            effective_from=payload.effective_from,
        )
        try:
            created = AdminManagementRepository.create_metal_rate(db, metal_rate)
            db.commit()
            return created
        except IntegrityError:
            db.rollback()
            raise HTTPException(status_code=409, detail="A metal rate for this metal type and effective date already exists")
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
            gender_id=AdminManagementService._resolve_gender_id(db, payload.gender),
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
                # Generated at insert time, once the product exists (H-04).
                normalized_variants.append(
                    {"stock_quantity": variant_item.stock_quantity, "price_override": variant_item.price_override, "sku_code": None}
                )
                continue

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
                        sku_code=variant_item["sku_code"] or AdminManagementService._next_sku(db, created),
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
    def _duplicate_sku(seed_sku: str | None, existing_skus_lower: set[str]) -> str:
        """Same `-COPY`, `-COPY-2`, ... pattern as VariantManager.tsx's
        buildDuplicateSku, applied server-side for bulk product duplication."""
        normalized_seed = (seed_sku or "").strip() or "VARIANT"
        candidate = f"{normalized_seed}-COPY"
        counter = 1
        while candidate.lower() in existing_skus_lower:
            counter += 1
            candidate = f"{normalized_seed}-COPY-{counter}"
        return candidate

    @staticmethod
    def duplicate_product(db: Session, store_id: UUID, product_id: UUID) -> Product:
        source = AdminManagementRepository.get_product_with_relations(db, product_id, store_id=store_id)
        if not source:
            raise HTTPException(status_code=404, detail="Product not found")

        name = f"{source.name} (Copy)"
        slug = AdminManagementService._unique_slug(
            AdminManagementService._slugify(name),
            lambda candidate: AdminManagementRepository.get_product_by_slug_global(db, candidate) is not None,
        )

        clone = Product(
            store_id=store_id,
            name=name,
            slug=slug,
            description=source.description,
            subcategory_id=source.subcategory_id,
            status="draft",
            featured=source.featured,
            customizable=source.customizable,
            gender_id=source.gender_id,
        )

        try:
            created = AdminManagementRepository.create_product(db, clone)

            created.collections = list(source.collections)
            created.tags = list(source.tags)

            for stone in source.stones:
                db.add(
                    ProductStone(
                        product_id=created.id,
                        stone_id=stone.stone_id,
                        quantity=stone.quantity,
                        total_carat_weight=stone.total_carat_weight,
                        # cost feeds price (H-09) — dropping it would silently
                        # reprice the copy. Certificate number/agency identify one
                        # physical stone, so a copy doesn't inherit them.
                        cost=stone.cost,
                        cut=stone.cut,
                        clarity=stone.clarity,
                        color=stone.color,
                        origin=stone.origin,
                    )
                )

            for image in source.images:
                db.add(
                    ProductImage(
                        product_id=created.id,
                        image_url=image.image_url,
                        is_primary=image.is_primary,
                        display_order=image.display_order,
                    )
                )

            existing_skus_lower = {
                sku.lower()
                for (sku,) in db.query(ProductVariant.sku_code).filter(
                    ProductVariant.store_id == store_id, ProductVariant.sku_code.isnot(None)
                )
            }

            for variant in source.variants:
                new_sku = AdminManagementService._duplicate_sku(variant.sku_code, existing_skus_lower)
                existing_skus_lower.add(new_sku.lower())

                new_variant = ProductVariant(
                    store_id=store_id,
                    product_id=created.id,
                    metal_id=variant.metal_id,
                    size_value=variant.size_value,
                    spec_note=variant.spec_note,
                    base_metal_id=variant.base_metal_id,
                    metal_color_id=variant.metal_color_id,
                    metal_purity_id=variant.metal_purity_id,
                    weight=variant.weight,
                    metal_type=variant.metal_type,
                    metal_weight_grams=variant.metal_weight_grams,
                    stone_quantity=variant.stone_quantity,
                    stone_cost=variant.stone_cost,
                    making_charges=variant.making_charges,
                    cost_price=variant.cost_price,
                    price_override=variant.price_override,
                    stock_quantity=0,
                    sku_code=new_sku,
                    status=variant.status,
                    # internal_notes intentionally NOT cloned: it's a staff-only
                    # physical stock-location note (e.g. "box 4, shelf B") for the
                    # ORIGINAL batch. A clone starts as 0-stock/not-yet-received,
                    # so the source note would be actively misleading if copied.
                )
                AdminManagementRepository.create_variant(db, new_variant)

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
            product.gender_id = AdminManagementService._resolve_gender_id(db, payload.gender)

        try:
            db.commit()
            db.refresh(product)
            return product
        except Exception:
            db.rollback()
            raise

    @staticmethod
    def delete_product(db: Session, store_id: UUID, product_id: UUID, force: bool = False) -> None:
        """H-08: soft delete. Sets deleted_at instead of hard-deleting the product
        and cascading through its variants/images/sales/etc - those rows must
        survive so existing orders and sales history keep resolving product/variant
        details. `force` is accepted for API compatibility with callers but soft
        delete has no dependency gate to bypass."""
        product = AdminManagementRepository.get_product_by_id(db, product_id, store_id=store_id)
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")

        try:
            product.deleted_at = func.now()
            logger.info("delete_product (soft) product_id=%s store_id=%s", product_id, store_id)
            db.commit()
        except Exception:
            db.rollback()
            raise

    @staticmethod
    def _validate_metal_colour_pairing(metal_color, base_metal_id) -> None:
        """Reject a colour that does not belong to the chosen base metal (D23).

        Gold comes in yellow, white and rose; silver does not come in rose.
        Enforced server-side, not merely hidden in the admin dropdown — the
        dev database already contained a variant saved as Gold / Silver.

        A colour whose own base_metal_id is NULL is not yet classified (see
        migration 0019, which leaves such rows unmapped rather than guessing).
        Those are allowed through so existing data keeps working; tightening
        that is a follow-up once staff have corrected it.
        """
        if metal_color is None or base_metal_id is None:
            return
        colour_metal = getattr(metal_color, "base_metal_id", None)
        if colour_metal is None:
            return
        if colour_metal != base_metal_id:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Metal colour {metal_color.name!r} does not belong to the "
                    f"selected metal."
                ),
            )

    @staticmethod
    def _resolve_metal_id_from_legacy(
        db: Session, base_metal_id: int | None, metal_color_id: int | None, metal_purity_id: int | None
    ) -> int | None:
        """D25/H-10: if a legacy (base metal, colour, purity) triad names an
        existing `metals` row, resolve its id so metal_id stays in sync with
        legacy-only writes -- readers already prefer metal_id over the legacy
        columns (H-07). Any leg missing, or no such combination yet, -> None;
        legacy-only data keeps working unchanged."""
        if base_metal_id is None or metal_color_id is None or metal_purity_id is None:
            return None
        matches = AdminManagementRepository.get_metals_by_selectors(
            db, base_metal_id, [metal_color_id], [metal_purity_id]
        )
        return matches[0].id if matches else None

    @staticmethod
    def _resolve_and_validate_metal_id(
        db: Session,
        metal_id: int,
        base_metal_id: int | None,
        metal_color_id: int | None,
        metal_purity_id: int | None,
    ) -> Metal:
        """H-10: metal_id must reference a real `metals` row (404 otherwise);
        if the request ALSO names legacy ids, they must agree with that row's
        own combination or the request is ambiguous (422) rather than one
        side silently winning."""
        metal = AdminManagementRepository.get_metal_by_id(db, metal_id)
        if metal is None:
            raise HTTPException(status_code=404, detail="Metal combination not found")
        if (
            (base_metal_id is not None and base_metal_id != metal.base_metal_id)
            or (metal_color_id is not None and metal_color_id != metal.metal_color_id)
            or (metal_purity_id is not None and metal_purity_id != metal.metal_purity_id)
        ):
            raise HTTPException(
                status_code=422,
                detail="metal_id does not match the given base_metal_id/metal_color_id/metal_purity_id",
            )
        return metal

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

        sku_code = (payload.sku_code or "").strip() or AdminManagementService._next_sku(db, product)
        if payload.sku_code and db.query(ProductVariant.id).filter(func.lower(ProductVariant.sku_code) == sku_code.lower()).first():
            raise HTTPException(
                status_code=409,
                detail=f"SKU {sku_code} is already used by another item. Change it, or leave SKU blank to generate one.",
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
            AdminManagementService._validate_metal_colour_pairing(metal_color, payload.base_metal_id)
        if payload.metal_purity_id is not None:
            metal_purity = AdminManagementRepository.get_metal_purity_by_id(db, payload.metal_purity_id)
            if not metal_purity:
                raise HTTPException(status_code=404, detail="Metal purity not found")

        # H-10: metal_id given -> validate it and let it win, writing the
        # legacy ids from the Metal row so old readers stay consistent.
        # Otherwise, a full legacy triad resolves metal_id if that
        # combination already exists (D25); partial/absent legacy ids leave
        # metal_id null, unchanged from before this ticket.
        resolved_base_metal_id = payload.base_metal_id
        resolved_metal_color_id = payload.metal_color_id
        resolved_metal_purity_id = payload.metal_purity_id
        if payload.metal_id is not None:
            metal = AdminManagementService._resolve_and_validate_metal_id(
                db, payload.metal_id, payload.base_metal_id, payload.metal_color_id, payload.metal_purity_id
            )
            resolved_metal_id = metal.id
            resolved_base_metal_id = metal.base_metal_id
            resolved_metal_color_id = metal.metal_color_id
            resolved_metal_purity_id = metal.metal_purity_id
        else:
            resolved_metal_id = AdminManagementService._resolve_metal_id_from_legacy(
                db, payload.base_metal_id, payload.metal_color_id, payload.metal_purity_id
            )

        variant = ProductVariant(
            store_id=store_id,
            product_id=product_id,
            metal_id=resolved_metal_id,
            base_metal_id=resolved_base_metal_id,
            metal_type=payload.metal_type or (metal_type.name if metal_type else None),
            metal_color_id=resolved_metal_color_id,
            metal_purity_id=resolved_metal_purity_id,
            weight=payload.weight if payload.weight is not None else payload.metal_weight_grams,
            metal_weight_grams=payload.metal_weight_grams if payload.metal_weight_grams is not None else payload.weight,
            stone_quantity=payload.stone_quantity,
            stone_cost=payload.stone_cost,
            making_charges=payload.making_charges,
            cost_price=payload.cost_price,
            price_override=payload.price_override,
            stock_quantity=payload.stock_quantity,
            sku_code=sku_code,
            internal_notes=payload.internal_notes,
            huid_number=payload.huid_number,
            size_value=payload.size_value,
            spec_note=payload.spec_note,
        )

        try:
            created = AdminManagementRepository.create_variant(db, variant)
            db.commit()
            db.refresh(created)
            return created
        except IntegrityError as exc:
            db.rollback()
            raise HTTPException(
                status_code=422, detail=AdminManagementService._variant_integrity_error_detail(exc)
            )
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
            # Compare against the metal this update RESULTS in, not just the
            # one it carries — changing only the colour must still be checked
            # against the variant's existing metal.
            effective_base_metal_id = (
                payload.base_metal_id if payload.base_metal_id is not None else variant.base_metal_id
            )
            AdminManagementService._validate_metal_colour_pairing(metal_color, effective_base_metal_id)
        if payload.metal_purity_id is not None:
            metal_purity = AdminManagementRepository.get_metal_purity_by_id(db, payload.metal_purity_id)
            if not metal_purity:
                raise HTTPException(status_code=404, detail="Metal purity not found")

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
            "internal_notes",
            "huid_number",
            "size_value",
            "spec_note",
        ]:
            value = getattr(payload, field)
            if value is not None:
                setattr(variant, field, value)

        if payload.weight is not None and payload.metal_weight_grams is None:
            variant.metal_weight_grams = payload.weight
        if payload.metal_weight_grams is not None and payload.weight is None:
            variant.weight = payload.metal_weight_grams

        # H-10: metal_id given -> validate + let it win, overwriting the
        # legacy ids from the Metal row (they may already be set above to the
        # same values; this is what keeps them consistent when metal_id is
        # the only metal field in the request). Otherwise, if this request's
        # own legacy ids form a full triad, resolve metal_id from it -- same
        # combination-or-null rule as create_variant. A request that touches
        # neither leaves metal_id untouched.
        if payload.metal_id is not None:
            metal = AdminManagementService._resolve_and_validate_metal_id(
                db, payload.metal_id, payload.base_metal_id, payload.metal_color_id, payload.metal_purity_id
            )
            variant.metal_id = metal.id
            variant.base_metal_id = metal.base_metal_id
            variant.metal_color_id = metal.metal_color_id
            variant.metal_purity_id = metal.metal_purity_id
        elif (
            payload.base_metal_id is not None
            or payload.metal_color_id is not None
            or payload.metal_purity_id is not None
        ):
            # Any legacy id changed -> re-resolve from the variant's resulting
            # triad, so metal_id never keeps pointing at the old combination.
            variant.metal_id = AdminManagementService._resolve_metal_id_from_legacy(
                db, variant.base_metal_id, variant.metal_color_id, variant.metal_purity_id
            )

        try:
            db.commit()
            db.refresh(variant)
            return variant
        except IntegrityError as exc:
            db.rollback()
            raise HTTPException(
                status_code=422, detail=AdminManagementService._variant_integrity_error_detail(exc)
            )
        except Exception:
            db.rollback()
            raise

    @staticmethod
    def restock_variant(db: Session, store_id: UUID, variant_id: UUID, quantity: int) -> ProductVariant:
        if quantity <= 0:
            raise HTTPException(status_code=422, detail="Restock quantity must be positive")
        if physical_unit_service.is_tracked(db, variant_id):
            raise HTTPException(status_code=409, detail="This item is tracked piece by piece: add the new pieces instead of a count")
        variant = AdminManagementRepository.increment_variant_stock(
            db, variant_id=variant_id, store_id=store_id, quantity=quantity
        )
        if not variant:
            raise HTTPException(status_code=404, detail="Variant not found")
        db.commit()
        db.refresh(variant)
        return variant

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
                # H-10: row total, used by pricing_service._stone_cost.
                "cost": item.cost,
                # H-05: certification fields folded back from the admin-backend
                # B-02 local patch -- StoneAssignmentItem carries them now.
                "cut": item.cut,
                "clarity": item.clarity,
                "color": item.color,
                "origin": item.origin,
                "certificate_number": item.certificate_number,
                "certification_agency": item.certification_agency,
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
