"""Drop dead customers table

The ``customers`` table (backing the ``Customer`` SQLAlchemy model,
``urjaa_core/models/customer.py``) is orphaned: grepped the whole codebase,
it's referenced exactly once outside its own file (``models/__init__.py``'s
model registry — plain metadata boilerplate, no query/insert/read anywhere).
Every admin "customer" function (``create_customer``/``update_customer``/
``list_customers``/``archive_customer`` in ``sales_service.py``) already
operates on ``User``, not ``Customer`` — this is the tail end of the
``sales.customer_id`` migration (0007), which moved the live FK to
``users`` and intentionally left the old table in place as a separate,
more deliberate decision. That decision is made now: nothing reads this
table, so it's dropped.

Confirmed empty via ``SELECT count(*) FROM customers`` immediately before
writing this migration (0 rows) — no data to lose.

Revision ID: 0008_drop_customers_table
Revises: 0007_fix_sales_customer_id_type
Create Date: 2026-09-22
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

# revision identifiers, used by Alembic.
revision = "0008_drop_customers_table"
down_revision = "0007_fix_sales_customer_id_type"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Indexes, the PK constraint, and the owned customers_id_seq are all
    # dropped automatically by Postgres along with the table.
    op.drop_table("customers")


def downgrade() -> None:
    op.create_table(
        "customers",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("phone", sa.String(20), nullable=True),
        sa.Column("email", sa.String(150), nullable=True),
        sa.Column("address", sa.Text, nullable=True),
        sa.Column("feedback", sa.Text, nullable=True),
        sa.Column("is_deleted", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("created_at", sa.TIMESTAMP, server_default=sa.func.now()),
        sa.Column("updated_at", sa.TIMESTAMP, server_default=sa.func.now()),
        sa.Column("store_id", UUID(as_uuid=True), sa.ForeignKey("stores.id"), nullable=False),
    )
    op.create_index("idx_customers_email", "customers", ["email"])
    op.create_index("idx_customers_is_deleted", "customers", ["is_deleted"])
    op.create_index("idx_customers_phone", "customers", ["phone"])
    op.create_index("idx_customers_store_id", "customers", ["store_id"])
