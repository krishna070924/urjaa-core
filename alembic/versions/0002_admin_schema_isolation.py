"""Move admin RBAC tables into an admin schema, create GRANT-scoped DB roles

URJ repo-split Task 4.1. Moves the three pure-RBAC tables (``permissions``,
``roles``, ``role_permissions`` — the ORM classes are named ``AdminPermission``,
``AdminRole``, ``AdminRolePermission``) into a new Postgres ``admin`` schema and
creates two DB roles:

- ``urjaa_storefront``: used by the storefront backend. Gets full DML on
  ``public`` but NO grants on ``admin`` at all (explicit REVOKE, belt-and-braces
  against default-privilege surprises). This is a structural boundary: even a
  fully compromised storefront app process, using this DB role, cannot read or
  write the RBAC tables.
- ``urjaa_admin_svc``: used by the admin backend. Gets full DML on both
  ``public`` and ``admin``.

Confirmed in earlier repo-split phases that ``permissions``/``roles``/
``role_permissions`` have zero storefront-side code access. The one existing
cross-schema reference is ``admin_users.role_id -> roles.id`` (an admin-only
table), which remains a valid FK across schemas after the move.

Role passwords are NOT hardcoded here. They are read at migration-run time
from the ``STOREFRONT_DB_PASSWORD`` / ``ADMIN_DB_PASSWORD`` environment
variables, following the same env-var-driven secret convention this repo's
``alembic/env.py`` already uses for ``DATABASE_URL``. CI / deploy is expected
to set those two variables before running ``alembic upgrade head``.

Revision ID: 0002_admin_schema_isolation
Revises: 0001
Create Date: 2026-08-10
"""

import os

from sqlalchemy import text

from alembic import op

# revision identifiers, used by Alembic.
revision = "0002_admin_schema_isolation"
down_revision = "0001"
branch_labels = None
depends_on = None

_MOVED_TABLES = ("permissions", "roles", "role_permissions")


def _require_password(env_var: str) -> str:
    value = os.getenv(env_var)
    if not value:
        raise RuntimeError(
            f"{env_var} is not set. This migration creates DB roles with "
            f"passwords sourced from the environment (never hardcoded in the "
            f"migration file) — set {env_var} before running "
            f"'alembic upgrade head'."
        )
    return value


def upgrade() -> None:
    bind = op.get_bind()

    # Fail fast, before any DDL, if the role passwords aren't available.
    storefront_pw = _require_password("STOREFRONT_DB_PASSWORD")
    admin_pw = _require_password("ADMIN_DB_PASSWORD")

    bind.execute(text("CREATE SCHEMA IF NOT EXISTS admin"))
    for table in _MOVED_TABLES:
        bind.execute(text(f"ALTER TABLE public.{table} SET SCHEMA admin"))

    # CREATE ROLE does not support bind parameters for identifiers/literals in
    # a DO block the way DML does, so build the DO $$ ... $$ body with the
    # password values substituted client-side (never written to the migration
    # source; only present in memory for this run) rather than embedded in
    # this file.
    bind.execute(
        text(
            """
            DO $do$
            BEGIN
                IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'urjaa_storefront') THEN
                    EXECUTE format('CREATE ROLE urjaa_storefront LOGIN PASSWORD %L', :storefront_pw);
                END IF;
                IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'urjaa_admin_svc') THEN
                    EXECUTE format('CREATE ROLE urjaa_admin_svc LOGIN PASSWORD %L', :admin_pw);
                END IF;
            END
            $do$;
            """
        ).bindparams(storefront_pw=storefront_pw, admin_pw=admin_pw)
    )

    bind.execute(text("GRANT USAGE ON SCHEMA public TO urjaa_storefront, urjaa_admin_svc"))
    bind.execute(
        text(
            "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public "
            "TO urjaa_storefront, urjaa_admin_svc"
        )
    )
    bind.execute(text("GRANT USAGE ON SCHEMA admin TO urjaa_admin_svc"))
    bind.execute(
        text("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA admin TO urjaa_admin_svc")
    )
    # Belt-and-braces: urjaa_storefront never had admin grants, but make the
    # boundary explicit and immune to future default-privilege changes.
    bind.execute(text("REVOKE ALL ON SCHEMA admin FROM urjaa_storefront"))


def downgrade() -> None:
    bind = op.get_bind()
    for table in _MOVED_TABLES:
        bind.execute(text(f"ALTER TABLE admin.{table} SET SCHEMA public"))
    bind.execute(text("DROP SCHEMA IF EXISTS admin"))
    # Deliberately not dropping urjaa_storefront/urjaa_admin_svc roles here:
    # they may own other objects or be referenced by live connections outside
    # this migration's transaction, and DROP ROLE is not safely reversible in
    # an automated downgrade. Reversing the schema move (the security-relevant
    # part) is sufficient for downgrade correctness.
