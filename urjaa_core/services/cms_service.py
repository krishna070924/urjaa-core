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
from sqlalchemy import func
from sqlalchemy.orm import Session

from urjaa_core.models.category import Category
from urjaa_core.models.collection import Collection
from urjaa_core.models.product import Product
from urjaa_core.models.stone import Stone
from urjaa_core.models.subcategory import Subcategory
from urjaa_core.models.tag import Tag
from urjaa_core.models.website_config import WebsiteConfig
from urjaa_core.repositories.product_repository import ProductRepository
from urjaa_core.schemas.cms_content import HERO_PAGES, POLICY_KEYS, FaqContent, HomePageContent, OurStoryContent, PoliciesContent
from urjaa_core.schemas.product import ProductResponse
from urjaa_core.services.pricing_service import PricingService
from urjaa_core.utils.currency import format_price_or_request


MAX_VERSIONS = 5
MAX_BEST_SELLERS = 8
BESTSELLER_TAG_NAME = "Bestseller"

PAGE_MODELS: dict[str, type[BaseModel]] = {
    "home": HomePageContent,
    "our-story": OurStoryContent,
    "policies": PoliciesContent,
    "faq": FaqContent,
}

PAGE_STORAGE_KEYS: dict[str, str] = {
    "home": "cms.home",
    "our-story": "cms.our_story",
    "policies": "cms.policies",
    "faq": "cms.faq",
}

_EMPTY_HOME_RESOLVED: dict[str, Any] = {
    "hero_slides": [],
    "shop_by_category": [],
    "deck": {"products": []},
    "exclusive_offers": {"slots": [{"image_url": None, "link": None}] * 3},
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


def _normalize_home_raw(raw: dict[str, Any]) -> dict[str, Any]:
    """O-02 backward compat for Home content saved before this change:
    - old single `hero` object -> one-slide `hero_slides` list (no link).
    - old `best_sellers.product_ids` (manual picks, replaced by the
      Bestseller tag, D42) is dropped rather than rejected.
    Applied on every read path (get_page, restore, storefront resolve) so
    pre-existing rows keep working with no DB migration.
    """
    if not isinstance(raw, dict):
        return raw
    raw = dict(raw)

    old_hero = raw.pop("hero", "absent")
    if "hero_slides" not in raw and old_hero != "absent":
        if isinstance(old_hero, dict) and old_hero.get("media_url"):
            raw["hero_slides"] = [
                {
                    "media_type": old_hero.get("media_type", "image"),
                    "media_url": old_hero["media_url"],
                    "poster_url": old_hero.get("poster_url"),
                    "link": None,
                }
            ]
        else:
            raw["hero_slides"] = []

    best_sellers = raw.get("best_sellers")
    if isinstance(best_sellers, dict) and "product_ids" in best_sellers:
        raw["best_sellers"] = {k: v for k, v in best_sellers.items() if k != "product_ids"}

    return raw


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
    category_ids |= {
        link.id for slide in content.hero_slides for link in slide.links() if link.kind == "category"
    }
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
    collection_ids |= {
        link.id for slide in content.hero_slides for link in slide.links() if link.kind == "collection"
    }
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

    product_ids = set(content.deck.product_ids) | set(content.curated_by_urjaa.product_ids)
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
    current = current if isinstance(current, dict) else None
    if current is not None and page == "home":
        current = _normalize_home_raw(current)
    return current, versions


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


def _stamp_policy_dates(content: dict[str, Any], previous: dict[str, Any] | None) -> None:
    """'Last updated' per policy page = when its content last changed."""
    previous = previous or {}
    today = datetime.now(timezone.utc).date().isoformat()
    for key in POLICY_KEYS:
        page = content.get(key)
        if not isinstance(page, dict):
            continue
        before = previous.get(key) if isinstance(previous.get(key), dict) else None
        strip = lambda d: {k: v for k, v in d.items() if k != "updated_at"}  # noqa: E731
        if before is not None and strip(before) == strip(page):
            page["updated_at"] = before.get("updated_at") or today
        else:
            page["updated_at"] = today


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
    if page == "policies":
        _stamp_policy_dates(content_dict, value.get("current"))
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
    target_content = target["content"]
    if page == "home":
        target_content = _normalize_home_raw(target_content)
    try:
        # Re-validate: the schema may have evolved since this version was saved.
        content_model = model_cls.model_validate(target_content)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors())
    warnings = _validate_references(db, page, content_model)

    remaining = versions[:index] + versions[index + 1 :]
    remaining = _push_current_into_versions(row.value, remaining)

    content_dict = content_model.model_dump(mode="json")
    if page == "policies":
        _stamp_policy_dates(content_dict, row.value.get("current"))
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

def _price_products(db: Session, products: list[Product]) -> list[dict[str, Any]]:
    """Shared no-N+1 pricing pass: one discount map, one rate cache, for
    however many products were already fetched — same pattern as
    ProductService.get_products."""
    if not products:
        return []
    rate_cache: dict = {}
    discount_map = PricingService.resolve_best_discounts(
        db,
        store_ids={product.store_id for product in products},
        product_ids={product.id for product in products},
    )
    cards = []
    for product in products:
        priced = PricingService.price_product_starting(product, db, rate_cache=rate_cache, discount_map=discount_map)
        product.starting_price = priced.price
        product.formatted_price = format_price_or_request(product.starting_price)
        product.original_price = priced.original_price
        product.discount_percent = priced.discount_percent
        product.discount_ends_at = priced.discount_ends_at
        cards.append(ProductResponse.model_validate(product, from_attributes=True).model_dump(mode="json"))
    return cards


def _resolve_products(db: Session, product_ids: list[UUID]) -> dict[UUID, dict[str, Any]]:
    if not product_ids:
        return {}
    products = ProductRepository.get_products_by_ids(db, store_id=None, product_ids=product_ids)
    return {UUID(card["id"]): card for card in _price_products(db, products)}


def _resolve_best_sellers(db: Session) -> list[dict[str, Any]]:
    """D42: Best Sellers is automatic — up to 8 active products tagged
    "Bestseller", best-selling first (same sort as the catalog's
    best_selling query)."""
    tag = db.query(Tag).filter(func.lower(Tag.name) == BESTSELLER_TAG_NAME.lower()).first()
    if tag is None:
        return []
    products, _total = ProductRepository.get_products(
        db, store_id=None, tag_slug=tag.slug, sort="best_selling", limit=MAX_BEST_SELLERS
    )
    return _price_products(db, products)


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


def _hero_link_href(kind: str, slug: str) -> str:
    return f"/collections?category={slug}" if kind == "category" else f"/collections?collection={slug}"


def _resolve_hero_link(link, categories_by_id, collections_by_id) -> dict[str, Any] | None:
    """Link -> {kind, name, href}; None when its target no longer exists."""
    if link is None:
        return None
    if link.kind == "page":
        return {"kind": "page", "name": None, "href": HERO_PAGES[link.page]}
    entity = (categories_by_id if link.kind == "category" else collections_by_id).get(link.id)
    if not entity:
        return None
    return {"kind": link.kind, "name": entity["name"], "href": _hero_link_href(link.kind, entity["slug"])}


def _resolve_offer_slots(db: Session, slots: list, categories_by_id, collections_by_id) -> list[dict[str, Any]]:
    """P-04: each offer banner -> {image_url, link: {kind, name, href} | None}.
    A link whose target was deleted/deactivated resolves to None (banner
    still shows, just isn't clickable)."""
    links = [slot.link for slot in slots if slot.link]
    product_ids = [l.product_id for l in links if l.kind == "product"]
    sub_ids = [l.id for l in links if l.kind == "subcategory"]
    products = (
        {
            row.id: (row.name, f"/product/{row.slug}")
            for row in db.query(Product.id, Product.name, Product.slug).filter(
                Product.id.in_(product_ids), Product.status == "active", Product.deleted_at.is_(None)
            )
        }
        if product_ids
        else {}
    )
    subs = (
        {
            row.id: (row.name, f"/collections?category={row.category_slug}&subcategory={row.slug}")
            for row in db.query(Subcategory.id, Subcategory.name, Subcategory.slug, Category.slug.label("category_slug"))
            .join(Category, Category.id == Subcategory.category_id)
            .filter(Subcategory.id.in_(sub_ids), Category.is_deleted.is_(False))
        }
        if sub_ids
        else {}
    )

    def resolve(link):
        if link is None:
            return None
        if link.kind == "product":
            hit = products.get(link.product_id)
        elif link.kind == "subcategory":
            hit = subs.get(link.id)
        else:
            entity = (categories_by_id if link.kind == "category" else collections_by_id).get(link.id)
            hit = (entity["name"], _hero_link_href(link.kind, entity["slug"])) if entity else None
        return {"kind": link.kind, "name": hit[0], "href": hit[1]} if hit else None

    return [{"image_url": slot.image_url, "link": resolve(slot.link)} for slot in slots]


def _resolve_hero_slides(
    db: Session,
    slides: list,
    categories_by_id: dict[int, dict[str, Any]],
    collections_by_id: dict[int, dict[str, Any]],
) -> list[dict[str, Any]]:
    def button(b):
        if b is None:
            return None
        return {"label": b.label, "link": _resolve_hero_link(b.link, categories_by_id, collections_by_id)}

    resolved = []
    for slide in slides:
        resolved.append(
            {
                "media_type": slide.media_type,
                "media_url": slide.media_url,
                "poster_url": slide.poster_url,
                "link": _resolve_hero_link(slide.link, categories_by_id, collections_by_id),
                "show_text": slide.show_text,
                "eyebrow": slide.eyebrow,
                "location_line": slide.location_line,
                "headline": slide.headline,
                "headline_accent": slide.headline_accent,
                "body": slide.body,
                "primary_button": button(slide.primary_button),
                "secondary_button": button(slide.secondary_button),
                "spotlight": slide.spotlight.model_dump() if slide.spotlight else None,
            }
        )
    return resolved


def resolve_home_for_storefront(db: Session) -> dict[str, Any]:
    current, _ = get_page(db, "home")
    if current is None:
        return dict(_EMPTY_HOME_RESOLVED)

    content = HomePageContent.model_validate(current)

    product_ids = list(
        dict.fromkeys([*content.deck.product_ids, *content.curated_by_urjaa.product_ids])
    )
    category_ids = [tile.category_id for tile in content.shop_by_category]
    category_ids += [link.id for slide in content.hero_slides for link in slide.links() if link.kind == "category"]
    offer_links = [slot.link for slot in content.exclusive_offers.slots if slot.link]
    category_ids += [link.id for link in offer_links if link.kind == "category"]
    collection_ids = [tile.collection_id for tile in content.curated_collections.tiles]
    collection_ids += [
        link.id for slide in content.hero_slides for link in slide.links() if link.kind == "collection"
    ]
    collection_ids += [link.id for link in offer_links if link.kind == "collection"]

    products_by_id = _resolve_products(db, product_ids)
    categories_by_id = _resolve_categories(db, category_ids)
    collections_by_id = _resolve_collections(db, collection_ids)
    best_sellers = _resolve_best_sellers(db)
    stone_ids = [tile.stone_id for tile in content.stone_stories.tiles]
    stone_names = (
        {row.id: row.name for row in db.query(Stone.id, Stone.name).filter(Stone.id.in_(stone_ids))}
        if stone_ids
        else {}
    )

    return {
        "hero_slides": _resolve_hero_slides(db, content.hero_slides, categories_by_id, collections_by_id),
        "shop_by_category": [
            {**categories_by_id[tile.category_id], "image": tile.image_url}
            for tile in content.shop_by_category
            if tile.category_id in categories_by_id
        ],
        "deck": {
            "products": [products_by_id[pid] for pid in content.deck.product_ids if pid in products_by_id]
        },
        "exclusive_offers": {
            "slots": _resolve_offer_slots(db, content.exclusive_offers.slots, categories_by_id, collections_by_id)
        },
        "best_sellers": {"products": best_sellers},
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


def resolve_plain_page_for_storefront(db: Session, page: str) -> dict[str, Any]:
    """Policies / FAQ: stored content as-is; {} when nothing saved (the
    storefront then shows its designed copy)."""
    current, _ = get_page(db, page)
    return current if isinstance(current, dict) else {}
