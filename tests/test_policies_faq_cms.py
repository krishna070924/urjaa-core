"""O-05: policies + FAQ CMS. Rolled-back transaction against the dev DB.

Run: .venv/bin/python tests/test_policies_faq_cms.py
"""
import os

os.environ.setdefault("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/urjaa")

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from urjaa_core.core.database import engine
from urjaa_core.services import cms_service


def expect_422(payload, page):
    try:
        cms_service.save_page(db, page, payload, saved_by="t")
        raise AssertionError(f"accepted: {payload}")
    except HTTPException as exc:
        assert exc.status_code == 422, exc.detail


def main() -> None:
    global db
    conn = engine.connect()
    outer = conn.begin()
    db = Session(bind=conn, join_transaction_mode="create_savepoint")
    try:
        db.execute(text("DELETE FROM website_configs WHERE key IN ('cms.policies', 'cms.faq')"))
        ship = {"title": "Shipping", "intro": "", "sections": [{"heading": "Dispatch", "paragraphs": ["We ship."], "bullets": ["Insured"]}]}
        saved, _ = cms_service.save_page(db, "policies", {"shipping": ship, "terms": None}, saved_by="t")
        assert saved["shipping"]["updated_at"] and saved["terms"] is None
        first_date = saved["shipping"]["updated_at"]

        # Client cannot set the date; unchanged page keeps its date.
        ship2 = dict(ship, updated_at="1999-01-01")
        saved, _ = cms_service.save_page(db, "policies", {"shipping": ship2}, saved_by="t")
        assert saved["shipping"]["updated_at"] == first_date, saved["shipping"]["updated_at"]
        print("policy 'last updated' server-set, kept when unchanged  OK")

        expect_422({"shipping": {"title": "", "sections": []}}, "policies")
        expect_422({"shipping": dict(ship, extra="x")}, "policies")
        expect_422({"unknown_page": ship}, "policies")
        print("policy validation (title, extra, page keys)          OK")

        item = {"category": "shipping", "question": "How long?", "answer": "A few days.", "most_asked": True, "related_link": "/policies/shipping"}
        saved, _ = cms_service.save_page(db, "faq", {"items": [item]}, saved_by="t")
        assert saved["items"][0]["most_asked"] is True
        expect_422({"items": [dict(item, category="misc")]}, "faq")
        expect_422({"items": [dict(item, related_link="https://evil.example.com")]}, "faq")
        expect_422({"items": [dict(item, answer="")]}, "faq")
        assert cms_service.resolve_plain_page_for_storefront(db, "faq")["items"][0]["question"] == "How long?"
        print("faq: fixed categories, fixed links, round-trip        OK")
    finally:
        db.close()
        outer.rollback()
        conn.close()


if __name__ == "__main__":
    main()
