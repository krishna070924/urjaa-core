"""Drop the EAV tables: attributes, attribute_values, product_attributes,
variant_types, variant_type_attributes, variant_attributes

Ticket: docs/frontend-transition-to-2.0/slice-H-variant-schema/H-06-retire-eav-code-and-tables.md
Decision: docs/decisions/variant-model-eav-vs-fixed.md (D21)

This is the destructive half of H-06. The additive half (D21: a fixed
`product_variants.size_value` column plus `subcategories.size_label`/
`size_unit`, H-01) and gender's move off EAV onto `products.gender_id`
(H-08/H-11) already shipped and are verified. All code that read or wrote
these six tables -- the variant-level EAV path and the product-level
generic attribute-facet path alike -- was removed from urjaa-core and
urjaa-admin-backend in commits earlier on this same branch, confirmed by
`grep -rn "attribute_value|variant_type|variant_attribute|product_attribute"`
coming back comment-only. Per H-06's own ordering, this migration ships
only after that code removal is merged and verified -- never in the same
change.

Drop order respects the FK graph: `subcategories.default_variant_type_id`
(points at `variant_types`) first, then the two junction tables
(`variant_type_attributes`, `variant_attributes`), then `product_attributes`,
then `variant_types`, then `attribute_values`, then `attributes` last (every
other table's FK points at one of these two or at a junction over them).

`upgrade()` prints each table's row count immediately before dropping it --
the auditable record the ticket asks for. Decision D21's own record notes
every EAV row in this database was test scaffolding at decision time, so
these counts are expected to be 0 or near it.

DOWNGRADE IS DESTRUCTIVE TO DATA: `downgrade()` recreates all six tables and
the `subcategories.default_variant_type_id` column with their pre-drop
schema (columns, FKs, unique constraints, indexes), but empty -- any EAV
rows that existed when `upgrade()` ran are gone and are NOT restored. This
is the acceptable, explicitly-stated tradeoff the ticket allows ("recreating
empty tables on downgrade is acceptable and should be stated"). Running this
downgrade against a database that has had real EAV data written since this
migration's upgrade() ran is a data-loss operation.

Known, accepted gap: this downgrade does NOT re-run 0011's GRANT to
urjaa_storefront/urjaa_admin_svc on the two junction tables it recreates
(`variant_attributes`, `variant_type_attributes`), so a downgraded database
leaves those two tables ungrantable to the app roles until a follow-up GRANT
migration runs -- same class of pre-existing gap as finding C22 in the
project INDEX. Out of scope here, same as it was there.

Revision ID: 0028_drop_eav_tables
Revises: 0027_variant_sku_sequence
Create Date: 2026-10-01
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

# revision identifiers, used by Alembic.
revision = "0028_drop_eav_tables"
down_revision = "0027_variant_sku_sequence"
branch_labels = None
depends_on = None

_EAV_TABLES = (
    "variant_type_attributes",
    "variant_attributes",
    "product_attributes",
    "variant_types",
    "attribute_values",
    "attributes",
)


def upgrade() -> None:
    bind = op.get_bind()
    for table in _EAV_TABLES:
        count = bind.execute(sa.text(f"SELECT count(*) FROM {table}")).scalar()
        print(f"H-06 drop-EAV audit: {table} had {count} row(s) before drop")

    op.drop_column("subcategories", "default_variant_type_id")

    op.drop_index("idx_variant_type_attributes_attribute", table_name="variant_type_attributes")
    op.drop_index("idx_variant_type_attributes_variant_type", table_name="variant_type_attributes")
    op.drop_table("variant_type_attributes")

    op.drop_index("idx_variant_attributes_value", table_name="variant_attributes")
    op.drop_index("idx_variant_attributes_variant", table_name="variant_attributes")
    op.drop_table("variant_attributes")

    op.drop_table("product_attributes")

    op.drop_table("variant_types")

    op.drop_table("attribute_values")

    op.drop_table("attributes")


# Recreates empty tables only -- see the module docstring. Any EAV data that
# existed when upgrade() ran is NOT restored by this downgrade.
def downgrade() -> None:
    op.create_table(
        "attributes",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(100)),
        sa.Column("slug", sa.String(120)),
        sa.Column("filterable", sa.Boolean, server_default=sa.true()),
        sa.UniqueConstraint("slug", name="uq_attributes_slug"),
    )

    op.create_table(
        "attribute_values",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("attribute_id", sa.Integer, sa.ForeignKey("attributes.id")),
        sa.Column("value", sa.String(100)),
        sa.UniqueConstraint("attribute_id", "value", name="uq_attribute_values_attribute_value"),
    )

    op.create_table(
        "variant_types",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("slug", sa.String(150), nullable=False),
        sa.Column("description", sa.Text),
        sa.Column("display_order", sa.Integer),
        sa.UniqueConstraint("slug", name="variant_types_slug_key"),
    )

    op.create_table(
        "product_attributes",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("product_id", UUID(as_uuid=True), sa.ForeignKey("products.id")),
        sa.Column("attribute_value_id", sa.Integer, sa.ForeignKey("attribute_values.id")),
        sa.UniqueConstraint(
            "product_id", "attribute_value_id", name="uq_product_attributes_product_attribute_value"
        ),
    )
    op.create_index("idx_product_attributes_compound", "product_attributes", ["product_id", "attribute_value_id"])
    op.create_index("idx_product_attributes_product", "product_attributes", ["product_id"])
    op.create_index("idx_product_attributes_value", "product_attributes", ["attribute_value_id"])

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

    op.create_table(
        "variant_type_attributes",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("variant_type_id", sa.Integer, sa.ForeignKey("variant_types.id")),
        sa.Column("attribute_id", sa.Integer, sa.ForeignKey("attributes.id")),
    )
    op.create_index("idx_variant_type_attributes_variant_type", "variant_type_attributes", ["variant_type_id"])
    op.create_index("idx_variant_type_attributes_attribute", "variant_type_attributes", ["attribute_id"])

    op.add_column(
        "subcategories",
        sa.Column("default_variant_type_id", sa.Integer, sa.ForeignKey("variant_types.id"), nullable=True),
    )
