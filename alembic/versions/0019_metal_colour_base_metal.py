"""Map metal colours to base metals

Task: docs/frontend-transition-to-2.0/slice-H-variant-schema/H-02-metal-colour-mapping.md

Decision D23. MetalPurity already has base_metal_id; MetalColor did not — it
was a flat list, so nothing related a colour to the metal it belongs to.
Gold comes in yellow, white and rose; silver does not come in rose.

The consequence was live in the dev database: one variant was saved as
Gold / Silver, and the admin had no way to narrow the colour dropdown to the
colours valid for the chosen metal.

Backfill policy:
  - Rose and Yellow are gold colours -> mapped to the Gold base metal.
  - "Silver" is a BASE METAL entered as a colour. It is deliberately left
    unmapped (NULL) rather than guessed at or deleted: a variant references
    it, and only a human knows whether that piece is gold or silver. The
    migration prints a warning naming the affected rows.

base_metal_id is nullable precisely so that unresolved row can persist
without blocking the migration. Enforcing NOT NULL is a follow-up once the
data is corrected by staff.

Revision ID: 0019_metal_colour_base_metal
Revises: 0018_fixed_variant_dimensions
Create Date: 2026-09-29
"""

from alembic import op
import sqlalchemy as sa

revision = "0019_metal_colour_base_metal"
down_revision = "0018_fixed_variant_dimensions"
branch_labels = None
depends_on = None

# Colours that belong to gold. Anything not listed is left unmapped and
# reported rather than guessed.
GOLD_COLOURS = ("yellow", "rose", "white")


def upgrade() -> None:
    op.add_column("metal_colors", sa.Column("base_metal_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_metal_colors_base_metal",
        "metal_colors",
        "base_metals",
        ["base_metal_id"],
        ["id"],
    )

    conn = op.get_bind()

    gold = conn.execute(
        sa.text("SELECT id FROM base_metals WHERE lower(name) = 'gold' LIMIT 1")
    ).scalar()

    if gold is not None:
        conn.execute(
            sa.text(
                """
                UPDATE metal_colors
                SET base_metal_id = :gold
                WHERE base_metal_id IS NULL
                  AND lower(name) = ANY(:names)
                """
            ),
            {"gold": gold, "names": list(GOLD_COLOURS)},
        )

    unmapped = conn.execute(
        sa.text(
            """
            SELECT mc.id, mc.name, count(v.id) AS variants
            FROM metal_colors mc
            LEFT JOIN product_variants v ON v.metal_color_id = mc.id
            WHERE mc.base_metal_id IS NULL
            GROUP BY mc.id, mc.name
            ORDER BY mc.id
            """
        )
    ).fetchall()

    for row in unmapped:
        print(
            f"[0019] metal_colors id={row[0]} name={row[1]!r} left UNMAPPED "
            f"({row[2]} variant(s) reference it). Not guessed and not deleted — "
            f"a human must decide which base metal it belongs to, or whether it "
            f"is a base metal that was entered as a colour."
        )


def downgrade() -> None:
    op.drop_constraint("fk_metal_colors_base_metal", "metal_colors", type_="foreignkey")
    op.drop_column("metal_colors", "base_metal_id")
