from datetime import date, timedelta
from math import ceil
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from urjaa_core.models.admin_user import AdminUser
from urjaa_core.models.order import Order
from urjaa_core.models.order_item import OrderItem
from urjaa_core.models.product import Product
from urjaa_core.models.product_review import ProductReview
from urjaa_core.models.user import User
from urjaa_core.schemas.admin.reviews import (
    AdminReviewCounts,
    AdminReviewResponse,
    PaginatedAdminReviewsResponse,
)
from urjaa_core.schemas.review import (
    FeaturedReviewsResponse,
    ProductReviewPublicResponse,
    ProductReviewsResponse,
    ReviewCreateRequest,
    ReviewCreateResponse,
)


REVIEW_SORT_VALUES = ("latest", "highest")
VERIFIED_PURCHASE_STATUSES = ("CONFIRMED", "PROCESSING", "SHIPPED", "DELIVERED")
# UX-12: what the public sees -- not hidden by staff, not (soft) deleted.
PUBLIC_REVIEW_FILTER = (ProductReview.is_approved.is_(True), ProductReview.deleted_at.is_(None))


class ReviewService:
    @staticmethod
    def _mask_reviewer_name(full_name: str | None) -> str:
        parts = [part for part in (full_name or "").strip().split(" ") if part]
        if not parts:
            return "Verified Buyer"

        first_name = parts[0]
        if len(parts) == 1:
            return first_name

        return f"{first_name} {parts[-1][0].upper()}."

    @staticmethod
    def _normalize_sort(sort: str) -> str:
        normalized = (sort or "latest").strip().lower()
        if normalized not in REVIEW_SORT_VALUES:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid sort. Allowed values: {', '.join(REVIEW_SORT_VALUES)}",
            )

        return normalized

    @staticmethod
    def _to_public(
        review: ProductReview,
        *,
        reviewer_name: str | None,
        product_name: str | None = None,
        product_slug: str | None = None,
    ) -> ProductReviewPublicResponse:
        return ProductReviewPublicResponse(
            id=review.id,
            product_id=review.product_id,
            product_name=product_name,
            product_slug=product_slug,
            rating=review.rating,
            title=review.title,
            content=review.content,
            is_verified_purchase=bool(review.is_verified_purchase),
            reviewer_name=ReviewService._mask_reviewer_name(reviewer_name),
            created_at=review.created_at,
            reply_content=review.reply_content,
            replied_at=review.replied_at,
        )

    @staticmethod
    def _get_product_or_404(db: Session, product_id: UUID) -> Product:
        product = (
            db.query(Product)
            .filter(Product.id == product_id, Product.deleted_at.is_(None))
            .first()
        )
        if product is None:
            raise HTTPException(status_code=404, detail="Product not found")

        return product

    @staticmethod
    def _get_rating_breakdown(db: Session, product_id: UUID) -> dict[int, int]:
        rows = (
            db.query(ProductReview.rating, func.count(ProductReview.id))
            .filter(ProductReview.product_id == product_id, *PUBLIC_REVIEW_FILTER)
            .group_by(ProductReview.rating)
            .all()
        )

        breakdown = {star: 0 for star in range(1, 6)}
        for rating, count in rows:
            breakdown[int(rating)] = int(count)

        return breakdown

    @staticmethod
    def list_product_reviews(
        db: Session,
        *,
        product_id: UUID,
        page: int = 1,
        limit: int = 10,
        sort: str = "latest",
        rating: int | None = None,
    ) -> ProductReviewsResponse:
        normalized_sort = ReviewService._normalize_sort(sort)
        product = ReviewService._get_product_or_404(db, product_id)

        base_query = (
            db.query(ProductReview, User.full_name)
            .outerjoin(User, User.id == ProductReview.user_id)
            .filter(ProductReview.product_id == product.id, *PUBLIC_REVIEW_FILTER)
        )

        # Unfiltered stats -- a `rating` filter narrows the list below, never
        # the product's overall average/count/breakdown.
        total_count = base_query.count()

        aggregate = (
            db.query(func.avg(ProductReview.rating), func.count(ProductReview.id))
            .filter(ProductReview.product_id == product.id, *PUBLIC_REVIEW_FILTER)
            .first()
        )
        average_value = float(aggregate[0]) if aggregate and aggregate[0] is not None else 0.0
        average_rating = round(average_value, 1)
        rating_breakdown = ReviewService._get_rating_breakdown(db, product.id)

        query = base_query if rating is None else base_query.filter(ProductReview.rating == rating)

        filtered_count = query.count()
        pages = max(1, ceil(filtered_count / limit)) if filtered_count > 0 else 1

        if normalized_sort == "highest":
            query = query.order_by(ProductReview.rating.desc(), ProductReview.created_at.desc())
        else:
            query = query.order_by(ProductReview.created_at.desc())

        rows = query.offset((page - 1) * limit).limit(limit).all()

        items = [
            ReviewService._to_public(
                review,
                reviewer_name=full_name,
                product_name=product.name,
                product_slug=product.slug,
            )
            for review, full_name in rows
        ]

        return ProductReviewsResponse(
            average_rating=average_rating,
            total_count=total_count,
            rating_breakdown=rating_breakdown,
            rating_filter=rating,
            filtered_count=filtered_count,
            items=items,
            page=page,
            limit=limit,
            pages=pages,
            sort=normalized_sort,
        )

    @staticmethod
    def _is_verified_purchase(db: Session, *, user_id: UUID, product_id: UUID) -> bool:
        match = (
            db.query(OrderItem.id)
            .join(Order, Order.id == OrderItem.order_id)
            .filter(
                Order.user_id == user_id,
                OrderItem.product_id == product_id,
                Order.status.in_(VERIFIED_PURCHASE_STATUSES),
            )
            .first()
        )
        return match is not None

    @staticmethod
    def create_review(
        db: Session,
        *,
        payload: ReviewCreateRequest,
        current_user: User,
    ) -> ReviewCreateResponse:
        product = ReviewService._get_product_or_404(db, payload.product_id)

        clean_content = payload.content.strip()
        if not clean_content:
            raise HTTPException(status_code=422, detail="content is required")

        existing = (
            db.query(ProductReview)
            .filter(ProductReview.product_id == product.id, ProductReview.user_id == current_user.id)
            .first()
        )
        if existing is not None:
            raise HTTPException(status_code=409, detail="You have already reviewed this product")

        clean_title = payload.title.strip() if isinstance(payload.title, str) else None
        if clean_title == "":
            clean_title = None

        verified_purchase = ReviewService._is_verified_purchase(
            db,
            user_id=current_user.id,
            product_id=product.id,
        )

        review = ProductReview(
            product_id=product.id,
            user_id=current_user.id,
            rating=payload.rating,
            title=clean_title,
            content=clean_content,
            is_verified_purchase=verified_purchase,
            is_approved=True,
        )

        db.add(review)
        db.commit()
        db.refresh(review)

        return ReviewCreateResponse(
            message="Review submitted successfully.",
            review=ReviewService._to_public(
                review,
                reviewer_name=current_user.full_name,
                product_name=product.name,
                product_slug=product.slug,
            ),
        )

    @staticmethod
    def get_featured_reviews(db: Session, *, limit: int = 5) -> FeaturedReviewsResponse:
        normalized_limit = min(max(limit, 5), 10)

        rows = (
            db.query(ProductReview, User.full_name, Product.name, Product.slug)
            .join(Product, Product.id == ProductReview.product_id)
            .outerjoin(User, User.id == ProductReview.user_id)
            .filter(
                *PUBLIC_REVIEW_FILTER,
                ProductReview.rating >= 4,
                Product.deleted_at.is_(None),
            )
            .order_by(ProductReview.rating.desc(), ProductReview.created_at.desc())
            .limit(normalized_limit)
            .all()
        )

        items = [
            ReviewService._to_public(
                review,
                reviewer_name=reviewer_name,
                product_name=product_name,
                product_slug=product_slug,
            )
            for review, reviewer_name, product_name, product_slug in rows
        ]

        return FeaturedReviewsResponse(items=items, limit=normalized_limit)

    # ---- UX-12 admin moderation + staff reply ---------------------------

    @staticmethod
    def _admin_query(db: Session):
        return (
            db.query(ProductReview, Product.name, Product.slug, User.full_name, User.email, AdminUser.email)
            .join(Product, Product.id == ProductReview.product_id)
            .outerjoin(User, User.id == ProductReview.user_id)
            .outerjoin(AdminUser, AdminUser.id == ProductReview.replied_by_admin_id)
            .filter(ProductReview.deleted_at.is_(None))
        )

    @staticmethod
    def _to_admin(row) -> AdminReviewResponse:
        review, product_name, product_slug, reviewer_name, reviewer_email, replied_by_email = row
        return AdminReviewResponse(
            id=review.id,
            product_id=review.product_id,
            product_name=product_name or "",
            product_slug=product_slug,
            user_id=review.user_id,
            reviewer_name=reviewer_name,
            reviewer_email=reviewer_email,
            rating=review.rating,
            title=review.title,
            content=review.content,
            is_verified_purchase=bool(review.is_verified_purchase),
            is_approved=review.is_approved,
            created_at=review.created_at,
            moderated_at=review.moderated_at,
            reply_content=review.reply_content,
            replied_at=review.replied_at,
            replied_by_email=replied_by_email,
        )

    @staticmethod
    def admin_list(
        db: Session,
        *,
        q: str | None = None,
        rating: int | None = None,
        has_reply: bool | None = None,
        is_approved: bool | None = None,
        product_id: UUID | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        page: int = 1,
        limit: int = 20,
    ) -> PaginatedAdminReviewsResponse:
        query = ReviewService._admin_query(db)
        term = (q or "").strip()
        if term:
            like = f"%{term}%"
            query = query.filter(or_(Product.name.ilike(like), User.full_name.ilike(like), User.email.ilike(like)))
        if rating is not None:
            query = query.filter(ProductReview.rating == rating)
        if has_reply is not None:
            reply_col = ProductReview.reply_content
            query = query.filter(reply_col.is_not(None) if has_reply else reply_col.is_(None))
        if is_approved is not None:
            query = query.filter(ProductReview.is_approved.is_(is_approved))
        if product_id is not None:
            query = query.filter(ProductReview.product_id == product_id)
        if date_from is not None:
            query = query.filter(ProductReview.created_at >= date_from)
        if date_to is not None:
            query = query.filter(ProductReview.created_at < date_to + timedelta(days=1))

        total = query.count()
        rows = (
            query.order_by(ProductReview.created_at.desc(), ProductReview.id)
            .offset((page - 1) * limit)
            .limit(limit)
            .all()
        )

        live = ProductReview.deleted_at.is_(None)
        visible, hidden, awaiting = (
            db.query(
                func.count(ProductReview.id).filter(ProductReview.is_approved.is_(True)),
                func.count(ProductReview.id).filter(ProductReview.is_approved.is_(False)),
                func.count(ProductReview.id).filter(
                    ProductReview.is_approved.is_(True), ProductReview.reply_content.is_(None)
                ),
            )
            .filter(live)
            .one()
        )

        return PaginatedAdminReviewsResponse(
            items=[ReviewService._to_admin(row) for row in rows],
            page=page,
            limit=limit,
            total=total,
            pages=max(1, ceil(total / limit)),
            counts=AdminReviewCounts(visible=visible, hidden=hidden, awaiting_reply=awaiting),
        )

    @staticmethod
    def _admin_get_row(db: Session, review_id: UUID):
        row = ReviewService._admin_query(db).filter(ProductReview.id == review_id).first()
        if row is None:
            raise HTTPException(status_code=404, detail="Review not found")
        return row

    @staticmethod
    def _admin_save(db: Session, review_id: UUID, **fields) -> AdminReviewResponse:
        review = ReviewService._admin_get_row(db, review_id)[0]
        for key, value in fields.items():
            setattr(review, key, value)
        db.commit()
        return ReviewService._to_admin(ReviewService._admin_get_row(db, review_id))

    @staticmethod
    def admin_set_approved(db: Session, review_id: UUID, *, is_approved: bool, admin_id: int) -> AdminReviewResponse:
        return ReviewService._admin_save(
            db, review_id, is_approved=is_approved, moderated_at=func.now(), moderated_by_admin_id=admin_id
        )

    @staticmethod
    def admin_delete(db: Session, review_id: UUID, *, admin_id: int) -> None:
        # Soft delete: gone from public + admin lists, row kept for audit.
        review = ReviewService._admin_get_row(db, review_id)[0]
        review.deleted_at = review.moderated_at = func.now()
        review.moderated_by_admin_id = admin_id
        db.commit()

    @staticmethod
    def admin_set_reply(db: Session, review_id: UUID, *, content: str, admin_id: int) -> AdminReviewResponse:
        clean = content.strip()
        if not clean:
            raise HTTPException(status_code=422, detail="Reply cannot be empty")
        return ReviewService._admin_save(
            db, review_id, reply_content=clean, replied_at=func.now(), replied_by_admin_id=admin_id
        )

    @staticmethod
    def admin_delete_reply(db: Session, review_id: UUID) -> AdminReviewResponse:
        return ReviewService._admin_save(db, review_id, reply_content=None, replied_at=None, replied_by_admin_id=None)
