from datetime import datetime
import logging
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload

from urjaa_core.models.base_metal import BaseMetal
from urjaa_core.models.metal_rate import MetalRate
from urjaa_core.models.order import Order
from urjaa_core.models.product import Product
from urjaa_core.models.product_variant import ProductVariant
from urjaa_core.models.sale import Sale
from urjaa_core.models.user import User


logger = logging.getLogger(__name__)

CUSTOMER_SOURCES = ("WEBSITE", "STORE", "ADMIN")


class SalesRepository:
    @staticmethod
    def count_products_by_status(db: Session, status: str, store_id: UUID) -> int:
        return int(
            db.query(func.count(Product.id))
            .filter(Product.status == status, Product.store_id == store_id)
            .scalar()
            or 0
        )

    @staticmethod
    def count_featured_products(db: Session, store_id: UUID) -> int:
        return int(
            db.query(func.count(Product.id))
            .filter(Product.featured.is_(True), Product.store_id == store_id)
            .scalar()
            or 0
        )

    @staticmethod
    def count_variants(db: Session, store_id: UUID) -> int:
        return int(
            db.query(func.count(ProductVariant.id)).filter(ProductVariant.store_id == store_id).scalar() or 0
        )

    @staticmethod
    def count_in_stock_variants(db: Session, store_id: UUID) -> int:
        return int(
            db.query(func.count(ProductVariant.id))
            .filter(ProductVariant.stock_quantity > 0, ProductVariant.store_id == store_id)
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
    def get_variants_for_catalog_estimation(db: Session, store_id: UUID) -> list[ProductVariant]:
        return db.query(ProductVariant).filter(ProductVariant.store_id == store_id).all()

    @staticmethod
    def get_latest_metal_rate_map(db: Session) -> dict[int, float]:
        latest_rate_subquery = (
            db.query(
                MetalRate.base_metal_id.label("base_metal_id"),
                func.max(MetalRate.effective_from).label("latest_effective_from"),
            )
            .group_by(MetalRate.base_metal_id)
            .subquery()
        )

        rows = (
            db.query(MetalRate.base_metal_id, MetalRate.rate_per_gram)
            .join(
                latest_rate_subquery,
                (MetalRate.base_metal_id == latest_rate_subquery.c.base_metal_id)
                & (MetalRate.effective_from == latest_rate_subquery.c.latest_effective_from),
            )
            .all()
        )

        return {int(base_metal_id): float(rate) for base_metal_id, rate in rows}

    @staticmethod
    def get_latest_rate_by_metal_type(db: Session, metal_type: str) -> float | None:
        normalized = (metal_type or "").strip().lower()
        if not normalized:
            return None

        base_metal = (
            db.query(BaseMetal)
            .filter(func.lower(BaseMetal.name) == normalized)
            .first()
        )
        if not base_metal:
            return None

        invalid_count = int(
            db.query(func.count(MetalRate.id))
            .filter(
                MetalRate.base_metal_id == base_metal.id,
                MetalRate.rate_per_gram <= 0,
            )
            .scalar()
            or 0
        )
        if invalid_count > 0:
            logger.warning(
                "Invalid metal rate rows detected",
                extra={
                    "metal_type": base_metal.name,
                    "base_metal_id": base_metal.id,
                    "invalid_rate_rows": invalid_count,
                },
            )

        latest_rate = (
            db.query(MetalRate)
            .filter(
                MetalRate.base_metal_id == base_metal.id,
                MetalRate.rate_per_gram > 0,
            )
            .order_by(MetalRate.effective_from.desc())
            .first()
        )
        if not latest_rate:
            return None
        return float(latest_rate.rate_per_gram)

    @staticmethod
    def get_product_by_id(db: Session, product_id: UUID, store_id: UUID) -> Product | None:
        return db.query(Product).filter(Product.id == product_id, Product.store_id == store_id).first()

    @staticmethod
    def get_variant_by_id_for_update(db: Session, variant_id: UUID, store_id: UUID) -> ProductVariant | None:
        return (
            db.query(ProductVariant)
            .filter(ProductVariant.id == variant_id, ProductVariant.store_id == store_id)
            .with_for_update()
            .first()
        )

    @staticmethod
    def get_customer_by_id(
        db: Session,
        customer_id: UUID,
        include_deleted: bool = False,
    ) -> User | None:
        query = db.query(User).filter(User.id == customer_id, User.source.in_(CUSTOMER_SOURCES))
        if not include_deleted:
            query = query.filter(User.is_active.is_(True))
        return query.first()

    @staticmethod
    def get_customer_by_id_any_state(db: Session, customer_id: UUID) -> User | None:
        return (
            db.query(User)
            .filter(User.id == customer_id, User.source.in_(CUSTOMER_SOURCES))
            .first()
        )

    @staticmethod
    def count_customers(db: Session, include_deleted: bool = False) -> int:
        query = db.query(func.count(User.id)).filter(User.source.in_(CUSTOMER_SOURCES))
        if not include_deleted:
            query = query.filter(User.is_active.is_(True))
        return int(query.scalar() or 0)

    @staticmethod
    def list_customers(
        db: Session,
        page: int,
        limit: int,
        include_deleted: bool = False,
    ) -> list[User]:
        offset = (page - 1) * limit
        query = db.query(User).filter(User.source.in_(CUSTOMER_SOURCES))
        if not include_deleted:
            query = query.filter(User.is_active.is_(True))

        return query.order_by(User.updated_at.desc(), User.id.desc()).offset(offset).limit(limit).all()

    @staticmethod
    def create_customer(db: Session, customer: User) -> User:
        db.add(customer)
        db.flush()
        db.refresh(customer)
        return customer

    @staticmethod
    def update_customer(db: Session, customer: User) -> User:
        db.flush()
        db.refresh(customer)
        return customer

    @staticmethod
    def count_sales_by_customer(db: Session, customer_id: UUID) -> int:
        return int(
            db.query(func.count(Sale.id))
            .filter(Sale.customer_id == customer_id)
            .scalar()
            or 0
        )

    @staticmethod
    def create_sale(db: Session, sale: Sale) -> Sale:
        db.add(sale)
        db.flush()
        db.refresh(sale)
        return sale

    @staticmethod
    def get_sale_by_id(db: Session, sale_id: UUID, store_id: UUID) -> Sale | None:
        return (
            db.query(Sale)
            .options(
                selectinload(Sale.product),
                selectinload(Sale.variant),
                selectinload(Sale.customer),
            )
            .filter(Sale.id == sale_id, Sale.store_id == store_id)
            .first()
        )

    @staticmethod
    def get_order_by_id(db: Session, order_id: UUID, store_id: UUID) -> Order | None:
        return (
            db.query(Order)
            .options(
                selectinload(Order.sale).selectinload(Sale.product),
                selectinload(Order.sale).selectinload(Sale.variant),
                selectinload(Order.sale).selectinload(Sale.customer),
            )
            .filter(Order.id == order_id, Order.store_id == store_id)
            .first()
        )

    @staticmethod
    def list_sales_for_export(
        db: Session,
        store_id: UUID,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        customer_id: UUID | None = None,
    ) -> list[Sale]:
        return SalesRepository.list_sales(
            db,
            store_id=store_id,
            start_date=start_date,
            end_date=end_date,
            customer_id=customer_id,
            page=1,
            limit=100000,
        )

    @staticmethod
    def list_sales(
        db: Session,
        store_id: UUID,
        page: int,
        limit: int,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        customer_id: UUID | None = None,
    ) -> list[Sale]:
        offset = (page - 1) * limit
        query = (
            db.query(Sale)
            .options(
                selectinload(Sale.product),
                selectinload(Sale.variant),
                selectinload(Sale.customer),
            )
            .order_by(Sale.date_time.desc(), Sale.created_at.desc())
            .filter(Sale.store_id == store_id)
        )

        if start_date is not None:
            query = query.filter(Sale.date_time >= start_date)
        if end_date is not None:
            query = query.filter(Sale.date_time <= end_date)
        if customer_id is not None:
            query = query.filter(Sale.customer_id == customer_id)

        return query.offset(offset).limit(limit).all()

    @staticmethod
    def count_sales(
        db: Session,
        store_id: UUID,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        customer_id: UUID | None = None,
    ) -> int:
        query = db.query(func.count(Sale.id)).filter(Sale.store_id == store_id)
        if start_date is not None:
            query = query.filter(Sale.date_time >= start_date)
        if end_date is not None:
            query = query.filter(Sale.date_time <= end_date)
        if customer_id is not None:
            query = query.filter(Sale.customer_id == customer_id)
        return int(query.scalar() or 0)

    @staticmethod
    def get_low_stock_variants(
        db: Session,
        threshold: int,
        store_id: UUID,
        limit: int = 15,
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
    def get_out_of_stock_variants(db: Session, store_id: UUID, limit: int = 15) -> list[tuple[ProductVariant, Product]]:
        return (
            db.query(ProductVariant, Product)
            .join(Product, Product.id == ProductVariant.product_id)
            .filter(ProductVariant.stock_quantity <= 0, ProductVariant.store_id == store_id)
            .order_by(Product.updated_at.desc())
            .limit(limit)
            .all()
        )
