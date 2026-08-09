"""Campaign service — Phase 6.

Resolves audience from JSONB filter, executes campaigns, creates notification logs.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from uuid import UUID

logger = logging.getLogger(__name__)

UTC = timezone.utc
FRONTEND_BASE_URL = os.getenv("FRONTEND_BASE_URL", "https://urjaa.com")


def resolve_campaign_audience(campaign: any, db: any) -> list[any]:
    """Resolve matching users from campaign.audience_filter."""
    from urjaa_core.models.user import User
    from urjaa_core.models.order import Order
    from urjaa_core.models.cart_event import CartEvent
    from urjaa_core.models.wishlist import Wishlist
    from sqlalchemy import func

    filters = campaign.audience_filter or {}
    now = datetime.now(UTC)

    q = db.query(User).filter(
        User.whatsapp_opt_in.is_(True),
        User.whatsapp_number.isnot(None),
        User.is_active.is_(True),
    )

    inactive_days = filters.get("inactive_days")
    if inactive_days:
        cutoff = now - timedelta(days=int(inactive_days))
        q = q.filter(
            (User.last_seen_at < cutoff) | (User.last_seen_at.is_(None))
        )

    min_spend = filters.get("min_total_spend")
    if min_spend:
        from sqlalchemy import func
        spend_subq = (
            db.query(Order.user_id, func.sum(Order.total_amount).label("total"))
            .group_by(Order.user_id)
            .subquery()
        )
        q = q.join(spend_subq, spend_subq.c.user_id == User.id).filter(
            spend_subq.c.total >= float(min_spend)
        )

    has_abandoned_cart = filters.get("has_abandoned_cart")
    if has_abandoned_cart:
        cart_cutoff = now - timedelta(days=30)
        abandon_subq = (
            db.query(CartEvent.user_id)
            .filter(
                CartEvent.event_type == "checkout_abandoned",
                CartEvent.occurred_at >= cart_cutoff,
                CartEvent.user_id.isnot(None),
            )
            .distinct()
            .subquery()
        )
        q = q.join(abandon_subq, abandon_subq.c.user_id == User.id)

    min_wishlist_age_days = filters.get("min_wishlist_age_days")
    if min_wishlist_age_days:
        wishlist_cutoff = now - timedelta(days=int(min_wishlist_age_days))
        wishlist_subq = (
            db.query(Wishlist.user_id)
            .filter(
                Wishlist.created_at <= wishlist_cutoff,
                Wishlist.user_id.isnot(None),
            )
            .distinct()
            .subquery()
        )
        q = q.join(wishlist_subq, wishlist_subq.c.user_id == User.id)

    rfm_segment = filters.get("rfm_segment")
    if rfm_segment and campaign.store_id:
        try:
            from urjaa_core.services.analytics_service import compute_rfm_scores
            rfm_scores = compute_rfm_scores(campaign.store_id, db)
            matching_user_ids = {
                uid
                for uid, result in rfm_scores.items()
                if result.segment.lower() == str(rfm_segment).lower()
            }
            if matching_user_ids:
                q = q.filter(User.id.in_(matching_user_ids))
            else:
                return []
        except Exception:
            logger.exception("campaign_service: rfm_segment filter failed")

    return q.all()


def execute_campaign(campaign_id: UUID, db: any) -> dict:
    """Execute a campaign: resolve audience, send messages, log results."""
    from urjaa_core.models.notification_campaign import NotificationCampaign, NotificationLog
    from urjaa_core.services.whatsapp_service import get_whatsapp_service

    campaign = db.query(NotificationCampaign).filter(NotificationCampaign.id == campaign_id).first()
    if campaign is None:
        return {"error": "Campaign not found"}

    campaign.status = "sending"
    db.commit()

    try:
        users = resolve_campaign_audience(campaign, db)
        logger.info("campaign_service: executing campaign %s for %d users", campaign_id, len(users))

        wa = get_whatsapp_service()
        shop_url = f"{FRONTEND_BASE_URL}/shop"
        sent = 0
        failed = 0
        now = datetime.now(UTC)

        for user in users:
            phone = user.whatsapp_number or ""
            name = user.full_name or "Customer"
            success = False
            provider_msg_id = None
            error_msg = None

            try:
                if campaign.trigger_type == "wishlist_reminder":
                    product_name = campaign.template_params.get("product_name", "an item")
                    days = campaign.template_params.get("days", 7)
                    success, provider_msg_id = wa.send_wishlist_reminder(name, phone, product_name, days, shop_url)
                elif campaign.trigger_type == "cart_abandon":
                    product_name = campaign.template_params.get("product_name", "your item")
                    cart_url = f"{FRONTEND_BASE_URL}/cart"
                    success, provider_msg_id = wa.send_cart_abandonment(name, phone, product_name, cart_url)
                elif campaign.trigger_type == "reengagement":
                    days = campaign.template_params.get("days_inactive", 30)
                    success, provider_msg_id = wa.send_reengagement(name, phone, days, shop_url)
                elif campaign.trigger_type == "promo_code":
                    product_name = campaign.template_params.get("product_name", "new arrivals")
                    discount = campaign.template_params.get("discount_pct", 10)
                    code = campaign.template_params.get("promo_code", "URJAA10")
                    success, provider_msg_id = wa.send_promo_offer(name, phone, product_name, discount, code, shop_url)
                else:
                    # manual / product_launch: send body directly
                    body = campaign.template_params.get("body", "New arrivals from Urjaa Ornaments!")
                    success, provider_msg_id = wa.send_template(phone, campaign.template_name, {"body": body})

                if not success:
                    error_msg = provider_msg_id
                    provider_msg_id = None
            except Exception as exc:
                success = False
                error_msg = str(exc)

            status_val = "sent" if success else "failed"
            if success:
                sent += 1
            else:
                failed += 1

            log = NotificationLog(
                campaign_id=campaign_id,
                user_id=user.id,
                channel="whatsapp",
                recipient=phone,
                status=status_val,
                provider_msg_id=provider_msg_id if success else None,
                error_message=error_msg if not success else None,
                sent_at=now if success else None,
            )
            db.add(log)

        campaign.status = "sent"
        campaign.sent_at = now
        campaign.recipient_count = len(users)
        db.commit()

        return {
            "campaign_id": str(campaign_id),
            "total": len(users),
            "sent": sent,
            "failed": failed,
        }

    except Exception as exc:
        logger.exception("campaign_service: execute_campaign failed for %s", campaign_id)
        campaign.status = "failed"
        db.commit()
        return {"error": str(exc)}
