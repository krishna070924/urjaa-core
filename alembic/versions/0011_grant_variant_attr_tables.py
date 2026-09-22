"""Grant urjaa_storefront/urjaa_admin_svc on variant_attributes /
variant_type_attributes (0010 gap)

Task: docs/feature-additions-2026-09-19/variant-attribute-system/tasks/05-storefront-api-compat.md

Found while live-verifying task 05's storefront compat fix against a real
seeded cart/wishlist: 0010_variant_attribute_system created two new tables
(``variant_attributes``, ``variant_type_attributes``) and their two backing
``_id_seq`` sequences, but (unlike 0006's fix for the equivalent sequence
gap) never granted either app DB role anything on them. 0002's original
``GRANT ... ON ALL TABLES IN SCHEMA public`` was a one-time snapshot, not
``ALTER DEFAULT PRIVILEGES`` — it does not cover tables/sequences created by
later migrations. Confirmed directly: querying ``urjaa_core.services.
cart_service.CartService.get_cart`` as the live ``urjaa_storefront`` role
against a real cart_item whose variant has attribute_values raised
``psycopg2.errors.InsufficientPrivilege: permission denied for table
variant_attributes`` — independent of and in addition to the dangling
``.size`` read task 05 already fixes; without this grant, task 05's own
fix would still 500 every priced-and-attributed cart/wishlist fetch once
the urjaa-backend pin moved.

Mirrors 0002's original scope (both roles get full DML on this table, same
as every other public-schema table) and 0006's sequence-grant pattern.

Revision ID: 0011_grant_variant_attr_tables
Revises: 0010_variant_attribute_system
Create Date: 2026-09-22
"""

from sqlalchemy import text

from alembic import op

# revision identifiers, used by Alembic.
revision = "0011_grant_variant_attr_tables"
down_revision = "0010_variant_attribute_system"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        text(
            "GRANT SELECT, INSERT, UPDATE, DELETE ON public.variant_attributes, "
            "public.variant_type_attributes TO urjaa_storefront, urjaa_admin_svc"
        )
    )
    bind.execute(
        text(
            "GRANT USAGE, SELECT ON SEQUENCE public.variant_attributes_id_seq, "
            "public.variant_type_attributes_id_seq TO urjaa_storefront, urjaa_admin_svc"
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        text(
            "REVOKE ALL ON SEQUENCE public.variant_attributes_id_seq, "
            "public.variant_type_attributes_id_seq FROM urjaa_storefront, urjaa_admin_svc"
        )
    )
    bind.execute(
        text(
            "REVOKE ALL ON public.variant_attributes, public.variant_type_attributes "
            "FROM urjaa_storefront, urjaa_admin_svc"
        )
    )
