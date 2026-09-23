"""AdminManagementService._duplicate_sku is the one piece of non-trivial branch
logic in duplicate_product that doesn't need a DB to exercise (same -COPY,
-COPY-2, ... collision-avoidance loop as VariantManager.tsx's buildDuplicateSku,
now run server-side for bulk product duplication). The rest of duplicate_product
is an ORM clone flow, covered by the live click-through in AGENT_LOG.md instead.
"""

import os

# admin_management_service transitively imports urjaa_core.core.database, which
# builds a SQLAlchemy engine from DATABASE_URL at import time (lazily connects,
# so a placeholder is fine for this DB-free unit test).
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from urjaa_core.services.admin.admin_management_service import AdminManagementService

_duplicate_sku = AdminManagementService._duplicate_sku


def test_duplicate_sku_appends_copy_suffix():
    assert _duplicate_sku("RING-001", set()) == "RING-001-COPY"


def test_duplicate_sku_avoids_collision():
    existing = {"ring-001-copy"}
    assert _duplicate_sku("RING-001", existing) == "RING-001-COPY-2"


def test_duplicate_sku_avoids_multiple_collisions():
    existing = {"ring-001-copy", "ring-001-copy-2", "ring-001-copy-3"}
    assert _duplicate_sku("RING-001", existing) == "RING-001-COPY-4"


def test_duplicate_sku_falls_back_when_seed_blank():
    assert _duplicate_sku(None, set()) == "VARIANT-COPY"
    assert _duplicate_sku("  ", set()) == "VARIANT-COPY"


if __name__ == "__main__":
    test_duplicate_sku_appends_copy_suffix()
    test_duplicate_sku_avoids_collision()
    test_duplicate_sku_avoids_multiple_collisions()
    test_duplicate_sku_falls_back_when_seed_blank()
    print("OK")
