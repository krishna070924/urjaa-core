from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Query

from urjaa_core.models.attribute import Attribute
from urjaa_core.models.attribute_value import AttributeValue
from urjaa_core.models.base_metal import BaseMetal
from urjaa_core.models.category import Category
from urjaa_core.models.collection import Collection
from urjaa_core.models.metal_color import MetalColor
from urjaa_core.models.metal_purity import MetalPurity
from urjaa_core.models.metal_rate import MetalRate
from urjaa_core.models.order import Order
from urjaa_core.models.order_item import OrderItem
from urjaa_core.models.product import Product
from urjaa_core.models.product_attribute import ProductAttribute
from urjaa_core.models.product_collection import ProductCollection
from urjaa_core.models.product_stone import ProductStone
from urjaa_core.models.product_tag import ProductTag
from urjaa_core.models.product_variant import ProductVariant
from urjaa_core.models.stone import Stone
from urjaa_core.models.subcategory import Subcategory
from urjaa_core.models.tag import Tag


class CatalogQueryBuilder:

    FILTER_REGISTRY = {
        "category_id": "filter_category_id",
        "collection_id": "filter_collection_id",
        "category": "filter_category",
        "subcategory": "filter_subcategory",
        "stone": "filter_stone",
        "featured": "filter_featured",
        "customizable": "filter_customizable",
        "collection": "filter_collection",
        "tag": "filter_tag",
        "metal": "filter_metal",
        "metal_color": "filter_metal_color",
        "purity": "filter_purity",
        "min_price": "filter_min_price",
        "max_price": "filter_max_price",
    }

    def __init__(self, query: Query, store_id: UUID | None):
        self.query = query
        self.store_id = store_id
        self.joins = set()
        self._price_subquery = None

    @staticmethod
    def _normalize_values(value: str | Sequence[str] | None) -> list[str]:
        if value is None:
            return []

        if isinstance(value, str):
            candidates = [value]
        elif isinstance(value, Sequence):
            candidates = [str(item) for item in value if item is not None]
        else:
            candidates = [str(value)]

        normalized: list[str] = []
        for candidate in candidates:
            for token in candidate.split(","):
                cleaned = token.strip().lower()
                if cleaned and cleaned not in normalized:
                    normalized.append(cleaned)

        return normalized

    # ------------------------------------------------
    # Join Helpers (EXPLICIT JOINS)
    # ------------------------------------------------

    def _join_subcategory(self):
        if "subcategory" not in self.joins:
            self.query = self.query.join(
                Subcategory, Subcategory.id == Product.subcategory_id
            )
            self.joins.add("subcategory")

    def _join_category(self):
        self._join_subcategory()

        if "category" not in self.joins:
            self.query = self.query.join(
                Category, Category.id == Subcategory.category_id
            )
            self.joins.add("category")

    def _join_stone(self):
        if "product_stone" not in self.joins:
            self.query = self.query.join(
                ProductStone, ProductStone.product_id == Product.id
            )
            self.joins.add("product_stone")

        if "stone" not in self.joins:
            self.query = self.query.join(
                Stone, Stone.id == ProductStone.stone_id
            )
            self.joins.add("stone")

    def _join_collection(self):
        if "product_collection" not in self.joins:
            self.query = self.query.join(
                ProductCollection, ProductCollection.product_id == Product.id
            )
            self.joins.add("product_collection")

        if "collection" not in self.joins:
            self.query = self.query.join(
                Collection, Collection.id == ProductCollection.collection_id
            )
            self.joins.add("collection")

    def _join_tag(self):
        if "product_tag" not in self.joins:
            self.query = self.query.join(
                ProductTag, ProductTag.product_id == Product.id
            )
            self.joins.add("product_tag")

        if "tag" not in self.joins:
            self.query = self.query.join(
                Tag, Tag.id == ProductTag.tag_id
            )
            self.joins.add("tag")

    def _join_variant(self):
        if "variant" not in self.joins:
            self.query = self.query.join(
                ProductVariant, ProductVariant.product_id == Product.id
            )
            if self.store_id is not None:
                self.query = self.query.filter(ProductVariant.store_id == self.store_id)
            self.joins.add("variant")

    def _join_base_metal(self):
        self._join_variant()
        if "base_metal" not in self.joins:
            self.query = self.query.join(
                BaseMetal, BaseMetal.id == ProductVariant.base_metal_id
            )
            self.joins.add("base_metal")

    def _join_metal_color(self):
        self._join_variant()
        if "metal_color" not in self.joins:
            self.query = self.query.join(
                MetalColor, MetalColor.id == ProductVariant.metal_color_id
            )
            self.joins.add("metal_color")

    def _join_metal_purity(self):
        self._join_variant()
        if "metal_purity" not in self.joins:
            self.query = self.query.join(
                MetalPurity, MetalPurity.id == ProductVariant.metal_purity_id
            )
            self.joins.add("metal_purity")

    def _join_min_product_price(self):
        if self._price_subquery is not None:
            return

        latest_rate_subquery = (
            self.query.session.query(
                MetalRate.base_metal_id.label("base_metal_id"),
                func.max(MetalRate.effective_from).label("latest_effective_from"),
            )
            # URJ-066: ignore future-dated rows so the SQL price filter/sort/buckets
            # agree with MetalRateRepository.get_latest_rate on which rate is current.
            # NOTE: a metal with NO effective rate still coalesces to 0 below (priced
            # as stone+making for facet/sort purposes) while the Python read path
            # renders "Price on Request" — a known display/facet divergence tracked
            # for URJ-072 (unpriced-product guardrails), out of scope here.
            .filter(MetalRate.effective_from <= func.current_timestamp())
            .group_by(MetalRate.base_metal_id)
            .subquery()
        )

        latest_rates = (
            self.query.session.query(
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

        min_price_per_product = (
            self.query.session.query(
                ProductVariant.product_id.label("product_id"),
                func.min(computed_price).label("product_price"),
            )
            .outerjoin(latest_rates, latest_rates.c.base_metal_id == ProductVariant.base_metal_id)
            .outerjoin(MetalPurity, MetalPurity.id == ProductVariant.metal_purity_id)
        )

        if self.store_id is not None:
            min_price_per_product = min_price_per_product.filter(ProductVariant.store_id == self.store_id)

        self._price_subquery = min_price_per_product.group_by(ProductVariant.product_id).subquery()

        self.query = self.query.join(
            self._price_subquery,
            self._price_subquery.c.product_id == Product.id,
        )

    # ------------------------------------------------
    # Filter Application
    # ------------------------------------------------

    def apply_filters(self, filters: dict):

        for key, value in filters.items():

            if value is None:
                continue

            method_name = self.FILTER_REGISTRY.get(key)

            if not method_name:
                continue

            method = getattr(self, method_name)
            method(value)

        return self

    # ------------------------------------------------
    # Individual Filters
    # ------------------------------------------------

    def filter_category_id(self, category_id: int | None):
        if category_id is not None:
            self._join_subcategory()
            self.query = self.query.filter(Subcategory.category_id == category_id)

        return self

    def filter_category(self, category_slug: str | Sequence[str] | None):
        category_values = self._normalize_values(category_slug)
        if category_values:
            self._join_category()
            self.query = self.query.filter(func.lower(Category.slug).in_(category_values))

        return self

    def filter_collection_id(self, collection_id: int | None):
        if collection_id is not None:
            self._join_collection()
            self.query = self.query.filter(ProductCollection.collection_id == collection_id)

        return self

    def filter_subcategory(self, subcategory_slug: str | Sequence[str] | None):
        subcategory_values = self._normalize_values(subcategory_slug)
        if subcategory_values:
            self._join_subcategory()
            self.query = self.query.filter(func.lower(Subcategory.slug).in_(subcategory_values))

        return self

    def filter_stone(self, stone_name: str | Sequence[str] | None):
        stone_values = self._normalize_values(stone_name)
        if stone_values:
            self._join_stone()
            self.query = self.query.filter(func.lower(Stone.name).in_(stone_values))

        return self

    def filter_collection(self, collection_slug: str | Sequence[str] | None):
        collection_values = self._normalize_values(collection_slug)
        if collection_values:
            self._join_collection()
            self.query = self.query.filter(func.lower(Collection.slug).in_(collection_values))

        return self

    def filter_tag(self, tag_slug: str | Sequence[str] | None):
        tag_values = self._normalize_values(tag_slug)
        if tag_values:
            self._join_tag()
            self.query = self.query.filter(func.lower(Tag.slug).in_(tag_values))

        return self

    def filter_metal(self, metal_name: str | Sequence[str] | None):
        metal_values = self._normalize_values(metal_name)
        if metal_values:
            self._join_base_metal()
            self.query = self.query.filter(func.lower(BaseMetal.name).in_(metal_values))

        return self

    def filter_metal_color(self, metal_color_name: str | Sequence[str] | None):
        color_values = self._normalize_values(metal_color_name)
        if color_values:
            self._join_metal_color()
            self.query = self.query.filter(func.lower(MetalColor.name).in_(color_values))

        return self

    def filter_purity(self, purity_label: str | Sequence[str] | None):
        purity_values = self._normalize_values(purity_label)
        if purity_values:
            self._join_metal_purity()
            self.query = self.query.filter(func.lower(MetalPurity.purity_label).in_(purity_values))

        return self

    def filter_featured(self, featured: bool | None):
        if featured is not None:
            self.query = self.query.filter(Product.featured == featured)

        return self

    def filter_customizable(self, customizable: bool | None):
        if customizable is not None:
            self.query = self.query.filter(Product.customizable == customizable)

        return self

    def filter_min_price(self, min_price: float | None):
        if min_price is not None:
            self._join_min_product_price()
            price_subquery = self._price_subquery
            if price_subquery is None:
                return self

            self.query = self.query.filter(price_subquery.c.product_price >= min_price)

        return self

    def filter_max_price(self, max_price: float | None):
        if max_price is not None:
            self._join_min_product_price()
            price_subquery = self._price_subquery
            if price_subquery is None:
                return self

            self.query = self.query.filter(price_subquery.c.product_price <= max_price)

        return self

    def apply_sort(self, sort: str | None):
        if not sort or sort == "relevance":
            return self

        if sort == "newest":
            self.query = self.query.order_by(Product.created_at.desc(), Product.id.desc())
            return self

        if sort in {"price_asc", "price_desc"}:
            self._join_min_product_price()
            price_subquery = self._price_subquery
            if price_subquery is None:
                return self

            price_order = price_subquery.c.product_price.asc() if sort == "price_asc" else price_subquery.c.product_price.desc()
            self.query = self.query.order_by(price_order, Product.created_at.desc(), Product.id.desc())

        if sort == "best_selling":
            best_selling_subquery = (
                self.query.session.query(
                    OrderItem.product_id.label("product_id"),
                    func.coalesce(func.sum(OrderItem.quantity), 0).label("units_sold"),
                )
                .join(Order, Order.id == OrderItem.order_id)
                .filter(func.lower(func.coalesce(Order.status, "")) != "cancelled")
            )

            if self.store_id is not None:
                best_selling_subquery = best_selling_subquery.filter(OrderItem.store_id == self.store_id)

            best_selling_subquery = best_selling_subquery.group_by(OrderItem.product_id).subquery()

            self.query = (
                self.query
                .outerjoin(best_selling_subquery, best_selling_subquery.c.product_id == Product.id)
                .order_by(func.coalesce(best_selling_subquery.c.units_sold, 0).desc(), Product.created_at.desc(), Product.id.desc())
            )

        return self

    # ------------------------------------------------
    # Attribute Filters
    # ------------------------------------------------

    def filter_attributes(self, attributes: dict | None):

        if not attributes:
            return self

        for attr_slug, value in attributes.items():

            normalized_values = self._normalize_values(value)
            if not normalized_values:
                continue

            subquery = (
                self.query.session.query(ProductAttribute.product_id)
                .join(AttributeValue, AttributeValue.id == ProductAttribute.attribute_value_id)
                .join(Attribute, Attribute.id == AttributeValue.attribute_id)
                .filter(
                    func.lower(Attribute.slug) == func.lower(attr_slug),
                    Attribute.filterable.is_(True),
                    func.lower(AttributeValue.value).in_(normalized_values),
                )
                .subquery()
            )

            self.query = self.query.filter(Product.id.in_(subquery))

        return self

    # ------------------------------------------------
    # Only Active Products
    # ------------------------------------------------

    def only_active(self):
        self.query = self.query.filter(
            Product.status == "active",
        )
        if self.store_id is not None:
            self.query = self.query.filter(Product.store_id == self.store_id)
        return self

    # ------------------------------------------------
    # Final Query
    # ------------------------------------------------

    def build(self):
        return self.query
