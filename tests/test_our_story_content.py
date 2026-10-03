"""O-07: every Our Story line editable (None = designed, "" = hidden).
No DB needed for the schema rules; one save round-trip runs inside a
rolled-back transaction.

Run: .venv/bin/python tests/test_our_story_content.py
"""
import os

os.environ.setdefault("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/urjaa")

from pydantic import ValidationError
from sqlalchemy.orm import Session

from urjaa_core.core.config import settings
from urjaa_core.core.database import engine
from urjaa_core.schemas.cms_content import OurStoryContent
from urjaa_core.services import cms_service


def main() -> None:
    base = settings.media_base_url.rstrip("/")

    empty = OurStoryContent.model_validate({})
    assert empty.journey.founders == [] and empty.opening.heading is None
    print("empty content = all designed                   OK")

    content = {
        "journey": {
            "heading": "Two Visionaries",
            "body": "",
            "founders": [
                {"name": "A. Jain", "role": "Founder", "image_url": f"{base}/urjaa/cms/f1.jpg"},
                {"name": "B. Jain", "role": "Co-Founder", "image_url": None},
            ],
            "pillars": [{"title": "Craft", "text": "By hand."}],
        },
        "workbench": {"stats": [{"value": "24K", "label": "Gold Leaf"}]},
        "hands": {"image_caption": "", "tags": ["Setting", "Polki"]},
        "emblem": {"caption": "Our mark"},
        "next_chapter": {"primary_button_label": "Explore", "secondary_button_label": ""},
    }
    OurStoryContent.model_validate(content)
    print("founders/pillars/stats/tags/captions accepted   OK")

    for bad in (
        {"journey": {"founders": [{"name": "x"}] * 5}},
        {"hands": {"tags": ["t"] * 7}},
        {"journey": {"founders": [{"image_url": "https://evil.example.com/x.jpg"}]}},
        {"journey": {"unknown": "x"}},
    ):
        try:
            OurStoryContent.model_validate(bad)
            raise AssertionError(f"accepted: {bad}")
        except ValidationError:
            pass
    print("limits, foreign URL, unknown field rejected     OK")

    conn = engine.connect()
    outer = conn.begin()
    db = Session(bind=conn, join_transaction_mode="create_savepoint")
    try:
        saved, _ = cms_service.save_page(db, "our-story", content, saved_by="tester@urjaa.test")
        assert saved["journey"]["founders"][0]["name"] == "A. Jain"
        assert saved["journey"]["body"] == "" and saved["opening"]["heading"] is None
        resolved = cms_service.resolve_our_story_for_storefront(db)
        assert resolved["journey"]["founders"][1]["role"] == "Co-Founder"
        print("save + storefront read round-trip               OK")
    finally:
        db.close()
        outer.rollback()
        conn.close()


if __name__ == "__main__":
    main()
