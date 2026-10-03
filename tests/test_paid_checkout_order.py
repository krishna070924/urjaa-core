"""Checkout order paid -> stock taken, website sales per line, bag cleared;
admin cancel restores only what was taken. Rolled-back dev-DB transaction.

Run: .venv/bin/python tests/test_paid_checkout_order.py
"""
import os

os.environ.setdefault("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/urjaa")

from sqlalchemy import text
from sqlalchemy.orm import Session

from urjaa_core.core.database import engine
from urjaa_core.models.order import Order
from urjaa_core.services.order_service import OrderService


def main() -> None:
    conn = engine.connect()
    outer = conn.begin()
    db = Session(bind=conn, join_transaction_mode="create_savepoint")
    q = lambda sql, **kw: db.execute(text(sql), kw)
    stock = lambda v: q("SELECT stock_quantity FROM product_variants WHERE id = :v", v=v).scalar()
    try:
        order = db.query(Order).filter(Order.user_id.isnot(None)).first()
        item = q("SELECT id, variant_id, product_id FROM order_items WHERE order_id = :o LIMIT 1", o=order.id).one()
        q("DELETE FROM order_items WHERE order_id = :o AND id <> :i", o=order.id, i=item.id)
        q("UPDATE order_items SET quantity = 1, line_total = 1000 WHERE id = :i", i=item.id)
        q("DELETE FROM sales WHERE order_id = :o", o=order.id)
        q("UPDATE orders SET status = 'PENDING' WHERE id = :o", o=order.id)
        cart_id = q("SELECT id FROM carts WHERE user_id = :u", u=order.user_id).scalar() or q(
            "INSERT INTO carts (id, user_id) VALUES (gen_random_uuid(), :u) RETURNING id", u=order.user_id).scalar()
        q("DELETE FROM cart_items WHERE cart_id = :c", c=cart_id)
        q("INSERT INTO cart_items (id, cart_id, product_id, variant_id, quantity) VALUES (gen_random_uuid(), :c, :p, :v, 1)",
          c=cart_id, p=item.product_id, v=item.variant_id)
        q("DELETE FROM variant_physical_units WHERE variant_id = :v", v=item.variant_id)
        q("UPDATE product_variants SET stock_quantity = 3 WHERE id = :v", v=item.variant_id)

        # Unpaid checkout order cancelled: nothing was taken, nothing restored.
        OrderService.update_admin_order_status(db, order_id=order.id, status="CANCELLED")
        assert stock(item.variant_id) == 3
        q("UPDATE orders SET status = 'PENDING' WHERE id = :o", o=order.id)
        db.expire_all()

        # Sold out between order and payment -> 409 before opening payment.
        from fastapi import HTTPException
        q("UPDATE product_variants SET stock_quantity = 0 WHERE id = :v", v=item.variant_id)
        try:
            OrderService.assert_checkout_order_in_stock(db, order)
            raise AssertionError("allowed payment for sold-out item")
        except HTTPException as exc:
            assert exc.status_code == 409
        q("UPDATE product_variants SET stock_quantity = 3 WHERE id = :v", v=item.variant_id)
        OrderService.assert_checkout_order_in_stock(db, order)

        # Paid (count-only): stock -1, one website sale, bag emptied.
        OrderService.record_paid_checkout_order(db, order)
        assert stock(item.variant_id) == 2
        sale = q("SELECT source, status, final_price FROM sales WHERE order_id = :o", o=order.id).one()
        assert (sale.source, sale.status, float(sale.final_price)) == ("website", "COMPLETED", 1000.0), sale
        assert q("SELECT count(*) FROM cart_items WHERE cart_id = :c", c=cart_id).scalar() == 0

        # Admin moves it on: sale follows; cancel restores the taken stock.
        q("UPDATE orders SET status = 'CONFIRMED' WHERE id = :o", o=order.id)
        db.expire_all()
        OrderService.update_admin_order_status(db, order_id=order.id, status="PROCESSING")
        assert q("SELECT status FROM sales WHERE order_id = :o", o=order.id).scalar() == "PROCESSING"
        OrderService.update_admin_order_status(db, order_id=order.id, status="CANCELLED")
        assert stock(item.variant_id) == 3

        # Pieces-tracked variant: a piece is reserved for the line, stock follows.
        q("DELETE FROM sales WHERE order_id = :o", o=order.id)
        ins = "INSERT INTO variant_physical_units (variant_id, status_id) SELECT :v, id FROM unit_statuses WHERE code = 'in_stock'"
        q(ins, v=item.variant_id); q(ins, v=item.variant_id)
        OrderService.record_paid_checkout_order(db, order)
        assert stock(item.variant_id) == 1
        assert q("SELECT count(*) FROM variant_physical_units u JOIN unit_statuses s ON s.id = u.status_id "
                 "WHERE u.order_item_id = :i AND s.code = 'reserved'", i=item.id).scalar() == 1
        print("paid checkout order: stock, pieces, sales, bag, cancel  OK")
    finally:
        db.close()
        outer.rollback()
        conn.close()


if __name__ == "__main__":
    main()
