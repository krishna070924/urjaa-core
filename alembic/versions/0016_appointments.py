"""Add appointments table (showroom-visit bookings)

Task: docs/frontend-transition-to-2.0/slice-F-appointments/F-01-backend.md

D2: real backend for the ~700 LOC of appointment UI shipped with nothing
behind it. Distinct from `commission_requests` (custom-design commissions,
no showroom/service-type/reschedule/"No Show").

D19: availability is free-form — no advisor-capacity/slot-inventory model,
staff confirm/reschedule in admin. D20: account required, so `user_id` is
NOT NULL (no guest booking).

`status` is constrained at the DB level to the storefront's fixed vocabulary
(urjaa-storefront/src/lib/appointments.ts AppointmentStatus) — a CHECK
constraint, same pattern as `chk_orders_status_allowed` (0013) and
`chk_product_stones_certification_agency` (0015).

Revision ID: 0016_appointments
Revises: 0015_product_stone_certification
Create Date: 2026-09-27
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision = "0016_appointments"
down_revision = "0015_product_stone_certification"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "appointments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("store_location_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("store_locations.id"), nullable=False),
        sa.Column("service_type", sa.String(50), nullable=False),
        sa.Column("appointment_date", sa.Date(), nullable=False),
        sa.Column("appointment_time", sa.String(64), nullable=False),
        sa.Column("guests", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("reference", sa.String(20), nullable=False, unique=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="Confirmed"),
        sa.Column("advisor", sa.String(120), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_appointments_user_id", "appointments", ["user_id"])
    op.create_index("ix_appointments_store_location_id", "appointments", ["store_location_id"])
    op.create_index("ix_appointments_status", "appointments", ["status"])
    op.create_check_constraint(
        "chk_appointments_status_allowed",
        "appointments",
        "status IN ('Confirmed', 'Rescheduled', 'Completed', 'Cancelled', 'No Show')",
    )


def downgrade() -> None:
    op.drop_table("appointments")
