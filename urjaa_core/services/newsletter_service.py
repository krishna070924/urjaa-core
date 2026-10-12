"""Newsletter / offer-popup leads: subscribe with a consent snapshot, and
C13's fix -- unsubscribe only with an HMAC token bound to the email, so
nobody can unsubscribe an address they don't control."""
import hashlib
import hmac
import os
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from urjaa_core.core.rate_limit import enforce_in_memory_rate_limit
from urjaa_core.models.newsletter_subscriber import NewsletterSubscriber
from urjaa_core.schemas.cms_content import DEFAULT_POPUP_CONSENT_TEXT, FOOTER_CONSENT_TEXT, WHATSAPP_CONSENT_TEXT
from urjaa_core.schemas.newsletter import NewsletterSubscribeRequest
from urjaa_core.services import cms_service

SECRET_ENV = "NEWSLETTER_UNSUBSCRIBE_SECRET"


def _find(db: Session, email: str) -> NewsletterSubscriber | None:
    return db.query(NewsletterSubscriber).filter(func.lower(NewsletterSubscriber.email) == email).first()


def _consent_text(db: Session, source: str) -> str:
    if source == "footer":
        return FOOTER_CONSENT_TEXT
    current, _ = cms_service.get_page(db, "popup")
    return (current or {}).get("consent_text") or DEFAULT_POPUP_CONSENT_TEXT


def subscribe(db: Session, payload: NewsletterSubscribeRequest, client_ip: str) -> None:
    enforce_in_memory_rate_limit(namespace="newsletter:subscribe:ip", key=client_ip, max_requests=5, window_seconds=60)
    email = str(payload.email).strip().lower()
    row = _find(db, email)
    if row is None:
        row = NewsletterSubscriber(email=email)
        db.add(row)
    if payload.whatsapp_opt_in:
        row.phone = payload.phone
        row.whatsapp_opt_in = True
    # Latest agreement wins: what they ticked now, when, and where.
    # ponytail: no double opt-in, so anyone can (re)subscribe any address;
    # add a confirm-by-email step once RESEND is live (C19).
    row.unsubscribed_at = None
    row.subscribed_at = datetime.utcnow()
    row.source = payload.source
    row.consent_text = _consent_text(db, payload.source) + ("\n" + WHATSAPP_CONSENT_TEXT if row.whatsapp_opt_in else "")
    db.commit()


def _secret() -> bytes:
    secret = os.getenv(SECRET_ENV, "")
    if len(secret) < 32:
        raise HTTPException(status_code=503, detail="Unsubscribe links are not set up yet. Please contact us.")
    return secret.encode()


def unsubscribe_token(email: str) -> str:
    """Put this in every marketing email's unsubscribe link:
    /newsletter/unsubscribe?email=<email>&token=<token>. Never expires, so
    old emails keep working; rotating the secret invalidates every link."""
    message = b"newsletter-unsubscribe:" + email.strip().lower().encode()
    return hmac.new(_secret(), message, hashlib.sha256).hexdigest()


def unsubscribe(db: Session, email: str, token: str, client_ip: str) -> None:
    enforce_in_memory_rate_limit(namespace="newsletter:unsubscribe:ip", key=client_ip, max_requests=10, window_seconds=60)
    email = email.strip().lower()
    if not hmac.compare_digest(unsubscribe_token(email).encode(), token.strip().encode()):
        raise HTTPException(status_code=400, detail="This unsubscribe link is invalid. Use the link in our latest email, or contact us.")
    row = _find(db, email)
    if row is not None and row.unsubscribed_at is None:
        row.unsubscribed_at = datetime.utcnow()
        # Withdrawal covers every channel; the phone was only kept for WhatsApp.
        row.whatsapp_opt_in = False
        row.phone = None
        db.commit()
