"""H-03 self-check against the live dev database, as the admin app role.
One transaction, rolled back — no fixtures left behind.

Run: .venv/bin/python tests/test_physical_units.py
"""
import os
import uuid
from decimal import Decimal

os.environ.setdefault("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/urjaa")

from fastapi import HTTPException
from sqlalchemy import text

from urjaa_core.core.database import SessionLocal
from urjaa_core.models import Order, OrderItem, Product, ProductVariant, Sale, Store
from urjaa_core.models.variant_physical_unit import UnitStatus, VariantPhysicalUnit
from urjaa_core.services import physical_unit_service as units


def status_of(db, unit):
    db.refresh(unit)
    return db.get(UnitStatus, unit.status_id).code


def stock(db, variant):
    db.refresh(variant)
    return variant.stock_quantity


def raises(code, fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except HTTPException as exc:
        assert exc.status_code == code, exc.detail
        return
    raise AssertionError(f"expected HTTP {code}")


def main() -> None:
    db = SessionLocal()
    try:
        db.execute(text("SET ROLE urjaa_admin_svc"))
        store = db.query(Store).first()
        product = Product(store_id=store.id, name="Unit check", slug=f"units-{uuid.uuid4().hex[:8]}")
        db.add(product)
        db.flush()
        variant = ProductVariant(store_id=store.id, product_id=product.id, stock_quantity=4, sku_code=f"H03-{uuid.uuid4().hex[:8]}")
        plain = ProductVariant(store_id=store.id, product_id=product.id, stock_quantity=4, sku_code=f"H03-{uuid.uuid4().hex[:8]}")
        db.add_all([variant, plain])
        db.flush()

        # Untracked variant: no-op, counter untouched, picking pieces rejected.
        assert units.take_units(db, plain.id, 1, order_item=None) == []
        raises(422, units.take_units, db, plain.id, 1, unit_ids=[1])
        print("untracked variant               no-op   OK")

        in_stock = db.query(UnitStatus).filter_by(code="in_stock").one().id
        pieces = [VariantPhysicalUnit(variant_id=variant.id, status_id=in_stock, huid_number=h,
                                      weight_grams=Decimal(w)) for h, w in (("H03AA1", "5.10"), ("H03AA2", "5.35"), (None, "5.20"))]
        db.add_all(pieces)
        db.flush()
        assert stock(db, variant) == 3, "stock must follow units, not the old counter"
        variant.stock_quantity = 99
        db.flush()
        assert stock(db, variant) == 3
        print("stock = in_stock units (3), direct write ignored OK")

        order = Order(store_id=store.id, total_amount=Decimal("1"))
        db.add(order)
        db.flush()
        line = OrderItem(order_id=order.id, store_id=store.id, product_id=product.id, variant_id=variant.id,
                         product_name="x", quantity=2, unit_price=Decimal("1"), line_total=Decimal("2"))
        db.add(line)
        db.flush()

        taken = units.take_units(db, variant.id, 2, order_item=line)
        assert [u.id for u in taken] == [pieces[0].id, pieces[1].id], "online must take oldest first"
        assert status_of(db, pieces[0]) == "reserved" and stock(db, variant) == 1
        print("online order reserves oldest 2   OK")

        swapped = units.swap_reserved_unit(db, variant.id, line.id, pieces[1].id, pieces[2].id)
        assert swapped.id == pieces[2].id and status_of(db, pieces[1]) == "in_stock" and stock(db, variant) == 1
        print("dispatch swap                    OK")

        units.release_units(db, [line.id])
        assert stock(db, variant) == 3 and status_of(db, pieces[0]) == "in_stock" and pieces[0].order_item_id is None
        units.take_units(db, variant.id, 2, order_item=line)
        units.mark_sold(db, [line.id])
        assert status_of(db, pieces[0]) == "sold" and pieces[0].order_item_id == line.id and stock(db, variant) == 1
        print("cancel releases, ship sells      OK")

        sale = Sale(store_id=store.id, product_id=product.id, variant_id=variant.id, quantity=1,
                    final_price=Decimal("1"), cost_price=Decimal("0"), profit=Decimal("1"))
        db.add(sale)
        db.flush()
        raises(422, units.take_units, db, variant.id, 1, sale=sale)                 # must scan a piece
        raises(409, units.take_units, db, variant.id, 1, unit_ids=[pieces[0].id], sale=sale)  # already sold
        remaining = next(p for p in pieces if status_of(db, p) == "in_stock")
        units.take_units(db, variant.id, 1, unit_ids=[remaining.id], sale=sale)
        assert status_of(db, remaining) == "sold" and remaining.sale_id == sale.id and stock(db, variant) == 0
        print("in-store sale of scanned piece   OK")

        dup = VariantPhysicalUnit(variant_id=variant.id, status_id=in_stock, huid_number="H03AA1")
        db.add(dup)
        try:
            db.flush()
            raise AssertionError("duplicate HUID accepted")
        except Exception as exc:
            assert "uq_variant_physical_units_huid" in str(exc), exc
        print("duplicate HUID rejected          OK")
        db.rollback()
        db.execute(text("SET ROLE urjaa_admin_svc"))
        product = Product(store_id=store.id, name="Unit admin", slug=f"units-{uuid.uuid4().hex[:8]}")
        db.add(product)
        db.flush()
        counted = ProductVariant(store_id=store.id, product_id=product.id, stock_quantity=2, sku_code=f"H03-{uuid.uuid4().hex[:8]}")
        db.add(counted)
        db.flush()
        raises(422, units.add_units, db, store.id, counted.id, [{"huid_number": "H03BB1"}])
        added = units.add_units(db, store.id, counted.id, [{"huid_number": "H03BB1"}, {}])
        assert stock(db, counted) == 2 and len(units.list_units(db, store.id, counted.id)) == 2
        units.delete_unit(db, store.id, counted.id, added[1].id)
        assert stock(db, counted) == 1
        print("admin add/convert/delete         OK")
    finally:
        db.rollback()
        db.close()


if __name__ == "__main__":
    main()
