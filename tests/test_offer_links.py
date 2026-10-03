"""P-04: exclusive-offer banners link to a product / collection / category /
subcategory. Rolled-back transaction against the dev DB.

Run: .venv/bin/python tests/test_offer_links.py
"""
import os

os.environ.setdefault("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/urjaa")

from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.orm import Session

from urjaa_core.core.database import engine
from urjaa_core.schemas.cms_content import OfferLink
from urjaa_core.services import cms_service


def main() -> None:
    for bad in ({"kind": "product"}, {"kind": "category"}, {"kind": "product", "id": 1}, {"kind": "category", "id": 1, "product_id": "5f0c1f7e-0000-0000-0000-000000000000"}):
        try:
            OfferLink.model_validate(bad)
            raise AssertionError(f"accepted {bad}")
        except ValidationError:
            pass

    conn = engine.connect()
    outer = conn.begin()
    db = Session(bind=conn, join_transaction_mode="create_savepoint")
    try:
        product = db.execute(text("SELECT id, slug FROM products WHERE status = 'active' AND deleted_at IS NULL LIMIT 1")).one()
        sub = db.execute(text("SELECT s.id, s.slug, c.slug FROM subcategories s JOIN categories c ON c.id = s.category_id WHERE NOT c.is_deleted LIMIT 1")).one()
        cat = db.execute(text("SELECT id, slug FROM categories WHERE NOT is_deleted LIMIT 1")).one()

        current, _ = cms_service.get_page(db, "home")
        home = dict(current or {})
        home["exclusive_offers"] = {
            "slots": [
                {"image_url": None, "link": {"kind": "product", "product_id": str(product.id)}},
                {"image_url": None, "link": {"kind": "subcategory", "id": sub[0]}},
                {"image_url": None, "link": {"kind": "category", "id": cat.id}},
            ]
        }
        cms_service.save_page(db, "home", home, saved_by="t")
        slots = cms_service.resolve_home_for_storefront(db)["exclusive_offers"]["slots"]
        assert slots[0]["link"]["href"] == f"/product/{product.slug}", slots[0]
        assert slots[1]["link"]["href"] == f"/collections?category={sub[2]}&subcategory={sub[1]}", slots[1]
        assert slots[2]["link"]["href"] == f"/collections?category={cat.slug}", slots[2]

        # Deleted target -> banner stays, link drops.
        home["exclusive_offers"]["slots"][2]["link"] = {"kind": "category", "id": 987654}
        cms_service.save_page(db, "home", home, saved_by="t")
        assert cms_service.resolve_home_for_storefront(db)["exclusive_offers"]["slots"][2]["link"] is None
        print("offer links: validate, resolve, missing target  OK")
    finally:
        db.close()
        outer.rollback()
        conn.close()


if __name__ == "__main__":
    main()
