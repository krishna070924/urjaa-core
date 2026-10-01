from uuid import UUID

from sqlalchemy.orm import Session

from urjaa_core.repositories.product_repository import ProductRepository
from urjaa_core.services.catalog_aggregation_service import CatalogAggregationService
from urjaa_core.services.pricing_service import PricingService
from urjaa_core.utils.currency import format_price_or_request


class ProductService:

    @staticmethod
    def get_products(
        db: Session,
        store_id: UUID | None,
        category_id: int | None = None,
        collection_id: int | None = None,
        category: str | list[str] | None = None,
        subcategory: str | list[str] | None = None,
        stone: str | list[str] | None = None,
        collection: str | list[str] | None = None,
        sort: str | None = None,
        min_price: float | None = None,
        max_price: float | None = None,
        attributes: dict[str, str | list[str]] | None = None,
        featured: bool | None = None,
        customizable: bool | None = None,
        tag: str | list[str] | None = None,
        metal: str | list[str] | None = None,
        metal_color: str | list[str] | None = None,
        purity: str | list[str] | None = None,
        size: str | list[str] | None = None,
        page: int = 1,
        limit: int = 20,
    ):

        products, total = ProductRepository.get_products(
            db,
            store_id=store_id,
            category_id=category_id,
            collection_id=collection_id,
            category_slug=category,
            subcategory_slug=subcategory,
            stone_name=stone,
            collection_slug=collection,
            sort=sort,
            min_price=min_price,
            max_price=max_price,
            attributes=attributes,
            featured=featured,
            customizable=customizable,
            tag_slug=tag,
            metal_name=metal,
            metal_color_name=metal_color,
            purity_label=purity,
            size_value=size,
            page=page,
            limit=limit,
        )

        filters = {
            "category_id": category_id,
            "collection_id": collection_id,
            "category": category,
            "subcategory": subcategory,
            "stone": stone,
            "collection": collection,
            "tag": tag,
            "metal": metal,
            "metal_color": metal_color,
            "purity": purity,
            "size": size,
            "sort": sort,
            "min_price": min_price,
            "max_price": max_price,
            "featured": featured,
            "customizable": customizable,
        }

        filters_data = CatalogAggregationService.get_filters(
            db,
            store_id=store_id,
            filters=filters,
            attributes=attributes,
        )

        # Request-scoped caches: metal rates and (K-03) best-discount lookups,
        # so pricing N products hits each once, not once per product.
        rate_cache = {}
        discount_map = PricingService.resolve_best_discounts(
            db,
            store_ids={product.store_id for product in products},
            product_ids={product.id for product in products},
        )

        for product in products:
            priced = PricingService.price_product_starting(
                product, db, rate_cache=rate_cache, discount_map=discount_map,
            )
            product.starting_price = priced.price
            # URJ-066: a None starting price (missing metal rate) renders as
            # "Price on Request" instead of a misleading ₹0.
            product.formatted_price = format_price_or_request(product.starting_price)
            # K-03/D27: null when there's no discount on the cheapest variant.
            product.original_price = priced.original_price
            product.discount_percent = priced.discount_percent
            product.discount_ends_at = priced.discount_ends_at

        pages = (total + limit - 1) // limit

        return {
            "items": products,
            "page": page,
            "limit": limit,
            "total": total,
            "pages": pages,
            "filters": filters_data,
        }

    @staticmethod
    def get_product(db: Session, store_id: UUID | None, slug: str):

        product = ProductRepository.get_product_by_slug(db, store_id=store_id, slug=slug)

        if product:
            # Shared across starting_price + every variant below so pricing N
            # variants of the same metal/discount hits each cache once, not N times.
            rate_cache: dict = {}
            discount_map = PricingService.resolve_best_discounts(
                db, store_ids={product.store_id}, product_ids={product.id}
            )

            starting = PricingService.price_product_starting(
                product, db, rate_cache=rate_cache, discount_map=discount_map,
            )
            product.starting_price = starting.price
            product.formatted_price = format_price_or_request(product.starting_price)
            product.original_price = starting.original_price
            product.discount_percent = starting.discount_percent
            product.discount_ends_at = starting.discount_ends_at

            for variant in product.variants:
                priced = PricingService.price_variant(
                    variant, db, rate_cache=rate_cache, discount_map=discount_map
                )
                variant.price = priced.price
                variant.formatted_price = format_price_or_request(variant.price)
                variant.original_price = priced.original_price
                variant.discount_percent = priced.discount_percent
                variant.discount_ends_at = priced.discount_ends_at

        return product
