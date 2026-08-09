from copy import deepcopy
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from urjaa_core.models.category import Category
from urjaa_core.models.collection import Collection
from urjaa_core.repositories.admin.website_cms_repository import WebsiteCMSRepository


DEFAULT_HERO_ATELIER_DESCRIPTION = (
    "Each composition is crafted to hold detail, balance weight, "
    "and preserve brilliance through years of celebration."
)

DEFAULT_HERO_ATELIER_ROWS: list[dict[str, Any]] = [
    {
        "label": "Craft Window",
        "value": "2-4 Weeks",
        "highlight": False,
    },
    {
        "label": "Purity Promise",
        "value": "BIS Hallmarked",
        "highlight": True,
    },
    {
        "label": "Styling Support",
        "value": "Virtual Consult",
        "highlight": False,
    },
]

ALLOWED_HERO_ATELIER_DISPLAY_TYPES = {"info", "rates", "trust"}

DEFAULT_HERO_TAGS: list[dict[str, Any]] = [
    {
        "text": "Handcrafted Legacy",
        "link": "",
        "style": "default",
    },
    {
        "text": "Certified Stones",
        "link": "",
        "style": "highlight",
    },
    {
        "text": "Bespoke Finishing",
        "link": "",
        "style": "default",
    },
]

ALLOWED_HERO_TAG_STYLES = {"default", "highlight"}
MAX_HERO_TAGS = 5
MAX_TRUST_BAR_ITEMS = 4


DEFAULT_HOMEPAGE_CONFIG: dict[str, Any] = {
    "header": {
        "announcement_text": "",
        "enabled": True,
    },
    "hero": {
        "enabled": True,
        "title": "",
        "subtitle": "",
        "cta_text": "",
        "cta_link": "/products",
        "cta": {
            "text": "",
            "link": "/products",
        },
        "images": [],
        "items": [],
        "atelier_note": {
            "enableAtelierNote": True,
            "title": "Atelier Note",
            "description": DEFAULT_HERO_ATELIER_DESCRIPTION,
            "display_type": "info",
            "rows": deepcopy(DEFAULT_HERO_ATELIER_ROWS),
            "icon": None,
        },
        "hero_tags": {
            "enableTags": True,
            "tags": deepcopy(DEFAULT_HERO_TAGS),
        },
    },
    "trust_bar": {
        "enabled": True,
        "items": [],
    },
    "categories": {
        "enabled": True,
        "title": "",
        "subtitle": "",
        "items": [],
    },
    "categories_grid": [],
    "occasions": {
        "enabled": True,
        "items": [],
    },
    "price_buckets": {
        "enabled": True,
        "title": "",
        "items": [],
    },
    "collections": {
        "enabled": True,
        "title": "",
        "subtitle": "",
        "items": [],
    },
    "bestsellers": {
        "enabled": True,
        "items": [],
    },
    "bestsellers_enabled": True,
    "brand_story": {
        "enabled": True,
        "title": "",
        "description": "",
        "image": {
            "url": "",
            "alt": "",
        },
    },
    "cta_section": {
        "text": "",
        "link": "/products",
    },
    "sections": [],
    "schema_version": "2.0.0",
}


class WebsiteCMSService:
    HOMEPAGE_KEY = "homepage"

    @staticmethod
    def _normalize_hero(payload: dict[str, Any]) -> dict[str, Any]:
        raw_hero = payload.get("hero")
        hero_data = raw_hero if isinstance(raw_hero, dict) else {}

        enabled = hero_data.get("enabled") if isinstance(hero_data.get("enabled"), bool) else True
        title = hero_data.get("title") if isinstance(hero_data.get("title"), str) else ""
        subtitle = hero_data.get("subtitle") if isinstance(hero_data.get("subtitle"), str) else ""

        raw_cta = hero_data.get("cta")
        cta_object = raw_cta if isinstance(raw_cta, dict) else {}
        cta_text = hero_data.get("cta_text") if isinstance(hero_data.get("cta_text"), str) else ""
        cta_link = hero_data.get("cta_link") if isinstance(hero_data.get("cta_link"), str) else ""
        normalized_primary_cta = {
            "label": cta_text or (cta_object.get("text") if isinstance(cta_object.get("text"), str) else ""),
            "href": cta_link or (cta_object.get("link") if isinstance(cta_object.get("link"), str) else "/products"),
        }

        raw_atelier_note = hero_data.get("atelier_note")
        if not isinstance(raw_atelier_note, dict):
            raw_atelier_note = hero_data.get("atelierNote")
        atelier_note_data = raw_atelier_note if isinstance(raw_atelier_note, dict) else {}

        raw_enable_atelier = atelier_note_data.get("enableAtelierNote")
        if isinstance(raw_enable_atelier, bool):
            enable_atelier_note = raw_enable_atelier
        else:
            raw_atelier_enabled = atelier_note_data.get("enabled")
            enable_atelier_note = raw_atelier_enabled if isinstance(raw_atelier_enabled, bool) else True

        raw_atelier_title = atelier_note_data.get("title")
        atelier_title = raw_atelier_title if isinstance(raw_atelier_title, str) and raw_atelier_title.strip() else "Atelier Note"

        raw_atelier_description = atelier_note_data.get("description")
        atelier_description = (
            raw_atelier_description
            if isinstance(raw_atelier_description, str) and raw_atelier_description.strip()
            else DEFAULT_HERO_ATELIER_DESCRIPTION
        )

        raw_display_type = atelier_note_data.get("display_type")
        if not isinstance(raw_display_type, str):
            raw_display_type = atelier_note_data.get("displayType")
        display_type_candidate = raw_display_type.strip().lower() if isinstance(raw_display_type, str) else "info"
        display_type = display_type_candidate if display_type_candidate in ALLOWED_HERO_ATELIER_DISPLAY_TYPES else "info"

        raw_rows = atelier_note_data.get("rows")
        normalized_rows: list[dict[str, Any]] = []
        if isinstance(raw_rows, list):
            for row in raw_rows:
                if not isinstance(row, dict):
                    continue

                raw_label = row.get("label")
                label = raw_label if isinstance(raw_label, str) else ""

                raw_value = row.get("value")
                value = raw_value if isinstance(raw_value, str) else ""

                raw_highlight = row.get("highlight")
                highlight = raw_highlight if isinstance(raw_highlight, bool) else False

                if not label.strip() and not value.strip():
                    continue

                normalized_rows.append(
                    {
                        "label": label,
                        "value": value,
                        "highlight": highlight,
                    }
                )

        if not normalized_rows:
            normalized_rows = deepcopy(DEFAULT_HERO_ATELIER_ROWS)

        raw_icon = atelier_note_data.get("icon")
        icon = raw_icon.strip() if isinstance(raw_icon, str) and raw_icon.strip() else None

        raw_hero_tags = hero_data.get("hero_tags")
        if not isinstance(raw_hero_tags, dict):
            raw_hero_tags = hero_data.get("heroTags")
        if not isinstance(raw_hero_tags, dict) and (
            "enableTags" in hero_data or "tags" in hero_data
        ):
            raw_hero_tags = hero_data
        hero_tags_data = raw_hero_tags if isinstance(raw_hero_tags, dict) else {}

        raw_enable_tags = hero_tags_data.get("enableTags")
        if isinstance(raw_enable_tags, bool):
            enable_tags = raw_enable_tags
        else:
            raw_tags_enabled = hero_tags_data.get("enabled")
            enable_tags = raw_tags_enabled if isinstance(raw_tags_enabled, bool) else True

        raw_tags = hero_tags_data.get("tags")
        normalized_tags: list[dict[str, str]] = []
        if isinstance(raw_tags, list):
            for tag in raw_tags:
                if not isinstance(tag, dict):
                    continue

                raw_text = tag.get("text")
                text = raw_text.strip() if isinstance(raw_text, str) else ""
                if not text:
                    continue

                raw_link = tag.get("link")
                link = raw_link.strip() if isinstance(raw_link, str) else ""

                raw_style = tag.get("style")
                style_candidate = raw_style.strip().lower() if isinstance(raw_style, str) else "default"
                style = style_candidate if style_candidate in ALLOWED_HERO_TAG_STYLES else "default"

                normalized_tags.append(
                    {
                        "text": text,
                        "link": link,
                        "style": style,
                    }
                )

        if not normalized_tags:
            normalized_tags = deepcopy(DEFAULT_HERO_TAGS)

        normalized_tags = normalized_tags[:MAX_HERO_TAGS]

        raw_items = hero_data.get("items")
        normalized_items: list[dict[str, Any]] = []

        if isinstance(raw_items, list):
            for item in raw_items:
                if not isinstance(item, dict):
                    continue

                image = WebsiteCMSService._normalize_image(item.get("image"))
                if not image["url"]:
                    continue

                raw_headline = item.get("headline")
                headline = raw_headline if isinstance(raw_headline, str) else title

                raw_description = item.get("description")
                description = raw_description if isinstance(raw_description, str) else subtitle

                raw_item_cta = item.get("cta")
                item_cta = raw_item_cta if isinstance(raw_item_cta, dict) else {}
                if not item_cta:
                    raw_primary_cta = item.get("primaryCta")
                    item_cta = raw_primary_cta if isinstance(raw_primary_cta, dict) else {}

                cta_label = item_cta.get("label") if isinstance(item_cta.get("label"), str) else normalized_primary_cta["label"]
                cta_href = item_cta.get("href") if isinstance(item_cta.get("href"), str) else normalized_primary_cta["href"]

                normalized_cta = {
                    "label": cta_label,
                    "href": cta_href,
                }

                normalized_items.append(
                    {
                        "image": image,
                        "headline": headline,
                        "description": description,
                        "cta": normalized_cta,
                        # Backward-compatible alias for existing clients.
                        "primaryCta": normalized_cta,
                    }
                )

        if not normalized_items:
            raw_images = hero_data.get("images")
            if isinstance(raw_images, list):
                for image_value in raw_images:
                    image = WebsiteCMSService._normalize_image(image_value)
                    if not image["url"]:
                        continue

                    normalized_items.append(
                        {
                            "image": image,
                            "headline": title,
                            "description": subtitle,
                            "cta": {
                                "label": normalized_primary_cta["label"],
                                "href": normalized_primary_cta["href"],
                            },
                            "primaryCta": {
                                "label": normalized_primary_cta["label"],
                                "href": normalized_primary_cta["href"],
                            },
                        }
                    )

        normalized_images = [item["image"].get("url", "") for item in normalized_items if isinstance(item.get("image"), dict)]

        return {
            "enabled": enabled,
            "title": title,
            "subtitle": subtitle,
            "cta_text": normalized_primary_cta["label"],
            "cta_link": normalized_primary_cta["href"],
            "cta": {
                "text": normalized_primary_cta["label"],
                "link": normalized_primary_cta["href"],
            },
            "items": normalized_items,
            "images": normalized_images,
            "atelier_note": {
                "enableAtelierNote": enable_atelier_note,
                "title": atelier_title,
                "description": atelier_description,
                "display_type": display_type,
                "rows": normalized_rows,
                "icon": icon,
            },
            "hero_tags": {
                "enableTags": enable_tags,
                "tags": normalized_tags,
            },
        }

    @staticmethod
    def _normalize_header(payload: dict[str, Any]) -> dict[str, Any]:
        raw = payload.get("header")
        if not isinstance(raw, dict):
            raw = {}

        raw_text = raw.get("announcement_text")
        announcement_text = raw_text if isinstance(raw_text, str) else ""

        raw_enabled = raw.get("enabled")
        enabled = raw_enabled if isinstance(raw_enabled, bool) else True

        return {
            "announcement_text": announcement_text,
            "enabled": enabled,
        }

    @staticmethod
    def _normalize_image(value: Any, fallback_alt: str = "") -> dict[str, str]:
        if isinstance(value, str):
            return {
                "url": value,
                "alt": fallback_alt,
            }

        if isinstance(value, dict):
            raw_url = value.get("url")
            raw_alt = value.get("alt")
            return {
                "url": raw_url if isinstance(raw_url, str) else "",
                "alt": raw_alt if isinstance(raw_alt, str) else fallback_alt,
            }

        return {
            "url": "",
            "alt": fallback_alt,
        }

    @staticmethod
    def _normalize_list_section(value: Any, allow_string_items: bool = False) -> dict[str, Any]:
        enabled = True
        title = ""
        subtitle = ""
        items: list[Any] = []

        if isinstance(value, list):
            source_items = value
        elif isinstance(value, dict):
            raw_enabled = value.get("enabled")
            enabled = raw_enabled if isinstance(raw_enabled, bool) else True

            raw_title = value.get("title")
            title = raw_title if isinstance(raw_title, str) else ""

            raw_subtitle = value.get("subtitle")
            subtitle = raw_subtitle if isinstance(raw_subtitle, str) else ""

            source_items = value.get("items")
            source_items = source_items if isinstance(source_items, list) else []
        else:
            source_items = []

        for item in source_items:
            if allow_string_items and isinstance(item, str):
                items.append(item)
            elif isinstance(item, dict):
                items.append(item)

        return {
            "enabled": enabled,
            "title": title,
            "subtitle": subtitle,
            "items": items,
        }

    @staticmethod
    def _normalize_trust_bar(payload: dict[str, Any]) -> dict[str, Any]:
        raw_section = payload.get("trust_bar")
        if raw_section is None:
            raw_section = payload.get("trustBar")

        # Backward compatibility: older payloads may still send trust items under features.
        if raw_section is None:
            raw_section = payload.get("features")

        enabled = True
        title = ""
        subtitle = ""

        if isinstance(raw_section, list):
            source_items = raw_section
        elif isinstance(raw_section, dict):
            raw_enabled = raw_section.get("enabled")
            enabled = raw_enabled if isinstance(raw_enabled, bool) else True

            raw_title = raw_section.get("title")
            title = raw_title if isinstance(raw_title, str) else ""

            raw_subtitle = raw_section.get("subtitle")
            subtitle = raw_subtitle if isinstance(raw_subtitle, str) else ""

            section_items = raw_section.get("items")
            source_items = section_items if isinstance(section_items, list) else []
        else:
            source_items = []

        normalized_items: list[dict[str, str]] = []
        for item in source_items:
            if isinstance(item, str):
                text = item.strip()
                if not text:
                    continue
                normalized_items.append(
                    {
                        "icon": "shield",
                        "title": text,
                        "subtitle": "",
                    }
                )
                continue

            if not isinstance(item, dict):
                continue

            raw_icon = item.get("icon")
            icon = raw_icon.strip() if isinstance(raw_icon, str) and raw_icon.strip() else "shield"

            raw_title = item.get("title")
            if not isinstance(raw_title, str):
                raw_title = item.get("text")
            title_value = raw_title.strip() if isinstance(raw_title, str) else ""

            raw_subtitle = item.get("subtitle")
            if not isinstance(raw_subtitle, str):
                raw_subtitle = item.get("description")
            subtitle_value = raw_subtitle.strip() if isinstance(raw_subtitle, str) else ""

            if not title_value and subtitle_value:
                title_value = subtitle_value

            if not title_value:
                continue

            normalized_items.append(
                {
                    "icon": icon,
                    "title": title_value,
                    "subtitle": subtitle_value,
                }
            )

            if len(normalized_items) >= MAX_TRUST_BAR_ITEMS:
                break

        return {
            "enabled": enabled,
            "title": title,
            "subtitle": subtitle,
            "items": normalized_items,
        }

    @staticmethod
    def _normalize_categories_grid(db: Session, payload: dict[str, Any]) -> list[dict[str, Any]]:
        rows = payload.get("categories_grid")
        if not isinstance(rows, list):
            return []

        category_ids: set[int] = set()
        for row in rows:
            if not isinstance(row, dict):
                continue
            raw_category_id = row.get("category_id")
            if not isinstance(raw_category_id, int):
                raw_category_id = row.get("id")
            if isinstance(raw_category_id, int) and raw_category_id > 0:
                category_ids.add(raw_category_id)

        categories_by_id: dict[int, Category] = {}
        if category_ids:
            categories = (
                db.query(Category)
                .filter(
                    Category.id.in_(category_ids),
                    Category.is_active.is_(True),
                    Category.is_deleted.is_(False),
                )
                .all()
            )
            categories_by_id = {category.id: category for category in categories}

        normalized_rows: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue

            raw_category_id = row.get("category_id")
            if not isinstance(raw_category_id, int):
                raw_category_id = row.get("id")
            category_id = raw_category_id if isinstance(raw_category_id, int) else 0

            raw_caption = row.get("caption")
            if not isinstance(raw_caption, str):
                raw_caption = row.get("subtitle")
            caption = raw_caption if isinstance(raw_caption, str) else ""

            category = categories_by_id.get(category_id)
            # Only keep rows that resolve to an active category.
            if category_id <= 0 or category is None:
                continue

            raw_category_name = row.get("category_name")
            if not isinstance(raw_category_name, str):
                raw_category_name = row.get("name")
            category_name = raw_category_name if isinstance(raw_category_name, str) else category.name
            if not category_name.strip():
                category_name = category.name

            raw_category_slug = row.get("category_slug")
            if not isinstance(raw_category_slug, str):
                raw_category_slug = row.get("slug")
            category_slug = raw_category_slug if isinstance(raw_category_slug, str) else category.slug
            if not category_slug.strip():
                category_slug = category.slug

            image = WebsiteCMSService._normalize_image(row.get("image"), category_name)
            normalized_rows.append(
                {
                    "id": category_id,
                    "name": category_name,
                    "slug": category_slug,
                    "caption": caption,
                    "image": image,
                    # Backward-compatible aliases.
                    "category_id": category_id,
                    "category_name": category_name,
                    "category_slug": category_slug,
                    "subtitle": caption,
                }
            )

        return normalized_rows

    @staticmethod
    def _normalize_collections(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
        raw_section = payload.get("collections")

        enabled = True
        title = ""
        subtitle = ""
        raw_items: list[Any] = []

        if isinstance(raw_section, list):
            raw_items = raw_section
        elif isinstance(raw_section, dict):
            raw_enabled = raw_section.get("enabled")
            enabled = raw_enabled if isinstance(raw_enabled, bool) else True

            raw_title = raw_section.get("title")
            title = raw_title if isinstance(raw_title, str) else ""

            raw_subtitle = raw_section.get("subtitle")
            subtitle = raw_subtitle if isinstance(raw_subtitle, str) else ""

            section_items = raw_section.get("items")
            raw_items = section_items if isinstance(section_items, list) else []

        collection_ids: set[int] = set()
        collection_slugs: set[str] = set()

        def _extract_slug(item: dict[str, Any]) -> str:
            raw_slug = item.get("slug")
            if not isinstance(raw_slug, str):
                raw_slug = item.get("collection_slug")

            if isinstance(raw_slug, str) and raw_slug.strip():
                return raw_slug.strip()

            raw_href = item.get("href")
            if not isinstance(raw_href, str):
                raw_href = item.get("link")

            if not isinstance(raw_href, str) or not raw_href.strip():
                return ""

            href = raw_href.strip()

            if "collection=" in href:
                return href.split("collection=", 1)[1].split("&", 1)[0].strip()

            if href.startswith("/collections/"):
                return href.rsplit("/", 1)[-1].strip()

            return ""

        for item in raw_items:
            if not isinstance(item, dict):
                continue

            raw_collection_id = item.get("collection_id")
            if isinstance(raw_collection_id, int) and raw_collection_id > 0:
                collection_ids.add(raw_collection_id)
                continue

            raw_id = item.get("id")
            if isinstance(raw_id, int) and raw_id > 0:
                collection_ids.add(raw_id)

            extracted_slug = _extract_slug(item)
            if extracted_slug:
                collection_slugs.add(extracted_slug)

        collections_by_id: dict[int, Collection] = {}
        if collection_ids:
            collections = db.query(Collection).filter(Collection.id.in_(collection_ids)).all()
            collections_by_id = {collection.id: collection for collection in collections}

        collections_by_slug: dict[str, Collection] = {}
        if collection_slugs:
            collections = db.query(Collection).filter(Collection.slug.in_(collection_slugs)).all()
            collections_by_slug = {collection.slug: collection for collection in collections}

        normalized_items: list[dict[str, Any]] = []
        for item in raw_items:
            if not isinstance(item, dict):
                continue

            raw_collection_id = item.get("collection_id")
            collection_id = raw_collection_id if isinstance(raw_collection_id, int) else None
            if collection_id is None:
                raw_id = item.get("id")
                collection_id = raw_id if isinstance(raw_id, int) else None

            explicit_slug = _extract_slug(item)
            collection = collections_by_id.get(collection_id or 0)
            if collection is None and explicit_slug:
                collection = collections_by_slug.get(explicit_slug)

            raw_title = item.get("title")
            item_title = raw_title if isinstance(raw_title, str) else (collection.name if collection else "")

            if collection is None and item_title.strip():
                collection = (
                    db.query(Collection)
                    .filter(func.lower(Collection.name) == item_title.strip().lower())
                    .first()
                )

            resolved_collection_id = collection.id if collection is not None else (collection_id or 0)
            resolved_collection_slug = collection.slug if collection is not None else explicit_slug

            if resolved_collection_id <= 0 or not resolved_collection_slug:
                continue

            image = WebsiteCMSService._normalize_image(item.get("image"), item_title)
            if not image["url"] and collection and collection.banner_image:
                image["url"] = collection.banner_image

            href = f"/products?collection={resolved_collection_slug}" if resolved_collection_slug else "/products"

            normalized_items.append(
                {
                    "id": resolved_collection_id,
                    "slug": resolved_collection_slug,
                    "title": item_title,
                    "image": image,
                    "href": href,
                    # Backward-compatible aliases.
                    "collection_id": resolved_collection_id,
                    "collection_slug": resolved_collection_slug,
                }
            )

        return {
            "enabled": enabled,
            "title": title,
            "subtitle": subtitle,
            "items": normalized_items,
        }

    @staticmethod
    def _normalize_categories(
        db: Session,
        payload: dict[str, Any],
        normalized_grid_items: list[dict[str, Any]],
    ) -> dict[str, Any]:
        raw_categories = payload.get("categories")
        raw_grid = payload.get("categories_grid")
        raw_grid_meta = raw_grid if isinstance(raw_grid, dict) else {}

        enabled = True
        title = ""
        subtitle = ""
        raw_items: list[Any] = []

        if isinstance(raw_categories, list):
            raw_items = raw_categories
        elif isinstance(raw_categories, dict):
            raw_enabled = raw_categories.get("enabled")
            enabled = raw_enabled if isinstance(raw_enabled, bool) else True

            raw_title = raw_categories.get("title")
            if isinstance(raw_title, str):
                title = raw_title
            else:
                legacy_title = raw_grid_meta.get("title")
                title = legacy_title if isinstance(legacy_title, str) else ""

            raw_subtitle = raw_categories.get("subtitle")
            if isinstance(raw_subtitle, str):
                subtitle = raw_subtitle
            else:
                legacy_subtitle = raw_grid_meta.get("subtitle")
                subtitle = legacy_subtitle if isinstance(legacy_subtitle, str) else ""

            raw_section_items = raw_categories.get("items")
            if isinstance(raw_section_items, list):
                raw_items = raw_section_items
        else:
            legacy_title = raw_grid_meta.get("title")
            title = legacy_title if isinstance(legacy_title, str) else ""

            legacy_subtitle = raw_grid_meta.get("subtitle")
            subtitle = legacy_subtitle if isinstance(legacy_subtitle, str) else ""

        ordered_category_ids: list[int] = []
        raw_item_data_by_id: dict[int, dict[str, Any]] = {}

        for item in raw_items:
            if isinstance(item, int):
                if item > 0:
                    ordered_category_ids.append(item)
                continue

            if not isinstance(item, dict):
                continue

            raw_id = item.get("id")
            category_id = raw_id if isinstance(raw_id, int) else None

            if category_id is None:
                raw_category_id = item.get("category_id")
                category_id = raw_category_id if isinstance(raw_category_id, int) else None

            if isinstance(category_id, int) and category_id > 0:
                ordered_category_ids.append(category_id)
                raw_item_data_by_id[category_id] = item

        for grid_item in normalized_grid_items:
            grid_category_id = grid_item.get("category_id")
            if isinstance(grid_category_id, int) and grid_category_id > 0:
                ordered_category_ids.append(grid_category_id)

        deduped_ids: list[int] = []
        seen_ids: set[int] = set()
        for category_id in ordered_category_ids:
            if category_id in seen_ids:
                continue
            seen_ids.add(category_id)
            deduped_ids.append(category_id)

        categories_by_id: dict[int, Category] = {}
        if deduped_ids:
            categories = (
                db.query(Category)
                .filter(
                    Category.id.in_(deduped_ids),
                    Category.is_active.is_(True),
                    Category.is_deleted.is_(False),
                )
                .all()
            )
            categories_by_id = {category.id: category for category in categories}

        grid_by_id: dict[int, dict[str, Any]] = {}
        for grid_item in normalized_grid_items:
            grid_category_id = grid_item.get("category_id")
            if isinstance(grid_category_id, int) and grid_category_id > 0:
                grid_by_id[grid_category_id] = grid_item

        normalized_items: list[dict[str, Any]] = []
        for category_id in deduped_ids:
            category = categories_by_id.get(category_id)
            # Drop stale rows that no longer map to active categories.
            if category is None:
                continue

            raw_item = raw_item_data_by_id.get(category_id, {})
            grid_item = grid_by_id.get(category_id, {})

            raw_name = raw_item.get("name")
            if not isinstance(raw_name, str):
                raw_name = grid_item.get("name")
            name = raw_name if isinstance(raw_name, str) else category.name
            if not name.strip():
                name = category.name

            raw_slug = raw_item.get("slug")
            if not isinstance(raw_slug, str):
                raw_slug = grid_item.get("slug")
            slug = raw_slug if isinstance(raw_slug, str) else category.slug
            if not slug.strip():
                slug = category.slug

            raw_caption = raw_item.get("caption")
            if not isinstance(raw_caption, str):
                raw_caption = raw_item.get("subtitle")
            if not isinstance(raw_caption, str):
                raw_caption = grid_item.get("caption")
            if not isinstance(raw_caption, str):
                raw_caption = grid_item.get("subtitle")
            caption = raw_caption if isinstance(raw_caption, str) else ""

            image = WebsiteCMSService._normalize_image(raw_item.get("image"), name)
            if not image["url"]:
                image = WebsiteCMSService._normalize_image(grid_item.get("image"), name)

            normalized_items.append(
                {
                    "id": category_id,
                    "name": name,
                    "slug": slug,
                    "caption": caption,
                    "image": image,
                }
            )

        return {
            "enabled": enabled,
            "title": title,
            "subtitle": subtitle,
            "items": normalized_items,
        }

    @staticmethod
    def _normalize_price_buckets(payload: dict[str, Any]) -> dict[str, Any]:
        raw_section = payload.get("price_buckets")

        enabled = True
        title = ""
        raw_items: list[Any] = []

        if isinstance(raw_section, list):
            raw_items = raw_section
        elif isinstance(raw_section, dict):
            raw_enabled = raw_section.get("enabled")
            enabled = raw_enabled if isinstance(raw_enabled, bool) else True

            raw_title = raw_section.get("title")
            title = raw_title if isinstance(raw_title, str) else ""

            section_items = raw_section.get("items")
            raw_items = section_items if isinstance(section_items, list) else []

        def parse_price(value: Any) -> int:
            if isinstance(value, (int, float)):
                return int(value)

            if isinstance(value, str):
                try:
                    return int(float(value.strip()))
                except ValueError:
                    return 0

            return 0

        normalized_items: list[dict[str, Any]] = []
        for item in raw_items:
            if not isinstance(item, dict):
                continue

            raw_item_title = item.get("title")
            legacy_label = item.get("label")
            item_title = raw_item_title if isinstance(raw_item_title, str) else (legacy_label if isinstance(legacy_label, str) else "")

            raw_subtitle = item.get("subtitle")
            subtitle = raw_subtitle if isinstance(raw_subtitle, str) else ""

            min_price = parse_price(item.get("min_price") if item.get("min_price") is not None else item.get("min"))
            max_price = parse_price(item.get("max_price") if item.get("max_price") is not None else item.get("max"))

            image = WebsiteCMSService._normalize_image(item.get("image"), item_title)

            raw_cta_text = item.get("cta_text")
            cta_text = raw_cta_text if isinstance(raw_cta_text, str) else ""

            raw_cta_link = item.get("cta_link")
            legacy_link = item.get("link")
            cta_link = raw_cta_link if isinstance(raw_cta_link, str) else (legacy_link if isinstance(legacy_link, str) else "")

            normalized_items.append(
                {
                    "title": item_title,
                    "subtitle": subtitle,
                    "min_price": min_price,
                    "max_price": max_price,
                    "image": image,
                    "cta_text": cta_text,
                    "cta_link": cta_link,
                }
            )

        return {
            "enabled": enabled,
            "title": title,
            "items": normalized_items,
        }

    @staticmethod
    def _normalize_brand_story(payload: dict[str, Any]) -> dict[str, Any]:
        raw = payload.get("brand_story")
        if not isinstance(raw, dict):
            raw = {}

        raw_title = raw.get("title")
        title: str = raw_title if isinstance(raw_title, str) else ""
        image = WebsiteCMSService._normalize_image(raw.get("image"), title)

        raw_enabled = raw.get("enabled")
        enabled = raw_enabled if isinstance(raw_enabled, bool) else True

        raw_description = raw.get("description")
        description = raw_description if isinstance(raw_description, str) else ""

        return {
            "enabled": enabled,
            "title": title,
            "description": description,
            "image": image,
        }

    @staticmethod
    def _normalize_cta_section(payload: dict[str, Any]) -> dict[str, Any]:
        raw = payload.get("cta_section")
        if not isinstance(raw, dict):
            raw = {}

        raw_text = raw.get("text")
        text = raw_text if isinstance(raw_text, str) else ""

        raw_link = raw.get("link")
        link = raw_link if isinstance(raw_link, str) and raw_link.strip() else "/products"

        return {
            "text": text,
            "link": link,
        }

    @staticmethod
    def _normalize_homepage_payload(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(payload)
        normalized["header"] = WebsiteCMSService._normalize_header(payload)
        normalized["hero"] = WebsiteCMSService._normalize_hero(payload)
        normalized["trust_bar"] = WebsiteCMSService._normalize_trust_bar(payload)
        normalized.pop("features", None)
        normalized_categories_grid = WebsiteCMSService._normalize_categories_grid(db, payload)
        normalized["categories_grid"] = normalized_categories_grid
        normalized["categories"] = WebsiteCMSService._normalize_categories(db, payload, normalized_categories_grid)
        normalized["occasions"] = WebsiteCMSService._normalize_list_section(payload.get("occasions"))
        normalized["price_buckets"] = WebsiteCMSService._normalize_price_buckets(payload)
        normalized["collections"] = WebsiteCMSService._normalize_collections(db, payload)
        normalized["bestsellers"] = WebsiteCMSService._normalize_list_section(payload.get("bestsellers"))

        raw_bestsellers_enabled = payload.get("bestsellers_enabled")
        if isinstance(raw_bestsellers_enabled, bool):
            normalized["bestsellers_enabled"] = raw_bestsellers_enabled
        else:
            normalized["bestsellers_enabled"] = bool(normalized["bestsellers"].get("enabled", True))

        normalized["brand_story"] = WebsiteCMSService._normalize_brand_story(payload)
        normalized["cta_section"] = WebsiteCMSService._normalize_cta_section(payload)

        sections = payload.get("sections")
        normalized["sections"] = sections if isinstance(sections, list) else []
        normalized["schema_version"] = "2.0.0"

        return normalized

    @staticmethod
    def _is_valid_trust_bar_section(value: Any) -> bool:
        if isinstance(value, list):
            return True

        if not isinstance(value, dict):
            return False

        items = value.get("items")
        enabled = value.get("enabled")

        if items is not None and not isinstance(items, list):
            return False
        if enabled is not None and not isinstance(enabled, bool):
            return False

        return True

    @staticmethod
    def _is_valid_list_section(value: Any) -> bool:
        # Backward compatibility: previously list sections were sent as arrays.
        if isinstance(value, list):
            return True

        if not isinstance(value, dict):
            return False

        items = value.get("items")
        enabled = value.get("enabled")

        if items is not None and not isinstance(items, list):
            return False
        if enabled is not None and not isinstance(enabled, bool):
            return False

        return True

    @staticmethod
    def get_homepage_config(db: Session) -> dict[str, Any]:
        config = WebsiteCMSRepository.fetch_by_key(db, WebsiteCMSService.HOMEPAGE_KEY)
        if config is None:
            return WebsiteCMSService._normalize_homepage_payload(db, deepcopy(DEFAULT_HOMEPAGE_CONFIG))
        if not isinstance(config.value, dict):
            return WebsiteCMSService._normalize_homepage_payload(db, deepcopy(DEFAULT_HOMEPAGE_CONFIG))
        return WebsiteCMSService._normalize_homepage_payload(db, config.value)

    @staticmethod
    def update_homepage_config(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Homepage payload must be a JSON object")

        if "hero" not in payload:
            raise HTTPException(status_code=400, detail="hero is required")
        raw_trust_bar = payload.get("trust_bar", payload.get("trustBar"))
        if raw_trust_bar is not None and not WebsiteCMSService._is_valid_trust_bar_section(raw_trust_bar):
            raise HTTPException(status_code=400, detail="trust_bar must be an array or { enabled, items } object")
        if "sections" not in payload or not isinstance(payload.get("sections"), list):
            raise HTTPException(status_code=400, detail="sections must be an array")

        normalized_payload = WebsiteCMSService._normalize_homepage_payload(db, payload)

        try:
            saved = WebsiteCMSRepository.upsert_by_key(db, WebsiteCMSService.HOMEPAGE_KEY, normalized_payload)
            db.commit()
            if not isinstance(saved.value, dict):
                return WebsiteCMSService._normalize_homepage_payload(db, deepcopy(DEFAULT_HOMEPAGE_CONFIG))
            return WebsiteCMSService._normalize_homepage_payload(db, saved.value)
        except Exception:
            db.rollback()
            raise
