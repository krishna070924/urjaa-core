"""Grant the app roles access to genders and product_statuses

Migration 0002 snapshotted table privileges, so any table created later is
unreachable by urjaa_storefront / urjaa_admin_svc until granted. It fails only
at runtime, against the real role, never in a schema test.

This is the fifth occurrence on this project. The grant now ships in the same
change as the table that needs it.

Revision ID: 0024_grant_gender_status_tables
Revises: 0023_product_gender_softdelete
Create Date: 2026-09-29
"""

from alembic import op
from sqlalchemy import text

revision = "0024_grant_gender_status_tables"
down_revision = "0023_product_gender_softdelete"
branch_labels = None
depends_on = None

TABLES = ("genders", "product_statuses")


def upgrade() -> None:
    bind = op.get_bind()
    for table in TABLES:
        bind.execute(text(f"GRANT SELECT, INSERT, UPDATE, DELETE ON public.{table} TO urjaa_storefront, urjaa_admin_svc"))
        bind.execute(text(f"GRANT USAGE, SELECT ON SEQUENCE public.{table}_id_seq TO urjaa_storefront, urjaa_admin_svc"))


def downgrade() -> None:
    bind = op.get_bind()
    for table in TABLES:
        bind.execute(text(f"REVOKE ALL ON public.{table} FROM urjaa_storefront, urjaa_admin_svc"))
        bind.execute(text(f"REVOKE ALL ON SEQUENCE public.{table}_id_seq FROM urjaa_storefront, urjaa_admin_svc"))
