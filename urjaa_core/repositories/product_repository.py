from sqlalchemy.orm import Session, selectinload
from sqlalchemy import case
from uuid import UUID
from urjaa_core.models.product import Product
from urjaa_core.repositories.catalog_query_builder import CatalogQueryBuilder


class ProductRepository:

    @staticmethod
    def get_products(
        db: Session,
        store_id: UUID | None,
        category_id: int | None = None,
        collection_id: int | None = None,
        category_slug: str | list[str] | None = None,
        subcategory_slug: str | list[str] | None = None,
        stone_name: str | list[str] | None = None,
        collection_slug: str | list[str] | None = None,
        sort: str | None = None,
        min_price: float | None = None,
        max_price: float | None = None,
        featured: bool | None = None,
        customizable: bool | None = None,
        attributes: dict[str, str | list[str]] | None = None,
        tag_slug: str | list[str] | None = None,
        metal_name: str | list[str] | None = None,
        metal_color_name: str | list[str] | None = None,
        purity_label: str | list[str] | None = None,
        page: int = 1,
        limit: int = 20,
    ):
        """
        Fetch products with filters using two-stage query pattern
        """

        offset = (page - 1) * limit

        filters = {
            "category_id": category_id,
            "collection_id": collection_id,
            "category": category_slug,
            "subcategory": subcategory_slug,
            "stone": stone_name,
            "collection": collection_slug,
            "tag": tag_slug,
            "metal": metal_name,
            "metal_color": metal_color_name,
            "purity": purity_label,
            "min_price": min_price,
            "max_price": max_price,
            "featured": featured,
            "customizable": customizable,
        }

        # -----------------------------
        # Stage 1 — Fetch Product IDs
        # -----------------------------
        id_query = db.query(Product.id).select_from(Product)

        query_builder = CatalogQueryBuilder(id_query, store_id=store_id)
        query_builder = query_builder.apply_filters(filters).filter_attributes(attributes).only_active()

        total = query_builder.build().distinct().count()

        id_query = query_builder.apply_sort(sort).build()

        raw_product_ids = [
            row[0]
            for row in id_query
            .offset(offset)
            .limit(limit)
            .all()
        ]

        product_ids = list(dict.fromkeys(raw_product_ids))

        if not product_ids:
            return [], total

        # -----------------------------
        # Stage 2 — Fetch Product Data
        # -----------------------------

        # Preserve order using CASE
        order_case = case(
            {pid: index for index, pid in enumerate(product_ids)},
            value=Product.id
        )

        product_query = (
            db.query(Product)
            .options(
                selectinload(Product.subcategory),
                selectinload(Product.variants),
                selectinload(Product.stones),
                selectinload(Product.attributes),
                selectinload(Product.collections),
                selectinload(Product.tags),
                selectinload(Product.images),
            )
            .filter(Product.id.in_(product_ids))
            .order_by(order_case)
        )

        if store_id is not None:
            product_query = product_query.filter(Product.store_id == store_id)

        products = product_query.all()

        # -----------------------------
        # Final Order Safety (Python)
        # -----------------------------
        product_map = {p.id: p for p in products}
        ordered_products = [
            product_map[pid]
            for pid in product_ids
            if pid in product_map
        ]

        return ordered_products, total

    @staticmethod
    def get_product_by_slug(db: Session, store_id: UUID | None, slug: str):
        """
        Fetch single product with all relations
        """

        query = (
            db.query(Product)
            .options(
                selectinload(Product.subcategory),
                selectinload(Product.variants),
                selectinload(Product.stones),
                selectinload(Product.attributes),
                selectinload(Product.collections),
                selectinload(Product.tags),
                selectinload(Product.images),   
            )
            .filter(
                Product.slug == slug,
                Product.status == "active",
            )
        )

        if store_id is not None:
            query = query.filter(Product.store_id == store_id)

        return query.first()

    @staticmethod
    def get_products_by_ids(db: Session, store_id: UUID | None, product_ids: list[int]):
        """
        Used in search flow — MUST match get_products loading strategy
        """

        if not product_ids:
            return []

        product_query = (
            db.query(Product)
            .options(
                selectinload(Product.subcategory),
                selectinload(Product.variants),
                selectinload(Product.stones),
                selectinload(Product.attributes),
                selectinload(Product.collections),
                selectinload(Product.tags),
                selectinload(Product.images),   
            )
            .filter(Product.id.in_(product_ids))
            .filter(
                Product.status == "active",
            )
        )

        if store_id is not None:
            product_query = product_query.filter(Product.store_id == store_id)

        products = product_query.all()

        # Preserve order
        product_map = {p.id: p for p in products}
        ordered_products = [
            product_map[pid]
            for pid in product_ids
            if pid in product_map
        ]

        return ordered_products