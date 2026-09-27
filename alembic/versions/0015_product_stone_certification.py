"""Add product_stones certification fields (cut/clarity/color/origin/
certificate_number/certification_agency)

Task: docs/frontend-transition-to-2.0/slice-B-catalog-api/B-02-gemstone-certification.md

The only genuinely new columns in the storefront-2.0 transition (finding C5).
`stones` is a clean name lookup table and `product_stones` already carries
quantity/total_carat_weight, but cut/clarity/colour/certificate number exist
nowhere, even though the PDP renders a GIA/IGI certification block.

Decision D4: fields attach to `product_stones`, not `products` or `stones` —
a piece can carry several separately-certified stones, and putting a
certificate number on `stones` would give "Diamond" itself one shared
certificate across every product using it.

Decision D3: every field nullable, never required to create a product or
variant. Decision D13: hand-entered by staff (no GIA/IGI import).

`certification_agency` is constrained at the DB level to the same
GIA/IGI/HRD/BIS union urjaa-storefront's GemstoneSpec.certificationAgency
type accepts (urjaa-storefront/src/types/product.ts) — a CHECK constraint
rather than app-side validation, same pattern as `chk_orders_status_allowed`
(0013) and `chk_metal_rates_rate_positive`. NULL still passes an `IN (...)`
CHECK (Postgres only evaluates the predicate for non-NULL values), so the
nullability requirement holds.

Revision ID: 0015_product_stone_certification
Revises: 0014_variant_huid_number
Create Date: 2026-09-27
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "0015_product_stone_certification"
down_revision = "0014_variant_huid_number"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("product_stones", sa.Column("cut", sa.String(50), nullable=True))
    op.add_column("product_stones", sa.Column("clarity", sa.String(20), nullable=True))
    op.add_column("product_stones", sa.Column("color", sa.String(20), nullable=True))
    op.add_column("product_stones", sa.Column("origin", sa.String(100), nullable=True))
    op.add_column("product_stones", sa.Column("certificate_number", sa.String(100), nullable=True))
    op.add_column("product_stones", sa.Column("certification_agency", sa.String(10), nullable=True))
    op.create_check_constraint(
        "chk_product_stones_certification_agency",
        "product_stones",
        "certification_agency IN ('GIA', 'IGI', 'HRD', 'BIS')",
    )


def downgrade() -> None:
    op.drop_constraint("chk_product_stones_certification_agency", "product_stones", type_="check")
    op.drop_column("product_stones", "certification_agency")
    op.drop_column("product_stones", "certificate_number")
    op.drop_column("product_stones", "origin")
    op.drop_column("product_stones", "color")
    op.drop_column("product_stones", "clarity")
    op.drop_column("product_stones", "cut")
