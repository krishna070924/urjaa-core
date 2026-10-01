from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from urjaa_core.models.discount import Discount
from urjaa_core.models.discount_product import DiscountProduct
from urjaa_core.models.product import Product
from urjaa_core.schemas.admin.discounts import DiscountCreateRequest, DiscountUpdateRequest


def _status(discount: Discount, now: datetime) -> str:
    """D28/D29 computed status -- not stored, derived from is_active + window."""
    if not discount.is_active:
        return "inactive"
    if discount.starts_at is not None and discount.starts_at > now:
        return "scheduled"
    if discount.ends_at is not None and discount.ends_at <= now:
        return "expired"
    return "active"


class AdminDiscountService:
    @staticmethod
    def _to_dict(discount: Discount, *, product_count: int | None = None, product_ids: list[UUID] | None = None) -> dict:
        return {
            "id": discount.id,
            "store_id": discount.store_id,
            "name": discount.name,
            "percent": discount.percent,
            "starts_at": discount.starts_at,
            "ends_at": discount.ends_at,
            "is_active": discount.is_active,
            "applies_to_all": discount.applies_to_all,
            "status": _status(discount, datetime.now(timezone.utc)),
            "product_count": product_count,
            "product_ids": product_ids,
            "created_at": discount.created_at,
            "updated_at": discount.updated_at,
        }

    @staticmethod
    def list_discounts(db: Session, *, store_id: UUID) -> list[dict]:
        discounts = (
            db.query(Discount)
            .filter(Discount.store_id == store_id)
            .order_by(Discount.created_at.desc())
            .all()
        )
        if not discounts:
            return []

        # One grouped query for every discount's product count -- avoids N+1.
        rows = (
            db.query(DiscountProduct.discount_id, func.count(DiscountProduct.product_id))
            .filter(DiscountProduct.discount_id.in_([d.id for d in discounts]))
            .group_by(DiscountProduct.discount_id)
            .all()
        )
        counts = dict(rows)

        return [
            # None (not 0) for applies_to_all -- it targets every product in the
            # store, not a specific, countable set.
            AdminDiscountService._to_dict(d, product_count=None if d.applies_to_all else counts.get(d.id, 0))
            for d in discounts
        ]

    @staticmethod
    def get_discount(db: Session, *, store_id: UUID, discount_id: int) -> Discount:
        discount = (
            db.query(Discount)
            .filter(Discount.id == discount_id, Discount.store_id == store_id)
            .first()
        )
        if discount is None:
            raise HTTPException(status_code=404, detail="Discount not found")
        return discount

    @staticmethod
    def get_discount_response(db: Session, *, store_id: UUID, discount_id: int) -> dict:
        discount = AdminDiscountService.get_discount(db, store_id=store_id, discount_id=discount_id)
        if discount.applies_to_all:
            return AdminDiscountService._to_dict(discount, product_count=None, product_ids=[])
        product_ids = [p.id for p in discount.products]
        return AdminDiscountService._to_dict(discount, product_count=len(product_ids), product_ids=product_ids)

    @staticmethod
    def _validate_product_ids(db: Session, store_id: UUID, product_ids: list[UUID]) -> None:
        if not product_ids:
            return
        found_ids = {
            row[0]
            for row in db.query(Product.id).filter(Product.id.in_(product_ids), Product.store_id == store_id).all()
        }
        missing = set(product_ids) - found_ids
        if missing:
            raise HTTPException(
                status_code=422, detail=f"Unknown product ids for this store: {sorted(str(m) for m in missing)}"
            )

    @staticmethod
    def _replace_products(db: Session, discount: Discount, product_ids: list[UUID]) -> None:
        db.query(DiscountProduct).filter(DiscountProduct.discount_id == discount.id).delete()
        for product_id in dict.fromkeys(product_ids):  # de-dupe, preserve order
            db.add(DiscountProduct(discount_id=discount.id, product_id=product_id))

    @staticmethod
    def create_discount(db: Session, *, store_id: UUID, payload: DiscountCreateRequest) -> dict:
        if not payload.applies_to_all and not payload.product_ids:
            raise HTTPException(status_code=422, detail="Provide product_ids or set applies_to_all")

        AdminDiscountService._validate_product_ids(db, store_id, payload.product_ids)

        discount = Discount(
            store_id=store_id,
            name=payload.name.strip(),
            percent=payload.percent,
            starts_at=payload.starts_at,
            ends_at=payload.ends_at,
            is_active=payload.is_active,
            applies_to_all=payload.applies_to_all,
        )
        db.add(discount)
        db.flush()

        if not payload.applies_to_all:
            AdminDiscountService._replace_products(db, discount, payload.product_ids)

        db.flush()
        db.refresh(discount)
        return AdminDiscountService.get_discount_response(db, store_id=store_id, discount_id=discount.id)

    @staticmethod
    def update_discount(db: Session, *, store_id: UUID, discount_id: int, payload: DiscountUpdateRequest) -> dict:
        discount = AdminDiscountService.get_discount(db, store_id=store_id, discount_id=discount_id)

        if payload.name is not None:
            name = payload.name.strip()
            if not name:
                raise HTTPException(status_code=422, detail="name cannot be blank")
            discount.name = name
        for field in ("percent", "starts_at", "ends_at", "is_active", "applies_to_all"):
            value = getattr(payload, field)
            if value is not None:
                setattr(discount, field, value)

        if payload.product_ids is not None:
            AdminDiscountService._validate_product_ids(db, store_id, payload.product_ids)
            AdminDiscountService._replace_products(db, discount, payload.product_ids)

        if not discount.applies_to_all:
            remaining = db.query(DiscountProduct).filter(DiscountProduct.discount_id == discount.id).count()
            if remaining == 0:
                raise HTTPException(status_code=422, detail="Provide product_ids or set applies_to_all")

        db.flush()
        db.refresh(discount)
        return AdminDiscountService.get_discount_response(db, store_id=store_id, discount_id=discount.id)

    @staticmethod
    def delete_discount(db: Session, *, store_id: UUID, discount_id: int) -> None:
        discount = AdminDiscountService.get_discount(db, store_id=store_id, discount_id=discount_id)
        db.delete(discount)
        db.flush()

    @staticmethod
    def list_discounts_for_product(db: Session, *, store_id: UUID, product_id: UUID) -> list[dict]:
        """Discounts (any status) that target this product -- store-wide ones
        plus ones that explicitly list it. Used on the admin product detail
        page; not window/is_active filtered, unlike pricing's best-discount
        resolution."""
        discounts = (
            db.query(Discount)
            .outerjoin(DiscountProduct, DiscountProduct.discount_id == Discount.id)
            .filter(
                Discount.store_id == store_id,
                or_(Discount.applies_to_all.is_(True), DiscountProduct.product_id == product_id),
            )
            .distinct()
            .all()
        )
        return [AdminDiscountService._to_dict(d) for d in discounts]
