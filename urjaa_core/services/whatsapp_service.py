"""WhatsApp messaging service — Phase 6.

Supports Twilio sandbox (dev) and Meta API (production).
Controlled via env var WHATSAPP_PROVIDER=twilio|meta (default: twilio).
If no credentials are set, runs in DRY_RUN mode (logs messages, returns success).
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


class WhatsAppService:
    def __init__(self) -> None:
        self.provider = os.getenv("WHATSAPP_PROVIDER", "twilio").lower()
        self.dry_run = False

        if self.provider == "twilio":
            sid = os.getenv("TWILIO_ACCOUNT_SID")
            token = os.getenv("TWILIO_AUTH_TOKEN")
            self.from_number = os.getenv("TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886")

            if not sid or not token:
                logger.warning("whatsapp_service: no Twilio credentials — running in DRY_RUN mode")
                self.dry_run = True
                self._client = None
            else:
                try:
                    from twilio.rest import Client as TwilioClient
                    self._client = TwilioClient(sid, token)
                    logger.info("whatsapp_service: Twilio client initialized")
                except ImportError:
                    logger.warning("whatsapp_service: twilio package not installed — DRY_RUN mode")
                    self.dry_run = True
                    self._client = None

        elif self.provider == "meta":
            self._meta_token = os.getenv("META_WHATSAPP_TOKEN")
            self._meta_phone_id = os.getenv("META_PHONE_NUMBER_ID")
            if not self._meta_token or not self._meta_phone_id:
                logger.warning("whatsapp_service: no Meta credentials — DRY_RUN mode")
                self.dry_run = True
            logger.info("whatsapp_service: Meta provider configured")
        else:
            logger.warning("whatsapp_service: unknown provider '%s' — DRY_RUN mode", self.provider)
            self.dry_run = True

    def _normalize_phone(self, phone: str) -> str:
        """Ensure phone number starts with 'whatsapp:+' for Twilio."""
        phone = phone.strip()
        if self.provider == "twilio":
            if not phone.startswith("whatsapp:"):
                if not phone.startswith("+"):
                    phone = "+" + phone
                phone = "whatsapp:" + phone
        return phone

    def send_template(self, to_phone: str, template_name: str, params: dict) -> tuple[bool, str | None]:
        """Send a WhatsApp message. Returns (success, message_id_or_error)."""
        try:
            body = params.get("body", str(params))
            to = self._normalize_phone(to_phone)

            if self.dry_run:
                logger.info(
                    "whatsapp_service DRY_RUN: template=%s to=%s body=%s",
                    template_name, to, body,
                )
                return True, f"dry_run_{template_name}"

            if self.provider == "twilio":
                message = self._client.messages.create(
                    body=body,
                    from_=self.from_number,
                    to=to,
                )
                return True, message.sid

            if self.provider == "meta":
                import urllib.request
                import json

                url = f"https://graph.facebook.com/v18.0/{self._meta_phone_id}/messages"
                data = json.dumps({
                    "messaging_product": "whatsapp",
                    "to": to_phone.replace("whatsapp:", "").replace("+", ""),
                    "type": "template",
                    "template": {
                        "name": template_name,
                        "language": {"code": "en"},
                        "components": [
                            {
                                "type": "body",
                                "parameters": [
                                    {"type": "text", "text": v}
                                    for v in params.get("values", [])
                                ],
                            }
                        ],
                    },
                }).encode()
                req = urllib.request.Request(
                    url,
                    data=data,
                    headers={
                        "Authorization": f"Bearer {self._meta_token}",
                        "Content-Type": "application/json",
                    },
                )
                with urllib.request.urlopen(req, timeout=10) as resp:
                    result = json.loads(resp.read())
                    msg_id = result.get("messages", [{}])[0].get("id")
                    return True, msg_id

        except Exception as exc:
            logger.exception("whatsapp_service: send_template failed for %s", to_phone)
            return False, str(exc)

        return False, "unsupported_provider"

    def send_wishlist_reminder(
        self,
        user_name: str,
        to_phone: str,
        product_name: str,
        days_in_wishlist: int,
        shop_url: str,
    ) -> tuple[bool, str | None]:
        body = (
            f"Hi {user_name}! \U0001f49b You have {product_name} in your Urjaa wishlist for "
            f"{days_in_wishlist} days. It is still available — grab it before it is gone! "
            f"Shop: {shop_url}"
        )
        return self.send_template(
            to_phone,
            "wishlist_reminder_1",
            {"body": body, "values": [user_name, product_name, str(days_in_wishlist), shop_url]},
        )

    def send_promo_offer(
        self,
        user_name: str,
        to_phone: str,
        product_name: str,
        discount_pct: int,
        promo_code: str,
        shop_url: str,
    ) -> tuple[bool, str | None]:
        body = (
            f"Hi {user_name}! You loved {product_name}. Here is {discount_pct}% off with code "
            f"{promo_code}. Valid 48 hours: {shop_url}"
        )
        return self.send_template(
            to_phone,
            "promo_offer_1",
            {"body": body, "values": [user_name, product_name, str(discount_pct), promo_code, shop_url]},
        )

    def send_reengagement(
        self,
        user_name: str,
        to_phone: str,
        days_inactive: int,
        shop_url: str,
    ) -> tuple[bool, str | None]:
        body = (
            f"Hi {user_name}! It has been {days_inactive} days since your last visit to "
            f"Urjaa Ornaments. Beautiful new arrivals are waiting for you ✨ {shop_url}"
        )
        return self.send_template(
            to_phone,
            "reengagement_1",
            {"body": body, "values": [user_name, str(days_inactive), shop_url]},
        )

    def send_cart_abandonment(
        self,
        user_name: str,
        to_phone: str,
        product_name: str,
        cart_url: str,
    ) -> tuple[bool, str | None]:
        body = (
            f"Hi {user_name}! You left {product_name} in your cart. "
            f"Complete your order before it sells out \U0001f6d2 {cart_url}"
        )
        return self.send_template(
            to_phone,
            "cart_abandon_1",
            {"body": body, "values": [user_name, product_name, cart_url]},
        )

    def send_rating_request(
        self,
        user_name: str,
        to_phone: str,
        product_names: list[str],
        rating_url: str,
    ) -> tuple[bool, str | None]:
        products_str = ", ".join(product_names[:3]) if product_names else "your recent purchase"
        body = (
            f"Hi {user_name}! Thank you for your Urjaa Ornaments purchase of {products_str}. "
            f"How did you like it? Rate your experience: {rating_url}"
        )
        return self.send_template(
            to_phone,
            "rating_request_1",
            {"body": body, "values": [user_name, products_str, rating_url]},
        )

    def send_review_request(
        self,
        user_name: str,
        to_phone: str,
        product_name: str,
        review_url: str,
    ) -> tuple[bool, str | None]:
        body = (
            f"Hi {user_name}! Glad you loved your {product_name}. "
            f"Would you leave a quick review? It helps others discover beautiful jewellery: {review_url}"
        )
        return self.send_template(
            to_phone,
            "review_request_1",
            {"body": body, "values": [user_name, product_name, review_url]},
        )


# Module-level singleton
_service: WhatsAppService | None = None


def get_whatsapp_service() -> WhatsAppService:
    global _service
    if _service is None:
        _service = WhatsAppService()
    return _service
