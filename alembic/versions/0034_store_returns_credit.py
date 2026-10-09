"""Store returns, credit notes, store credit and payment method on POS bills

- orders.payment_method ('cash'/'upi'/'card'/'split') + payment_details
  (amount per method, reference, and any payout to the customer). Old bills: NULL.
- sales.returned_quantity / returned_amount: how much of a bill line came
  back (ex-GST). The CHECK makes over-return impossible even under a race;
  Insights subtract returned_amount from the line's revenue.
- sale_returns + sale_return_lines: one row per return, credit note number
  from credit_note_sequences (same per-(store, month) UPSERT as invoices).
- store_credit_entries: per-customer ledger, +credit / -debit; balance = sum.
- custom_orders.sale_id: the bill line an alteration belongs to, so a return
  of that line can cancel it.

Additive only. GRANTs as in 0031.

Revision ID: 0034_store_returns_credit
Revises: 0033_staff_role_scope
Create Date: 2026-10-10
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0034_store_returns_credit"
down_revision = "0033_staff_role_scope"
branch_labels = None
depends_on = None

ROLES = "urjaa_storefront, urjaa_admin_svc"
NEW_TABLES = ("sale_returns", "sale_return_lines", "store_credit_entries")


def upgrade() -> None:
    op.add_column("orders", sa.Column("payment_method", sa.String(10), nullable=True))
    op.add_column("orders", sa.Column("payment_details", JSONB(), nullable=True))

    op.add_column("sales", sa.Column("returned_quantity", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("sales", sa.Column("returned_amount", sa.Numeric(12, 2), nullable=False, server_default="0"))
    op.create_check_constraint(
        "ck_sales_returned_quantity", "sales", "returned_quantity >= 0 AND returned_quantity <= quantity"
    )

    op.add_column(
        "custom_orders",
        sa.Column("sale_id", UUID(as_uuid=True), sa.ForeignKey("sales.id", ondelete="SET NULL"), nullable=True),
    )

    op.create_table(
        "credit_note_sequences",
        sa.Column("store_id", UUID(as_uuid=True), sa.ForeignKey("stores.id"), primary_key=True),
        sa.Column("period", sa.String(6), primary_key=True),
        sa.Column("seq", sa.Integer(), nullable=False, server_default="0"),
    )

    op.create_table(
        "sale_returns",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("store_id", UUID(as_uuid=True), sa.ForeignKey("stores.id"), nullable=False),
        sa.Column("order_id", UUID(as_uuid=True), sa.ForeignKey("orders.id"), nullable=False, index=True),
        sa.Column("credit_note_number", sa.String(50), nullable=False, unique=True),
        sa.Column("customer_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("reason", sa.String(20), nullable=False),
        sa.Column("reason_note", sa.Text(), nullable=True),
        sa.Column("taxable_value", sa.Numeric(12, 2), nullable=False),
        sa.Column("cgst", sa.Numeric(12, 2), nullable=False),
        sa.Column("sgst", sa.Numeric(12, 2), nullable=False),
        sa.Column("deduction_amount", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("deduction_reason", sa.Text(), nullable=True),
        sa.Column("refund_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("refund_method", sa.String(15), nullable=False),
        sa.Column("refund_reference", sa.String(100), nullable=True),
        sa.Column("created_by_admin_id", sa.Integer(), sa.ForeignKey("admin_users.id"), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("reason IN ('defect', 'size', 'changed_mind', 'exchange', 'other')", name="ck_sale_returns_reason"),
        sa.CheckConstraint("refund_method IN ('cash', 'upi', 'card', 'store_credit')", name="ck_sale_returns_refund_method"),
        sa.CheckConstraint("refund_amount >= 0 AND deduction_amount >= 0", name="ck_sale_returns_amounts"),
        sa.CheckConstraint("deduction_amount = 0 OR deduction_reason IS NOT NULL", name="ck_sale_returns_deduction_reason"),
    )

    op.create_table(
        "sale_return_lines",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("return_id", sa.Integer(), sa.ForeignKey("sale_returns.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("sale_id", UUID(as_uuid=True), sa.ForeignKey("sales.id"), nullable=False, index=True),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("taxable_value", sa.Numeric(12, 2), nullable=False),
        # HUID / serial of each piece that came back, frozen for the credit note.
        sa.Column("pieces", JSONB(), nullable=False, server_default="[]"),
        sa.CheckConstraint("quantity > 0", name="ck_sale_return_lines_quantity"),
    )

    op.create_table(
        "store_credit_entries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("customer_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("store_id", UUID(as_uuid=True), sa.ForeignKey("stores.id"), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("sale_return_id", sa.Integer(), sa.ForeignKey("sale_returns.id"), nullable=True),
        sa.Column("order_id", UUID(as_uuid=True), sa.ForeignKey("orders.id"), nullable=True, index=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_by_admin_id", sa.Integer(), sa.ForeignKey("admin_users.id"), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("amount <> 0", name="ck_store_credit_entries_amount"),
    )

    conn = op.get_bind()
    conn.execute(sa.text(f"GRANT SELECT, INSERT, UPDATE, DELETE ON public.credit_note_sequences TO {ROLES}"))
    for table in NEW_TABLES:
        conn.execute(sa.text(f"GRANT SELECT, INSERT, UPDATE, DELETE ON public.{table} TO {ROLES}"))
        conn.execute(sa.text(f"GRANT USAGE, SELECT ON SEQUENCE public.{table}_id_seq TO {ROLES}"))


def downgrade() -> None:
    conn = op.get_bind()
    for table in NEW_TABLES:
        conn.execute(sa.text(f"REVOKE ALL ON SEQUENCE public.{table}_id_seq FROM {ROLES}"))
        conn.execute(sa.text(f"REVOKE ALL ON public.{table} FROM {ROLES}"))
    conn.execute(sa.text(f"REVOKE ALL ON public.credit_note_sequences FROM {ROLES}"))

    op.drop_table("store_credit_entries")
    op.drop_table("sale_return_lines")
    op.drop_table("sale_returns")
    op.drop_table("credit_note_sequences")
    op.drop_column("custom_orders", "sale_id")
    op.drop_constraint("ck_sales_returned_quantity", "sales", type_="check")
    op.drop_column("sales", "returned_amount")
    op.drop_column("sales", "returned_quantity")
    op.drop_column("orders", "payment_details")
    op.drop_column("orders", "payment_method")
