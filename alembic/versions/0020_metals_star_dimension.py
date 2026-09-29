"""Metals as a star dimension: one valid-combination table

Task: docs/frontend-transition-to-2.0/slice-H-variant-schema/H-07-metals-star-dimension.md

Decision D25. A variant carried three independent FKs (base_metal_id,
metal_color_id, metal_purity_id), so ANY combination was representable —
including nonsense. The dev database contained a variant saved as Gold/Silver.

H-02 made that preventable with server-side validation. This makes it
impossible: a combination row either exists or it does not, so an invalid
pairing cannot be selected.

The three lookups stay normalised deliberately. Fully denormalising would
duplicate numeric_purity across every colour — a pricing input in more than
one place — and make renaming a colour a multi-row update.

metal_rates is NOT touched. Pricing is
  weight x rate(base_metal) x (numeric_purity/100) + stone_cost + making_charges
so colour has no effect on price and rates stay keyed on base metal.

ADDITIVE ONLY. The three legacy FK columns stay in place; removing them is a
separate ticket once every reader is migrated. H-01 taught that lesson.

metal_color_id is nullable on a combination: silver and platinum have no
colour variants.

Revision ID: 0020_metals_star_dimension
Revises: 0019_metal_colour_base_metal
Create Date: 2026-09-29
"""

from alembic import op
import sqlalchemy as sa

revision = "0020_metals_star_dimension"
down_revision = "0019_metal_colour_base_metal"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "metals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("base_metal_id", sa.Integer(), sa.ForeignKey("base_metals.id"), nullable=False),
        # Nullable: silver and platinum have no colour variants.
        sa.Column("metal_color_id", sa.Integer(), sa.ForeignKey("metal_colors.id"), nullable=True),
        sa.Column("metal_purity_id", sa.Integer(), sa.ForeignKey("metal_purities.id"), nullable=True),
        # Generated ("22K Yellow Gold") but editable — a jeweller may have
        # house terminology.
        sa.Column("display_name", sa.String(120), nullable=True),
        sa.UniqueConstraint(
            "base_metal_id",
            "metal_color_id",
            "metal_purity_id",
            name="uq_metals_combination",
        ),
    )

    op.add_column(
        "product_variants",
        sa.Column("metal_id", sa.Integer(), sa.ForeignKey("metals.id"), nullable=True),
    )

    conn = op.get_bind()

    # Build a combination row for each distinct pairing actually in use — but
    # ONLY where the colour genuinely belongs to the metal. A colour whose
    # base_metal_id is NULL (unclassified, see 0019) or points at a different
    # metal is NOT enshrined as a valid combination; those variants are left
    # unmapped and reported, because only a human can say what the piece is.
    conn.execute(
        sa.text(
            """
            INSERT INTO metals (base_metal_id, metal_color_id, metal_purity_id, display_name)
            SELECT DISTINCT
                v.base_metal_id,
                v.metal_color_id,
                v.metal_purity_id,
                trim(concat_ws(' ', mp.purity_label, mc.name, bm.name))
            FROM product_variants v
            JOIN base_metals bm ON bm.id = v.base_metal_id
            LEFT JOIN metal_colors mc ON mc.id = v.metal_color_id
            LEFT JOIN metal_purities mp ON mp.id = v.metal_purity_id
            WHERE v.base_metal_id IS NOT NULL
              AND (v.metal_color_id IS NULL OR mc.base_metal_id = v.base_metal_id)
              AND (v.metal_purity_id IS NULL OR mp.base_metal_id = v.base_metal_id)
            ON CONFLICT ON CONSTRAINT uq_metals_combination DO NOTHING
            """
        )
    )

    conn.execute(
        sa.text(
            """
            UPDATE product_variants v
            SET metal_id = m.id
            FROM metals m
            WHERE v.metal_id IS NULL
              AND m.base_metal_id = v.base_metal_id
              AND m.metal_color_id IS NOT DISTINCT FROM v.metal_color_id
              AND m.metal_purity_id IS NOT DISTINCT FROM v.metal_purity_id
            """
        )
    )

    unresolved = conn.execute(
        sa.text(
            """
            SELECT v.sku_code, bm.name, mc.name, mp.purity_label
            FROM product_variants v
            LEFT JOIN base_metals bm ON bm.id = v.base_metal_id
            LEFT JOIN metal_colors mc ON mc.id = v.metal_color_id
            LEFT JOIN metal_purities mp ON mp.id = v.metal_purity_id
            WHERE v.metal_id IS NULL AND v.base_metal_id IS NOT NULL
            ORDER BY v.sku_code
            """
        )
    ).fetchall()

    for row in unresolved:
        print(
            f"[0020] variant {row[0]!r} left UNMAPPED — "
            f"metal={row[1]!r} colour={row[2]!r} purity={row[3]!r}. That colour or "
            f"purity does not belong to that metal, so no valid combination was "
            f"created for it. Correct the variant in admin; not guessed."
        )


def downgrade() -> None:
    op.drop_column("product_variants", "metal_id")
    op.drop_table("metals")
