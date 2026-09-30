"""Per-piece physical units with their own HUID (D22)

Task: docs/frontend-transition-to-2.0/slice-H-variant-schema/H-03-per-piece-huid.md

BIS assigns a HUID per hallmarked physical item, not per SKU, so a variant with
five pieces in stock has five HUIDs. One row per piece here.

ONE SOURCE FOR AVAILABILITY. For a variant that has unit rows, the unit rows
are the truth and product_variants.stock_quantity is a cache the database keeps
equal to its count of in_stock units:
  - an AFTER trigger on variant_physical_units recomputes it on every change;
  - a BEFORE UPDATE trigger on product_variants overwrites any direct write, so
    a legacy "stock_quantity = n" can never drift from the units.
A variant with NO unit rows (e.g. unhallmarked silver) keeps its hand-kept
count exactly as before. Every existing stock reader keeps working unchanged.

Existing product_variants.huid_number values are migrated: that variant gets
one unit carrying the HUID plus (stock_quantity - 1) units without one, so its
count is unchanged. huid_number itself stays until every reader moves.

GRANT ships in the same migration (finding C22).

Revision ID: 0026_variant_physical_units
Revises: 0025_product_stone_cost
Create Date: 2026-09-30
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "0026_variant_physical_units"
down_revision = "0025_product_stone_cost"
branch_labels = None
depends_on = None

STATUSES = ["in_stock", "reserved", "sold", "returned"]
ROLES = "urjaa_storefront, urjaa_admin_svc"


def upgrade() -> None:
    conn = op.get_bind()

    op.create_table(
        "unit_statuses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(20), nullable=False, unique=True),
    )
    for code in STATUSES:
        conn.execute(sa.text("INSERT INTO unit_statuses (code) VALUES (:c)"), {"c": code})

    op.create_table(
        "variant_physical_units",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("variant_id", UUID(as_uuid=True), sa.ForeignKey("product_variants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status_id", sa.Integer(), sa.ForeignKey("unit_statuses.id"), nullable=False),
        sa.Column("huid_number", sa.String(50), nullable=True),
        sa.Column("weight_grams", sa.DECIMAL(10, 3), nullable=True),
        sa.Column("location_note", sa.Text(), nullable=True),
        sa.Column("order_item_id", sa.Integer(), sa.ForeignKey("order_items.id", ondelete="SET NULL"), nullable=True),
        sa.Column("sale_id", UUID(as_uuid=True), sa.ForeignKey("sales.id", ondelete="SET NULL"), nullable=True),
        sa.CheckConstraint("weight_grams IS NULL OR weight_grams > 0", name="ck_unit_weight_positive"),
    )
    op.create_index("ix_variant_physical_units_variant_id", "variant_physical_units", ["variant_id"])
    # A HUID identifies one piece in the country; optional because silver and
    # unhallmarked pieces have none (NULLs don't collide).
    op.create_index(
        "uq_variant_physical_units_huid", "variant_physical_units", ["huid_number"],
        unique=True, postgresql_where=sa.text("huid_number IS NOT NULL"),
    )

    conn.execute(sa.text("""
        CREATE FUNCTION variant_unit_stock(v uuid) RETURNS integer LANGUAGE sql STABLE AS $$
            SELECT CASE WHEN count(*) = 0 THEN NULL
                        ELSE (count(*) FILTER (WHERE s.code = 'in_stock'))::int END
            FROM variant_physical_units u JOIN unit_statuses s ON s.id = u.status_id
            WHERE u.variant_id = v
        $$
    """))
    conn.execute(sa.text("""
        CREATE FUNCTION units_sync_variant_stock() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP <> 'INSERT' THEN
                UPDATE product_variants SET stock_quantity = coalesce(variant_unit_stock(OLD.variant_id), 0)
                WHERE id = OLD.variant_id;
            END IF;
            IF TG_OP <> 'DELETE' THEN
                UPDATE product_variants SET stock_quantity = coalesce(variant_unit_stock(NEW.variant_id), 0)
                WHERE id = NEW.variant_id;
            END IF;
            RETURN NULL;
        END $$
    """))
    conn.execute(sa.text("""
        CREATE TRIGGER trg_units_sync_variant_stock
        AFTER INSERT OR UPDATE OR DELETE ON variant_physical_units
        FOR EACH ROW EXECUTE FUNCTION units_sync_variant_stock()
    """))
    conn.execute(sa.text("""
        CREATE FUNCTION variant_stock_from_units() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE n integer;
        BEGIN
            n := variant_unit_stock(NEW.id);
            IF n IS NOT NULL THEN NEW.stock_quantity := n; END IF;
            RETURN NEW;
        END $$
    """))
    conn.execute(sa.text("""
        CREATE TRIGGER trg_variant_stock_from_units
        BEFORE UPDATE OF stock_quantity ON product_variants
        FOR EACH ROW EXECUTE FUNCTION variant_stock_from_units()
    """))

    for table in ("unit_statuses", "variant_physical_units"):
        conn.execute(sa.text(f"GRANT SELECT, INSERT, UPDATE, DELETE ON public.{table} TO {ROLES}"))
        conn.execute(sa.text(f"GRANT USAGE, SELECT ON SEQUENCE public.{table}_id_seq TO {ROLES}"))

    moved = conn.execute(sa.text("""
        INSERT INTO variant_physical_units (variant_id, status_id, huid_number)
        SELECT v.id, s.id, CASE WHEN g.n = 1 THEN v.huid_number END
        FROM product_variants v
        CROSS JOIN LATERAL generate_series(1, GREATEST(coalesce(v.stock_quantity, 0), 1)) AS g(n)
        JOIN unit_statuses s ON s.code = CASE WHEN coalesce(v.stock_quantity, 0) >= g.n THEN 'in_stock' ELSE 'sold' END
        WHERE v.huid_number IS NOT NULL
        RETURNING variant_id, huid_number
    """)).fetchall()
    for variant_id, huid in moved:
        if huid:
            print(f"[0026] variant {variant_id}: HUID {huid} -> unit row")
    print(f"[0026] migrated {sum(1 for _, h in moved if h)} HUID(s) into {len(moved)} unit row(s)")


def downgrade() -> None:
    conn = op.get_bind()
    # Don't strand HUIDs: copy one back onto variants that have none.
    conn.execute(sa.text("""
        UPDATE product_variants v SET huid_number = u.huid_number
        FROM (SELECT DISTINCT ON (variant_id) variant_id, huid_number FROM variant_physical_units
              WHERE huid_number IS NOT NULL ORDER BY variant_id, id) u
        WHERE v.id = u.variant_id AND v.huid_number IS NULL
    """))
    conn.execute(sa.text("DROP TRIGGER trg_variant_stock_from_units ON product_variants"))
    conn.execute(sa.text("DROP TRIGGER trg_units_sync_variant_stock ON variant_physical_units"))
    conn.execute(sa.text("DROP FUNCTION variant_stock_from_units()"))
    conn.execute(sa.text("DROP FUNCTION units_sync_variant_stock()"))
    conn.execute(sa.text("DROP FUNCTION variant_unit_stock(uuid)"))
    op.drop_table("variant_physical_units")
    op.drop_table("unit_statuses")
