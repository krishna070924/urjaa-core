"""Variant attribute system: replace ProductVariant.size with EAV junctions

Design: docs/feature-additions-2026-09-19/variant-attribute-system/DESIGN.md
Task: docs/feature-additions-2026-09-19/variant-attribute-system/tasks/01-core-schema.md

``ProductVariant.size`` (a single free-text column, two different admin form
fields silently overwriting each other) is replaced by two junction tables
mirroring the existing ``product_attributes`` EAV pattern:

- ``variant_type_attributes`` (``variant_type_id`` -> ``variant_types.id``,
  ``attribute_id`` -> ``attributes.id``) — which flexible Attributes apply to
  a given Variant Type (e.g. "Ring" -> {Ring Size, Stone Type}).
- ``variant_attributes`` (``variant_id`` -> ``product_variants.id``,
  ``attribute_value_id`` -> ``attribute_values.id``) — the actual selected
  value(s) for one real variant/SKU. Same shape as ``product_attributes``,
  scoped to variants instead of products, including the
  ``UniqueConstraint(variant_id, attribute_value_id)`` that 0009 added to
  the sibling junction tables (``uq_product_attributes_product_attribute_value``
  etc.) as a worked example — this table gets that constraint from creation
  instead of drifting first.

Also adds ``subcategories.default_variant_type_id`` (nullable FK ->
``variant_types.id``) so Create Product can pre-select the right Variant
Type from the chosen subcategory.

Confirmed via row counts immediately before writing this migration:
``products``, ``product_variants``, ``variant_types``, ``attributes``,
``attribute_values`` all have 0 rows live — clean-slate change, no backfill
needed, ``size`` drop is lossless.

Revision ID: 0010_variant_attribute_system
Revises: 0009_schema_hygiene_cleanup
Create Date: 2026-09-22
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

# revision identifiers, used by Alembic.
revision = "0010_variant_attribute_system"
down_revision = "0009_schema_hygiene_cleanup"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "variant_type_attributes",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("variant_type_id", sa.Integer, sa.ForeignKey("variant_types.id")),
        sa.Column("attribute_id", sa.Integer, sa.ForeignKey("attributes.id")),
    )
    op.create_index(
        "idx_variant_type_attributes_variant_type", "variant_type_attributes", ["variant_type_id"]
    )
    op.create_index(
        "idx_variant_type_attributes_attribute", "variant_type_attributes", ["attribute_id"]
    )

    op.create_table(
        "variant_attributes",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("variant_id", UUID(as_uuid=True), sa.ForeignKey("product_variants.id")),
        sa.Column("attribute_value_id", sa.Integer, sa.ForeignKey("attribute_values.id")),
        sa.UniqueConstraint(
            "variant_id", "attribute_value_id", name="uq_variant_attributes_variant_attribute_value"
        ),
    )
    op.create_index("idx_variant_attributes_variant", "variant_attributes", ["variant_id"])
    op.create_index("idx_variant_attributes_value", "variant_attributes", ["attribute_value_id"])

    op.add_column(
        "subcategories",
        sa.Column("default_variant_type_id", sa.Integer, sa.ForeignKey("variant_types.id"), nullable=True),
    )

    op.drop_column("product_variants", "size")


def downgrade() -> None:
    op.add_column("product_variants", sa.Column("size", sa.String(20), nullable=True))

    op.drop_column("subcategories", "default_variant_type_id")

    op.drop_index("idx_variant_attributes_value", table_name="variant_attributes")
    op.drop_index("idx_variant_attributes_variant", table_name="variant_attributes")
    op.drop_table("variant_attributes")

    op.drop_index("idx_variant_type_attributes_attribute", table_name="variant_type_attributes")
    op.drop_index("idx_variant_type_attributes_variant_type", table_name="variant_type_attributes")
    op.drop_table("variant_type_attributes")
