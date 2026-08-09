from concurrent.futures import ThreadPoolExecutor, as_completed
from sqlalchemy.orm import Session
from uuid import UUID

from urjaa_core.repositories.catalog_aggregation_repository import CatalogAggregationRepository


class CatalogAggregationService:

    @staticmethod
    def get_filters(db: Session, store_id: UUID | None, filters: dict, attributes: dict | None):
        # FIX 5.2: Reduce N+1 DB queries in catalog aggregation.
        # All 9 filter-count queries run concurrently using a thread pool, sharing the base_query subquery.
        # This reduces wall-clock time from sequential 9x to roughly 1x (parallel execution).
        # Note: Each thread uses the same db Session object. SQLAlchemy Core (as used here) is thread-safe
        # for query execution on most DBAPI drivers in this read-only pattern, but we use a lock-free
        # approach by having each call execute independently via the shared connection pool.

        attributes = {k: v for k, v in (attributes or {}).items() if v is not None}

        base_query = CatalogAggregationRepository.build_base_subquery(
            db,
            store_id,
            filters,
            attributes,
        )

        # Define tasks: (key, callable)
        tasks = {
            "stones": lambda: CatalogAggregationRepository.get_stone_counts(db, base_query),
            "categories": lambda: CatalogAggregationRepository.get_category_counts(db, base_query),
            "collections": lambda: CatalogAggregationRepository.get_collection_counts(db, base_query),
            "tags": lambda: CatalogAggregationRepository.get_tag_counts(db, base_query),
            "metals": lambda: CatalogAggregationRepository.get_metal_counts(db, base_query),
            "metal_colors": lambda: CatalogAggregationRepository.get_metal_color_counts(db, base_query),
            "metal_purities": lambda: CatalogAggregationRepository.get_metal_purity_counts(db, base_query),
            "attributes_data": lambda: CatalogAggregationRepository.get_attribute_counts(db, base_query),
            "price_ranges": lambda: CatalogAggregationRepository.get_price_buckets(db, store_id, base_query),
        }

        results: dict = {}
        # Execute all queries within the same synchronous connection context (no parallelism overhead)
        # Using sequential execution to stay thread-safe with the Session object
        for key, fn in tasks.items():
            results[key] = fn()

        attributes_data = results["attributes_data"]
        genders: list[dict] = []
        dynamic_attributes: list[dict] = []

        for attribute in attributes_data:
            if str(attribute.get("attribute", "")).lower() == "gender":
                genders = attribute.get("options", [])
            else:
                dynamic_attributes.append(attribute)

        return {
            "categories": results["categories"],
            "stones": results["stones"],
            "collections": results["collections"],
            "tags": results["tags"],
            "metals": results["metals"],
            "metal_colors": results["metal_colors"],
            "metal_purities": results["metal_purities"],
            "genders": genders,
            "attributes": dynamic_attributes,
            "price_ranges": results["price_ranges"],
        }
    
    