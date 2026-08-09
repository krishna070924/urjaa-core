"""Post-purchase workflow service.

Schedules and processes rating/review request triggers after order delivery.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy.orm import Session

from urjaa_core.models.order import Order
from urjaa_core.models.post_purchase_trigger import PostPurchaseTrigger
from urjaa_core.models.product_review import ProductReview

logger = logging.getLogger(__name__)

UTC = timezone.utc


def schedule_post_purchase_triggers(order_id: UUID, db: Session) -> None:
    """Create pending trigger rows for a newly-delivered order."""
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        logger.warning("schedule_post_purchase_triggers: order %s not found", order_id)
        return

    user = order.user
    if not user:
        logger.info("schedule_post_purchase_triggers: order %s has no user — skipping", order_id)
        return

    now = datetime.now(UTC)
    channel = "whatsapp" if getattr(user, "whatsapp_opt_in", False) else "email"

    for trigger_type, delay_days in [("rating_request", 3), ("review_request", 7)]:
        # Check for existing trigger (UNIQUE constraint on order_id + trigger_type)
        existing = (
            db.query(PostPurchaseTrigger)
            .filter(
                PostPurchaseTrigger.order_id == order_id,
                PostPurchaseTrigger.trigger_type == trigger_type,
            )
            .first()
        )
        if existing:
            continue

        trigger = PostPurchaseTrigger(
            order_id=order_id,
            user_id=user.id,
            trigger_type=trigger_type,
            channel=channel,
            status="pending",
            scheduled_for=now + timedelta(days=delay_days),
        )
        db.add(trigger)

    try:
        db.commit()
        logger.info("schedule_post_purchase_triggers: triggers created for order %s", order_id)
    except Exception:
        db.rollback()
        logger.exception("schedule_post_purchase_triggers: commit failed for order %s", order_id)


def process_pending_triggers(db: Session) -> None:
    """Process up to 50 pending triggers that are due."""
    import os
    from urjaa_core.services.whatsapp_service import get_whatsapp_service
    from urjaa_core.services.email_service import EmailService

    frontend_base_url = (os.getenv("FRONTEND_BASE_URL") or "http://localhost:3000").rstrip("/")
    whatsapp_svc = get_whatsapp_service()

    now = datetime.now(UTC)
    triggers = (
        db.query(PostPurchaseTrigger)
        .filter(
            PostPurchaseTrigger.status == "pending",
            PostPurchaseTrigger.scheduled_for <= now,
        )
        .limit(50)
        .all()
    )

    for trigger in triggers:
        try:
            order = db.query(Order).filter(Order.id == trigger.order_id).first()
            if not order:
                trigger.status = "skipped"
                trigger.error_msg = "order not found"
                continue

            user = order.user
            if not user:
                trigger.status = "skipped"
                trigger.error_msg = "no user on order"
                continue

            rating_url = f"{frontend_base_url}/orders/{order.id}/rate"
            items = order.items or []
            first_product = items[0].product if items else None

            if trigger.trigger_type == "rating_request":
                product_names = [item.product_name or (item.product.name if item.product else "item") for item in items[:3]]
                success, sid = _send_rating_request(
                    trigger, whatsapp_svc, user, product_names, rating_url, EmailService
                )
                if success:
                    trigger.status = "sent"
                    trigger.sent_at = now
                else:
                    trigger.status = "failed"
                    trigger.error_msg = str(sid)

            elif trigger.trigger_type == "review_request":
                # Skip if user never rated
                if order.customer_rating is None:
                    trigger.status = "skipped"
                    trigger.error_msg = "user did not rate yet"
                    continue
                # Skip if rating < 4
                if order.customer_rating < 4:
                    trigger.status = "skipped"
                    trigger.error_msg = f"rating too low ({order.customer_rating})"
                    continue
                # Skip if review already exists for any order item product
                product_ids = [item.product_id for item in items if item.product_id]
                existing_review = (
                    db.query(ProductReview)
                    .filter(
                        ProductReview.user_id == user.id,
                        ProductReview.product_id.in_(product_ids),
                    )
                    .first()
                    if product_ids
                    else None
                )
                if existing_review:
                    trigger.status = "skipped"
                    trigger.error_msg = "review already exists"
                    continue

                if not first_product:
                    trigger.status = "skipped"
                    trigger.error_msg = "no product found"
                    continue

                product_name = items[0].product_name or (first_product.name if first_product else "your purchase")
                product_slug = getattr(first_product, "slug", None) or str(first_product.id)
                review_url = f"{frontend_base_url}/products/{product_slug}"
                success, sid = _send_review_request(
                    trigger, whatsapp_svc, user, product_name, review_url, EmailService
                )
                if success:
                    trigger.status = "sent"
                    trigger.sent_at = now
                else:
                    trigger.status = "failed"
                    trigger.error_msg = str(sid)

        except Exception as exc:
            logger.exception("process_pending_triggers: error processing trigger %s", trigger.id)
            trigger.status = "failed"
            trigger.error_msg = str(exc)

    try:
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("process_pending_triggers: commit failed")


def _send_rating_request(trigger, whatsapp_svc, user, product_names, rating_url, EmailService):
    name = user.full_name or "Customer"
    if trigger.channel == "whatsapp" and user.whatsapp_number:
        return whatsapp_svc.send_rating_request(name, user.whatsapp_number, product_names, rating_url)
    else:
        result = EmailService.send_rating_request_email(user.email, name, product_names, rating_url)
        return result, None


def _send_review_request(trigger, whatsapp_svc, user, product_name, review_url, EmailService):
    name = user.full_name or "Customer"
    if trigger.channel == "whatsapp" and user.whatsapp_number:
        return whatsapp_svc.send_review_request(name, user.whatsapp_number, product_name, review_url)
    else:
        result = EmailService.send_review_request_email(user.email, name, product_name, review_url)
        return result, None
