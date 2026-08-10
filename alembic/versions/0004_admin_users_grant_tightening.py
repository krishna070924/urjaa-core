"""Revoke urjaa_storefront's grants on admin_users entirely

URJ repo-split Task 4.2. ``admin_users`` lives in ``public`` (it wasn't moved
into the ``admin`` schema by 0002_admin_schema_isolation because
``admin_users.role_id`` has a cross-schema FK to ``admin.roles``, and because
some legacy code historically joined on it from the storefront side). That
means 0002's blanket ``GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN
SCHEMA public TO urjaa_storefront`` also covers ``admin_users`` — the
storefront's least-privilege role can currently read and write admin
credentials.

Verified (grep -rn "AdminUser" app/api/routes/*.py in the storefront route
tree) that storefront route code has zero remaining references to the
``AdminUser`` model. There is no legitimate reason for ``urjaa_storefront`` to
touch this table at all, so this migration revokes every privilege on it
(SELECT included, not just the write verbs) from that role. ``urjaa_admin_svc``
is unaffected — it keeps its full DML grant from 0002.

Revision ID: 0004_admin_users_grants
Revises: 0003_close_legacy_ddl_gaps
Create Date: 2026-08-10
"""

from sqlalchemy import text

from alembic import op

# revision identifiers, used by Alembic.
revision = "0004_admin_users_grants"
down_revision = "0003_close_legacy_ddl_gaps"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(text("REVOKE ALL ON public.admin_users FROM urjaa_storefront"))


def downgrade() -> None:
    bind = op.get_bind()
    # Symmetric with 0002's original blanket grant for admin_users' table.
    bind.execute(text("GRANT SELECT, INSERT, UPDATE, DELETE ON public.admin_users TO urjaa_storefront"))
