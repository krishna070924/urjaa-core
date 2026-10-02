"""L-02 self-check against the live dev database.

Proves: GET /products/{id}/reviews's new `rating` filter (1) returns only
reviews of that star rating, (2) leaves average_rating/total_count/
rating_breakdown computed over ALL approved reviews (not the filtered
subset), (3) computes `pages`/`filtered_count` off the filtered subset so
pagination is correct under a filter, and (4) a soft-deleted product still
404s with a filter applied.

Savepoint-joined Session, everything rolled back at the end -- same pattern
as tests/test_sku_autogeneration.py / tests/test_discounts.py.

Run: .venv/bin/python tests/test_review_filters.py
"""
import os
from uuid import uuid4

os.environ.setdefault("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/urjaa")

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from urjaa_core.core.database import engine
from urjaa_core.models import Product, ProductReview, Store, User
from urjaa_core.services.admin.admin_management_service import AdminManagementService as admin_svc
from urjaa_core.services.review_service import ReviewService


def main() -> None:
    conn = engine.connect()
    outer = conn.begin()
    db = Session(bind=conn, join_transaction_mode="create_savepoint")
    try:
        db.execute(text("SET ROLE urjaa_admin_svc"))

        store = db.query(Store).first()
        product = Product(
            id=uuid4(), store_id=store.id, name="L02 Review Filter Check",
            slug=f"l02-review-{uuid4().hex[:8]}", status="active",
        )
        db.add(product)
        db.flush()

        user = User(
            id=uuid4(), email=f"l02-{uuid4().hex[:10]}@test.local",
            password_hash="x", full_name="L02 Reviewer",
        )
        db.add(user)
        db.flush()

        # 7 approved reviews: 3x5*, 2x4*, 1x3*, 1x1* -- plus one unapproved
        # 5* review that must never surface in counts or the filtered list.
        ratings = [5, 5, 5, 4, 4, 3, 1]
        for r in ratings:
            db.add(ProductReview(id=uuid4(), product_id=product.id, user_id=user.id, rating=r, content="ok", is_approved=True))
        db.add(ProductReview(id=uuid4(), product_id=product.id, user_id=user.id, rating=5, content="pending", is_approved=False))
        db.flush()

        db.execute(text("SET ROLE urjaa_storefront"))

        # --- unfiltered baseline ---
        unfiltered = ReviewService.list_product_reviews(db, product_id=product.id, limit=50)
        assert unfiltered.total_count == 7, unfiltered.total_count
        assert unfiltered.rating_filter is None, unfiltered.rating_filter
        assert unfiltered.filtered_count == 7, unfiltered.filtered_count
        assert unfiltered.average_rating == round(sum(ratings) / len(ratings), 1), unfiltered.average_rating
        assert unfiltered.rating_breakdown == {1: 1, 2: 0, 3: 1, 4: 2, 5: 3}, unfiltered.rating_breakdown
        print("OK unfiltered: total/avg/breakdown match the 7 approved reviews (unapproved 5* excluded)")

        # --- filter to 5* only: list narrows, breakdown/average/total don't ---
        five_star = ReviewService.list_product_reviews(db, product_id=product.id, rating=5, limit=50)
        assert five_star.rating_filter == 5
        assert five_star.filtered_count == 3, five_star.filtered_count
        assert len(five_star.items) == 3, five_star.items
        assert all(item.rating == 5 for item in five_star.items)
        assert five_star.total_count == 7, "total_count must stay over ALL reviews under a filter"
        assert five_star.average_rating == unfiltered.average_rating, "average must stay over ALL reviews under a filter"
        assert five_star.rating_breakdown == unfiltered.rating_breakdown, "breakdown must stay over ALL reviews under a filter"
        print("OK rating=5 filter: 3 items returned, all 5*; breakdown/average/total unaffected")

        # --- empty filter (no 2* reviews at all) ---
        two_star = ReviewService.list_product_reviews(db, product_id=product.id, rating=2, limit=50)
        assert two_star.filtered_count == 0 and two_star.items == [] and two_star.pages == 1
        assert two_star.total_count == 7 and two_star.average_rating == unfiltered.average_rating
        print("OK rating=2 filter: empty list, stats still unaffected")

        # --- pagination under a filter: 3 matching 5* reviews, limit=2 -> 2 pages ---
        page1 = ReviewService.list_product_reviews(db, product_id=product.id, rating=5, limit=2, page=1)
        page2 = ReviewService.list_product_reviews(db, product_id=product.id, rating=5, limit=2, page=2)
        assert page1.filtered_count == 3 and page1.pages == 2 and len(page1.items) == 2, page1
        assert page2.filtered_count == 3 and page2.pages == 2 and len(page2.items) == 1, page2
        assert {i.id for i in page1.items} & {i.id for i in page2.items} == set(), "pages must not overlap"
        print("OK pagination under rating=5 filter: 3 items / limit=2 -> 2 pages (2 + 1), no overlap")

        # --- soft-deleted product still 404s, filter or not ---
        db.execute(text("SET ROLE urjaa_admin_svc"))
        admin_svc.delete_product(db, store_id=store.id, product_id=product.id)
        db.execute(text("SET ROLE urjaa_storefront"))
        try:
            ReviewService.list_product_reviews(db, product_id=product.id, rating=5)
            raise AssertionError("soft-deleted product did not 404")
        except HTTPException as exc:
            assert exc.status_code == 404, exc.status_code
        print("OK soft-deleted product still 404s with a rating filter applied")

        print("\nAll L-02 review filter checks passed.")
    finally:
        db.execute(text("RESET ROLE"))
        db.close()
        outer.rollback()
        conn.close()


if __name__ == "__main__":
    main()
    print("OK")
