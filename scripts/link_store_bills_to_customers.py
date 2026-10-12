"""One-off, idempotent: link existing store (POS) bills to their customer.

The POS always stored the customer on the bill's sales rows (sales.customer_id)
but left orders.user_id empty, so customer analytics never saw store buyers.
This sets orders.user_id + the name/phone/email snapshot from that customer,
exactly as new bills now do (SalesService.link_order_to_customer). Walk-in
bills (no customer on any line) stay unlinked. Customers are never created or
merged; numbers shared by more than one customer are only reported.

Run: DATABASE_URL=postgresql://... python scripts/link_store_bills_to_customers.py
"""
from sqlalchemy import func

from urjaa_core.core.database import SessionLocal
import urjaa_core.models  # noqa: F401  (register all mappers)
from urjaa_core.models.order import Order
from urjaa_core.models.sale import Sale
from urjaa_core.models.user import User
from urjaa_core.repositories.admin.sales_repository import CUSTOMER_SOURCES
from urjaa_core.services.admin.sales_service import USER_PHONE_KEY, SalesService


def main() -> None:
    db = SessionLocal()
    try:
        unlinked = db.query(Order).filter(Order.source == "store", Order.user_id.is_(None)).all()
        linked = walk_in = mixed = 0
        for order in unlinked:
            customer_ids = {sale.customer_id for sale in order.sale if sale.customer_id}
            if len(customer_ids) > 1:
                mixed += 1  # never seen; don't guess
                continue
            if not customer_ids:
                walk_in += 1
                continue
            SalesService.link_order_to_customer(order, db.get(User, customer_ids.pop()))
            linked += 1
        db.commit()

        shared = (
            db.query(USER_PHONE_KEY, func.count(User.id))
            .filter(User.source.in_(CUSTOMER_SOURCES), User.is_active.is_(True), func.length(USER_PHONE_KEY) == 10)
            .group_by(USER_PHONE_KEY)
            .having(func.count(User.id) > 1)
            .all()
        )
        print(f"store bills without a customer link: {len(unlinked)}")
        print(f"  linked now: {linked}   walk-in (no customer): {walk_in}   lines with different customers: {mixed}")
        print(f"mobile numbers saved on more than one customer (not merged): {len(shared)}")
        for key, count in shared:
            print(f"  ...{key[-4:]}: {count} customers")
    finally:
        db.close()


if __name__ == "__main__":
    main()
