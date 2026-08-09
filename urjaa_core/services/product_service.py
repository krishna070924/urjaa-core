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

        # Request-scoped cache for metal rates to reduce repeated DB reads
        rate_cache = {}

        for product in products:
            product.starting_price = PricingService.calculate_product_starting_price(
                product,
                db,
                rate_cache=rate_cache,
            )
            # URJ-066: a None starting price (missing metal rate) renders as
            # "Price on Request" instead of a misleading ₹0.
            product.formatted_price = format_price_or_request(product.starting_price)

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
            product.starting_price = PricingService.calculate_product_starting_price(
                product,
                db
            )
            product.formatted_price = format_price_or_request(product.starting_price)

        return product
