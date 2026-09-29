"""Require colour and purity on a metal combination

Task: docs/frontend-transition-to-2.0/slice-H-variant-schema/H-07-metals-star-dimension.md

0020 made metal_color_id and metal_purity_id nullable on `metals`, reasoning
that silver and platinum have no colour variants. That was wrong, and not for
a style reason:

    Postgres treats NULL as distinct from NULL, so
    UNIQUE (base_metal_id, metal_color_id, metal_purity_id) does NOT prevent
    duplicates once either column is null.

Demonstrated on the live database: two identical (Gold, NULL, NULL) rows
inserted cleanly, giving three interchangeable "Gold" combinations. The
uniqueness guarantee is the entire reason the combination table exists — a
nullable column silently switches it off.

So a metal combination is now always fully specified. Silver and platinum get
a colour row of their own ("Silver", "Natural") rather than a null; every
metal genuinely has a colour, even when there is only one.

Note the distinction: `metals.metal_color_id`/`metal_purity_id` are NOT NULL
because a COMBINATION must be complete, while `product_variants.metal_id`
stays nullable because a VARIANT may not have had its metal recorded yet.

Rows that cannot be completed are removed and their variants unpointed, with
the affected SKUs printed. Inventing a "Not specified" colour to satisfy the
constraint would put a non-value into a lookup table and make it selectable
forever.

Revision ID: 0022_metals_not_null_combination
Revises: 0021_grant_metals_table
Create Date: 2026-09-29
"""

from alembic import op
import sqlalchemy as sa

revision = "0022_metals_not_null_combination"
down_revision = "0021_grant_metals_table"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    incomplete = conn.execute(
        sa.text(
            """
            SELECT m.id, m.display_name, count(v.id)
            FROM metals m
            LEFT JOIN product_variants v ON v.metal_id = m.id
            WHERE m.metal_color_id IS NULL OR m.metal_purity_id IS NULL
            GROUP BY m.id, m.display_name
            ORDER BY m.id
            """
        )
    ).fetchall()

    for row in incomplete:
        print(
            f"[0022] metals id={row[0]} ({row[1]!r}) is incomplete — no colour "
            f"and/or purity. Removing it and unpointing {row[2]} variant(s); "
            f"those variants need their metal set in admin. Not invented."
        )

    conn.execute(
        sa.text(
            """
            UPDATE product_variants
            SET metal_id = NULL
            WHERE metal_id IN (
                SELECT id FROM metals
                WHERE metal_color_id IS NULL OR metal_purity_id IS NULL
            )
            """
        )
    )
    conn.execute(
        sa.text(
            "DELETE FROM metals WHERE metal_color_id IS NULL OR metal_purity_id IS NULL"
        )
    )

    op.alter_column("metals", "metal_color_id", existing_type=sa.Integer(), nullable=False)
    op.alter_column("metals", "metal_purity_id", existing_type=sa.Integer(), nullable=False)


def downgrade() -> None:
    op.alter_column("metals", "metal_purity_id", existing_type=sa.Integer(), nullable=True)
    op.alter_column("metals", "metal_color_id", existing_type=sa.Integer(), nullable=True)
