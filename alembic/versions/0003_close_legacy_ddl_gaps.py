"""Close legacy startup-hook DDL gaps in the 0001 baseline (users/carts/orders)

URJ repo-split Task 4.2. ``urjaa-backend``'s legacy ``@app.on_event("startup")``
hooks (inherited from the pre-repo-split monorepo, predating Alembic being the
schema source of truth) ran raw ``ALTER TABLE`` / ``CREATE TABLE`` / ``CREATE
INDEX`` DDL on every boot to converge the schema. Under the new least-privilege
``urjaa_storefront`` role (URJ-004/4.1, DML-only grants) those hooks fail with
``InsufficientPrivilege`` and hard-block the backend from booting at all.

Auditing every ``ensure_*`` hook against ``0001_baseline_schema.sql`` found it
covers all of them *except* three tables, where the hooks quietly patch columns/
indexes/constraints that the pg_dump-derived baseline never captured (these
columns are live, in-use SQLAlchemy ORM columns — not dead legacy cruft):

- ``users``: missing ``provider``, ``provider_id``, ``source``, ``last_store_id``,
  ``address``, ``feedback`` columns; the ``users_last_store_id_fkey`` FK; the
  ``users_source_check`` CHECK; and five indexes (``idx_users_last_store_id``,
  ``ix_users_source``, ``ix_users_provider``, ``ix_users_provider_id``,
  ``uq_users_provider_provider_id``).
- ``carts``: missing the ``uq_carts_user_id_not_null`` partial unique index
  (one cart per logged-in user).
- ``orders``: missing ``currency``, ``payment_status``, ``cancelled_at``
  columns and the ``idx_orders_payment_status`` index. (The
  ``order_payment_status`` enum TYPE itself *was* captured by the baseline —
  line 75-78 of 0001 — it was just never attached to a column.)

This migration adds exactly those columns/constraints/indexes, matching the
final shape the legacy hooks produced (verified statement-by-statement against
``urjaa_core/core/user_auth.py::ensure_user_auth_schema``,
``urjaa-backend/app/core/cart.py::ensure_cart_schema``, and
``urjaa-backend/app/core/website_features.py::ensure_website_feature_schema``),
so those hooks — and the redundant ``ensure_hidden_product_status_enum``,
``ensure_order_schema``, ``ensure_user_preferences_schema`` hooks, and the DDL
portion of ``ensure_admin_auth_bootstrap`` — can be safely deleted from
``urjaa-backend``'s startup path. Confirmed the dev/local Postgres used for
verification holds only dummy data, so no backward-compatible backfill logic is
needed here — nullable/defaulted columns are simply added.

Revision ID: 0003_close_legacy_ddl_gaps
Revises: 0002_admin_schema_isolation
Create Date: 2026-08-10
"""

from sqlalchemy import text

from alembic import op

# revision identifiers, used by Alembic.
revision = "0003_close_legacy_ddl_gaps"
down_revision = "0002_admin_schema_isolation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    # --- users -------------------------------------------------------------
    bind.execute(text("ALTER TABLE public.users ADD COLUMN IF NOT EXISTS provider VARCHAR(32)"))
    bind.execute(text("ALTER TABLE public.users ADD COLUMN IF NOT EXISTS provider_id VARCHAR(255)"))
    bind.execute(text("ALTER TABLE public.users ADD COLUMN IF NOT EXISTS source VARCHAR(16)"))
    bind.execute(text("ALTER TABLE public.users ADD COLUMN IF NOT EXISTS last_store_id UUID"))
    bind.execute(text("ALTER TABLE public.users ADD COLUMN IF NOT EXISTS address TEXT"))
    bind.execute(text("ALTER TABLE public.users ADD COLUMN IF NOT EXISTS feedback TEXT"))

    bind.execute(text("UPDATE public.users SET provider = 'local' WHERE provider IS NULL"))
    bind.execute(text("UPDATE public.users SET source = 'WEBSITE' WHERE source IS NULL"))

    bind.execute(text("ALTER TABLE public.users ALTER COLUMN provider SET DEFAULT 'local'"))
    bind.execute(text("ALTER TABLE public.users ALTER COLUMN provider SET NOT NULL"))
    bind.execute(text("ALTER TABLE public.users ALTER COLUMN source SET DEFAULT 'WEBSITE'"))
    bind.execute(text("ALTER TABLE public.users ALTER COLUMN source SET NOT NULL"))

    bind.execute(
        text(
            """
            ALTER TABLE public.users
            ADD CONSTRAINT users_last_store_id_fkey
            FOREIGN KEY (last_store_id) REFERENCES public.stores(id) ON DELETE SET NULL
            """
        )
    )
    bind.execute(
        text(
            """
            ALTER TABLE public.users
            ADD CONSTRAINT users_source_check
            CHECK (source IN ('WEBSITE', 'STORE', 'ADMIN'))
            """
        )
    )

    bind.execute(text("CREATE INDEX idx_users_last_store_id ON public.users(last_store_id)"))
    bind.execute(text("CREATE INDEX ix_users_source ON public.users(source)"))
    bind.execute(text("CREATE INDEX ix_users_provider ON public.users(provider)"))
    bind.execute(text("CREATE INDEX ix_users_provider_id ON public.users(provider_id)"))
    bind.execute(
        text(
            """
            CREATE UNIQUE INDEX uq_users_provider_provider_id
            ON public.users (provider, provider_id)
            WHERE provider_id IS NOT NULL
            """
        )
    )

    # --- carts ---------------------------------------------------------------
    bind.execute(
        text(
            """
            CREATE UNIQUE INDEX uq_carts_user_id_not_null
            ON public.carts (user_id)
            WHERE user_id IS NOT NULL
            """
        )
    )

    # --- orders --------------------------------------------------------------
    # order_payment_status ENUM type already exists in the 0001 baseline
    # (created but never attached to a column) — reuse it here.
    bind.execute(text("ALTER TABLE public.orders ADD COLUMN IF NOT EXISTS currency VARCHAR(3)"))
    bind.execute(
        text("ALTER TABLE public.orders ADD COLUMN IF NOT EXISTS payment_status public.order_payment_status")
    )
    bind.execute(text("ALTER TABLE public.orders ADD COLUMN IF NOT EXISTS cancelled_at TIMESTAMP"))

    bind.execute(text("UPDATE public.orders SET currency = 'INR' WHERE currency IS NULL"))
    bind.execute(text("UPDATE public.orders SET payment_status = 'unpaid' WHERE payment_status IS NULL"))

    bind.execute(text("ALTER TABLE public.orders ALTER COLUMN currency SET DEFAULT 'INR'"))
    bind.execute(text("ALTER TABLE public.orders ALTER COLUMN currency SET NOT NULL"))
    bind.execute(text("ALTER TABLE public.orders ALTER COLUMN payment_status SET DEFAULT 'unpaid'"))
    bind.execute(text("ALTER TABLE public.orders ALTER COLUMN payment_status SET NOT NULL"))

    bind.execute(text("CREATE INDEX idx_orders_payment_status ON public.orders(payment_status)"))


def downgrade() -> None:
    bind = op.get_bind()

    bind.execute(text("DROP INDEX IF EXISTS public.idx_orders_payment_status"))
    bind.execute(text("ALTER TABLE public.orders DROP COLUMN IF EXISTS cancelled_at"))
    bind.execute(text("ALTER TABLE public.orders DROP COLUMN IF EXISTS payment_status"))
    bind.execute(text("ALTER TABLE public.orders DROP COLUMN IF EXISTS currency"))

    bind.execute(text("DROP INDEX IF EXISTS public.uq_carts_user_id_not_null"))

    bind.execute(text("DROP INDEX IF EXISTS public.uq_users_provider_provider_id"))
    bind.execute(text("DROP INDEX IF EXISTS public.ix_users_provider_id"))
    bind.execute(text("DROP INDEX IF EXISTS public.ix_users_provider"))
    bind.execute(text("DROP INDEX IF EXISTS public.ix_users_source"))
    bind.execute(text("DROP INDEX IF EXISTS public.idx_users_last_store_id"))
    bind.execute(text("ALTER TABLE public.users DROP CONSTRAINT IF EXISTS users_source_check"))
    bind.execute(text("ALTER TABLE public.users DROP CONSTRAINT IF EXISTS users_last_store_id_fkey"))
    bind.execute(text("ALTER TABLE public.users DROP COLUMN IF EXISTS feedback"))
    bind.execute(text("ALTER TABLE public.users DROP COLUMN IF EXISTS address"))
    bind.execute(text("ALTER TABLE public.users DROP COLUMN IF EXISTS last_store_id"))
    bind.execute(text("ALTER TABLE public.users DROP COLUMN IF EXISTS source"))
    bind.execute(text("ALTER TABLE public.users DROP COLUMN IF EXISTS provider_id"))
    bind.execute(text("ALTER TABLE public.users DROP COLUMN IF EXISTS provider"))
