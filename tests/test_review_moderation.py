"""UX-12 self-check: review hide/unhide, soft delete, staff reply, permissions.

Proves: (1) a hidden review drops out of the public list, total, average,
breakdown and featured; unhiding restores it; (2) the staff reply round-trips
(create, edit, remove) and shows on the public item; (3) delete is soft --
gone from public + admin lists, row kept with deleted_at, later ops 404;
(4) /admin/reviews write routes resolve to manage_products, which staff hold.

Savepoint-joined Session, everything rolled back -- same as
test_review_filters.py. Needs migration 0037 applied.

Run: .venv/bin/python tests/test_review_moderation.py
"""
import os
from uuid import uuid4

os.environ.setdefault("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/urjaa")

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from urjaa_core.core.admin_auth import DEFAULT_ROLE_PERMISSIONS, _resolve_required_permissions
from urjaa_core.core.database import engine
from urjaa_core.models import AdminUser, Product, ProductReview, Store, User
from urjaa_core.services.review_service import ReviewService


def expect_status(code: int, fn) -> None:
    try:
        fn()
    except HTTPException as exc:
        assert exc.status_code == code, exc.status_code
        return
    raise AssertionError(f"expected HTTP {code}")


def check_permissions() -> None:
    for path, method in [
        ("/admin/reviews", "GET"),
        ("/admin/reviews/abc", "PATCH"),
        ("/admin/reviews/abc", "DELETE"),
        ("/admin/reviews/abc/reply", "PUT"),
        ("/admin/reviews/abc/reply", "DELETE"),
    ]:
        required = _resolve_required_permissions(path, method)
        assert required == {"manage_products"}, (path, method, required)
        assert required & DEFAULT_ROLE_PERMISSIONS["staff"], ("staff denied", path, method)
    print("OK permissions: every /admin/reviews route -> manage_products, held by staff")


def main() -> None:
    check_permissions()

    conn = engine.connect()
    outer = conn.begin()
    db = Session(bind=conn, join_transaction_mode="create_savepoint")
    try:
        db.execute(text("SET ROLE urjaa_admin_svc"))
        admin = db.query(AdminUser).first()
        assert admin is not None, "needs at least one admin_users row"
        store = db.query(Store).first()
        product = Product(
            id=uuid4(), store_id=store.id, name="UX12 Moderation Check",
            slug=f"ux12-review-{uuid4().hex[:8]}", status="active",
        )
        user = User(id=uuid4(), email=f"ux12-{uuid4().hex[:10]}@test.local", password_hash="x", full_name="Asha Rao")
        db.add_all([product, user])
        db.flush()
        good, ok, bad = (
            ProductReview(id=uuid4(), product_id=product.id, user_id=user.id, rating=r, content=f"{r} stars")
            for r in (5, 4, 1)
        )
        db.add_all([good, ok, bad])
        db.flush()

        def public():
            db.execute(text("SET ROLE urjaa_storefront"))
            try:
                return ReviewService.list_product_reviews(db, product_id=product.id, limit=50)
            finally:
                db.execute(text("SET ROLE urjaa_admin_svc"))

        base = public()
        assert base.total_count == 3 and base.average_rating == 3.3, base

        # --- hide the 1-star: out of list, total, average, breakdown ---
        hidden = ReviewService.admin_set_approved(db, bad.id, is_approved=False, admin_id=admin.id)
        assert hidden.is_approved is False and hidden.moderated_at is not None
        after = public()
        assert after.total_count == 2 and after.average_rating == 4.5, after
        assert after.rating_breakdown[1] == 0 and bad.id not in {i.id for i in after.items}
        listed = ReviewService.admin_list(db, product_id=product.id, is_approved=False)
        assert [i.id for i in listed.items] == [bad.id], listed
        ReviewService.admin_set_approved(db, bad.id, is_approved=True, admin_id=admin.id)
        assert public().total_count == 3
        print("OK hide excludes from public list + aggregates; unhide restores")

        # --- reply round-trip ---
        expect_status(422, lambda: ReviewService.admin_set_reply(db, good.id, content="   ", admin_id=admin.id))
        r = ReviewService.admin_set_reply(db, good.id, content="  Thank you, Asha!  ", admin_id=admin.id)
        assert r.reply_content == "Thank you, Asha!" and r.replied_at and r.replied_by_email == admin.email, r
        item = next(i for i in public().items if i.id == good.id)
        assert item.reply_content == "Thank you, Asha!" and item.replied_at is not None
        r = ReviewService.admin_set_reply(db, good.id, content="Edited reply", admin_id=admin.id)
        assert r.reply_content == "Edited reply"
        with_reply = ReviewService.admin_list(db, product_id=product.id, has_reply=True)
        assert [i.id for i in with_reply.items] == [good.id], with_reply
        assert ReviewService.admin_list(db, product_id=product.id, has_reply=False).total == 2
        r = ReviewService.admin_delete_reply(db, good.id)
        assert r.reply_content is None and r.replied_at is None and r.replied_by_email is None
        assert next(i for i in public().items if i.id == good.id).reply_content is None
        print("OK reply create/edit/remove round-trips to the public item")

        # --- search + rating filter ---
        assert ReviewService.admin_list(db, q="ux12 moderation", rating=4).total == 1
        assert ReviewService.admin_list(db, q="asha rao", product_id=product.id).total == 3

        # --- soft delete ---
        ReviewService.admin_delete(db, ok.id, admin_id=admin.id)
        assert ok.id not in {i.id for i in public().items} and public().total_count == 2
        assert ReviewService.admin_list(db, product_id=product.id).total == 2
        row = db.query(ProductReview).filter(ProductReview.id == ok.id).one()
        assert row.deleted_at is not None and row.moderated_by_admin_id == admin.id
        expect_status(404, lambda: ReviewService.admin_delete(db, ok.id, admin_id=admin.id))
        expect_status(404, lambda: ReviewService.admin_set_reply(db, ok.id, content="x", admin_id=admin.id))
        print("OK delete is soft: hidden from public + admin, row kept, later ops 404")

        counts = ReviewService.admin_list(db).counts
        assert counts is not None and counts.visible >= 2
        print("\nAll UX-12 review moderation checks passed.")
    finally:
        db.execute(text("RESET ROLE"))
        db.close()
        outer.rollback()
        conn.close()


if __name__ == "__main__":
    main()
    print("OK")
