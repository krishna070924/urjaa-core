"""Add ProductVariant.internal_notes (staff-only stock location notes)

Task: docs/feature-additions-2026-09-19/product-notes-field/TICKET.md

Additive, nullable ``Text`` column — no backfill needed regardless of row
count. Staff-only field for recording physical stock location (e.g. "box 4,
shelf B"); never exposed via storefront-facing schemas (``VariantResponse``,
``WishlistVariantResponse`` in ``urjaa_core/schemas/product.py`` and
``wishlist.py`` enumerate fields explicitly and are left untouched).

Revision ID: 0012_variant_internal_notes
Revises: 0011_grant_variant_attr_tables
Create Date: 2026-09-23
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "0012_variant_internal_notes"
down_revision = "0011_grant_variant_attr_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "product_variants",
        sa.Column("internal_notes", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("product_variants", "internal_notes")
