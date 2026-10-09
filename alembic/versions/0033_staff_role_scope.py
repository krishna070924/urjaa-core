"""Staff role scope + manage_catalog_setup permission (review 9).

Revision ID: 0033_staff_role_scope
Revises: 0032_pos_gst_alterations

Owner: staff see only Sales (incl. custom orders), Catalogue and Inventory,
and can create/edit products and stock. Changing catalogue setup
(categories, collections, tags, stones, metals, metal rates) moves to the
new manage_catalog_setup permission, granted to super_admin, admin and
manager. The staff role's permissions are replaced with the new set
(previously it could not even make sales).
"""

from alembic import op
from sqlalchemy import text

revision = "0033_staff_role_scope"
down_revision = "0032_pos_gst_alterations"
branch_labels = None
depends_on = None

NEW_PERMISSION = "manage_catalog_setup"
NEW_DESCRIPTION = "Set up categories, collections, tags, stones, metals and metal rates"
STAFF = ["manage_products", "manage_inventory", "manage_sales", "view_sales", "manage_orders", "view_orders"]
OLD_STAFF = ["manage_products", "manage_inventory", "manage_orders", "view_orders", "manage_customers", "view_tickets"]


def _set_role(bind, role: str, keys: list[str]) -> None:
    bind.execute(
        text("DELETE FROM admin.role_permissions WHERE role_id = (SELECT id FROM admin.roles WHERE name = :role)"),
        {"role": role},
    )
    bind.execute(
        text(
            """
            INSERT INTO admin.role_permissions (role_id, permission_id)
            SELECT r.id, p.id FROM admin.roles r JOIN admin.permissions p ON p.key = ANY(:keys)
            WHERE r.name = :role
            """
        ),
        {"role": role, "keys": keys},
    )


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        text("INSERT INTO admin.permissions (key, description) VALUES (:k, :d) ON CONFLICT (key) DO NOTHING"),
        {"k": NEW_PERMISSION, "d": NEW_DESCRIPTION},
    )
    bind.execute(
        text(
            """
            INSERT INTO admin.role_permissions (role_id, permission_id)
            SELECT r.id, p.id FROM admin.roles r, admin.permissions p
            WHERE r.name IN ('super_admin', 'admin', 'manager') AND p.key = :k
              AND NOT EXISTS (SELECT 1 FROM admin.role_permissions rp WHERE rp.role_id = r.id AND rp.permission_id = p.id)
            """
        ),
        {"k": NEW_PERMISSION},
    )
    _set_role(bind, "staff", STAFF)


def downgrade() -> None:
    bind = op.get_bind()
    _set_role(bind, "staff", OLD_STAFF)
    bind.execute(text("DELETE FROM admin.permissions WHERE key = :k"), {"k": NEW_PERMISSION})
