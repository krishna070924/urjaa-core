from __future__ import annotations

import asyncio
import hashlib
import hmac
from decimal import Decimal
from uuid import UUID

from fastapi import HTTPException
import razorpay

from urjaa_core.core.config import settings


class RazorpayService:
    def __init__(self) -> None:
        self.key_id = settings.razorpay_key_id.strip()
        self.key_secret = settings.razorpay_key_secret.strip()

        if not self.key_id or not self.key_secret:
            raise HTTPException(status_code=500, detail="Razorpay is not configured")

        self.client = razorpay.Client(auth=(self.key_id, self.key_secret))

    async def create_order(self, amount_inr: Decimal, order_id: UUID) -> dict:
        if amount_inr <= 0:
            raise HTTPException(status_code=400, detail="Amount must be greater than zero")

        amount_paise = int((amount_inr * Decimal("100")).quantize(Decimal("1")))
        payload = {
            "amount": amount_paise,
            "currency": "INR",
            "receipt": str(order_id),
        }

        def _create() -> dict:
            return self.client.order.create(payload)

        response = await asyncio.to_thread(_create)
        if not isinstance(response, dict):
            raise HTTPException(status_code=502, detail="Failed to create payment order")

        return response

    def verify_signature(self, razorpay_order_id: str, razorpay_payment_id: str, signature: str) -> bool:
        signing_payload = f"{razorpay_order_id}|{razorpay_payment_id}".encode("utf-8")
        digest = hmac.new(
            self.key_secret.encode("utf-8"),
            signing_payload,
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(digest, signature)
