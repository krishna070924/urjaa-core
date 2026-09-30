"""Per-stone cost on product_stones, and allow repeated stone types

Task: docs/frontend-transition-to-2.0/slice-H-variant-schema/H-09-stones-per-stone-cost.md

Model (settled): a stone row belongs to a PRODUCT, carries its own config, and
every variant of that product uses it. The same stone type in another product
is a separate row.

Two defects fixed:

1. No per-stone cost. product_stones described each stone in detail but had no
   cost; cost was a single lump `stone_cost` on the VARIANT, so a piece with a
   ruby and two diamonds could only record one number.

2. UNIQUE (product_id, stone_id) made it impossible for one product to carry
   the same stone type twice — e.g. two rubies of different carat, cost and
   certificate.

variant.stone_cost is NOT removed here. Pricing prefers the product's summed
stone costs and falls back to it, so existing prices do not move.

Revision ID: 0025_product_stone_cost
Revises: 0024_grant_gender_status_tables
Create Date: 2026-09-29
"""

from alembic import op
import sqlalchemy as sa

revision = "0025_product_stone_cost"
down_revision = "0024_grant_gender_status_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Nullable: cost may be unknown when the stone is first entered.
    op.add_column("product_stones", sa.Column("cost", sa.Numeric(12, 2), nullable=True))
    op.create_check_constraint(
        "chk_product_stones_cost_non_negative", "product_stones", "cost IS NULL OR cost >= 0"
    )
    op.drop_constraint("uq_product_stones_product_stone", "product_stones", type_="unique")


def downgrade() -> None:
    # Restoring the unique constraint fails if a product now carries a stone
    # type twice. That is deliberate: silently deleting a stone to make the
    # downgrade succeed would lose data.
    op.create_unique_constraint(
        "uq_product_stones_product_stone", "product_stones", ["product_id", "stone_id"]
    )
    op.drop_constraint("chk_product_stones_cost_non_negative", "product_stones", type_="check")
    op.drop_column("product_stones", "cost")
