"""Fix sales.customer_id type/FK drift: integer/customers -> uuid/users

The ``Sale`` SQLAlchemy model (``urjaa_core/models/sale.py``) declares
``customer_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), ...)``
with ``relationship("User", back_populates="sales")`` — and every piece of
application code that actually creates/reads a sale's customer already
agrees with that: ``SalesService`` (``urjaa_core/services/admin/sales_service.py``)
creates a new "customer" as ``User(...)`` (not the standalone ``Customer``
model), looks customers up via ``db.query(User)...``, and even its own PDF
receipt code reads ``sale.customer.full_name`` expecting a ``User``-shaped
object. The admin analytics endpoints (``GET /admin/analytics/customers/at-risk``
and ``GET /admin/analytics/customers/store-behavior``) join ``Sale.customer_id``
against ``User.id`` on that same assumption.

But the live database column was never migrated to match: ``sales.customer_id``
is still ``integer``, foreign-keyed to the original ``customers`` table (a
standalone walk-in-customer record, unrelated to ``users``, still present in
the ``0001`` baseline). Every query joining ``Sale.customer_id`` to ``User.id``
therefore fails outright: ``psycopg2.errors.UndefinedFunction: operator does
not exist: integer = uuid``.

Confirmed via grep that nothing in either backend still reads/writes the
``Customer`` model or the ``customers`` table for any live sales flow — it's
orphaned, superseded by this already-completed User-based design. Left in
place here rather than dropped: dropping a whole table is a separate,
more deliberate decision than fixing this type mismatch, and out of scope
for this fix.

Both ``sales`` and ``customers`` are confirmed empty in every environment
this has been checked against (fresh baseline, no seed data), so this is a
pure type/constraint change with no data to migrate or lose — verified via
``SELECT count(*) FROM sales`` / ``customers`` returning 0 immediately before
writing this migration.

Revision ID: 0007_fix_sales_customer_id_type
Revises: 0006_grant_sequence_usage
Create Date: 2026-09-19
"""

from sqlalchemy import text

from alembic import op

# revision identifiers, used by Alembic.
revision = "0007_fix_sales_customer_id_type"
down_revision = "0006_grant_sequence_usage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    bind.execute(text("ALTER TABLE public.sales DROP CONSTRAINT IF EXISTS sales_customer_id_fkey"))
    # USING NULL is safe (not a data-loss risk) only because the table is
    # confirmed empty — an integer customer_id has no meaningful UUID
    # equivalent to cast to, so this intentionally does not attempt one.
    bind.execute(text("ALTER TABLE public.sales ALTER COLUMN customer_id TYPE uuid USING NULL"))
    bind.execute(
        text(
            "ALTER TABLE public.sales "
            "ADD CONSTRAINT sales_customer_id_fkey "
            "FOREIGN KEY (customer_id) REFERENCES public.users(id)"
        )
    )


def downgrade() -> None:
    bind = op.get_bind()

    bind.execute(text("ALTER TABLE public.sales DROP CONSTRAINT IF EXISTS sales_customer_id_fkey"))
    bind.execute(text("ALTER TABLE public.sales ALTER COLUMN customer_id TYPE integer USING NULL"))
    bind.execute(
        text(
            "ALTER TABLE public.sales "
            "ADD CONSTRAINT sales_customer_id_fkey "
            "FOREIGN KEY (customer_id) REFERENCES public.customers(id)"
        )
    )
