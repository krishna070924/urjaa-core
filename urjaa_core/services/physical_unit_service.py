"""Consume and release physical pieces of a variant (D22, H-03).

A variant with unit rows is "tracked": which piece leaves matters, because
each has its own HUID. Its stock_quantity follows the units via DB triggers
(migration 0026), so callers keep their existing counter logic untouched and
call these alongside it. Untracked variants: every function is a no-op.

Online order  -> take_units(order_item=...)  oldest in-stock piece is reserved
Dispatched    -> mark_sold                    reserved -> sold
Cancelled     -> release_units                reserved -> in_stock
In-store sale -> take_units(sale=..., unit_ids=...)  the scanned pieces are sold
"""

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from urjaa_core.models.product_variant import ProductVariant
from urjaa_core.models.variant_physical_unit import UnitStatus, VariantPhysicalUnit


def _status_id(db: Session, code: str) -> int:
    return db.query(UnitStatus.id).filter(UnitStatus.code == code).scalar()


def is_tracked(db: Session, variant_id) -> bool:
    return db.query(VariantPhysicalUnit.id).filter(VariantPhysicalUnit.variant_id == variant_id).first() is not None


def take_units(db: Session, variant_id, quantity: int, *, unit_ids=None, order_item=None, sale=None) -> list[VariantPhysicalUnit]:
    if not is_tracked(db, variant_id):
        if unit_ids:
            raise HTTPException(status_code=422, detail="This item is not tracked piece by piece; do not select pieces")
        return []

    in_stock = db.query(VariantPhysicalUnit).filter(
        VariantPhysicalUnit.variant_id == variant_id,
        VariantPhysicalUnit.status_id == _status_id(db, "in_stock"),
    )
    if order_item is not None:
        units = in_stock.order_by(VariantPhysicalUnit.id).limit(quantity).with_for_update().all()
        new_status = "reserved"
    else:
        if not unit_ids:
            raise HTTPException(status_code=422, detail="Select which piece is being sold: this item is tracked by HUID")
        if len(set(unit_ids)) != quantity:
            raise HTTPException(status_code=422, detail=f"Select exactly {quantity} different piece(s)")
        units = in_stock.filter(VariantPhysicalUnit.id.in_(unit_ids)).with_for_update().all()
        new_status = "sold"

    if len(units) != quantity:
        raise HTTPException(status_code=409, detail="Not enough of the selected pieces are in stock")

    status_id = _status_id(db, new_status)
    for unit in units:
        unit.status_id = status_id
        unit.order_item_id = getattr(order_item, "id", None)
        unit.sale_id = getattr(sale, "id", None)
    db.flush()
    return units


def _move_order_units(db: Session, order_item_ids, from_code: str, to_code: str, keep_link: bool) -> None:
    if not order_item_ids:
        return
    values = {VariantPhysicalUnit.status_id: _status_id(db, to_code)}
    if not keep_link:
        values[VariantPhysicalUnit.order_item_id] = None
    db.query(VariantPhysicalUnit).filter(
        VariantPhysicalUnit.order_item_id.in_(order_item_ids),
        VariantPhysicalUnit.status_id == _status_id(db, from_code),
    ).update(values, synchronize_session=False)


def release_units(db: Session, order_item_ids) -> None:
    _move_order_units(db, order_item_ids, "reserved", "in_stock", keep_link=False)


def mark_sold(db: Session, order_item_ids) -> None:
    _move_order_units(db, order_item_ids, "reserved", "sold", keep_link=True)


def swap_reserved_unit(db: Session, variant_id, order_item_id: int, old_unit_id: int, new_unit_id: int) -> VariantPhysicalUnit:
    """Staff picked a different piece off the shelf at dispatch."""
    reserved, in_stock = _status_id(db, "reserved"), _status_id(db, "in_stock")
    old = db.query(VariantPhysicalUnit).filter(
        VariantPhysicalUnit.id == old_unit_id,
        VariantPhysicalUnit.variant_id == variant_id,
        VariantPhysicalUnit.order_item_id == order_item_id,
        VariantPhysicalUnit.status_id == reserved,
    ).with_for_update().first()
    if old is None:
        raise HTTPException(status_code=404, detail="That piece is not reserved for this order line")
    new = db.query(VariantPhysicalUnit).filter(
        VariantPhysicalUnit.id == new_unit_id,
        VariantPhysicalUnit.variant_id == variant_id,
        VariantPhysicalUnit.status_id == in_stock,
    ).with_for_update().first()
    if new is None:
        raise HTTPException(status_code=409, detail="The replacement piece must be an in-stock piece of the same item")
    old.status_id, old.order_item_id = in_stock, None
    new.status_id, new.order_item_id = reserved, order_item_id
    db.flush()
    return new


# --- Admin: recording pieces -------------------------------------------------

def _variant_or_404(db: Session, store_id, variant_id):
    variant = db.query(ProductVariant).filter(ProductVariant.id == variant_id, ProductVariant.store_id == store_id).first()
    if variant is None:
        raise HTTPException(status_code=404, detail="Variant not found")
    return variant


def list_units(db: Session, store_id, variant_id) -> list[VariantPhysicalUnit]:
    _variant_or_404(db, store_id, variant_id)
    return db.query(VariantPhysicalUnit).filter(VariantPhysicalUnit.variant_id == variant_id).order_by(VariantPhysicalUnit.id).all()


def add_units(db: Session, store_id, variant_id, pieces: list[dict]) -> list[VariantPhysicalUnit]:
    variant = _variant_or_404(db, store_id, variant_id)
    counted = int(variant.stock_quantity or 0)
    # Switching a counted variant to per-piece tracking replaces the count with
    # the number of pieces, so all of them must be entered — otherwise stock
    # silently drops from e.g. 5 to 1.
    if not is_tracked(db, variant_id) and counted > len(pieces):
        raise HTTPException(
            status_code=422,
            detail=f"This item has {counted} in stock by count. Enter all {counted} pieces to start tracking it piece by piece.",
        )
    in_stock = _status_id(db, "in_stock")
    units = [VariantPhysicalUnit(variant_id=variant_id, status_id=in_stock, **piece) for piece in pieces]
    db.add_all(units)
    _flush_or_duplicate_huid(db)
    return units


def update_unit(db: Session, store_id, variant_id, unit_id: int, changes: dict) -> VariantPhysicalUnit:
    _variant_or_404(db, store_id, variant_id)
    unit = db.query(VariantPhysicalUnit).filter(VariantPhysicalUnit.id == unit_id, VariantPhysicalUnit.variant_id == variant_id).first()
    if unit is None:
        raise HTTPException(status_code=404, detail="Piece not found")
    for field, value in changes.items():
        setattr(unit, field, value)
    _flush_or_duplicate_huid(db)
    return unit


def delete_unit(db: Session, store_id, variant_id, unit_id: int) -> None:
    """For pieces entered by mistake. Sold/reserved pieces are history and stay."""
    _variant_or_404(db, store_id, variant_id)
    deleted = db.query(VariantPhysicalUnit).filter(
        VariantPhysicalUnit.id == unit_id,
        VariantPhysicalUnit.variant_id == variant_id,
        VariantPhysicalUnit.status_id == _status_id(db, "in_stock"),
    ).delete(synchronize_session=False)
    if not deleted:
        raise HTTPException(status_code=409, detail="Only an in-stock piece can be removed")


def _flush_or_duplicate_huid(db: Session) -> None:
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        if "uq_variant_physical_units_huid" in str(exc):
            raise HTTPException(status_code=409, detail="That HUID is already recorded on another piece") from exc
        raise
