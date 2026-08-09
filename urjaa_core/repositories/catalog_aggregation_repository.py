import re
from uuid import UUID

from sqlalchemy.orm import Session
from sqlalchemy import func

from urjaa_core.models.product import Product
from urjaa_core.models.subcategory import Subcategory
from urjaa_core.models.category import Category
from urjaa_core.models.product_stone import ProductStone
from urjaa_core.models.stone import Stone
from urjaa_core.models.product_collection import ProductCollection
from urjaa_core.models.collection import Collection

from urjaa_core.repositories.catalog_query_builder import CatalogQueryBuilder

from urjaa_core.models.product_tag import ProductTag
from urjaa_core.models.tag import Tag

from urjaa_core.models.product_variant import ProductVariant
from urjaa_core.models.base_metal import BaseMetal
from urjaa_core.models.metal_color import MetalColor
from urjaa_core.models.metal_rate import MetalRate
from urjaa_core.models.metal_purity import MetalPurity
from urjaa_core.models.product_attribute import ProductAttribute
from urjaa_core.models.attribute_value import AttributeValue
from urjaa_core.models.attribute import Attribute


def _slugify(value: str | None) -> str:
    """Generate a lowercase slug from display text for filter payloads."""
    if not value:
        return ""

    normalized = re.sub(r"[^a-z0-9]+", "-", value.lower())
    return normalized.strip("-")

class CatalogAggregationRepository:

    @staticmethod
    def build_base_subquery(db: Session, store_id: UUID | None, filters: dict, attributes: dict | None):

        base_query = db.query(Product.id)

        base_query = (
            CatalogQueryBuilder(base_query, store_id=store_id)
            .apply_filters(filters)
            .filter_attributes(attributes)
            .only_active()
            .build()
            .distinct()
        ).subquery()

        return base_query

    @staticmethod
    def get_category_counts(db: Session, base_query):

        query = (
            db.query(
                Category.name,
                Category.slug,
                func.count(func.distinct(base_query.c.id)),
            )
            .select_from(base_query)
            .join(Product, Product.id == base_query.c.id)
            .join(Subcategory, Subcategory.id == Product.subcategory_id)
            .join(Category, Category.id == Subcategory.category_id)
            .group_by(Category.name, Category.slug, Category.display_order)
            .order_by(Category.display_order.asc(), Category.name.asc())
        )

        return [
            {"category": name, "slug": slug, "count": count}
            for name, slug, count in query.all()
        ]

    @staticmethod
    def get_stone_counts(db: Session, base_query):

        query = (
            db.query(
                Stone.name,
                func.count(func.distinct(base_query.c.id))
            )
            .select_from(base_query)
            .join(ProductStone, ProductStone.product_id == base_query.c.id)
            .join(Stone, Stone.id == ProductStone.stone_id)
            .group_by(Stone.name)
            .order_by(Stone.name.asc())
        )

        results = query.all()

        return [
            {"stone": name, "slug": _slugify(name), "count": count}
            for name, count in results
        ]

    @staticmethod
    def get_collection_counts(db: Session, base_query):

        query = (
            db.query(
                Collection.name,
                Collection.slug,
                func.count(func.distinct(base_query.c.id))
            )
            .select_from(base_query)
            .join(ProductCollection, ProductCollection.product_id == base_query.c.id)
            .join(Collection, Collection.id == ProductCollection.collection_id)
            .group_by(Collection.name, Collection.slug)
            .order_by(Collection.name.asc())
        )

        results = query.all()

        return [
            {"collection": name, "slug": slug, "count": count}
            for name, slug, count in results
        ]
    
    @staticmethod
    def get_tag_counts(db: Session, base_query):

        query = (
            db.query(
                Tag.name,
                Tag.slug,
                func.count(func.distinct(base_query.c.id))
            )
            .select_from(base_query)
            .join(ProductTag, ProductTag.product_id == base_query.c.id)
            .join(Tag, Tag.id == ProductTag.tag_id)
            .group_by(Tag.name, Tag.slug)
            .order_by(Tag.name.asc())
        )

        results = query.all()

        return [
            {"tag": name, "slug": slug, "count": count}
            for name, slug, count in results
        ]

    @staticmethod
    def get_metal_counts(db: Session, base_query):

        query = (
            db.query(
                BaseMetal.name,
                func.count(func.distinct(base_query.c.id)),
            )
            .select_from(base_query)
            .join(ProductVariant, ProductVariant.product_id == base_query.c.id)
            .join(BaseMetal, BaseMetal.id == ProductVariant.base_metal_id)
            .group_by(BaseMetal.name)
            .order_by(BaseMetal.name.asc())
        )

        return [
            {"metal": name, "slug": _slugify(name), "count": count}
            for name, count in query.all()
        ]

    @staticmethod
    def get_metal_color_counts(db: Session, base_query):

        query = (
            db.query(
                MetalColor.name,
                func.count(func.distinct(base_query.c.id)),
            )
            .select_from(base_query)
            .join(ProductVariant, ProductVariant.product_id == base_query.c.id)
            .join(MetalColor, MetalColor.id == ProductVariant.metal_color_id)
            .group_by(MetalColor.name)
            .order_by(MetalColor.name.asc())
        )

        return [
            {"metal_color": name, "slug": _slugify(name), "count": count}
            for name, count in query.all()
        ]

    @staticmethod
    def get_metal_purity_counts(db: Session, base_query):

        query = (
            db.query(
                MetalPurity.purity_label,
                BaseMetal.name,
                func.count(func.distinct(base_query.c.id)),
            )
            .select_from(base_query)
            .join(ProductVariant, ProductVariant.product_id == base_query.c.id)
            .join(MetalPurity, MetalPurity.id == ProductVariant.metal_purity_id)
            .join(BaseMetal, BaseMetal.id == MetalPurity.base_metal_id)
            .group_by(MetalPurity.purity_label, BaseMetal.name)
            .order_by(BaseMetal.name.asc(), MetalPurity.purity_label.asc())
        )

        return [
            {
                "purity": purity_label,
                "slug": _slugify(purity_label),
                "metal": metal_name,
                "count": count,
            }
            for purity_label, metal_name, count in query.all()
        ]

    @staticmethod
    def get_attribute_counts(db: Session, base_query):

        query = (
            db.query(
                Attribute.name,
                Attribute.slug,
                AttributeValue.value,
                func.count(func.distinct(base_query.c.id)),
            )
            .select_from(base_query)
            .join(ProductAttribute, ProductAttribute.product_id == base_query.c.id)
            .join(AttributeValue, AttributeValue.id == ProductAttribute.attribute_value_id)
            .join(Attribute, Attribute.id == AttributeValue.attribute_id)
            .filter(Attribute.filterable.is_(True))
            .group_by(Attribute.name, Attribute.slug, AttributeValue.value)
            .order_by(Attribute.name.asc(), AttributeValue.value.asc())
        )

        grouped: dict[str, dict] = {}

        for attribute_name, attribute_slug, value, count in query.all():
            key = attribute_slug or _slugify(attribute_name)
            if key not in grouped:
                grouped[key] = {
                    "attribute": key,
                    "label": attribute_name,
                    "options": [],
                }

            grouped[key]["options"].append(
                {
                    "value": value,
                    "slug": _slugify(value),
                    "count": count,
                }
            )

        attributes = list(grouped.values())
        attributes.sort(key=lambda item: item["label"].lower())
        return attributes
    
    @staticmethod
    def get_price_buckets(db: Session, store_id: UUID | None, base_query):
        latest_rate_subquery = (
            db.query(
                MetalRate.base_metal_id.label("base_metal_id"),
                func.max(MetalRate.effective_from).label("latest_effective_from"),
            )
            .group_by(MetalRate.base_metal_id)
            .subquery()
        )

        latest_rates = (
            db.query(
                MetalRate.base_metal_id.label("base_metal_id"),
                MetalRate.rate_per_gram.label("rate_per_gram"),
            )
            .join(
                latest_rate_subquery,
                (MetalRate.base_metal_id == latest_rate_subquery.c.base_metal_id)
                & (MetalRate.effective_from == latest_rate_subquery.c.latest_effective_from),
            )
            .subquery()
        )

        # Avoid DECIMAL(5,3) overflow by coalescing the ratio, not raw purity.
        purity_factor = func.coalesce(MetalPurity.numeric_purity / 100, 1)

        computed_price = func.coalesce(
            ProductVariant.price_override,
            (func.coalesce(ProductVariant.metal_weight_grams, 0) * func.coalesce(latest_rates.c.rate_per_gram, 0) * purity_factor)
            + func.coalesce(ProductVariant.stone_cost, 0)
            + func.coalesce(ProductVariant.making_charges, 0),
        )

        product_price_query = (
            db.query(
                ProductVariant.product_id.label("product_id"),
                func.min(computed_price).label("product_price"),
            )
            .join(base_query, ProductVariant.product_id == base_query.c.id)
            .outerjoin(latest_rates, latest_rates.c.base_metal_id == ProductVariant.base_metal_id)
            .outerjoin(MetalPurity, MetalPurity.id == ProductVariant.metal_purity_id)
        )

        if store_id is not None:
            product_price_query = product_price_query.filter(ProductVariant.store_id == store_id)

        product_price_query = product_price_query.group_by(ProductVariant.product_id).subquery()

        buckets = [
            (0, 25000),
            (25000, 50000),
            (50000, 100000),
            (100000, None),
        ]

        results = []

        for min_price, max_price in buckets:

            q = db.query(func.count(product_price_query.c.product_id))

            if max_price is not None:
                q = q.filter(product_price_query.c.product_price.between(min_price, max_price))
            else:
                q = q.filter(product_price_query.c.product_price >= min_price)

            count = q.scalar()

            results.append({
                "min": min_price,
                "max": max_price,
                "count": count
            })

        return results