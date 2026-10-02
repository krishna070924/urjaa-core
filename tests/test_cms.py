"""N-03 self-check against the live dev database, as both app DB roles.
cms_service commits internally (same convention as AdminManagementService),
so the session is joined to an outer transaction via savepoints and
everything is rolled back at the end — no fixture ever lands for real.

Run: .venv/bin/python tests/test_cms.py
"""
import os
import uuid
from decimal import Decimal

os.environ.setdefault("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/urjaa")

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.orm import Session

from urjaa_core.core.database import engine
from urjaa_core.models import Discount, DiscountProduct, Product, ProductVariant, Store
from urjaa_core.services import cms_service

CATEGORY_IDS = [1, 2, 3, 4]  # Rings, Necklaces, Earrings, Bangles & Bracelets — dev seed data
COLLECTION_IDS = [1, 2, 3, 4]
STONE_IDS = [2, 4, 5, 7]  # Polki, Emerald, Blue Sapphire, Pearl — see cms_content.py for the mapping


def _home_payload(product_ids: list[str]) -> dict:
    base = "http://localhost:8000/media"
    best_sellers = product_ids[:1]
    deck = product_ids[1:2] if len(product_ids) > 1 else []
    return {
        "hero": {"media_type": "image", "media_url": f"{base}/urjaa/cms/hero.jpg", "poster_url": None},
        "shop_by_category": [{"category_id": CATEGORY_IDS[0], "image_url": None}],
        "deck": {"product_ids": deck},
        "exclusive_offers": {"slots": [{}, {}, {}]},
        "best_sellers": {"product_ids": best_sellers},
        "curated_collections": {"tiles": [{"collection_id": cid, "image_url": None} for cid in COLLECTION_IDS]},
        "for_her_him": {"her_image_url": None, "him_image_url": None},
        "shop_by_occasion": {"bridal": None, "festive": None, "gifting": None, "everyday": None},
        "stone_stories": {"tiles": [{"stone_id": sid, "image_url": None} for sid in STONE_IDS]},
        "curated_by_urjaa": {"product_ids": []},
        "craftsmanship": {"slots": [{}, {}]},
    }


def _make_product(db: Session, store_id, *, price_override: str) -> uuid.UUID:
    product = Product(
        store_id=store_id,
        name="CMS test product",
        slug=f"cms-test-{uuid.uuid4().hex[:10]}",
        status="active",
    )
    db.add(product)
    db.flush()
    variant = ProductVariant(
        store_id=store_id,
        product_id=product.id,
        price_override=Decimal(price_override),
        sku_code=f"CMS-{uuid.uuid4().hex[:8]}",
    )
    db.add(variant)
    db.flush()
    return product.id


def test_valid_save_round_trips(db: Session, store_id) -> None:
    pid = _make_product(db, store_id, price_override="15000.00")
    content, warnings = cms_service.save_page(db, "home", _home_payload([str(pid)]), saved_by="tester@urjaa.test")
    assert warnings == [], warnings
    assert content["hero"]["media_url"].endswith("/urjaa/cms/hero.jpg")
    current, versions = cms_service.get_page(db, "home")
    assert current == content
    assert versions == []
    print("valid save round-trips                          OK")


def test_text_field_on_home_rejected(db: Session) -> None:
    payload = _home_payload([])
    payload["hero"]["caption"] = "Not allowed under D38"
    try:
        cms_service.save_page(db, "home", payload, saved_by="tester@urjaa.test")
        raise AssertionError("expected rejection of an unknown/text field")
    except HTTPException as exc:
        assert exc.status_code == 422, exc.detail
    print("text field on Home rejected                     OK")


def test_foreign_url_rejected(db: Session) -> None:
    payload = _home_payload([])
    payload["hero"]["media_url"] = "https://evil-cdn.example.com/hero.mp4"
    try:
        cms_service.save_page(db, "home", payload, saved_by="tester@urjaa.test")
        raise AssertionError("expected rejection of a foreign-host URL")
    except HTTPException as exc:
        assert exc.status_code == 422, exc.detail
    print("foreign URL rejected                            OK")


def test_sixth_save_keeps_only_five_versions(db: Session, store_id) -> None:
    pid = _make_product(db, store_id, price_override="12000.00")
    last_content = None
    for i in range(6):
        payload = _home_payload([str(pid)])
        # vary something harmless per save so each version is distinguishable
        payload["shop_by_category"] = [{"category_id": CATEGORY_IDS[0], "image_url": None}] if i % 2 == 0 else []
        last_content, _ = cms_service.save_page(db, "home", payload, saved_by=f"tester{i}@urjaa.test")

    current, versions = cms_service.get_page(db, "home")
    assert current == last_content
    assert len(versions) == 5, versions
    assert [v["index"] for v in versions] == [0, 1, 2, 3, 4]
    print("6th save keeps only 5 versions                   OK")


def test_restore_works(db: Session, store_id) -> None:
    pid = _make_product(db, store_id, price_override="9000.00")

    payload_a = _home_payload([str(pid)])
    payload_a["shop_by_category"] = [{"category_id": CATEGORY_IDS[0], "image_url": None}]
    content_a, _ = cms_service.save_page(db, "home", payload_a, saved_by="a@urjaa.test")

    payload_b = _home_payload([str(pid)])
    payload_b["shop_by_category"] = []
    content_b, _ = cms_service.save_page(db, "home", payload_b, saved_by="b@urjaa.test")

    current, versions = cms_service.get_page(db, "home")
    assert current == content_b
    assert len(versions) >= 1
    # version[0] should be content_a (the one pushed down by saving content_b)
    assert versions[0]["saved_by"] == "a@urjaa.test"

    restored, warnings = cms_service.restore_version(db, "home", 0, saved_by="restorer@urjaa.test")
    assert restored == content_a, "restore should bring back content_a's exact content"
    assert warnings == []

    current_after, versions_after = cms_service.get_page(db, "home")
    assert current_after == content_a
    # content_b (what was current right before the restore) should now be in versions
    assert any(v["saved_by"] == "b@urjaa.test" for v in versions_after)
    print("restore works                                    OK")


def test_storefront_skips_deleted_and_applies_discount(db: Session, store_id) -> None:
    kept_pid = _make_product(db, store_id, price_override="20000.00")
    doomed_pid = _make_product(db, store_id, price_override="5000.00")

    # 20% off, scoped to just this product so the test can't affect anything else.
    discount = Discount(store_id=store_id, name="CMS test discount", percent=Decimal("20.00"), is_active=True)
    db.add(discount)
    db.flush()
    db.add(DiscountProduct(discount_id=discount.id, product_id=kept_pid))
    db.flush()

    payload = _home_payload([])
    payload["best_sellers"] = {"product_ids": [str(kept_pid), str(doomed_pid)]}
    cms_service.save_page(db, "home", payload, saved_by="tester@urjaa.test")

    # Simulate the product being deleted *after* it was referenced by the CMS.
    db.execute(text("UPDATE products SET deleted_at = now() WHERE id = :pid"), {"pid": str(doomed_pid)})
    db.flush()

    db.execute(text("SET ROLE urjaa_storefront"))
    try:
        resolved = cms_service.resolve_home_for_storefront(db)
    finally:
        db.execute(text("SET ROLE urjaa_admin_svc"))

    resolved_ids = {p["id"] for p in resolved["best_sellers"]["products"]}
    assert str(kept_pid) in resolved_ids, resolved_ids
    assert str(doomed_pid) not in resolved_ids, "deleted product must not appear in storefront output"

    kept = next(p for p in resolved["best_sellers"]["products"] if p["id"] == str(kept_pid))
    assert kept["original_price"] == 20000.0, kept
    assert kept["starting_price"] == 16000.0, kept  # 20% off 20000
    assert kept["discount_percent"] == 20.0, kept
    print("storefront skips deleted + applies discount      OK")


def main() -> None:
    conn = engine.connect()
    outer = conn.begin()
    db = Session(bind=conn, join_transaction_mode="create_savepoint")
    try:
        db.execute(text("SET ROLE urjaa_admin_svc"))
        store = db.query(Store).first()
        assert store is not None, "dev DB needs at least one store"

        test_valid_save_round_trips(db, store.id)
        test_text_field_on_home_rejected(db)
        test_foreign_url_rejected(db)
        test_sixth_save_keeps_only_five_versions(db, store.id)
        test_restore_works(db, store.id)
        test_storefront_skips_deleted_and_applies_discount(db, store.id)
    finally:
        db.close()
        outer.rollback()
        conn.close()


if __name__ == "__main__":
    main()
    print("ok")
