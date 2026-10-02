"""M-02 self-check: "Shop by Occasion" (storefront) links to
`/collections?tag=<slug>`. CatalogQueryBuilder.filter_tag and
CatalogAggregationRepository.get_tag_counts already existed (filtering on
Tag.slug, case-insensitive) — this proves that path still narrows correctly
and reports the facet count, using tags/products this test creates itself so
it doesn't depend on seed state.

Runs against the live dev database inside a rolled-back transaction, same
pattern as tests/test_size_dimension_storefront.py / test_sku_autogeneration.py
— the dev catalogue is otherwise untouched.

Run: urjaa-core/.venv/bin/python tests/test_tag_filter.py
(PYTHONPATH pointed at this worktree)
"""
import os
import uuid

os.environ.setdefault("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/urjaa")

from sqlalchemy import text
from sqlalchemy.orm import Session

from urjaa_core.core.database import engine
from urjaa_core.models import Product, ProductTag, Store, Tag
from urjaa_core.repositories.catalog_aggregation_repository import CatalogAggregationRepository
from urjaa_core.repositories.catalog_query_builder import CatalogQueryBuilder


def test_tag_filter_and_facet_live() -> None:
    conn = engine.connect()
    outer = conn.begin()
    db = Session(bind=conn, join_transaction_mode="create_savepoint")
    try:
        db.execute(text("SET ROLE urjaa_admin_svc"))
        store = db.query(Store).first()
        assert store is not None, "dev DB has no seeded store"

        suffix = uuid.uuid4().hex[:8]
        tag = Tag(name=f"M02 Bridal {suffix}", slug=f"m02-bridal-{suffix}")
        other_tag = Tag(name=f"M02 Festive {suffix}", slug=f"m02-festive-{suffix}")
        db.add_all([tag, other_tag])
        db.flush()

        tagged = Product(
            store_id=store.id,
            name=f"M02 tagged {suffix}",
            slug=f"m02-tagged-{suffix}",
            status="active",
        )
        untagged = Product(
            store_id=store.id,
            name=f"M02 untagged {suffix}",
            slug=f"m02-untagged-{suffix}",
            status="active",
        )
        db.add_all([tagged, untagged])
        db.flush()

        db.add(ProductTag(product_id=tagged.id, tag_id=tag.id))
        db.flush()

        # --- filter_tag: ?tag=<slug> narrows to exactly the tagged product,
        # case-insensitively (link slugs are lowercase but this guards the
        # match regardless) ---
        matched = (
            CatalogQueryBuilder(db.query(Product.id), store_id=store.id)
            .apply_filters({"tag": tag.slug.upper()})
            .only_active()
            .build()
            .distinct()
            .all()
        )
        assert [row[0] for row in matched] == [tagged.id], matched
        print("filter_tag narrows to tag=<slug>        OK")

        no_match = (
            CatalogQueryBuilder(db.query(Product.id), store_id=store.id)
            .apply_filters({"tag": other_tag.slug})
            .only_active()
            .build()
            .distinct()
            .all()
        )
        assert no_match == [], no_match
        print("filter_tag excludes non-matching tag    OK")

        # --- get_tag_counts: one facet bucket for the tagged product, none
        # for the untagged one or the unused tag ---
        base_query = CatalogAggregationRepository.build_base_subquery(
            db, store.id, {}, None
        )
        buckets = {b["slug"]: b for b in CatalogAggregationRepository.get_tag_counts(db, base_query)}
        assert tag.slug in buckets and buckets[tag.slug]["count"] == 1, buckets
        assert other_tag.slug not in buckets, buckets
        print("get_tag_counts facet bucket             OK", buckets[tag.slug])
    finally:
        db.close()
        outer.rollback()
        conn.close()


if __name__ == "__main__":
    test_tag_filter_and_facet_live()
    print("ok")
