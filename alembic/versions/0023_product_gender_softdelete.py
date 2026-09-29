"""Add a genders lookup, product.gender_id, product statuses and soft delete

Task: docs/frontend-transition-to-2.0/slice-H-variant-schema/H-08-product-table-completion.md

Two things, both about the products table owning its own identity data rather
than borrowing it from EAV or overloading an enum.

1. GENDER — urgent. It currently lives in product_attributes, an EAV table
   that H-06 deletes. Nine products have it set, so dropping EAV first would
   silently lose it. Migrated here, before anything is destroyed.

2. SOFT DELETE — `status` already had `archived`, which meant BOTH
   "soft-deleted" and "not shown", while is_visible_on_website separately
   answered "should customers see it". That conflation makes "list deleted
   products" and "restore this" ambiguous, and an enum cannot record WHEN
   something was deleted. deleted_at does both.

   Status also moves from enum text to a lookup table with ids, per decision.
   The old enum column is left in place and kept in sync for now — removing it
   is a later change once every reader uses status_id. H-01 taught that
   additive-first lesson.

Revision ID: 0023_product_gender_softdelete
Revises: 0022_metals_not_null_combination
Create Date: 2026-09-29
"""

from alembic import op
import sqlalchemy as sa

revision = "0023_product_gender_softdelete"
down_revision = "0022_metals_not_null_combination"
branch_labels = None
depends_on = None

GENDERS = ["Women", "Men", "Unisex", "Kids"]
STATUSES = ["draft", "active", "hidden", "archived"]


def upgrade() -> None:
    conn = op.get_bind()

    op.create_table(
        "genders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(30), nullable=False, unique=True),
    )
    op.create_table(
        "product_statuses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(20), nullable=False, unique=True),
    )
    for name in GENDERS:
        conn.execute(sa.text("INSERT INTO genders (name) VALUES (:n)"), {"n": name})
    for code in STATUSES:
        conn.execute(sa.text("INSERT INTO product_statuses (code) VALUES (:c)"), {"c": code})

    op.add_column("products", sa.Column("gender_id", sa.Integer(), sa.ForeignKey("genders.id"), nullable=True))
    op.add_column("products", sa.Column("status_id", sa.Integer(), sa.ForeignKey("product_statuses.id"), nullable=True))
    op.add_column("products", sa.Column("deleted_at", sa.TIMESTAMP(), nullable=True))

    # Carry gender out of EAV before H-06 deletes those tables.
    moved = conn.execute(
        sa.text(
            """
            UPDATE products p
            SET gender_id = g.id
            FROM product_attributes pa
            JOIN attribute_values av ON av.id = pa.attribute_value_id
            JOIN attributes a ON a.id = av.attribute_id
            JOIN genders g ON lower(g.name) = lower(av.value)
            WHERE pa.product_id = p.id
              AND lower(a.name) = 'gender'
              AND p.gender_id IS NULL
            RETURNING p.id
            """
        )
    ).fetchall()
    print(f"[0023] migrated gender for {len(moved)} product(s) out of product_attributes")

    unmatched = conn.execute(
        sa.text(
            """
            SELECT DISTINCT av.value
            FROM product_attributes pa
            JOIN attribute_values av ON av.id = pa.attribute_value_id
            JOIN attributes a ON a.id = av.attribute_id
            WHERE lower(a.name) = 'gender'
              AND lower(av.value) NOT IN (SELECT lower(name) FROM genders)
            """
        )
    ).fetchall()
    for row in unmatched:
        print(
            f"[0023] gender value {row[0]!r} has no matching row in `genders` — "
            f"NOT migrated. Add it to the lookup and re-run, or set it in admin. "
            f"Not invented."
        )

    # Mirror the existing enum into status_id. The enum column stays for now.
    conn.execute(
        sa.text(
            """
            UPDATE products p
            SET status_id = ps.id
            FROM product_statuses ps
            WHERE ps.code = p.status::text AND p.status_id IS NULL
            """
        )
    )


def downgrade() -> None:
    op.drop_column("products", "deleted_at")
    op.drop_column("products", "status_id")
    op.drop_column("products", "gender_id")
    op.drop_table("product_statuses")
    op.drop_table("genders")
