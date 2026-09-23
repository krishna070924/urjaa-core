"""POS order grouping: orders.source/invoice_number, COMPLETED status,
invoice_sequences counter table

Task: docs/feature-additions-2026-09-19/pos-billing/tasks/01-core-order-grouping.md

``SalesService.create_bulk_sale`` created independent ``Sale`` rows for a
multi-item walk-in basket with no ``Order`` linking them, so there was no way
to produce one combined invoice for a POS transaction. This migration adds
the schema pieces the fix needs:

- ``chk_orders_status_allowed`` extended to allow ``'COMPLETED'`` (the
  terminal status a POS-created order is stamped with immediately, unlike
  the online-checkout ``PENDING`` -> ... lifecycle).
- ``orders.source`` (mirrors ``sales.source`` exactly, default
  ``'website'`` so every existing online-checkout ``Order(...)`` call site
  is unaffected and every pre-existing row backfills to the same value it
  implicitly had).
- ``orders.invoice_number``, nullable + unique (POS orders get one at
  creation; online orders don't use this field yet).
- ``invoice_sequences`` table: one row per ``(store_id, period)``, atomic
  monthly invoice-number counter via
  ``INSERT ... ON CONFLICT DO UPDATE ... RETURNING seq`` (Postgres UPSERT is
  atomic under concurrent access, no extra locking needed).

``orders.email``/``orders.full_name`` are also relaxed to nullable (DB and
ORM) — POS orders have no customer contact info to store.

Revision ID: 0013_order_grouping
Revises: 0012_variant_internal_notes
Create Date: 2026-09-24
"""

import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

# revision identifiers, used by Alembic.
revision = "0013_order_grouping"
down_revision = "0012_variant_internal_notes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Baseline schema (0001) left a partial UNIQUE index enforcing the old
    # one-Sale-per-Order relationship at the DB level, independent of the
    # ORM's now-dropped `uselist=False`. Must go too, or a second Sale in the
    # same Order fails with a UniqueViolation despite the model change.
    op.drop_index("uq_sales_order_id_not_null", table_name="sales")

    op.drop_constraint("chk_orders_status_allowed", "orders", type_="check")
    op.create_check_constraint(
        "chk_orders_status_allowed",
        "orders",
        "status IN ('PENDING', 'CONFIRMED', 'PROCESSING', 'SHIPPED', 'DELIVERED', 'CANCELLED', 'COMPLETED')",
    )

    op.alter_column("orders", "email", existing_type=sa.String(255), nullable=True)
    op.alter_column("orders", "full_name", existing_type=sa.String(200), nullable=True)

    op.add_column(
        "orders",
        sa.Column("source", sa.String(20), nullable=False, server_default="website"),
    )
    op.add_column("orders", sa.Column("invoice_number", sa.String(50), nullable=True))
    op.create_unique_constraint("uq_orders_invoice_number", "orders", ["invoice_number"])

    op.create_table(
        "invoice_sequences",
        sa.Column("store_id", UUID(as_uuid=True), sa.ForeignKey("stores.id"), primary_key=True),
        sa.Column("period", sa.String(6), primary_key=True),
        sa.Column("seq", sa.Integer(), nullable=False, server_default="0"),
    )

    bind = op.get_bind()
    bind.execute(
        text(
            "GRANT SELECT, INSERT, UPDATE, DELETE ON public.invoice_sequences "
            "TO urjaa_storefront, urjaa_admin_svc"
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(text("REVOKE ALL ON public.invoice_sequences FROM urjaa_storefront, urjaa_admin_svc"))

    op.drop_table("invoice_sequences")

    op.drop_constraint("uq_orders_invoice_number", "orders", type_="unique")
    op.drop_column("orders", "invoice_number")
    op.drop_column("orders", "source")

    op.alter_column("orders", "full_name", existing_type=sa.String(200), nullable=False)
    op.alter_column("orders", "email", existing_type=sa.String(255), nullable=False)

    op.drop_constraint("chk_orders_status_allowed", "orders", type_="check")
    op.create_check_constraint(
        "chk_orders_status_allowed",
        "orders",
        "status IN ('PENDING', 'CONFIRMED', 'PROCESSING', 'SHIPPED', 'DELIVERED', 'CANCELLED')",
    )

    op.create_index(
        "uq_sales_order_id_not_null",
        "sales",
        ["order_id"],
        unique=True,
        postgresql_where=sa.text("order_id IS NOT NULL"),
    )
