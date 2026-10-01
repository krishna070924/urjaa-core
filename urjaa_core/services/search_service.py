from uuid import UUID

from sqlalchemy.orm import Session

from urjaa_core.repositories.product_repository import ProductRepository
from urjaa_core.repositories.search_repository import SearchRepository
from urjaa_core.services.pricing_service import PricingService
from urjaa_core.utils.currency import format_price_or_request


class SearchService:

    @staticmethod
    def search_products(
        db: Session,
        store_id: UUID | None,
        query: str,
        filters: dict,
        attributes: dict | None,
        page: int,
        limit: int,
    ):
        """
        Search products using query + filters + attributes

        Flow:
        1. Get product IDs (search + filters applied)
        2. Fetch full product data using IDs
        3. Preserve order
        4. Attach pricing
        """

        # -----------------------------
        # Stage 1 — Get filtered IDs
        # -----------------------------
        product_ids, total = SearchRepository.search_products(
            db=db,
            store_id=store_id,
            query=query,
            filters=filters,
            attributes=attributes,
            page=page,
            limit=limit,
        )

        if not product_ids:
            return [], total

        # -----------------------------
        # Stage 2 — Fetch products
        # -----------------------------
        products = ProductRepository.get_products_by_ids(
            db=db,
            store_id=store_id,
            product_ids=product_ids,
        )

        # -----------------------------
        # Preserve order (VERY IMPORTANT)
        # -----------------------------
        product_map = {product.id: product for product in products}

        ordered_products = [
            product_map[pid]
            for pid in product_ids
            if pid in product_map
        ]

        # Request-scoped caches to avoid repeated metal rate / discount lookups.
        rate_cache = {}
        discount_map = PricingService.resolve_best_discounts(
            db,
            store_ids={product.store_id for product in ordered_products},
            product_ids={product.id for product in ordered_products},
        )

        # -----------------------------
        # Attach pricing
        # -----------------------------
        for product in ordered_products:
            # K-03: same discount-aware pricing as the catalog list (§5.5) —
            # search results share the same ProductResponse shape, so the price
            # shown here must match what /products and checkout would charge.
            priced = PricingService.price_product_starting(
                product, db, rate_cache=rate_cache, discount_map=discount_map,
            )
            product.starting_price = priced.price
            # URJ-066: an unpriceable search hit renders "Price on Request", matching
            # the catalog list / PDP read paths (not a blank price).
            product.formatted_price = format_price_or_request(product.starting_price)
            product.original_price = priced.original_price
            product.discount_percent = priced.discount_percent
            product.discount_ends_at = priced.discount_ends_at

        return ordered_products, total
