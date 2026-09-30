"""Sequence for server-generated variant SKUs (H-04)

Task: docs/frontend-transition-to-2.0/slice-H-variant-schema/H-04-sku-autogeneration.md

nextval() is atomic, so two staff saving at once can never draw the same
number — no check-then-insert race. GRANT in the same migration (C22).

Revision ID: 0027_variant_sku_sequence
Revises: 0026_variant_physical_units
Create Date: 2026-09-30
"""

from alembic import op

revision = "0027_variant_sku_sequence"
down_revision = "0026_variant_physical_units"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SEQUENCE variant_sku_seq")
    op.execute("GRANT USAGE, SELECT ON SEQUENCE variant_sku_seq TO urjaa_storefront, urjaa_admin_svc")


def downgrade() -> None:
    op.execute("DROP SEQUENCE variant_sku_seq")
