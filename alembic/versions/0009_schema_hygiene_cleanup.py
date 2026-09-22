"""Schema hygiene cleanup: drop duplicate columns, fix ORM/DB drift on indexes
and junction-table uniqueness

Ticket: docs/feature-additions-2026-09-19/schema-hygiene-cleanup/TICKET.md

Two genuine duplicate columns, confirmed dead by grepping every read/write
site in urjaa-core, urjaa-backend, and urjaa-admin-backend:

- ``stores.location`` (bare, unstructured ``TEXT``) is superseded by the
  structured ``store_locations`` table that actually powers the public
  "Our Stores" page. Beyond the two write sites the ticket named
  (``admin_management.py:159``, ``bootstrap.py``), this cleanup also found
  and removed: two more ``bootstrap.py`` read sites, the
  ``StoreCreateRequest``/``StoreUpdateRequest``/``AdminStoreResponse``
  schema fields (``urjaa_core/schemas/admin/management.py``), the
  create/edit "Location" form field and table column in
  ``urjaa-admin-frontend`` (``StoreManagementPage.tsx``, the first-store
  bootstrap modal in ``StoreContext.tsx``, ``adminApi.ts``,
  ``types/admin.ts``), and a read-only fallback in the dev-only
  ``seed_multistore_data.py`` utility (replaced with the literal "Unknown"
  it already evaluated to when location was unset).
- ``order_items.price`` duplicates ``unit_price`` exactly — both
  construction sites (``order_service.py``, ``checkout_service.py``) always
  wrote the identical value to both columns. Also found and fixed a real
  dangling reference the ticket didn't name:
  ``urjaa_core/schemas/order.py``'s ``OrderItemResponse.price`` field reads
  this column via ``orm_mode``/``getattr`` — dropping the column without
  fixing this would have broken every "get order" API response. Renamed
  that response field to ``unit_price`` (the surviving, always-identical
  column); confirmed no frontend code actually consumes either field name
  today (``ApiOrderItem.price``/``unit_price`` are both optional and
  unused), so this is a safe, lossless rename.

The other three items in the ticket (missing ``index=True`` on 4
``product_id`` FK columns; missing ``UniqueConstraint`` on 4 M2M junction
tables) turned out to **already be satisfied at the database level** —
confirmed via ``\\d`` against the live dev DB, not guessed:

- ``idx_product_variants_product``, ``idx_product_images_product_id``,
  ``idx_product_attributes_product``, ``idx_product_stones_product`` all
  already exist, created by the original ``0001_baseline_schema.sql``
  pg_dump replay.
- ``uq_product_attributes_product_attribute_value``,
  ``uq_product_collections_product_collection``,
  ``uq_product_stones_product_stone``, ``uq_product_tags_product_tag`` all
  already exist too, same origin.

The SQLAlchemy **model files** just never declared them (a one-directional
drift: DB ahead of the ORM, the opposite of what 0003 fixed for
users/carts/orders), so ``urjaa_core/models/product_variant.py``,
``product_image.py``, ``product_attribute.py``, ``product_stone.py``,
``product_collection.py``, and ``product_tag.py`` were updated to declare
``index=True`` / ``UniqueConstraint(..., name=...)`` matching the exact
existing DB object names — this migration does **not** re-create any of
those (would either error as a duplicate constraint name or, worse, silently
create a redundant duplicate index under a different auto-generated name).

``metal_rates`` is the one genuinely missing piece: only an index
(``idx_metal_rates_lookup``, not unique) exists on
``(base_metal_id, effective_from)`` — no uniqueness guarantee. Confirmed 0
existing rows and 0 duplicate ``(base_metal_id, effective_from)`` pairs
before adding the constraint, so no backfill/cleanup needed.

Confirmed via row counts immediately before writing this migration:
``stores`` has 1 row (no ``location`` value to lose), ``order_items`` and
``metal_rates`` are both empty. Low-volume dev DB, same low-risk pattern as
prior migrations this session.

Coordination note: chains onto ``0008_drop_customers_table``, which is
present in this checkout's working tree and already applied to the shared
dev DB (``alembic_version`` confirmed at that revision) but was **not**
committed to git by this session — that is separate, unrelated work
(dropping the orphaned ``customers`` table) from another in-flight branch.
If that branch merges into ``dev`` after this one, its migration's
``down_revision`` will need rebasing onto this revision instead of 0007.

Revision ID: 0009_schema_hygiene_cleanup
Revises: 0008_drop_customers_table
Create Date: 2026-09-22
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "0009_schema_hygiene_cleanup"
down_revision = "0008_drop_customers_table"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("stores", "location")

    op.drop_constraint("chk_order_items_price_non_negative", "order_items", type_="check")
    op.drop_column("order_items", "price")

    op.create_unique_constraint(
        "uq_metal_rates_base_metal_effective_from",
        "metal_rates",
        ["base_metal_id", "effective_from"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_metal_rates_base_metal_effective_from", "metal_rates", type_="unique")

    op.add_column("order_items", sa.Column("price", sa.Numeric(12, 2), nullable=False, server_default="0"))
    op.create_check_constraint("chk_order_items_price_non_negative", "order_items", "price >= 0")
    # Backfill from unit_price (the two columns were always written identical
    # in every code path that constructed an OrderItem), then drop the
    # temporary default now that every row has a real value.
    op.execute("UPDATE order_items SET price = unit_price")
    op.alter_column("order_items", "price", server_default=None)

    op.add_column("stores", sa.Column("location", sa.Text(), nullable=True))
