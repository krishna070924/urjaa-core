"""Seed the admin RBAC catalog (permissions, roles, role_permissions)

URJ repo-split Task 4.2 follow-up. Critical finding from review: deleting
`ensure_admin_auth_schema` from `urjaa-backend`'s startup hooks (this task,
earlier commit) removed the *only* code path across the split repos that
populated `admin.permissions` / `admin.roles` / `admin.role_permissions`.
`urjaa-admin-backend` has zero startup hooks and no seeding logic of its own
— confirmed by grepping its route tree: `bootstrap.py`'s only route
(`GET /admin/stores/bootstrap`) is a store-listing endpoint gated behind an
existing admin login, not a first-run seeding path, and
`admin_management.py` / `users.py` have no unauthenticated route either. A
fresh repo-split deployment was left with an empty RBAC catalog and no way
to populate it.

This migration restores exactly the catalog-seeding half of the old
`ensure_admin_auth_bootstrap` (the permission descriptions, role
descriptions, and role→permission-set mappings) as an idempotent Alembic
DATA migration, using `ON CONFLICT DO NOTHING` so it's safe to run against a
DB that already has some/all of this data (e.g. re-running on an
environment migrated before this fix landed).

Deliberately NOT restored here: the old hook's *default AdminUser* creation
(env-var-driven `ADMIN_DEFAULT_EMAIL`/`ADMIN_DEFAULT_PASSWORD`, falling back
to the hardcoded `admin@urjaa.local` / `admin123` when those env vars were
unset). That is a checked-in-adjacent default-credential pattern — a
migration is version-controlled, so a fallback password embedded in its
logic is effectively a shared secret in source control, and this specific
default (`admin@urjaa.local`) is already known-broken by a separate rule
elsewhere in this codebase (admin login rejects non-public-domain emails,
URJ-067) — restoring it here would not even produce a working login.
Flagged back to the task owner as its own decision point rather than
silently reintroducing it (see task-4.2-report.md addendum #2 for detail):
this codebase currently has **no** legitimate "create the first admin"
mechanism anywhere in the split repos (`POST /admin/users` in
`urjaa-admin-backend` requires an already-authenticated admin with
`manage_admin_users`, so it cannot bootstrap the very first account).

The permission/role/mapping data is imported directly from
`urjaa_core.core.admin_auth` (`ADMIN_PERMISSION_DESCRIPTIONS`,
`ROLE_DESCRIPTIONS`, `DEFAULT_ROLE_PERMISSIONS`) rather than hand-copied, so
this migration can never drift from what the application actually defines
as the current catalog shape at the time it runs.

Revision ID: 0005_seed_admin_rbac
Revises: 0004_admin_users_grants
Create Date: 2026-08-10
"""

from sqlalchemy import text

from alembic import op

# revision identifiers, used by Alembic.
revision = "0005_seed_admin_rbac"
down_revision = "0004_admin_users_grants"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from urjaa_core.core.admin_auth import (
        ADMIN_PERMISSION_DESCRIPTIONS,
        DEFAULT_ROLE_PERMISSIONS,
        ROLE_DESCRIPTIONS,
    )

    bind = op.get_bind()

    for key, description in ADMIN_PERMISSION_DESCRIPTIONS.items():
        bind.execute(
            text(
                """
                INSERT INTO admin.permissions (key, description)
                VALUES (:key, :description)
                ON CONFLICT (key) DO NOTHING
                """
            ).bindparams(key=key, description=description)
        )

    for role_name, description in ROLE_DESCRIPTIONS.items():
        bind.execute(
            text(
                """
                INSERT INTO admin.roles (name, description)
                VALUES (:name, :description)
                ON CONFLICT (name) DO NOTHING
                """
            ).bindparams(name=role_name, description=description)
        )

    for role_name, permission_keys in DEFAULT_ROLE_PERMISSIONS.items():
        for permission_key in sorted(permission_keys):
            bind.execute(
                text(
                    """
                    INSERT INTO admin.role_permissions (role_id, permission_id)
                    SELECT r.id, p.id
                    FROM admin.roles r, admin.permissions p
                    WHERE r.name = :role_name AND p.key = :permission_key
                    ON CONFLICT (role_id, permission_id) DO NOTHING
                    """
                ).bindparams(role_name=role_name, permission_key=permission_key)
            )


def downgrade() -> None:
    from urjaa_core.core.admin_auth import (
        ADMIN_PERMISSION_DESCRIPTIONS,
        DEFAULT_ROLE_PERMISSIONS,
        ROLE_DESCRIPTIONS,
    )

    bind = op.get_bind()

    for role_name, permission_keys in DEFAULT_ROLE_PERMISSIONS.items():
        for permission_key in permission_keys:
            bind.execute(
                text(
                    """
                    DELETE FROM admin.role_permissions
                    USING admin.roles r, admin.permissions p
                    WHERE admin.role_permissions.role_id = r.id
                      AND admin.role_permissions.permission_id = p.id
                      AND r.name = :role_name
                      AND p.key = :permission_key
                    """
                ).bindparams(role_name=role_name, permission_key=permission_key)
            )

    for role_name in ROLE_DESCRIPTIONS:
        bind.execute(
            text("DELETE FROM admin.roles WHERE name = :name").bindparams(name=role_name)
        )

    for key in ADMIN_PERMISSION_DESCRIPTIONS:
        bind.execute(
            text("DELETE FROM admin.permissions WHERE key = :key").bindparams(key=key)
        )
