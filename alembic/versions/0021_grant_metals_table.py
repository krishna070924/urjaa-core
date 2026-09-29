"""Grant the app roles access to the metals table

Migration 0002 took a one-time snapshot of table privileges for
urjaa_storefront and urjaa_admin_svc, so ANY table created afterwards is
unreachable by the application until it is granted. It fails only at runtime,
only against the real role, and never in a schema-level test.

This is the FOURTH occurrence on this project (0011 variant attribute tables,
0017 appointments, a missing admin route permission rule, and now 0020's
metals). 0020 created the table and the storefront immediately returned
500 with "permission denied for table metals" on every product query.

Any migration that creates a table must ship its GRANT alongside it.

Revision ID: 0021_grant_metals_table
Revises: 0020_metals_star_dimension
Create Date: 2026-09-29
"""

from alembic import op
from sqlalchemy import text

revision = "0021_grant_metals_table"
down_revision = "0020_metals_star_dimension"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        text("GRANT SELECT, INSERT, UPDATE, DELETE ON public.metals TO urjaa_storefront, urjaa_admin_svc")
    )
    # The table has a serial primary key; without the sequence grant an INSERT
    # fails even when the table itself is writable.
    bind.execute(
        text("GRANT USAGE, SELECT ON SEQUENCE public.metals_id_seq TO urjaa_storefront, urjaa_admin_svc")
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        text("REVOKE ALL ON public.metals FROM urjaa_storefront, urjaa_admin_svc")
    )
    bind.execute(
        text("REVOKE ALL ON SEQUENCE public.metals_id_seq FROM urjaa_storefront, urjaa_admin_svc")
    )
