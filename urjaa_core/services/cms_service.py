"""N-03: CMS storage + resolution for the Home and Our Story pages.

Storage shape (one `website_configs` row per page, no migration needed —
the table already exists and both app DB roles already have full DML on it):

    {
      "current": {...page content, already schema-validated...},
      "current_saved_at": "<iso8601>",
      "current_saved_by": "<admin email>",
      "versions": [
        {"saved_at": "...", "saved_by": "...", "content": {...}},
        ...  # newest first, capped at MAX_VERSIONS
      ]
    }
"""
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from urjaa_core.models.category import Category
from urjaa_core.models.collection import Collection
from urjaa_core.models.product import Product
from urjaa_core.models.stone import Stone
from urjaa_core.models.website_config import WebsiteConfig
from urjaa_core.repositories.product_repository import ProductRepository
from urjaa_core.schemas.cms_content import HomePageContent, OurStoryContent
from urjaa_core.schemas.product import ProductResponse
from urjaa_core.services.pricing_service import PricingService
from urjaa_core.utils.currency import format_price_or_request


MAX_VERSIONS = 5

PAGE_MODELS: dict[str, type[BaseModel]] = {
    "home": HomePageContent,
    "our-story": OurStoryContent,
}

PAGE_STORAGE_KEYS: dict[str, str] = {
    "home": "cms.home",
    "our-story": "cms.our_story",
}

_EMPTY_HOME_RESOLVED: dict[str, Any] = {
    "hero": None,
    "shop_by_category": [],
    "deck": {"products": []},
    "exclusive_offers": {"slots": [{"image_url": None}, {"image_url": None}, {"image_url": None}]},
    "best_sellers": {"products": []},
    "curated_collections": {"tiles": []},
    "for_her_him": {"her_image_url": None, "him_image_url": None},
    "shop_by_occasion": {"bridal": None, "festive": None, "gifting": None, "everyday": None},
    "stone_stories": {"tiles": []},
    "curated_by_urjaa": {"products": []},
    "craftsmanship": {"slots": [{"image_url": None}, {"image_url": None}]},
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _require_page(page: str) -> None:
    if page not in PAGE_MODELS:
        raise HTTPException(status_code=404, detail=f"Unknown CMS page: {page}")


def _get_row(db: Session, page: str) -> WebsiteConfig | None:
    return db.query(WebsiteConfig).filter(WebsiteConfig.key == PAGE_STORAGE_KEYS[page]).first()


def _validate_products(db: Session, product_ids: set[UUID]) -> list[str]:
    if not product_ids:
        return []
    rows = (
        db.query(Product.id, Product.status, Product.deleted_at)
        .filter(Product.id.in_(product_ids))
        .all()
    )
    found = {row[0] for row in rows}
    missing = product_ids - found
    if missing:
        raise HTTPException(status_code=400, detail=f"Unknown product id(s): {sorted(str(m) for m in missing)}")

    warnings: list[str] = []
    for product_id, status, deleted_at in rows:
        if deleted_at is not None:
            raise HTTPException(status_code=400, detail=f"Product {product_id} has been deleted")
        if status != "active":
            warnings.append(f"Product {product_id} is not active (status={status})")
    return warnings


def _validate_references(db: Session, page: str, content: BaseModel) -> list[str]:
    if page != "home":
        return []

    content: HomePageContent  # type: ignore[assignment]
    warnings: list[str] = []

    category_ids = {tile.category_id for tile in content.shop_by_category}
    if category_ids:
        found = {
            row.id
            for row in db.query(Category.id).filter(
                Category.id.in_(category_ids), Category.is_deleted.is_(False)
            )
        }
        missing = category_ids - found
        if missing:
            raise HTTPException(status_code=400, detail=f"Unknown category id(s): {sorted(missing)}")

    collection_ids = {tile.collection_id for tile in content.curated_collections.tiles}
    if collection_ids:
        found = {row.id for row in db.query(Collection.id).filter(Collection.id.in_(collection_ids))}
        missing = collection_ids - found
        if missing:
            raise HTTPException(status_code=400, detail=f"Unknown collection id(s): {sorted(missing)}")

    stone_ids = {tile.stone_id for tile in content.stone_stories.tiles}
    if stone_ids:
        found = {row.id for row in db.query(Stone.id).filter(Stone.id.in_(stone_ids))}
        missing = stone_ids - found
        if missing:
            raise HTTPException(status_code=400, detail=f"Unknown stone id(s): {sorted(missing)}")

    product_ids = (
        set(content.deck.product_ids)
        | set(content.best_sellers.product_ids)
        | set(content.curated_by_urjaa.product_ids)
    )
    warnings.extend(_validate_products(db, product_ids))
    return warnings


def get_page(db: Session, page: str) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """Current content (full) + version history (metadata only, no content)."""
    _require_page(page)
    row = _get_row(db, page)
    if row is None or not isinstance(row.value, dict):
        return None, []

    current = row.value.get("current")
    versions_raw = row.value.get("versions") or []
    versions = [
        {"index": i, "saved_at": v.get("saved_at"), "saved_by": v.get("saved_by")}
        for i, v in enumerate(versions_raw)
        if isinstance(v, dict)
    ]
    return (current if isinstance(current, dict) else None), versions


def _push_current_into_versions(value: dict[str, Any], versions: list) -> list:
    previous_current = value.get("current")
    if isinstance(previous_current, dict):
        versions.insert(
            0,
            {
                "saved_at": value.get("current_saved_at") or _now_iso(),
                "saved_by": value.get("current_saved_by") or "unknown",
                "content": previous_current,
            },
        )
    return versions[:MAX_VERSIONS]


def save_page(db: Session, page: str, raw_content: dict[str, Any], saved_by: str) -> tuple[dict[str, Any], list[str]]:
    _require_page(page)
    model_cls = PAGE_MODELS[page]
    try:
        content_model = model_cls.model_validate(raw_content)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors())

    warnings = _validate_references(db, page, content_model)

    row = _get_row(db, page)
    if row is None:
        row = WebsiteConfig(key=PAGE_STORAGE_KEYS[page], value={})
        db.add(row)
        db.flush()

    value = row.value if isinstance(row.value, dict) else {}
    versions = _push_current_into_versions(value, list(value.get("versions") or []))

    content_dict = content_model.model_dump(mode="json")
    row.value = {
        "current": content_dict,
        "current_saved_at": _now_iso(),
        "current_saved_by": saved_by,
        "versions": versions,
    }
    db.add(row)
    db.commit()
    db.refresh(row)
    return content_dict, warnings


def restore_version(db: Session, page: str, index: int, saved_by: str) -> tuple[dict[str, Any], list[str]]:
    _require_page(page)
    row = _get_row(db, page)
    if row is None or not isinstance(row.value, dict):
        raise HTTPException(status_code=404, detail="No saved content for this page")

    versions = list(row.value.get("versions") or [])
    if index < 0 or index >= len(versions):
        raise HTTPException(status_code=404, detail="Version not found")

    target = versions[index]
    if not isinstance(target, dict) or not isinstance(target.get("content"), dict):
        raise HTTPException(status_code=404, detail="Version not found")

    model_cls = PAGE_MODELS[page]
    try:
        # Re-validate: the schema may have evolved since this version was saved.
        content_model = model_cls.model_validate(target["content"])
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors())
    warnings = _validate_references(db, page, content_model)

    remaining = versions[:index] + versions[index + 1 :]
    remaining = _push_current_into_versions(row.value, remaining)

    content_dict = content_model.model_dump(mode="json")
    row.value = {
        "current": content_dict,
        "current_saved_at": _now_iso(),
        "current_saved_by": saved_by,
        "versions": remaining,
    }
    db.add(row)
    db.commit()
    db.refresh(row)
    return content_dict, warnings


# =============================================================================
# Storefront resolution (public, read-only)
# =============================================================================

def _resolve_products(db: Session, product_ids: list[UUID]) -> dict[UUID, dict[str, Any]]:
    if not product_ids:
        return {}
    products = ProductRepository.get_products_by_ids(db, store_id=None, product_ids=product_ids)
    if not products:
        return {}

    # Same no-N+1 pattern as ProductService.get_products: one discount map,
    # one rate cache, shared across every product being priced.
    rate_cache: dict = {}
    discount_map = PricingService.resolve_best_discounts(
        db,
        store_ids={product.store_id for product in products},
        product_ids={product.id for product in products},
    )

    resolved: dict[UUID, dict[str, Any]] = {}
    for product in products:
        priced = PricingService.price_product_starting(product, db, rate_cache=rate_cache, discount_map=discount_map)
        product.starting_price = priced.price
        product.formatted_price = format_price_or_request(product.starting_price)
        product.original_price = priced.original_price
        product.discount_percent = priced.discount_percent
        product.discount_ends_at = priced.discount_ends_at
        resolved[product.id] = ProductResponse.model_validate(product, from_attributes=True).model_dump(mode="json")
    return resolved


def _resolve_categories(db: Session, category_ids: list[int]) -> dict[int, dict[str, Any]]:
    if not category_ids:
        return {}
    rows = db.query(Category).filter(Category.id.in_(category_ids), Category.is_deleted.is_(False)).all()
    return {row.id: {"id": row.id, "name": row.name, "slug": row.slug} for row in rows}


def _resolve_collections(db: Session, collection_ids: list[int]) -> dict[int, dict[str, Any]]:
    if not collection_ids:
        return {}
    rows = db.query(Collection).filter(Collection.id.in_(collection_ids)).all()
    return {row.id: {"id": row.id, "name": row.name, "slug": row.slug} for row in rows}


def resolve_home_for_storefront(db: Session) -> dict[str, Any]:
    current, _ = get_page(db, "home")
    if current is None:
        return dict(_EMPTY_HOME_RESOLVED)

    content = HomePageContent.model_validate(current)

    product_ids = list(
        dict.fromkeys(
            [*content.deck.product_ids, *content.best_sellers.product_ids, *content.curated_by_urjaa.product_ids]
        )
    )
    category_ids = [tile.category_id for tile in content.shop_by_category]
    collection_ids = [tile.collection_id for tile in content.curated_collections.tiles]

    products_by_id = _resolve_products(db, product_ids)
    categories_by_id = _resolve_categories(db, category_ids)
    collections_by_id = _resolve_collections(db, collection_ids)
    stone_ids = [tile.stone_id for tile in content.stone_stories.tiles]
    stone_names = (
        {row.id: row.name for row in db.query(Stone.id, Stone.name).filter(Stone.id.in_(stone_ids))}
        if stone_ids
        else {}
    )

    return {
        "hero": content.hero.model_dump(mode="json") if content.hero else None,
        "shop_by_category": [
            {**categories_by_id[tile.category_id], "image": tile.image_url}
            for tile in content.shop_by_category
            if tile.category_id in categories_by_id
        ],
        "deck": {
            "products": [products_by_id[pid] for pid in content.deck.product_ids if pid in products_by_id]
        },
        "exclusive_offers": {
            "slots": [slot.model_dump(mode="json") for slot in content.exclusive_offers.slots]
        },
        "best_sellers": {
            "products": [products_by_id[pid] for pid in content.best_sellers.product_ids if pid in products_by_id]
        },
        "curated_collections": {
            "tiles": [
                {**collections_by_id[tile.collection_id], "image": tile.image_url}
                for tile in content.curated_collections.tiles
                if tile.collection_id in collections_by_id
            ]
        },
        "for_her_him": content.for_her_him.model_dump(mode="json"),
        "shop_by_occasion": content.shop_by_occasion.model_dump(mode="json"),
        # Name included so the storefront links by name, never by a db id.
        "stone_stories": {
            "tiles": [
                {**tile.model_dump(mode="json"), "name": stone_names.get(tile.stone_id)}
                for tile in content.stone_stories.tiles
            ]
        },
        "curated_by_urjaa": {
            "products": [
                products_by_id[pid] for pid in content.curated_by_urjaa.product_ids if pid in products_by_id
            ]
        },
        "craftsmanship": {
            "slots": [slot.model_dump(mode="json") for slot in content.craftsmanship.slots]
        },
    }


def resolve_our_story_for_storefront(db: Session) -> dict[str, Any]:
    current, _ = get_page(db, "our-story")
    return current if isinstance(current, dict) else {}
