"""Add fixed variant size dimension and per-subcategory size labelling

Task: docs/frontend-transition-to-2.0/slice-H-variant-schema/H-01-fixed-variant-dimensions.md

Decision D21: the EAV attribute system is retired in favour of one fixed
dimension plus a per-subcategory label.

Why: the four variation axes in this catalogue — necklace length, ring size,
bangle diameter, bracelet length — are ONE axis with four labels. Each is a
single scalar measurement of the piece, differing in name and unit, not in
structure. EAV exists for dimensions that differ structurally; these do not.
Metal was never an EAV concern (base_metal -> purity is already a FK).

The five EAV tables cost staff three configuration screens before a product
could be created, and produced one flat, unclickable string
(`attribute_label`) at the storefront. This migration is purely ADDITIVE —
dropping the EAV tables happens in a separate later migration, so this can
ship and be verified before anything is destroyed.

`size_value` is text, not numeric: ring sizes, lengths in inches and diameters
in mm are not one number type, and some are not numbers at all.

Revision ID: 0018_fixed_variant_dimensions
Revises: 0017_grant_appointments_table
Create Date: 2026-09-29
"""

from alembic import op
import sqlalchemy as sa

revision = "0018_fixed_variant_dimensions"
down_revision = "0017_grant_appointments_table"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The variation value itself, e.g. "6", "18", "2.4". Nullable: most
    # products (a pendant, a brooch) do not vary by size at all.
    op.add_column("product_variants", sa.Column("size_value", sa.String(50), nullable=True))

    # Escape hatch for genuinely one-off descriptors, so a rare exception never
    # forces a migration. Display-only — never filtered on. Deliberately NOT a
    # second attribute system.
    op.add_column("product_variants", sa.Column("spec_note", sa.String(200), nullable=True))

    # What that value is CALLED, per category. A subcategory with no
    # size_label means that category does not vary by size, and the admin
    # hides the field entirely.
    op.add_column("subcategories", sa.Column("size_label", sa.String(50), nullable=True))
    op.add_column("subcategories", sa.Column("size_unit", sa.String(20), nullable=True))

    # Carry existing EAV values across. Every real row today is a ring size,
    # but this is written generally rather than assuming that: it takes the
    # first attribute value per variant, which is what `attribute_label`
    # effectively surfaced for single-attribute variants.
    op.execute(
        """
        UPDATE product_variants pv
        SET size_value = sub.value
        FROM (
            SELECT DISTINCT ON (va.variant_id) va.variant_id, av.value
            FROM variant_attributes va
            JOIN attribute_values av ON av.id = va.attribute_value_id
            WHERE av.value IS NOT NULL AND av.value <> ''
            ORDER BY va.variant_id, va.id
        ) AS sub
        WHERE pv.id = sub.variant_id
          AND pv.size_value IS NULL
        """
    )


def downgrade() -> None:
    op.drop_column("subcategories", "size_unit")
    op.drop_column("subcategories", "size_label")
    op.drop_column("product_variants", "spec_note")
    op.drop_column("product_variants", "size_value")
