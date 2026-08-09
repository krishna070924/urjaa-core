from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from urjaa_core.models.product import Product
from urjaa_core.models.product_variant import ProductVariant


class InventoryRepository:
    @staticmethod
    def count_variants(db: Session, store_id: UUID) -> int:
        return int(
            db.query(func.count(ProductVariant.id)).filter(ProductVariant.store_id == store_id).scalar() or 0
        )

    @staticmethod
    def total_stock_units(db: Session, store_id: UUID) -> int:
        return int(
            db.query(func.coalesce(func.sum(ProductVariant.stock_quantity), 0))
            .filter(ProductVariant.store_id == store_id)
            .scalar()
            or 0
        )

    @staticmethod
    def count_low_stock_variants(db: Session, threshold: int, store_id: UUID) -> int:
        return int(
            db.query(func.count(ProductVariant.id))
            .filter(
                ProductVariant.stock_quantity > 0,
                ProductVariant.stock_quantity <= threshold,
                ProductVariant.store_id == store_id,
            )
            .scalar()
            or 0
        )

    @staticmethod
    def count_out_of_stock_variants(db: Session, store_id: UUID) -> int:
        return int(
            db.query(func.count(ProductVariant.id))
            .filter(ProductVariant.stock_quantity <= 0, ProductVariant.store_id == store_id)
            .scalar()
            or 0
        )

    @staticmethod
    def get_low_stock_variants(
        db: Session,
        threshold: int,
        store_id: UUID,
        limit: int = 10,
    ) -> list[tuple[ProductVariant, Product]]:
        return (
            db.query(ProductVariant, Product)
            .join(Product, Product.id == ProductVariant.product_id)
            .filter(
                ProductVariant.stock_quantity > 0,
                ProductVariant.stock_quantity <= threshold,
                ProductVariant.store_id == store_id,
            )
            .order_by(ProductVariant.stock_quantity.asc(), Product.updated_at.desc())
            .limit(limit)
            .all()
        )

    @staticmethod
    def get_out_of_stock_variants(db: Session, store_id: UUID, limit: int = 10) -> list[tuple[ProductVariant, Product]]:
        return (
            db.query(ProductVariant, Product)
            .join(Product, Product.id == ProductVariant.product_id)
            .filter(ProductVariant.stock_quantity <= 0, ProductVariant.store_id == store_id)
            .order_by(Product.updated_at.desc())
            .limit(limit)
            .all()
        )

    @staticmethod
    def get_inventory_export_rows(db: Session, store_id: UUID) -> list[tuple[ProductVariant, Product]]:
        return (
            db.query(ProductVariant, Product)
            .join(Product, Product.id == ProductVariant.product_id)
            .filter(ProductVariant.store_id == store_id)
            .order_by(Product.name.asc(), ProductVariant.sku_code.asc())
            .all()
        )
