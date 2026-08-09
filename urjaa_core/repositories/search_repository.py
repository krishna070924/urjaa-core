from sqlalchemy.orm import Session
from sqlalchemy import func, or_
from uuid import UUID

from urjaa_core.models.product import Product
from urjaa_core.repositories.catalog_query_builder import CatalogQueryBuilder


class SearchRepository:

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

        offset = (page - 1) * limit

        # -----------------------------
        # Search Components
        # -----------------------------

        search_query = func.plainto_tsquery("english", query)

        # Full-text rank
        rank = func.ts_rank(Product.search_vector, search_query)

        # Fuzzy similarity
        similarity = func.similarity(Product.name, query)

        # Combined score
        score = (func.coalesce(rank, 0) + similarity)

        # -----------------------------
        # Base Query (IDs)
        # -----------------------------

        id_query = db.query(Product.id)

        id_query = (
            CatalogQueryBuilder(id_query, store_id=store_id)
            .apply_filters(filters)
            .filter_attributes(attributes)
            .only_active()
            .build()
        )

        # -----------------------------
        # Apply Search Logic
        # -----------------------------

        id_query = id_query.filter(
            or_(
                Product.search_vector.op("@@")(search_query),  # FTS
                similarity > 0.3  # fuzzy match threshold
            )
        )

        # -----------------------------
        # Add Ranking + Ordering
        # -----------------------------

        id_query = (
            id_query
            .add_columns(score.label("score"))
            .order_by(score.desc())
        )

        # -----------------------------
        # Total Count
        # -----------------------------

        total = id_query.count()

        # -----------------------------
        # Pagination
        # -----------------------------

        results = (
            id_query
            .offset(offset)
            .limit(limit)
            .all()
        )

        # Extract product IDs
        product_ids = [row[0] for row in results]

        return product_ids, total