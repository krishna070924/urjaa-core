"""Offer popup v1: PopupContent validation, storefront date window, lead
capture with consent snapshot, subscribe rate limit, signed unsubscribe (C13).

Same convention as test_cms.py: joined to an outer transaction and rolled
back, so nothing lands for real. Run against a throwaway DB migrated to head:
    DATABASE_URL=... .venv/bin/python tests/test_popup_leads.py
"""
import os
import uuid
from datetime import datetime, timedelta, timezone

os.environ.setdefault("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/urjaa")

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.orm import Session

from urjaa_core.core.config import settings
from urjaa_core.core.database import engine
from urjaa_core.models.collection import Collection
from urjaa_core.models.newsletter_subscriber import NewsletterSubscriber
from urjaa_core.schemas.cms_content import (
    DEFAULT_POPUP_CONSENT_TEXT,
    FOOTER_CONSENT_TEXT,
    WHATSAPP_CONSENT_TEXT,
    PopupContent,
)
from urjaa_core.schemas.newsletter import NewsletterSubscribeRequest
from urjaa_core.services import cms_service, newsletter_service

MEDIA = settings.media_base_url.rstrip("/")
NOW = datetime.now(timezone.utc)


def _raises(fn, exc=ValidationError, status: int | None = None) -> None:
    try:
        fn()
    except exc as e:
        if status is not None:
            assert e.status_code == status, (e.status_code, e.detail)
        return
    raise AssertionError(f"expected {exc.__name__}")


def test_popup_schema() -> None:
    PopupContent()  # all defaults valid (disabled)
    ok = {"enabled": True, "title": "Early access", "capture": "email"}
    assert PopupContent.model_validate(ok).consent_text == DEFAULT_POPUP_CONSENT_TEXT
    bad = [
        {"bogus": 1},
        {"starts_at": NOW.isoformat(), "ends_at": (NOW - timedelta(hours=1)).isoformat()},
        {"starts_at": "2026-10-12T10:00:00"},  # naive datetime
        {"image_url": f"{MEDIA}/urjaa/cms/p.jpg"},  # no alt text
        {"image_url": "https://evil.example/p.jpg", "image_alt": "x"},
        {"enabled": True, "capture": "email"},  # nothing to show
        {"enabled": True, "title": "Sale", "capture": "none"},  # link-only without a button
        {"consent_text": "short"},
        {"pages": []},
        {"pages": ["checkout"]},
        {"delay_seconds": 1},
        {"hide_for_days": 365},
        {"link": {"kind": "collection"}},
    ]
    for payload in bad:
        _raises(lambda: PopupContent.model_validate(payload))


def test_popup_resolution(db: Session) -> None:
    coll = Collection(name="Diwali Sale", slug=f"popup-test-{uuid.uuid4().hex[:8]}")
    db.add(coll)
    db.flush()
    base = {
        "enabled": True,
        "title": "Early access",
        "cta_label": "Shop the sale",
        "link": {"kind": "collection", "id": coll.id},
        "capture": "email_whatsapp",
    }
    cms_service.save_page(db, "popup", {**base, "enabled": False}, saved_by="t@urjaa.test")
    assert cms_service.resolve_popup_for_storefront(db) == {}

    cms_service.save_page(db, "popup", {**base, "starts_at": (NOW + timedelta(days=1)).isoformat()}, saved_by="t@urjaa.test")
    assert cms_service.resolve_popup_for_storefront(db) == {}, "scheduled popup must not leak"
    assert cms_service.resolve_popup_for_storefront(db, now=NOW + timedelta(days=2))["title"] == "Early access"

    cms_service.save_page(db, "popup", {**base, "ends_at": (NOW - timedelta(minutes=1)).isoformat()}, saved_by="t@urjaa.test")
    assert cms_service.resolve_popup_for_storefront(db) == {}, "ended popup must not show"

    cms_service.save_page(db, "popup", base, saved_by="t@urjaa.test")
    live = cms_service.resolve_popup_for_storefront(db)
    assert live["link"] == {"kind": "collection", "name": "Diwali Sale", "href": f"/collections?collection={coll.slug}"}
    assert live["whatsapp_consent_text"] == WHATSAPP_CONSENT_TEXT
    assert live["consent_text"] == DEFAULT_POPUP_CONSENT_TEXT and len(live["key"]) == 16
    assert not {"enabled", "starts_at", "ends_at"} & live.keys()

    # Link-only popup whose collection is gone: nothing worth showing.
    cms_service.save_page(db, "popup", {**base, "capture": "none", "link": {"kind": "collection", "id": 987654}}, saved_by="t@urjaa.test")
    assert cms_service.resolve_popup_for_storefront(db) == {}

    # A versioned CMS page like the others.
    _, versions = cms_service.get_page(db, "popup")
    # >= 4 (this test saved 6); capped, and pre-existing saves on the dev DB may fill the cap.
    assert 4 <= len(versions) <= cms_service.MAX_VERSIONS


def _row(db: Session, email: str) -> NewsletterSubscriber:
    return db.query(NewsletterSubscriber).filter(NewsletterSubscriber.email == email).one()


def test_subscribe_consent(db: Session) -> None:
    ip = f"10.0.0.{uuid.uuid4().int % 250}"
    email = f"Lead-{uuid.uuid4().hex[:8]}@Example.com"
    newsletter_service.subscribe(db, NewsletterSubscribeRequest(email=email), ip)
    row = _row(db, email.lower())
    assert (row.source, row.consent_text, row.phone, row.whatsapp_opt_in) == ("footer", FOOTER_CONSENT_TEXT, None, False)

    # Popup re-submit with WhatsApp ticked: phone normalised, both texts stored,
    # and the popup's saved consent text (not anything the client sent).
    cms_service.save_page(db, "popup", {"consent_text": "Yes, email me Urjaa offers. Unsubscribe any time."}, saved_by="t@urjaa.test")
    payload = NewsletterSubscribeRequest(email=email, phone="+91 98201 44092", whatsapp_opt_in=True, source="popup")
    newsletter_service.subscribe(db, payload, ip)
    db.refresh(row)
    assert (row.source, row.phone, row.whatsapp_opt_in) == ("popup", "+919820144092", True)
    assert row.consent_text == "Yes, email me Urjaa offers. Unsubscribe any time.\n" + WHATSAPP_CONSENT_TEXT

    # Phone without the WhatsApp tick is dropped; tick without a phone is rejected.
    assert NewsletterSubscribeRequest(email=email, phone="9820144092").phone is None
    _raises(lambda: NewsletterSubscribeRequest(email=email, whatsapp_opt_in=True))
    _raises(lambda: NewsletterSubscribeRequest(email=email, source="admin"))


def test_subscribe_rate_limit(db: Session) -> None:
    ip = f"rl-{uuid.uuid4().hex}"
    for i in range(5):
        newsletter_service.subscribe(db, NewsletterSubscribeRequest(email=f"rl{i}-{uuid.uuid4().hex[:6]}@example.com"), ip)
    _raises(lambda: newsletter_service.subscribe(db, NewsletterSubscribeRequest(email="rl-x@example.com"), ip), HTTPException, 429)


def test_unsubscribe_token(db: Session) -> None:
    email = f"unsub-{uuid.uuid4().hex[:8]}@example.com"
    ip = f"un-{uuid.uuid4().hex}"
    newsletter_service.subscribe(db, NewsletterSubscribeRequest(email=email, phone="9820144092", whatsapp_opt_in=True), f"s-{ip}")

    os.environ.pop(newsletter_service.SECRET_ENV, None)
    _raises(lambda: newsletter_service.unsubscribe(db, email, "x" * 64, ip), HTTPException, 503)  # fail closed

    os.environ[newsletter_service.SECRET_ENV] = "test-secret-" + "a" * 40
    token = newsletter_service.unsubscribe_token(email)
    assert token == newsletter_service.unsubscribe_token(f"  {email.upper()} ")

    other = newsletter_service.unsubscribe_token("someone-else@example.com")
    for bad in ("", "nope", other, token[:-1] + ("0" if token[-1] != "0" else "1"), "é" * 64):
        _raises(lambda: newsletter_service.unsubscribe(db, email, bad, ip), HTTPException, 400)
    assert _row(db, email).unsubscribed_at is None, "bad tokens must not unsubscribe"

    newsletter_service.unsubscribe(db, email, token, ip)
    row = _row(db, email)
    assert row.unsubscribed_at is not None and row.whatsapp_opt_in is False and row.phone is None

    # Different secret = old links stop working.
    os.environ[newsletter_service.SECRET_ENV] = "rotated-" + "b" * 40
    _raises(lambda: newsletter_service.unsubscribe(db, email, token, ip), HTTPException, 400)


def main() -> None:
    test_popup_schema()
    conn = engine.connect()
    outer = conn.begin()
    db = Session(bind=conn, join_transaction_mode="create_savepoint")
    try:
        db.execute(text("SET ROLE urjaa_admin_svc"))
        test_popup_resolution(db)
        db.execute(text("SET ROLE urjaa_storefront"))
        test_subscribe_consent(db)  # also saves cms.popup -- storefront role has DML on website_configs
        test_subscribe_rate_limit(db)
        test_unsubscribe_token(db)
    finally:
        db.close()
        outer.rollback()
        conn.close()


if __name__ == "__main__":
    main()
    print("ok")
