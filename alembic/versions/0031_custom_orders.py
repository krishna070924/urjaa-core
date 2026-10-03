"""Custom Orders + Karigars (D44, O-04 part a)

Task: docs/frontend-transition-to-2.0/slice-O-review-3/README.md decision D44

Offline bespoke-order tracking: a Kanban board (Order taken -> Design
finalised -> With karigar -> Quality check -> Ready for pickup -> Delivered,
+ Cancelled) plus a store-scoped karigar (artisan) directory. Every status
move, karigar assignment, and edit is logged to `custom_order_events` (who,
when) per D44's "moves logged" requirement -- an audit trail, not just a
mutable `status` column.

`custom_order_statuses` is a small fixed lookup, seeded here (not
admin-editable) so status_id FKs are stable ints instead of magic strings.

GRANT ships in the same migration (established convention, see 0029).

Revision ID: 0031_custom_orders
Revises: 0030_unit_serial_number
Create Date: 2026-10-03
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0031_custom_orders"
down_revision = "0030_unit_serial_number"
branch_labels = None
depends_on = None

ROLES = "urjaa_storefront, urjaa_admin_svc"

# D44 Kanban vocabulary, in board order.
STATUS_SEED = [
    ("order_taken", "Order taken", 1),
    ("design_finalised", "Design finalised", 2),
    ("with_karigar", "With karigar", 3),
    ("quality_check", "Quality check", 4),
    ("ready_for_pickup", "Ready for pickup", 5),
    ("delivered", "Delivered", 6),
    ("cancelled", "Cancelled", 7),
]


def upgrade() -> None:
    op.create_table(
        "karigars",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("store_id", UUID(as_uuid=True), sa.ForeignKey("stores.id"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("phone", sa.String(15), nullable=False),
        sa.Column("speciality", sa.String(200), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.TIMESTAMP(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_karigars_store_id", "karigars", ["store_id"])

    custom_order_statuses = op.create_table(
        "custom_order_statuses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(30), nullable=False, unique=True),
        sa.Column("label", sa.String(60), nullable=False),
        sa.Column("display_order", sa.Integer(), nullable=False),
    )
    op.bulk_insert(
        custom_order_statuses,
        [{"code": code, "label": label, "display_order": order} for code, label, order in STATUS_SEED],
    )

    op.create_table(
        "custom_orders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("store_id", UUID(as_uuid=True), sa.ForeignKey("stores.id"), nullable=False),
        sa.Column("customer_name", sa.String(120), nullable=False),
        sa.Column("customer_phone", sa.String(15), nullable=False),
        sa.Column("taken_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("taken_by_admin_id", sa.Integer(), sa.ForeignKey("admin_users.id"), nullable=True),
        sa.Column("karigar_id", sa.Integer(), sa.ForeignKey("karigars.id"), nullable=True),
        sa.Column("status_id", sa.Integer(), sa.ForeignKey("custom_order_statuses.id"), nullable=False),
        sa.Column("design_notes", sa.Text(), nullable=True),
        sa.Column("reference_image_urls", JSONB(), nullable=False, server_default="[]"),
        sa.Column("expected_date", sa.Date(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_custom_orders_store_id_status_id", "custom_orders", ["store_id", "status_id"])
    op.create_index("ix_custom_orders_karigar_id", "custom_orders", ["karigar_id"])

    op.create_table(
        "custom_order_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("custom_orders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("by_admin_id", sa.Integer(), sa.ForeignKey("admin_users.id"), nullable=True),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("from_value", sa.String(120), nullable=True),
        sa.Column("to_value", sa.String(120), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "kind IN ('created', 'status', 'karigar', 'edit')", name="ck_custom_order_events_kind"
        ),
    )
    op.create_index("ix_custom_order_events_order_id", "custom_order_events", ["order_id"])

    conn = op.get_bind()
    for table in ("karigars", "custom_order_statuses", "custom_orders", "custom_order_events"):
        conn.execute(sa.text(f"GRANT SELECT, INSERT, UPDATE, DELETE ON public.{table} TO {ROLES}"))
        conn.execute(sa.text(f"GRANT USAGE, SELECT ON SEQUENCE public.{table}_id_seq TO {ROLES}"))


def downgrade() -> None:
    conn = op.get_bind()
    for table in ("karigars", "custom_order_statuses", "custom_orders", "custom_order_events"):
        conn.execute(sa.text(f"REVOKE ALL ON SEQUENCE public.{table}_id_seq FROM urjaa_storefront, urjaa_admin_svc"))
        conn.execute(sa.text(f"REVOKE ALL ON public.{table} FROM {ROLES}"))

    op.drop_index("ix_custom_order_events_order_id", table_name="custom_order_events")
    op.drop_table("custom_order_events")

    op.drop_index("ix_custom_orders_karigar_id", table_name="custom_orders")
    op.drop_index("ix_custom_orders_store_id_status_id", table_name="custom_orders")
    op.drop_table("custom_orders")

    op.drop_table("custom_order_statuses")

    op.drop_index("ix_karigars_store_id", table_name="karigars")
    op.drop_table("karigars")
