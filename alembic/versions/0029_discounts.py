"""Discounts: percentage off, optional window, best-wins (D27-D29, K-03)

Task: docs/frontend-transition-to-2.0/slice-K-admin-v2/K-03-discounts-backend.md

`discounts` + `discount_products` (many-to-many; empty when applies_to_all).
A discount reduces the WHOLE computed price (D27) by a flat percentage
(D28); overlap resolution (best percent wins, D29) is pricing-service logic,
not schema. `order_items` gains two nullable audit columns so an order line
remembers what it was discounted from.

GRANT ships in the same migration (finding C22).

Revision ID: 0029_discounts
Revises: 0028_drop_eav_tables
Create Date: 2026-10-01
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "0029_discounts"
down_revision = "0028_drop_eav_tables"
branch_labels = None
depends_on = None

ROLES = "urjaa_storefront, urjaa_admin_svc"


def upgrade() -> None:
    op.create_table(
        "discounts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("store_id", UUID(as_uuid=True), sa.ForeignKey("stores.id"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("percent", sa.Numeric(5, 2), nullable=False),
        sa.Column("starts_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("ends_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("applies_to_all", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.TIMESTAMP(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("percent > 0 AND percent <= 90", name="ck_discounts_percent_range"),
        sa.CheckConstraint(
            "ends_at IS NULL OR starts_at IS NULL OR ends_at > starts_at",
            name="ck_discounts_window_order",
        ),
    )
    op.create_index("ix_discounts_store_id", "discounts", ["store_id"])

    op.create_table(
        "discount_products",
        sa.Column("discount_id", sa.Integer(), sa.ForeignKey("discounts.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("product_id", UUID(as_uuid=True), sa.ForeignKey("products.id", ondelete="CASCADE"), primary_key=True),
    )

    op.add_column("order_items", sa.Column("original_unit_price", sa.Numeric(12, 2), nullable=True))
    op.add_column("order_items", sa.Column("discount_percent", sa.Numeric(5, 2), nullable=True))

    conn = op.get_bind()
    for table in ("discounts", "discount_products"):
        conn.execute(sa.text(f"GRANT SELECT, INSERT, UPDATE, DELETE ON public.{table} TO {ROLES}"))
    conn.execute(sa.text(f"GRANT USAGE, SELECT ON SEQUENCE public.discounts_id_seq TO {ROLES}"))


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("REVOKE ALL ON SEQUENCE public.discounts_id_seq FROM urjaa_storefront, urjaa_admin_svc"))
    for table in ("discounts", "discount_products"):
        conn.execute(sa.text(f"REVOKE ALL ON public.{table} FROM {ROLES}"))

    op.drop_column("order_items", "discount_percent")
    op.drop_column("order_items", "original_unit_price")

    op.drop_table("discount_products")
    op.drop_index("ix_discounts_store_id", table_name="discounts")
    op.drop_table("discounts")
