"""POS: GST on store bills + alterations left at the counter

Owner decisions (POS rebuild):
- Store prices exclude GST (same as the website). The bill adds 3% GST
  (CGST 1.5% + SGST 1.5%, HSN 7113) on the post-discount amount. The tax is
  frozen on the order at sale time -- `orders.tax_amount` -- never
  recomputed. `orders.total_amount` stays the ex-GST net (what Insights
  sums); amount collected = total_amount + tax_amount. Existing rows: 0.
- A piece sold but left for resizing auto-creates a Custom Order linked
  back to the bill: `custom_orders.sale_order_id`. The promise printed on
  the bill ("Alteration: resize to 14, ready by ...") is frozen on the sale
  line itself (`sales.alteration_note`) so a later board edit doesn't
  rewrite an issued invoice.

Additive only. GRANT not needed: table-level grants already cover new columns.

Revision ID: 0032_pos_gst_alterations
Revises: 0031_custom_orders
Create Date: 2026-10-09
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "0032_pos_gst_alterations"
down_revision = "0031_custom_orders"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("tax_amount", sa.Numeric(12, 2), nullable=False, server_default="0"))
    op.add_column("sales", sa.Column("alteration_note", sa.Text(), nullable=True))
    op.add_column(
        "custom_orders",
        sa.Column(
            "sale_order_id",
            UUID(as_uuid=True),
            sa.ForeignKey("orders.id", ondelete="SET NULL", name="fk_custom_orders_sale_order_id"),
            nullable=True,
        ),
    )
    op.create_index("ix_custom_orders_sale_order_id", "custom_orders", ["sale_order_id"])


def downgrade() -> None:
    op.drop_index("ix_custom_orders_sale_order_id", table_name="custom_orders")
    op.drop_column("custom_orders", "sale_order_id")
    op.drop_column("sales", "alteration_note")
    op.drop_column("orders", "tax_amount")
