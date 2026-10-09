"""Old-jewellery exchange (buy-back) on POS bills

One row per old piece the customer hands in against a bill. Not inventory:
a record of what was taken, at what weight/purity/rate, and its value. The
bill's GST stays on the new items; the old value is taken off after GST.

Revision ID: 0035_old_gold_exchange
Revises: 0034_store_returns_credit
Create Date: 2026-10-10
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "0035_old_gold_exchange"
down_revision = "0034_store_returns_credit"
branch_labels = None
depends_on = None

ROLES = "urjaa_storefront, urjaa_admin_svc"


def upgrade() -> None:
    op.create_table(
        "old_gold_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("order_id", UUID(as_uuid=True), sa.ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("description", sa.String(200), nullable=False),
        sa.Column("base_metal_id", sa.Integer(), sa.ForeignKey("base_metals.id"), nullable=False),
        sa.Column("purity", sa.Numeric(6, 3), nullable=False),  # percent, e.g. 91.600 for 22K
        sa.Column("gross_weight", sa.Numeric(10, 3), nullable=False),
        sa.Column("stone_weight", sa.Numeric(10, 3), nullable=False, server_default="0"),
        sa.Column("net_weight", sa.Numeric(10, 3), nullable=False),
        sa.Column("rate_per_gram", sa.Numeric(12, 2), nullable=False),
        sa.Column("deduction_amount", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("deduction_reason", sa.Text(), nullable=True),
        sa.Column("value", sa.Numeric(12, 2), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("net_weight > 0 AND value >= 0 AND rate_per_gram > 0", name="ck_old_gold_items_values"),
    )
    conn = op.get_bind()
    conn.execute(sa.text(f"GRANT SELECT, INSERT, UPDATE, DELETE ON public.old_gold_items TO {ROLES}"))
    conn.execute(sa.text(f"GRANT USAGE, SELECT ON SEQUENCE public.old_gold_items_id_seq TO {ROLES}"))


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text(f"REVOKE ALL ON SEQUENCE public.old_gold_items_id_seq FROM {ROLES}"))
    conn.execute(sa.text(f"REVOKE ALL ON public.old_gold_items FROM {ROLES}"))
    op.drop_table("old_gold_items")
