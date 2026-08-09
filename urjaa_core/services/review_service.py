from math import ceil
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from urjaa_core.models.order import Order
from urjaa_core.models.order_item import OrderItem
from urjaa_core.models.product import Product
from urjaa_core.models.product_review import ProductReview
from urjaa_core.models.user import User
from urjaa_core.schemas.review import (
    FeaturedReviewsResponse,
    ProductReviewPublicResponse,
    ProductReviewsResponse,
    ReviewCreateRequest,
    ReviewCreateResponse,
)


REVIEW_SORT_VALUES = ("latest", "highest")
VERIFIED_PURCHASE_STATUSES = ("CONFIRMED", "PROCESSING", "SHIPPED", "DELIVERED")


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
        )

    @staticmethod
    def _get_product_or_404(db: Session, product_id: UUID) -> Product:
        product = db.query(Product).filter(Product.id == product_id).first()
        if product is None:
            raise HTTPException(status_code=404, detail="Product not found")

        return product

    @staticmethod
    def _get_rating_breakdown(db: Session, product_id: UUID) -> dict[int, int]:
        rows = (
            db.query(ProductReview.rating, func.count(ProductReview.id))
            .filter(ProductReview.product_id == product_id, ProductReview.is_approved.is_(True))
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
    ) -> ProductReviewsResponse:
        normalized_sort = ReviewService._normalize_sort(sort)
        product = ReviewService._get_product_or_404(db, product_id)

        query = (
            db.query(ProductReview, User.full_name)
            .outerjoin(User, User.id == ProductReview.user_id)
            .filter(ProductReview.product_id == product.id, ProductReview.is_approved.is_(True))
        )

        total_count = query.count()
        pages = max(1, ceil(total_count / limit)) if total_count > 0 else 1

        aggregate = (
            db.query(func.avg(ProductReview.rating), func.count(ProductReview.id))
            .filter(ProductReview.product_id == product.id, ProductReview.is_approved.is_(True))
            .first()
        )
        average_value = float(aggregate[0]) if aggregate and aggregate[0] is not None else 0.0
        average_rating = round(average_value, 1)

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
            rating_breakdown=ReviewService._get_rating_breakdown(db, product.id),
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
            .filter(ProductReview.is_approved.is_(True), ProductReview.rating >= 4)
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
