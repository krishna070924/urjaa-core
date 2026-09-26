"""Add ProductVariant.huid_number (BIS hallmark ID)

Task: docs/feature-additions-2026-09-19/huid-number-field/TICKET.md

BIS's HUID (Hallmark Unique Identification) is the 6-character alphanumeric
code assigned to hallmarked gold jewelry in India. Additive, nullable
``String`` column, no backfill needed regardless of row count, no uniqueness
constraint (see ticket). Staff-only field, matching where ``internal_notes``
lives; never exposed via storefront-facing schemas (``VariantResponse``,
``WishlistVariantResponse`` in ``urjaa_core/schemas/product.py`` and
``wishlist.py`` enumerate fields explicitly and are left untouched).

Revision ID: 0014_variant_huid_number
Revises: 0013_order_grouping
Create Date: 2026-09-26
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "0014_variant_huid_number"
down_revision = "0013_order_grouping"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "product_variants",
        sa.Column("huid_number", sa.String(50), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("product_variants", "huid_number")
