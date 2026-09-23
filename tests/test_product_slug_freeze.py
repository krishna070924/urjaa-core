"""Self-check for the slug-freeze-on-publish behavior.

Root cause: update_product() used to regenerate product.slug from the name
on every rename, regardless of status. Decided fix (see
docs/feature-additions-2026-09-19/hide-slug/TICKET.md): keep auto-following
the name while status == "draft"; freeze the slug forever once the product
first becomes non-draft.
"""

import os
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

# admin_management_service transitively imports urjaa_core.core.database, which
# builds a SQLAlchemy engine from DATABASE_URL at import time (lazily connects,
# so a placeholder is fine for this DB-free, mocked-repository test).
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from urjaa_core.schemas.admin.management import ProductUpdateRequest
from urjaa_core.services.admin.admin_management_service import AdminManagementService


def _make_product(name: str, slug: str, status: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        name=name,
        slug=slug,
        status=status,
        subcategory=None,
        subcategory_id=None,
    )


def _update(product, name: str, status: str | None = None):
    db = MagicMock()
    payload = ProductUpdateRequest(name=name, status=status)
    with patch(
        "urjaa_core.services.admin.admin_management_service.AdminManagementRepository"
    ) as repo:
        repo.get_product_by_id.return_value = product
        repo.get_product_by_slug.return_value = None  # no collision -> slug used as-is
        return AdminManagementService.update_product(db, uuid4(), product.id, payload)


def demo() -> None:
    # Draft: slug keeps following renames.
    product = _make_product("Ruby Ring", "ruby-ring", "draft")
    _update(product, "Ruby Band")
    assert product.slug == "ruby-band", product.slug
    _update(product, "Ruby Band Deluxe")
    assert product.slug == "ruby-band-deluxe", product.slug

    # Publish: slug freezes on the same rename that flips status non-draft
    # only if the pre-update status was still draft (it was), then any
    # rename afterwards must NOT touch the slug.
    _update(product, "Ruby Band Deluxe", status="active")
    frozen_slug = product.slug
    _update(product, "Totally Different Name")
    assert product.slug == frozen_slug, (
        f"slug should stay frozen after publish, got {product.slug!r}"
    )
    assert product.name == "Totally Different Name"


if __name__ == "__main__":
    demo()
    print("OK")
