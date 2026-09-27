"""Grant urjaa_storefront/urjaa_admin_svc on appointments (0016 gap)

Task: docs/frontend-transition-to-2.0/slice-F-appointments/F-01-backend.md

Same class of gap as 0011_grant_variant_attr_tables: 0002's original
``GRANT ... ON ALL TABLES IN SCHEMA public`` was a one-time snapshot, not
``ALTER DEFAULT PRIVILEGES`` — it does not cover a table created by a later
migration. Confirmed live: `POST /appointments` as the real `urjaa_storefront`
role raised ``psycopg2.errors.InsufficientPrivilege: permission denied for
table appointments`` during F-01's own endpoint verification.

Mirrors 0011's fix exactly. No sequence grant needed — `appointments.id` is a
client-side UUID default (`uuid.uuid4`), not a serial/identity column.

Revision ID: 0017_grant_appointments_table
Revises: 0016_appointments
Create Date: 2026-09-27
"""

from sqlalchemy import text

from alembic import op

# revision identifiers, used by Alembic.
revision = "0017_grant_appointments_table"
down_revision = "0016_appointments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        text("GRANT SELECT, INSERT, UPDATE, DELETE ON public.appointments TO urjaa_storefront, urjaa_admin_svc")
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(text("REVOKE ALL ON public.appointments FROM urjaa_storefront, urjaa_admin_svc"))
