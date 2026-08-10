"""Grant sequence USAGE to urjaa_storefront / urjaa_admin_svc (0002 gap)

URJ repo-split Task 4.2 follow-up. Found while verifying 0005's RBAC seed
migration end-to-end: `0002_admin_schema_isolation`'s
`GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public/admin
TO ...` does NOT cover sequences — in Postgres, sequences are a distinct
object type from tables, and `ALL TABLES` grants never include them. Every
serial/integer-PK table (``admin_users``, ``categories``, ``customers``,
``admin.permissions``, ``admin.roles``, etc.) has been silently uninsertable
by both DB roles since 0002 landed: an `INSERT` into any such table fails
with `permission denied for sequence <table>_id_seq`, independent of the
DDL-vs-DML distinction this whole task chain has been about — this is a
missing GRANT, not DDL.

Reproduced directly: inserting a test `AdminUser` as `urjaa_admin_svc` (the
role that's supposed to have full DML on `admin_users`) failed with
`psycopg2.errors.InsufficientPrivilege: permission denied for sequence
admin_users_id_seq` prior to this migration.

Grants `USAGE, SELECT` on every sequence in `public` to both
`urjaa_storefront` and `urjaa_admin_svc` (mirroring 0002's `ALL TABLES IN
SCHEMA public` scope for both roles), and on every sequence in `admin` to
`urjaa_admin_svc` only (mirroring 0002's `ALL TABLES IN SCHEMA admin` scope,
which is admin-service-only).

Revision ID: 0006_grant_sequence_usage
Revises: 0005_seed_admin_rbac
Create Date: 2026-08-10
"""

from sqlalchemy import text

from alembic import op

# revision identifiers, used by Alembic.
revision = "0006_grant_sequence_usage"
down_revision = "0005_seed_admin_rbac"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        text("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO urjaa_storefront, urjaa_admin_svc")
    )
    bind.execute(text("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA admin TO urjaa_admin_svc"))
    # Belt-and-braces, matching 0002's explicit boundary statement for admin_users' schema.
    bind.execute(text("REVOKE ALL ON ALL SEQUENCES IN SCHEMA admin FROM urjaa_storefront"))
    # Symmetric with 0004_admin_users_grants' table-level REVOKE ALL: don't leave
    # urjaa_storefront with USAGE on the one public-schema sequence that backs a
    # table it has zero access to.
    bind.execute(text("REVOKE ALL ON SEQUENCE public.admin_users_id_seq FROM urjaa_storefront"))


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(text("REVOKE ALL ON ALL SEQUENCES IN SCHEMA admin FROM urjaa_admin_svc"))
    bind.execute(text("REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM urjaa_storefront, urjaa_admin_svc"))
