"""Piece serial number for non-HUID gifting items (D37, N-01)

Task: docs/frontend-transition-to-2.0/slice-N-gifting-cms/README.md

Watches (and other gifting pieces with no BIS hallmark) need a way to
identify one physical piece without a HUID. Additive column on the existing
variant_physical_units table (H-03/0026) -- no new table, the per-piece model
already exists.

Unique PER VARIANT, not globally: a HUID is a BIS-assigned national ID so
global uniqueness is correct for it, but a watch serial is only guaranteed
unique within its own brand/model -- two unrelated variants (different watch
models) could legitimately carry the same serial. Scoping the partial unique
index to (variant_id, serial_number) still catches the real mistake (the same
piece entered twice under one variant) without rejecting a coincidental
cross-variant match.

GRANT not needed: the table's GRANT (0026) already covers all its columns.

Revision ID: 0030_unit_serial_number
Revises: 0029_discounts
Create Date: 2026-10-02
"""

from alembic import op
import sqlalchemy as sa

revision = "0030_unit_serial_number"
down_revision = "0029_discounts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("variant_physical_units", sa.Column("serial_number", sa.String(100), nullable=True))
    op.create_index(
        "uq_variant_physical_units_serial_per_variant",
        "variant_physical_units",
        ["variant_id", "serial_number"],
        unique=True,
        postgresql_where=sa.text("serial_number IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_variant_physical_units_serial_per_variant", table_name="variant_physical_units")
    op.drop_column("variant_physical_units", "serial_number")
